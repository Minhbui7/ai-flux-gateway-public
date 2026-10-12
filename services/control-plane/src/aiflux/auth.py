from dataclasses import dataclass
from typing import Any
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from sqlalchemy import select, true
from sqlalchemy.orm import Session

from aiflux.config import Settings
from aiflux.db import get_db
from aiflux.models import Member, Organization

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    organization_id: str
    organization_name: str
    tenant_id: str
    object_id: str
    role: str


class TokenVerifier:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.clients: dict[str, PyJWKClient] = {}

    def verify(self, token: str, tenant_id: str) -> dict[str, Any]:
        issuer = f"https://login.microsoftonline.com/{tenant_id}/v2.0"
        client = self.clients.setdefault(
            tenant_id,
            PyJWKClient(f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys", timeout=10),
        )
        key = client.get_signing_key_from_jwt(token).key
        return jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=self.settings.entra_audience,
            issuer=issuer,
            options={"require": ["exp", "iat", "nbf", "iss", "aud", "tid", "oid"]},
        )


def get_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> Principal:
    if credentials is None:
        raise HTTPException(401, "Access token required", headers={"WWW-Authenticate": "Bearer"})
    token = credentials.credentials
    try:
        hints = jwt.decode(token, options={"verify_signature": False})
        tenant_id = str(UUID(hints["tid"]))
        object_id = str(UUID(hints["oid"]))
    except (jwt.PyJWTError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(401, "Invalid access token") from exc
    org = db.scalar(
        select(Organization).where(
            Organization.tenant_id == tenant_id,
            Organization.enabled == true(),
        )
    )
    if org is None:
        raise HTTPException(403, "Tenant is not approved")
    try:
        claims = request.app.state.token_verifier.verify(token, tenant_id)
    except jwt.PyJWKClientConnectionError as exc:
        raise HTTPException(503, "Identity signing keys temporarily unavailable") from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(401, "Invalid access token") from exc
    if claims.get("tid") != tenant_id or claims.get("oid") != object_id:
        raise HTTPException(401, "Invalid access token identity")
    settings: Settings = request.app.state.settings
    if settings.required_scope not in str(claims.get("scp", "")).split():
        raise HTTPException(403, "Required delegated API scope is missing")
    member = db.scalar(
        select(Member).where(
            Member.organization_id == org.id,
            Member.object_id == object_id,
            Member.enabled == true(),
        )
    )
    if member is None:
        raise HTTPException(403, "User is not approved")
    if member.role == "ids_admin" and tenant_id != settings.home_tenant_id:
        raise HTTPException(403, "IDS administrators must belong to the home tenant")
    return Principal(org.id, org.name, tenant_id, object_id, member.role)


def get_admin(principal: Principal = Depends(get_principal)) -> Principal:
    if principal.role != "ids_admin":
        raise HTTPException(403, "IDS administrator role required")
    return principal
