import logging
import re
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import ValidationError
from sqlalchemy import func, literal, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from aiflux.apim import ApimClient, ApimError
from aiflux.auth import Principal, TokenVerifier, get_admin, get_principal
from aiflux.catalog import Catalog
from aiflux.config import Settings, get_settings
from aiflux.db import engine_for, get_db
from aiflux.finops import aware, create_price, usage_csv, usage_response
from aiflux.models import Base, Member, ModelPrice, Organization, SafetyEvent, TeamSubscription
from aiflux.schemas import (
    CatalogOutput,
    EnabledRequest,
    IdentityOutput,
    KeyRequest,
    MemberCreate,
    MemberOutput,
    OrganizationCreate,
    OrganizationOutput,
    Page,
    PriceCreate,
    PriceEnd,
    PriceOutput,
    SafetyOutput,
    StateRequest,
    SubscriptionCreate,
    SubscriptionOutput,
    UsagePage,
)
from aiflux.subscriptions import (
    audit,
    create_subscription,
    lock_organization,
    owned,
    reconcile,
    subscription_dict,
)

Db = Annotated[Session, Depends(get_db)]
User = Annotated[Principal, Depends(get_principal)]
Admin = Annotated[Principal, Depends(get_admin)]
log = logging.getLogger(__name__)


def apim_client(request: Request) -> ApimClient:
    return request.app.state.apim


Apim = Annotated[ApimClient, Depends(apim_client)]


