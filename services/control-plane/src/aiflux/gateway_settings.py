import hashlib
import json
import logging
import xml.etree.ElementTree as ET
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from aiflux.apim import ApimClient, ApimError
from aiflux.auth import Principal
from aiflux.config import Settings
from aiflux.managed_controls import render_managed, safety_relaxed, validate_configuration
from aiflux.models import GatewaySettings, GatewaySettingsRevision
from aiflux.schemas import (
    GatewayCapabilities,
    GatewayConfiguration,
    GatewayRevisionOutput,
    GatewayScope,
    GatewaySettingsOutput,
    GatewaySettingsUpdate,
    ManagedGatewayConfiguration,
    SafetyConfiguration,
    SafetySettingsUpdate,
)
from aiflux.subscriptions import audit

log = logging.getLogger(__name__)
BOOTSTRAP = Path("gateway/policies/settings-unconfigured.xml")


def bootstrap_fragment() -> str:
    try:
        value = BOOTSTRAP.read_text(encoding="utf-8")
    except OSError as exc:
        log.error("Gateway settings bootstrap policy is not packaged")
        raise HTTPException(503, "Gateway settings bootstrap policy is not packaged") from exc
    return value


def max_tpm(scope: GatewayScope) -> int:
    return 2048 if scope == "dev-openai" else 20000


def require_scope(settings: Settings, scope: GatewayScope) -> None:
    if scope not in settings.gateway_settings_scopes:
        raise HTTPException(409, "Admin gateway settings are not enabled for this API")


def fingerprint(xml: str) -> str:
    try:
        canonical = ET.canonicalize(xml, strip_text=True)
    except ET.ParseError as exc:
        raise ApimError() from exc
    return hashlib.sha256(canonical.encode()).hexdigest()


def render_fragment(scope: GatewayScope, config: GatewayConfiguration) -> str:
    # Only typed, bounded values enter XML. API policy structure stays Terraform-owned.
    prefix = f"{scope}:"
    key = '(string)context.Subscription.Id + ":" + (string)context.Variables["aiflux-model"]'
    return (
        '<fragment>'
        f'<set-variable name="aiflux-safety-threshold" value="@({config.safety_threshold})" />'
        f'<rate-limit-by-key calls="{config.rpm}" renewal-period="60" '
        f'counter-key=\'@("rpm:{prefix}" + {key})\' />'
        f'<llm-token-limit id="aiflux-managed-token-limit" counter-key=\'@("tpm:{prefix}" + {key})\' '
        f'tokens-per-minute="{config.tpm}" token-quota="{config.token_quota}" '
        f'token-quota-period="{config.quota_period}" estimate-prompt-tokens="true" '
        'retry-after-variable-name="aiflux-token-retry-after" />'
        '</fragment>'
    )


def revision_at(db: Session, scope: str, version: int) -> GatewaySettingsRevision:
    return db.scalars(
        select(GatewaySettingsRevision).where(
            GatewaySettingsRevision.scope == scope, GatewaySettingsRevision.version == version,
        )
    ).one()


def revision_output(row: GatewaySettingsRevision) -> GatewayRevisionOutput:
    from aiflux.finops import aware

    return GatewayRevisionOutput(
        version=row.version, configuration=configuration_at(row),
        reason=row.reason, object_id=row.object_id, occurred_at=aware(row.occurred_at),
        state=row.state, error=row.error,
    )


def canonical_scope(settings: Settings, scope: GatewayScope) -> GatewayScope:
    return sorted(settings.gateway_settings_scopes)[0] if settings.gateway_controls_v2_enabled else scope


def configuration_at(row: GatewaySettingsRevision) -> GatewayConfiguration | ManagedGatewayConfiguration:
    stored = json.loads(row.configuration)
    if "configuration" in stored:
        return ManagedGatewayConfiguration.model_validate(stored["configuration"])
    return GatewayConfiguration.model_validate(stored)


