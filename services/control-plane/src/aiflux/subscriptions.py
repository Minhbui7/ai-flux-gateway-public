import logging
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aiflux.apim import ApimClient, ApimError
from aiflux.auth import Principal
from aiflux.models import AuditEvent, Organization, Team, TeamSubscription
from aiflux.schemas import SubscriptionCreate

log = logging.getLogger(__name__)


def team_identity(organization_id: str, name: str) -> str:
    # Exact label bytes avoid SQL collation accidentally merging differently named teams.
    return str(uuid5(NAMESPACE_URL, f"aiflux:team:{organization_id}:{name}"))


def audit(
    db: Session, principal: Principal, action: str, target: str, organization_id: str | None = None,
) -> None:
    db.add(
        AuditEvent(
            organization_id=organization_id or principal.organization_id,
            object_id=principal.object_id,
            action=action,
            target_id=target,
        )
    )


def subscription_dict(row: TeamSubscription) -> dict[str, Any]:
    from aiflux.finops import aware

    return {field: getattr(row, field) for field in ("id", "name", "team", "state")} | {
        "created_at": aware(row.created_at).isoformat(),
    }


def lock_organization(db: Session, organization_id: str) -> Organization:
    org = db.scalar(
        select(Organization)
        .where(Organization.id == organization_id)
        .with_hint(
            Organization,
            "WITH (UPDLOCK, HOLDLOCK)",
            dialect_name="mssql",
        )
        .execution_options(populate_existing=True)
    )
    if org is None or not org.enabled:
        raise HTTPException(403, "Organization is disabled")
    return org


def owned(db: Session, sid: UUID, principal: Principal) -> TeamSubscription:
    row = db.scalar(
        select(TeamSubscription)
        .where(
            TeamSubscription.id == str(sid),
            TeamSubscription.organization_id == principal.organization_id,
        )
        .with_hint(TeamSubscription, "WITH (UPDLOCK, HOLDLOCK)", dialect_name="mssql")
    )
    if row is None:
        raise HTTPException(404, "Subscription not found")
    return row


def admin_owned(db: Session, sid: UUID) -> TeamSubscription:
    organization_id = db.scalar(
        select(TeamSubscription.organization_id).where(TeamSubscription.id == str(sid)),
    )
    if organization_id is None:
        raise HTTPException(404, "Subscription not found")
    lock_organization(db, organization_id)
    row = db.scalar(
        select(TeamSubscription).where(TeamSubscription.id == str(sid))
        .with_hint(TeamSubscription, "WITH (UPDLOCK, HOLDLOCK)", dialect_name="mssql")
    )
    if row is None:
        raise HTTPException(404, "Subscription not found")
    return row


def reconcile(db: Session, row: TeamSubscription, apim: ApimClient, principal: Principal) -> None:
    lock_organization(db, row.organization_id)
    try:
        # PUT is idempotent; ownership is durable before any key becomes usable.
        apim.ensure(row.id, row.name, row.desired_state)
    except ApimError as exc:
        row.state = "failed"
        audit(db, principal, "subscription.provision.failed", row.id, row.organization_id)
        db.commit()
        log.warning("APIM reconciliation failed subscription=%s status=%s", row.id, exc.status_code)
        raise HTTPException(502, "APIM operation failed; subscription reconciliation is required") from exc
    row.state = row.desired_state
    audit(db, principal, "subscription.reconciled", row.id, row.organization_id)
    db.commit()


def create_subscription(
    db: Session,
    principal: Principal,
    payload: SubscriptionCreate,
    idempotency_key: UUID,
    apim: ApimClient,
    organization_id: str | None = None,
) -> TeamSubscription:
    organization_id = organization_id or principal.organization_id
    lock_organization(db, organization_id)
    sid = str(uuid5(NAMESPACE_URL, f"aiflux:{organization_id}:{idempotency_key}"))
    row = db.get(TeamSubscription, sid)
    if row is not None:
        if row.name != payload.name or row.team != payload.team:
            raise HTTPException(409, "Idempotency key already used with a different request")
        if row.state in ("pending", "failed"):
            reconcile(db, row, apim, principal)
        return row
    team_id = team_identity(organization_id, payload.team)
    if db.get(Team, team_id) is None:
        db.add(Team(id=team_id, organization_id=organization_id, name=payload.team))
        db.flush()
    row = TeamSubscription(
        id=sid,
        organization_id=organization_id,
        name=payload.name,
        team=payload.team,
        team_id=team_id,
        idempotency_key=str(idempotency_key),
        state="pending",
        desired_state="active",
    )
    db.add(row)
    audit(db, principal, "subscription.requested", row.id, organization_id)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.get(TeamSubscription, sid)
        if existing is None:
            raise
        if existing.name != payload.name or existing.team != payload.team:
            raise HTTPException(409, "Idempotency key already used with a different request") from None
        row = existing
    reconcile(db, row, apim, principal)
    return row