def entity_dict(row: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: getattr(row, field) for field in fields}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="AIFLUX control plane", version="0.1.0")
    app.state.settings = settings
    app.state.token_verifier = TokenVerifier(settings)
    app.state.apim = ApimClient(settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    )

    @app.middleware("http")
    async def secure_responses(request: Request, call_next: Any) -> Response:
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(IntegrityError)
    async def integrity_failure(request: Request, exc: IntegrityError) -> Response:
        from fastapi.responses import JSONResponse

        log.warning("Database constraint conflict path=%s", request.url.path)
        return JSONResponse({"detail": "Conflicting record; refresh and retry"}, status_code=409)

    @app.exception_handler(SQLAlchemyError)
    async def database_failure(request: Request, exc: SQLAlchemyError) -> Response:
        from fastapi.responses import JSONResponse

        log.error("Database operation failed type=%s", type(exc).__name__)
        return JSONResponse({"detail": "Database temporarily unavailable"}, status_code=503)

    @app.exception_handler(ApimError)
    async def management_failure(request: Request, exc: ApimError) -> Response:
        from fastapi.responses import JSONResponse

        log.warning("APIM management failure status=%s", exc.status_code)
        return JSONResponse({"detail": "APIM management operation failed"}, status_code=502)

    @app.get("/health")
    def health() -> dict:
        return {"status": "alive"}

    @app.get("/.well-known/acme-challenge/{token}", response_class=PlainTextResponse)
    def acme_challenge(token: str) -> PlainTextResponse:
        if not settings.acme_challenge_enabled or not re.fullmatch(r"[A-Za-z0-9_-]{20,128}", token):
            raise HTTPException(404, "Not found")
        path = settings.acme_challenge_directory / token
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 300:
            raise HTTPException(404, "Not found")
        value = path.read_text(encoding="ascii")
        if not re.fullmatch(re.escape(token) + r"\.[A-Za-z0-9_-]{43}", value):
            raise HTTPException(404, "Not found")
        return PlainTextResponse(value)

    @app.api_route(
        "/_edge-denied/{path:path}",
        methods=["GET", "HEAD", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    )
    def edge_denied(path: str) -> PlainTextResponse:
        return PlainTextResponse("Public application routes are not released", status_code=403)

    @app.get("/ready")
    def ready() -> dict:
        if settings.identity_errors():
            raise HTTPException(503, "Required identity/database configuration is incomplete")
        with engine_for(settings.database_url).connect() as connection:
            connection.execute(text("SELECT 1"))
            for table in Base.metadata.sorted_tables:
                connection.execute(select(literal(1)).select_from(table).limit(1))
        return {"status": "ready"}

    @app.get("/api/me", response_model=IdentityOutput)
    def me(principal: User) -> dict:
        return asdict(principal)

    @app.get("/api/models", response_model=Page[CatalogOutput])
    def models(principal: User) -> dict:
        if not settings.catalog_configured:
            raise HTTPException(503, "Model catalog has not passed gateway capability validation")
        try:
            catalog = Catalog.load(settings.catalog_path)
        except (OSError, ValueError, ValidationError) as exc:
            log.error("Catalog configuration invalid type=%s", type(exc).__name__)
            raise HTTPException(503, "Model catalog is unavailable") from exc
        if settings.gateway_max_completion_tokens is not None:
            for model in catalog.models:
                if model.max_completion_tokens is not None:
                    model.max_completion_tokens = min(
                        model.max_completion_tokens, settings.gateway_max_completion_tokens
                    )
        items = [
            model.model_dump(
                include={"id", "provider", "capabilities", "enabled", "placeholder", "max_completion_tokens"}
            )
            for model in catalog.models
            if model.enabled or model.placeholder
        ]
        return {"items": items, "total": len(items)}

    @app.get("/api/subscriptions", response_model=Page[SubscriptionOutput])
    def subscriptions(
        principal: User,
        db: Db,
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=100),
    ) -> dict:
        condition = TeamSubscription.organization_id == principal.organization_id
        items = db.scalars(
            select(TeamSubscription)
            .where(condition)
            .order_by(
                TeamSubscription.created_at.desc(),
                TeamSubscription.id,
            )
            .offset(offset)
            .limit(limit)
        ).all()
        return {
            "items": [subscription_dict(row) for row in items],
            "total": db.scalar(select(func.count()).select_from(TeamSubscription).where(condition)),
        }

    @app.post("/api/subscriptions", status_code=201, response_model=SubscriptionOutput)
    def new_subscription(
        payload: SubscriptionCreate,
        principal: User,
        db: Db,
        apim: Apim,
        idempotency_key: UUID = Header(alias="Idempotency-Key"),
    ) -> dict:
        return subscription_dict(create_subscription(db, principal, payload, idempotency_key, apim))

    @app.post("/api/subscriptions/{sid}/reveal")
    def reveal(sid: UUID, payload: KeyRequest, principal: User, db: Db, apim: Apim) -> dict:
        lock_organization(db, principal.organization_id)
        row = owned(db, sid, principal)
        if row.state != "active":
            raise HTTPException(409, "Only active subscriptions can reveal keys")
        audit(db, principal, f"subscription.reveal.{payload.key}", row.id)
        db.flush()
        secret = apim.reveal(row.id, payload.key)
        db.commit()
        return {"key": secret}

    @app.post("/api/subscriptions/{sid}/rotate")
    def rotate(sid: UUID, payload: KeyRequest, principal: User, db: Db, apim: Apim) -> dict:
        lock_organization(db, principal.organization_id)
        row = owned(db, sid, principal)
        if row.state not in ("active", "suspended"):
            raise HTTPException(409, "Reconcile the subscription before rotating")
        audit(db, principal, f"subscription.rotate.{payload.key}", row.id)
        db.flush()
        apim.rotate(row.id, payload.key)
        db.commit()
        return {"state": row.state}

    @app.put("/api/subscriptions/{sid}/state", response_model=SubscriptionOutput)
    def subscription_state(sid: UUID, payload: StateRequest, principal: User, db: Db, apim: Apim) -> dict:
        lock_organization(db, principal.organization_id)
        row = owned(db, sid, principal)
        row.desired_state = payload.state
        row.state = "pending"
        audit(db, principal, "subscription.state.requested", row.id)
        db.commit()
        reconcile(db, row, apim, principal)
        return subscription_dict(row)

    @app.post("/api/subscriptions/{sid}/reconcile", response_model=SubscriptionOutput)
    def subscription_reconcile(sid: UUID, principal: User, db: Db, apim: Apim) -> dict:
        lock_organization(db, principal.organization_id)
        row = owned(db, sid, principal)
        reconcile(db, row, apim, principal)
        return subscription_dict(row)

    def usage(
        db: Session,
        organization_id: str | None,
        days: int,
        subscription_id: UUID | None,
        offset: int,
        limit: int,
    ) -> dict:
        if subscription_id is not None and organization_id is not None:
            row = db.get(TeamSubscription, str(subscription_id))
            if row is None or row.organization_id != organization_id:
                raise HTTPException(404, "Subscription not found")
        return usage_response(
            db, organization_id, days, str(subscription_id) if subscription_id else None, offset, limit
        )

    @app.get("/api/usage", response_model=UsagePage)
    def customer_usage(
        principal: User,
        db: Db,
        days: int = Query(30, ge=1, le=366),
        subscription_id: UUID | None = None,
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=100),
    ) -> dict:
        return usage(db, principal.organization_id, days, subscription_id, offset, limit)

    def export(db: Session, org: str | None, days: int, subscription_id: UUID | None) -> Response:
        usage(db, org, days, subscription_id, 0, 1)
        try:
            content = usage_csv(db, org, days, str(subscription_id) if subscription_id else None)
        except ValueError as exc:
            raise HTTPException(413, str(exc)) from exc
        return Response(
            content,
            media_type="text/csv",
            headers={
                "Content-Disposition": 'attachment; filename="aiflux-usage.csv"',
            },
        )

    @app.get("/api/usage/export")
    def customer_export(
        principal: User,
        db: Db,
        days: int = Query(30, ge=1, le=366),
        subscription_id: UUID | None = None,
    ) -> Response:
        return export(db, principal.organization_id, days, subscription_id)

    @app.get("/api/admin/usage", response_model=UsagePage)
    def admin_usage(
        principal: Admin,
        db: Db,
        days: int = Query(30, ge=1, le=366),
        organization_id: UUID | None = None,
        subscription_id: UUID | None = None,
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=100),
    ) -> dict:
        return usage(
            db, str(organization_id) if organization_id else None, days, subscription_id, offset, limit
        )

    @app.get("/api/admin/usage/export")
    def admin_export(
        principal: Admin,
        db: Db,
        days: int = Query(30, ge=1, le=366),
        organization_id: UUID | None = None,
        subscription_id: UUID | None = None,
    ) -> Response:
        return export(db, str(organization_id) if organization_id else None, days, subscription_id)

    @app.get("/api/admin/organizations", response_model=Page[OrganizationOutput])
    def organizations(principal: Admin, db: Db) -> dict:
        rows = db.scalars(select(Organization).order_by(Organization.name)).all()
        return {
            "items": [entity_dict(row, ("id", "name", "tenant_id", "enabled")) for row in rows],
            "total": len(rows),
        }

    @app.post("/api/admin/organizations", status_code=201, response_model=OrganizationOutput)
    def add_organization(payload: OrganizationCreate, principal: Admin, db: Db) -> dict:
        org = Organization(name=payload.name, tenant_id=str(payload.tenant_id))
        db.add(org)
        db.flush()
        audit(db, principal, "organization.created", org.id)
        db.commit()
        return entity_dict(org, ("id", "name", "tenant_id", "enabled"))

    @app.put("/api/admin/organizations/{oid}", response_model=OrganizationOutput)
    def enable_organization(oid: UUID, payload: EnabledRequest, principal: Admin, db: Db, apim: Apim) -> dict:
        org = db.scalar(
            select(Organization)
            .where(Organization.id == str(oid))
            .with_hint(
                Organization,
                "WITH (UPDLOCK, HOLDLOCK)",
                dialect_name="mssql",
            )
        )
        if org is None:
            raise HTTPException(404, "Organization not found")
        if org.id == principal.organization_id and not payload.enabled:
            raise HTTPException(409, "Cannot disable your own IDS organization")
        org.enabled = payload.enabled
        audit(db, principal, "organization.enabled" if payload.enabled else "organization.disabled", org.id)
        if not payload.enabled:
            rows = db.scalars(
                select(TeamSubscription).where(TeamSubscription.organization_id == org.id)
            ).all()
            for row in rows:
                row.desired_state = "suspended"
                row.state = "pending"
            db.commit()
            for row in rows:
                current_org = db.scalar(
                    select(Organization)
                    .where(Organization.id == org.id)
                    .with_hint(Organization, "WITH (UPDLOCK, HOLDLOCK)", dialect_name="mssql")
                    .execution_options(populate_existing=True)
                )
                if current_org is None or current_org.enabled:
                    raise HTTPException(409, "Organization state changed during key suspension")
                try:
                    apim.ensure(row.id, row.name, "suspended")
                except ApimError as exc:
                    row.state = "failed"
                    db.commit()
                    log.warning("Organization suspension incomplete organization=%s", org.id)
                    raise HTTPException(
                        502,
                        "Portal access disabled; key suspension incomplete. Retry disable.",
                    ) from exc
                row.state = "suspended"
                db.commit()
        else:
            db.commit()
        return entity_dict(org, ("id", "name", "tenant_id", "enabled"))

    @app.get("/api/admin/members", response_model=Page[MemberOutput])
    def members(organization_id: UUID, principal: Admin, db: Db) -> dict:
        rows = db.scalars(select(Member).where(Member.organization_id == str(organization_id))).all()
        return {
            "items": [
                entity_dict(row, ("id", "organization_id", "object_id", "role", "enabled")) for row in rows
            ],
            "total": len(rows),
        }

    @app.post("/api/admin/members", status_code=201, response_model=MemberOutput)
    def add_member(payload: MemberCreate, principal: Admin, db: Db) -> dict:
        org = db.get(Organization, str(payload.organization_id))
        if org is None:
            raise HTTPException(404, "Organization not found")
        if payload.role == "ids_admin" and org.tenant_id != settings.home_tenant_id:
            raise HTTPException(422, "IDS roles can only be granted within the home tenant")
        member = Member(organization_id=org.id, object_id=str(payload.object_id), role=payload.role)
        db.add(member)
        db.flush()
        audit(db, principal, "member.approved", member.id)
        db.commit()
        return entity_dict(member, ("id", "organization_id", "object_id", "role", "enabled"))

    @app.put("/api/admin/members/{mid}", response_model=MemberOutput)
    def enable_member(mid: UUID, payload: EnabledRequest, principal: Admin, db: Db) -> dict:
        member = db.get(Member, str(mid))
        if member is None:
            raise HTTPException(404, "Member not found")
        if member.organization_id == principal.organization_id and member.object_id == principal.object_id:
            raise HTTPException(409, "Cannot disable your own administrator membership")
        member.enabled = payload.enabled
        audit(db, principal, "member.enabled" if payload.enabled else "member.disabled", member.id)
        db.commit()
        return entity_dict(member, ("id", "organization_id", "object_id", "role", "enabled"))

    @app.get("/api/admin/safety", response_model=Page[SafetyOutput])
    def safety(
        principal: Admin,
        db: Db,
        days: int = Query(30, ge=1, le=366),
        organization_id: UUID | None = None,
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=100),
    ) -> dict:
        conditions = [SafetyEvent.occurred_at >= datetime.now(UTC) - timedelta(days=days)]
        if organization_id is not None:
            conditions.append(SafetyEvent.organization_id == str(organization_id))
        rows = db.scalars(
            select(SafetyEvent)
            .where(*conditions)
            .order_by(
                SafetyEvent.occurred_at.desc(),
                SafetyEvent.id,
            )
            .offset(offset)
            .limit(limit)
        ).all()
        return {
            "items": [
                entity_dict(
                    row, ("id", "organization_id", "subscription_id", "category", "action", "correlation_id")
                )
                | {"occurred_at": aware(row.occurred_at).isoformat()}
                for row in rows
            ],
            "total": db.scalar(select(func.count()).select_from(SafetyEvent).where(*conditions)),
        }

    @app.get("/api/admin/prices", response_model=Page[PriceOutput])
    def prices(principal: Admin, db: Db) -> dict:
        rows = db.scalars(select(ModelPrice).order_by(ModelPrice.effective_from.desc())).all()
        return {"items": [price_dict(row) for row in rows], "total": len(rows)}

    @app.post("/api/admin/prices", status_code=201, response_model=PriceOutput)
    def add_price(payload: PriceCreate, principal: Admin, db: Db) -> dict:
        try:
            row, _ = create_price(db, payload)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        audit(db, principal, "price.created", row.id)
        db.commit()
        return price_dict(row)

    @app.put("/api/admin/prices/{pid}/end", response_model=PriceOutput)
    def end_price(pid: UUID, payload: PriceEnd, principal: Admin, db: Db) -> dict:
        row = db.scalar(
            select(ModelPrice)
            .where(ModelPrice.id == str(pid))
            .with_hint(ModelPrice, "WITH (UPDLOCK, HOLDLOCK)", dialect_name="mssql")
        )
        if row is None:
            raise HTTPException(404, "Price not found")
        if row.effective_to is not None or payload.effective_to <= aware(row.effective_from):
            raise HTTPException(409, "Only an open period can be closed after its effective start")
        row.effective_to = payload.effective_to
        audit(db, principal, "price.period.closed", row.id)
        db.commit()
        return price_dict(row)

    return app


def price_dict(row: ModelPrice) -> dict:
    values = entity_dict(row, ("id", "model", "provider", "region", "currency", "input_includes_cached"))
    for name in (
        "input_per_million",
        "output_per_million",
        "cached_input_per_million",
        "cache_write_per_million",
    ):
        value = getattr(row, name)
        values[name] = str(value) if value is not None else None
    values["effective_from"] = aware(row.effective_from).isoformat()
    values["effective_to"] = aware(row.effective_to).isoformat() if row.effective_to else None
    return values


app = create_app()
