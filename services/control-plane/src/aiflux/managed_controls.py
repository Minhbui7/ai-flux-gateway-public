"""Typed, bounded runtime fragment compiler; routing remains Terraform-owned."""
import json
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from typing import TypedDict

from fastapi import HTTPException
from sqlalchemy import select, true
from sqlalchemy.orm import Session

from aiflux.config import Settings
from aiflux.models import Organization, Team, TeamSubscription
from aiflux.schemas import GatewayLimits, ManagedGatewayConfiguration, SafetyConfiguration

MAX_FRAGMENT_BYTES = 65536


class Binding(TypedDict):
    organization_id: str
    team_id: str
    subscription_id: str


def validate_configuration(
    db: Session, settings: Settings, config: ManagedGatewayConfiguration, tpm_ceiling: int,
) -> list[Binding]:
    if not settings.gateway_controls_v2_enabled:
        raise HTTPException(409, "Managed gateway controls have not been provisioned")
    limits = [config.defaults, *(item.limits for item in config.teams),
              *(item.limits for item in config.subscriptions)]
    for limit in limits:
        if limit.rpm > settings.gateway_max_rpm or limit.tpm > tpm_ceiling:
            raise HTTPException(422, "Limits exceed the operator-approved RPM/TPM ceiling")
        if (limit.request_quota is not None and limit.request_quota_period == "Monthly"
                and not settings.gateway_monthly_request_quota_available):
            raise HTTPException(409, "Calendar-month request quota requires operator capability validation")
    validate_safety(settings, config.safety)
    rows = db.execute(
        select(TeamSubscription, Organization)
        .join(Organization, TeamSubscription.organization_id == Organization.id)
        .where(Organization.enabled == true())
        .order_by(TeamSubscription.id).limit(201),
    ).all()
    if len(rows) > 200:
        raise HTTPException(422, "Managed policy capacity is 200 subscriptions; operator review required")
    bindings = []
    for subscription, org in rows:
        team = db.get(Team, subscription.team_id) if subscription.team_id else None
        if team is None or team.organization_id != org.id:
            raise HTTPException(409, "Stable team migration is required before publishing controls")
        bindings.append(Binding(
            organization_id=org.id, team_id=team.id, subscription_id=subscription.id,
        ))
    teams = {(item["organization_id"], item["team_id"]) for item in bindings}
    subscriptions = {(item["organization_id"], item["subscription_id"]) for item in bindings}
    team_targets = [(str(item.organization_id), str(item.team_id)) for item in config.teams]
    sub_targets = [(str(item.organization_id), str(item.subscription_id)) for item in config.subscriptions]
    if len(set(team_targets)) != len(team_targets) or len(set(sub_targets)) != len(sub_targets):
        raise HTTPException(422, "Duplicate limit targets are not allowed")
    if not set(team_targets) <= teams or not set(sub_targets) <= subscriptions:
        raise HTTPException(422, "Limit target is unavailable or does not belong to the organization")
    return bindings


def validate_safety(settings: Settings, safety: SafetyConfiguration) -> None:
    if safety.protected_material and not settings.gateway_protected_material_available:
        raise HTTPException(409, "Protected-text detection requires operator capability validation")
    if not settings.gateway_safety_relaxation_allowed and not all((
        safety.input_filtering, safety.output_filtering, safety.prompt_attack,
    )):
        raise HTTPException(422, "The operator requires input/output scanning and prompt protection")


def safety_relaxed(previous: SafetyConfiguration, desired: SafetyConfiguration) -> bool:
    return any(getattr(desired, name) > getattr(previous, name)
               for name in ("hate", "violence", "sexual", "self_harm")) or any(
        getattr(previous, name) and not getattr(desired, name)
        for name in ("prompt_attack", "protected_material", "input_filtering", "output_filtering")
    )