def render_revision(scope: GatewayScope, row: GatewaySettingsRevision) -> str:
    config = configuration_at(row)
    if isinstance(config, ManagedGatewayConfiguration):
        return render_managed(config, json.loads(row.configuration)["bindings"])
    return render_fragment(scope, config)


def settings_output(
    db: Session, scope: GatewayScope, settings: Settings | None = None,
) -> GatewaySettingsOutput:
    key = canonical_scope(settings, scope) if settings else scope
    head = db.get(GatewaySettings, key)
    ceiling = min(max_tpm(item) for item in settings.gateway_settings_scopes) if (
        settings and settings.gateway_controls_v2_enabled
    ) else max_tpm(scope)
    return GatewaySettingsOutput(
        scope=scope, max_tpm=ceiling, max_rpm=settings.gateway_max_rpm if settings else 2,
        version=head.version if head else 0,
        published_version=head.published_version if head else None,
        desired=revision_output(revision_at(db, key, head.version)) if head and head.version else None,
        capabilities=GatewayCapabilities(
            managed_controls_enabled=settings.gateway_controls_v2_enabled,
            protected_material_available=settings.gateway_protected_material_available,
            monthly_request_quota_available=settings.gateway_monthly_request_quota_available,
            safety_relaxation_allowed=settings.gateway_safety_relaxation_allowed,
            enforcement_enabled=settings.gateway_enforcement_enabled,
            initial_safety_threshold=settings.gateway_initial_safety_threshold,
        ) if settings else GatewayCapabilities(),
    )


def locked_head(db: Session, scope: GatewayScope) -> GatewaySettings | None:
    return db.scalar(
        select(GatewaySettings).where(GatewaySettings.scope == scope)
        .with_hint(GatewaySettings, "WITH (UPDLOCK, HOLDLOCK)", dialect_name="mssql")
        .execution_options(populate_existing=True)
    )


def migrated_safety(config: GatewayConfiguration | None, initial_threshold: int = 1) -> SafetyConfiguration:
    threshold = config.safety_threshold if config else initial_threshold
    return SafetyConfiguration(
        profile="Custom", hate=threshold, violence=threshold, sexual=threshold, self_harm=threshold,
        prompt_attack=True, protected_material=False, input_filtering=True, output_filtering=True,
    )


