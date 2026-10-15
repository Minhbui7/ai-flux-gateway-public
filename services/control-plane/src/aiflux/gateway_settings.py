import hashlib
import logging
import xml.etree.ElementTree as ET
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from aiflux.apim import ApimClient, ApimError
from aiflux.auth import Principal
from aiflux.config import Settings
from aiflux.models import GatewaySettings, GatewaySettingsRevision
from aiflux.schemas import (
    GatewayConfiguration,
    GatewayRevisionOutput,
    GatewayScope,
    GatewaySettingsOutput,
    GatewaySettingsUpdate,
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
        version=row.version, configuration=GatewayConfiguration.model_validate_json(row.configuration),
        reason=row.reason, object_id=row.object_id, occurred_at=aware(row.occurred_at),
        state=row.state, error=row.error,
    )


def settings_output(db: Session, scope: GatewayScope) -> GatewaySettingsOutput:
    head = db.get(GatewaySettings, scope)
    return GatewaySettingsOutput(
        scope=scope, max_tpm=max_tpm(scope), version=head.version if head else 0,
        published_version=head.published_version if head else None,
        desired=revision_output(revision_at(db, scope, head.version)) if head and head.version else None,
    )


def locked_head(db: Session, scope: GatewayScope) -> GatewaySettings | None:
    return db.scalar(
        select(GatewaySettings).where(GatewaySettings.scope == scope)
        .with_hint(GatewaySettings, "WITH (UPDLOCK, HOLDLOCK)", dialect_name="mssql")
        .execution_options(populate_existing=True)
    )


def save_settings(
    db: Session, settings: Settings, apim: ApimClient, principal: Principal,
    scope: GatewayScope, payload: GatewaySettingsUpdate,
) -> GatewaySettingsOutput:
    require_scope(settings, scope)
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