def render_managed(config: ManagedGatewayConfiguration, bindings: Sequence[Binding]) -> str:
    root = ET.Element("fragment")

    def variable(parent: ET.Element, name: str, value: str | int | bool) -> None:
        expression = f"@({str(value).lower()})" if type(value) in (int, bool) else str(value)
        ET.SubElement(parent, "set-variable", name=name, value=expression)

    variable(root, "aiflux-managed-v2", True)
    variable(root, "aiflux-quota-now", "@(DateTime.UtcNow)")
    for category in ("hate", "violence", "sexual", "self_harm"):
        variable(root, "aiflux-" + category.replace("_", "-") + "-threshold",
                 getattr(config.safety, category))
    for setting in ("prompt_attack", "protected_material", "input_filtering", "output_filtering"):
        variable(root, "aiflux-" + setting.replace("_", "-"), getattr(config.safety, setting))

    # One lookup table plus one limits branch per distinct target avoids repeating
    # safety configuration or a complete policy for every subscription.
    mapping = {
        item["subscription_id"]: [item["organization_id"], item["team_id"]] for item in bindings
    }
    encoded = json.dumps(mapping, separators=(",", ":")).replace('"', '""')
    variable(root, "aiflux-target", (
        '@{ var targets = JObject.Parse(@"' + encoded + '"); '
        'var id = context.Subscription.Id; '
        'return targets[id] == null ? "" : targets[id].ToString(Newtonsoft.Json.Formatting.None); }'
    ))
    choose = ET.SubElement(root, "choose")
    unknown = ET.SubElement(choose, "when", condition='@((string)context.Variables["aiflux-target"] == "")')
    response = ET.SubElement(unknown, "return-response")
    ET.SubElement(response, "set-status", code="403", reason="Subscription controls not published")
    header = ET.SubElement(response, "set-header", {"name": "Content-Type", "exists-action": "override"})
    ET.SubElement(header, "value").text = "application/json"
    ET.SubElement(response, "set-body").text = json.dumps({"error": {
        "message": "Subscription controls must be published by an administrator.",
        "type": "permission_error", "code": "subscription_controls_unpublished", "param": None,
    }}, separators=(",", ":"))
    for name, index in (("organization", 0), ("team", 1)):
        variable(root, f"aiflux-{name}-id",
                 f'@((string)JArray.Parse((string)context.Variables["aiflux-target"])[{index}])')

    def policies(parent: ET.Element, limit: GatewayLimits, kind: str) -> None:
        variable(parent, f"aiflux-{kind}-concurrency", limit.concurrency)
        identity = ('(string)context.Subscription.Id' if kind == "subscription"
                    else '(string)context.Variables["aiflux-team-id"]')
        key = f'"aiflux:v2:{kind}:" + {identity}'
        ET.SubElement(parent, "rate-limit-by-key", {
            "calls": str(limit.rpm), "renewal-period": "60", "counter-key": f'@("rpm:" + {key})',
        })
        ET.SubElement(parent, "llm-token-limit", {
            "counter-key": f'@("tokens:" + {key})', "tokens-per-minute": str(limit.tpm),
            "token-quota": str(limit.token_quota), "token-quota-period": limit.quota_period,
            "estimate-prompt-tokens": "true", "retry-after-variable-name": "aiflux-token-retry-after",
        })
        if limit.request_quota is not None:
            date_format = "yyyyMMdd" if limit.request_quota_period == "Daily" else "yyyyMM"
            next_period = 'now.Date.AddDays(1)' if limit.request_quota_period == "Daily" else (
                'new DateTime(now.Year, now.Month, 1).AddMonths(1)'
            )
            variable(parent, "aiflux-request-quota-retry-after", (
                '@{ var now = (DateTime)context.Variables["aiflux-quota-now"]; '
                f'return Math.Max(1, (int)Math.Ceiling(({next_period} - now).TotalSeconds)); }}'
            ))
            # Calendar-partitioned lifetime counters keep edits/rollbacks in the same
            # UTC period without relying on an approximate 30-day month.
            ET.SubElement(parent, "quota-by-key", {
                "calls": str(limit.request_quota), "renewal-period": "0",
                "counter-key": f'@("calls:{date_format}:" + {key} + ":" + '
                               f'((DateTime)context.Variables["aiflux-quota-now"]).ToString("{date_format}"))',
            })

    variable(root, "aiflux-team-concurrency", 0)
    if config.teams:
        team_choose = ET.SubElement(root, "choose")
        for target in sorted(config.teams, key=lambda item: str(item.team_id)):
            branch = ET.SubElement(team_choose, "when", condition=(
                f'@((string)context.Variables["aiflux-team-id"] == "{target.team_id}")'
            ))
            policies(branch, target.limits, "team")

    sub_choose = ET.SubElement(root, "choose") if config.subscriptions or config.teams else root
    for subscription_target in sorted(config.subscriptions, key=lambda item: str(item.subscription_id)):
        branch = ET.SubElement(
            sub_choose, "when",
            condition=f'@(context.Subscription.Id == "{subscription_target.subscription_id}")',
        )
        policies(branch, subscription_target.limits, "subscription")
    for target in sorted(config.teams, key=lambda item: str(item.team_id)):
        branch = ET.SubElement(sub_choose, "when", condition=(
            f'@((string)context.Variables["aiflux-team-id"] == "{target.team_id}")'
        ))
        policies(branch, target.limits, "subscription")
    policies(
        ET.SubElement(sub_choose, "otherwise") if sub_choose is not root else root,
        config.defaults, "subscription",
    )
    value = ET.tostring(root, encoding="unicode")
    if len(value.encode("utf-8")) > MAX_FRAGMENT_BYTES:
        raise HTTPException(422, "Managed settings exceed the supported 64KiB policy capacity")
    return value