def save_managed(
    db: Session, settings: Settings, apim: ApimClient, principal: Principal,
    scope: GatewayScope, payload: GatewaySettingsUpdate, *, safety_update: bool = False,
    binding_refresh: str | None = None,
) -> GatewaySettingsOutput:
    config = payload.configuration
    if not isinstance(config, ManagedGatewayConfiguration):
        raise HTTPException(422, "Versioned configuration is required")
    scopes = sorted(set(settings.gateway_settings_scopes))
    key = canonical_scope(settings, scope)
    # All guarded routes share one revision and counter namespace. Locking one
    # canonical head prevents two routes from publishing incompatible token limits.
    head = locked_head(db, key)
    if (head.version if head else 0) != payload.expected_version:
        raise HTTPException(409, "Settings changed; refresh before saving")
    prior = revision_at(db, key, head.version) if head and head.version else None
    if prior is not None and prior.state != "published":
        raise HTTPException(409, "Reconcile the pending or failed revision before saving another")
    previous = configuration_at(prior) if prior else None
    expected_safety = (
        previous.safety if isinstance(previous, ManagedGatewayConfiguration)
        else migrated_safety(previous, settings.gateway_initial_safety_threshold)
    )
    if not safety_update and config.safety != expected_safety:
        raise HTTPException(409, "Initialize gateway settings, then publish safety on the safety page")
    if scopes:
        tpm_ceiling = min(max_tpm(item) for item in scopes)
    else:
        raise HTTPException(409, "No guarded API scopes are provisioned")
    bindings = validate_configuration(db, settings, config, tpm_ceiling)
    desired = render_managed(config, bindings)
    bases = {}
    for item in scopes:
        scoped_head = db.get(GatewaySettings, item)
        scoped_revision = revision_at(db, item, scoped_head.version) if (
            scoped_head and scoped_head.version
        ) else None
        if scoped_revision is not None and scoped_revision.state != "published":
            raise HTTPException(409, "Reconcile existing API revisions before enabling shared controls")
        if not isinstance(previous, ManagedGatewayConfiguration) and scoped_revision is not None:
            scoped_config = configuration_at(scoped_revision)
            if isinstance(scoped_config, GatewayConfiguration) and (
                migrated_safety(scoped_config) != expected_safety
            ):
                raise HTTPException(409, "Existing API safety settings differ; operator migration required")
        baseline = render_revision(item, prior) if (
            prior is not None and isinstance(previous, ManagedGatewayConfiguration)
        ) else render_revision(item, scoped_revision) if scoped_revision else bootstrap_fragment()
        current, etag = apim.get_settings_fragment(item)
        if fingerprint(current) != fingerprint(baseline):
            raise HTTPException(409, f"APIM settings drift detected for {item}; operator review required")
        bases[item] = {"hash": fingerprint(current), "etag": etag}
    version = payload.expected_version + 1
    if head is None:
        db.add(GatewaySettings(scope=key, version=version))
    else:
        result = db.execute(
            update(GatewaySettings).where(
                GatewaySettings.scope == key, GatewaySettings.version == payload.expected_version,
            ).values(version=version),
        )
        if result.rowcount != 1:
            raise HTTPException(409, "Settings changed; refresh before saving")
    db.add(GatewaySettingsRevision(
        scope=key, version=version, reason=payload.reason, object_id=principal.object_id,
        configuration=json.dumps({
            "configuration": config.model_dump(mode="json"), "bindings": bindings,
            "bases": bases, "desired_hash": fingerprint(desired),
            "binding_refresh": binding_refresh,
        }, separators=(",", ":")),
        base_hash=bases[key]["hash"], base_etag=bases[key]["etag"],
    ))
    audit(db, principal, "gateway.settings.requested", f"{key}:{version}")
    db.commit()
    return publish_managed(db, settings, apim, principal, scope, version)


def subscription_access(db: Session, settings: Settings, sid: str) -> tuple[str, str | None]:
    if not settings.gateway_controls_v2_enabled:
        return "not_managed", "Versioned gateway membership is not enabled."
    if not settings.gateway_settings_scopes:
        return "pending", "Gateway scopes are not provisioned."
    scope = canonical_scope(settings, settings.gateway_settings_scopes[0])
    head = db.get(GatewaySettings, scope)
    if head is None or not head.published_version:
        return "pending", "An administrator must initialize Gateway settings."
    revision = revision_at(db, scope, head.published_version)
    stored = json.loads(revision.configuration)
    if any(item["subscription_id"] == sid for item in stored.get("bindings", [])):
        return "ready", None
    return "pending", "Gateway membership publication is pending. Reconcile to retry."


def refresh_subscription_bindings(
    db: Session, settings: Settings, apim: ApimClient, principal: Principal, sid: str,
) -> None:
    if not settings.gateway_controls_v2_enabled:
        return
    if not settings.gateway_settings_scopes:
        raise HTTPException(409, "Gateway scopes are not provisioned")
    scope = canonical_scope(settings, settings.gateway_settings_scopes[0])
    head = locked_head(db, scope)
    if head is None or not head.version or not head.published_version:
        raise HTTPException(409, "Initialize Gateway settings before publishing subscription access")
    current = revision_at(db, scope, head.version)
    if current.state != "published":
        if json.loads(current.configuration).get("binding_refresh") != sid:
            raise HTTPException(409, "Another gateway revision needs administrator reconciliation")
        publish_managed(db, settings, apim, principal, scope, head.version)
        return
    if subscription_access(db, settings, sid)[0] == "ready":
        return
    config = configuration_at(current)
    if not isinstance(config, ManagedGatewayConfiguration):
        raise HTTPException(409, "Initialize versioned Gateway settings before publishing access")
    save_managed(db, settings, apim, principal, scope, GatewaySettingsUpdate(
        expected_version=head.version, configuration=config,
        reason=f"Automatic subscription membership refresh: {sid}",
    ), binding_refresh=sid)


