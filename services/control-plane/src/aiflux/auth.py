from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
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

MISE_VERSION = "2.4.1"
MISE_SKU = "MISE_Python"


@dataclass(frozen=True)
class Principal:
    organization_id: str
    organization_name: str
    tenant_id: str
    object_id: str
    role: str


class TokenVerifier:
    def __init__(self, settings: Settings, http_client: httpx.Client | None = None):
        self.settings = settings
        self.clients: dict[str, PyJWKClient] = {}
        self._http_client = http_client

    @property
    def http_client(self) -> httpx.Client:
        if self._http_client is None:
            self._http_client = httpx.Client(timeout=10.0)
        return self._http_client

    def _mise_headers(self) -> dict[str, str]:
        client_id = self.settings.entra_client_id or ""
        return {
            "User-Agent": f"{MISE_SKU}/{MISE_VERSION}",
            "x-client-SKU": MISE_SKU,
            "x-client-VER": MISE_VERSION,
            "x-app-id": client_id,
            "x-client-current-telemetry": f"2|1001,0|{client_id},0|",
        }

    def verify_via_sidecar(self, token: str, tenant_id: str) -> dict[str, Any]:
        endpoint = self.settings.mise_validation_endpoint
        if not endpoint:
            raise ValueError("MISE validation endpoint is not configured")
        try:
            resp = self.http_client.get(
                endpoint,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "User-Agent": f"{MISE_SKU}/{MISE_VERSION}",
                    "x-client-SKU": MISE_SKU,
                    "x-client-VER": MISE_VERSION,
                    "x-app-id": self.settings.entra_client_id or "",
                },
            )
        except (httpx.RequestError, httpx.HTTPError) as exc:
            raise jwt.PyJWKClientConnectionError("MISE validation sidecar temporarily unavailable") from exc

        if resp.status_code == 200:
            try:
                data = resp.json()
            except Exception as exc:
                raise jwt.PyJWTError("Invalid JSON response from MISE sidecar") from exc

            claims = data.get("claims", data) if isinstance(data, dict) else None
            if not isinstance(claims, dict):
                raise jwt.PyJWTError("Invalid claims structure returned by MISE sidecar")

            for claim in ("exp", "iss", "aud", "tid", "oid"):
                if claim not in claims:
                    raise jwt.MissingRequiredClaimError(f"Missing required claim: {claim}")

            now_ts = datetime.now(UTC).timestamp()
            if isinstance(claims.get("exp"), int | float) and claims["exp"] < now_ts:
                raise jwt.ExpiredSignatureError("Token has expired")

            if claims.get("aud") != self.settings.entra_audience:
                raise jwt.InvalidAudienceError("Audience does not match configured entra_audience")

            expected_issuer = f"https://login.microsoftonline.com/{tenant_id}/v2.0"
            if claims.get("iss") != expected_issuer:
                raise jwt.InvalidIssuerError("Issuer does not match expected tenant issuer")

            return claims
        elif resp.status_code in (401, 403, 400):
            raise jwt.PyJWTError(f"MISE sidecar rejected access token with status {resp.status_code}")
        else:
            raise jwt.PyJWKClientConnectionError(
                f"MISE sidecar returned unexpected HTTP status {resp.status_code}"
            )

    def verify(self, token: str, tenant_id: str) -> dict[str, Any]:
        if self.settings.mise_validation_endpoint:
            return self.verify_via_sidecar(token, tenant_id)

        issuer = f"https://login.microsoftonline.com/{tenant_id}/v2.0"
        client = self.clients.setdefault(
            tenant_id,
            PyJWKClient(
                f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys",
                timeout=10,
                headers=self._mise_headers(),
            ),
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