def save_safety(
    db: Session, settings: Settings, apim: ApimClient, principal: Principal,
    scope: GatewayScope, payload: SafetySettingsUpdate,
) -> GatewaySettingsOutput:
    require_scope(settings, scope)
    if not settings.gateway_controls_v2_enabled:
        raise HTTPException(409, "Managed Content Safety controls have not been provisioned")
    head = locked_head(db, canonical_scope(settings, scope))
    if head is None or head.version != payload.expected_version:
        raise HTTPException(409, "Settings changed; refresh before saving")
    config = configuration_at(revision_at(db, head.scope, head.version))
    if not isinstance(config, ManagedGatewayConfiguration):
        raise HTTPException(409, "Initialize versioned gateway settings before publishing safety")
    if safety_relaxed(config.safety, payload.configuration) and not payload.acknowledge_relaxation:
        raise HTTPException(422, "Explicit acknowledgement is required to relax safety")
    config = config.model_copy(update={"safety": payload.configuration})
    return save_managed(db, settings, apim, principal, scope, GatewaySettingsUpdate(
        expected_version=payload.expected_version, configuration=config, reason=payload.reason,
    ), safety_update=True)


def publish_managed(
    db: Session, settings: Settings, apim: ApimClient, principal: Principal,
    scope: GatewayScope, expected_version: int,
) -> GatewaySettingsOutput:
    key = canonical_scope(settings, scope)
    head = locked_head(db, key)
    if head is None or head.version != expected_version:
        raise HTTPException(409, "Settings changed; refresh before reconciling")
    row = revision_at(db, key, head.version)
    config = configuration_at(row)
    if not isinstance(config, ManagedGatewayConfiguration):
        raise HTTPException(409, "Legacy revisions require operator migration before shared reconciliation")
    stored = json.loads(row.configuration)
    desired = render_managed(config, stored["bindings"])
    if sorted(stored["bases"]) != sorted(set(settings.gateway_settings_scopes)):
        raise HTTPException(409, "Provisioned API scopes changed; operator reconciliation required")
    # Acquire a write lock on SQLite too; SQL Server already uses UPDLOCK/HOLDLOCK.
    db.execute(update(GatewaySettings).where(
        GatewaySettings.scope == key, GatewaySettings.version == expected_version,
    ).values(version=expected_version))
    try:
        for item, base in sorted(stored["bases"].items()):
            current, etag = apim.get_settings_fragment(item)
            if fingerprint(current) != fingerprint(desired):
                if fingerprint(current) != base["hash"] or etag != base["etag"]:
                    raise ApimError(412)
                apim.put_settings_fragment(item, desired, etag)
            readback, _ = apim.get_settings_fragment(item)
            if fingerprint(readback) != fingerprint(desired):
                raise ApimError(409)
    except ApimError as exc:
        row.state = "failed"
        row.error = f"Publication incomplete at {item}; reconcile all API scopes before further changes"
        audit(db, principal, "gateway.settings.failed", f"{key}:{head.version}")
        db.commit()
        log.warning("Shared controls publication failed scope=%s status=%s", key, exc.status_code)
        raise HTTPException(502, row.error) from exc
    row.state, row.error = "published", None
    head.published_version = head.version
    audit(db, principal, "gateway.settings.published", f"{key}:{head.version}")
    db.commit()
    return settings_output(db, scope, settings)


def save_settings(
    db: Session, settings: Settings, apim: ApimClient, principal: Principal,
    scope: GatewayScope, payload: GatewaySettingsUpdate,
) -> GatewaySettingsOutput:
    require_scope(settings, scope)
    if isinstance(payload.configuration, ManagedGatewayConfiguration):
        return save_managed(db, settings, apim, principal, scope, payload)
    if settings.gateway_controls_v2_enabled:
        raise HTTPException(409, "Upgrade to the versioned controls contract before writing settings")
    if payload.configuration.tpm > max_tpm(scope):
        raise HTTPException(422, f"This API permits at most {max_tpm(scope)} tokens per minute")
    head = locked_head(db, scope)
    if (head.version if head else 0) != payload.expected_version:
        raise HTTPException(409, "Settings changed; refresh before saving")
    if head is not None and head.version and revision_at(db, scope, head.version).state != "published":
        raise HTTPException(409, "Reconcile the pending or failed revision before saving another")
    current, etag = apim.get_settings_fragment(scope)
    baseline = bootstrap_fragment() if head is None else render_fragment(
        scope, GatewayConfiguration.model_validate_json(
            revision_at(db, scope, head.version).configuration,
        ),
    )
    if fingerprint(current) != fingerprint(baseline):
        raise HTTPException(409, "APIM settings drift detected; operator reconciliation is required")
    version = payload.expected_version + 1
    if head is None:
        head = GatewaySettings(scope=scope, version=version)
        db.add(head)
    else:
        result = db.execute(
            update(GatewaySettings)
            .where(GatewaySettings.scope == scope, GatewaySettings.version == payload.expected_version)
            .values(version=version)
        )
        if result.rowcount != 1:
            raise HTTPException(409, "Settings changed; refresh before saving")
    revision = GatewaySettingsRevision(
        scope=scope, version=version, configuration=payload.configuration.model_dump_json(),
        reason=payload.reason, object_id=principal.object_id,
        base_hash=fingerprint(current), base_etag=etag,
    )
    db.add(revision)
    audit(db, principal, "gateway.settings.requested", f"{scope}:{version}")
    db.commit()
    return publish_settings(db, settings, apim, principal, scope, version)


def publish_settings(
    db: Session, settings: Settings, apim: ApimClient, principal: Principal,
    scope: GatewayScope, expected_version: int,
) -> GatewaySettingsOutput:
    require_scope(settings, scope)
    if settings.gateway_controls_v2_enabled:
        return publish_managed(db, settings, apim, principal, scope, expected_version)
    # Hold the scope lock through the conditional remote write and state commit.
    # A crash rolls back publication state; reconciliation detects a completed remote write.
    head = locked_head(db, scope)
    if head is None or head.version != expected_version:
        raise HTTPException(409, "Settings changed; refresh before reconciling")
    result = db.execute(
        update(GatewaySettings)
        .where(GatewaySettings.scope == scope, GatewaySettings.version == expected_version)
        .values(version=expected_version)
    )
    if result.rowcount != 1:
        raise HTTPException(409, "Settings changed; refresh before reconciling")
    revision = revision_at(db, scope, head.version)
    config = GatewayConfiguration.model_validate_json(revision.configuration)
    desired = render_fragment(scope, config)
    try:
        current, etag = apim.get_settings_fragment(scope)
        if fingerprint(current) != fingerprint(desired):
            if fingerprint(current) != revision.base_hash or etag != revision.base_etag:
                raise ApimError(412)
            apim.put_settings_fragment(scope, desired, etag)
        readback, _ = apim.get_settings_fragment(scope)
        if fingerprint(readback) != fingerprint(desired):
            raise ApimError(409)
    except ApimError as exc:
        revision.state = "failed"
        revision.error = (
            "APIM settings conflict; operator reconciliation required"
            if exc.status_code in (409, 412) else "APIM publication failed; retry reconciliation"
        )
        audit(db, principal, "gateway.settings.failed", f"{scope}:{head.version}")
        db.commit()
        log.warning("Gateway settings publication failed scope=%s status=%s", scope, exc.status_code)
        raise HTTPException(502, revision.error) from exc
    revision.state = "published"
    revision.error = None
    head.published_version = head.version
    audit(db, principal, "gateway.settings.published", f"{scope}:{head.version}")
    db.commit()
    return settings_output(db, scope)
