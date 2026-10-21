from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import httpx
import jwt
import pytest
from aiflux.app import create_app
from aiflux.auth import MISE_SKU, MISE_VERSION, TokenVerifier
from aiflux.config import Settings
from aiflux.db import engine_for
from aiflux.models import Base, Member, Organization
from conftest import CUSTOMER, CUSTOMER_USER, FakeApim
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

TEST_APP_ID = "00000000-0000-4000-8000-000000000003"


def test_mise_telemetry_headers_contain_version_sku_and_client_id():
    settings = Settings(
        entra_audience="api://aiflux-test",
        entra_client_id=TEST_APP_ID,
        home_tenant_id="11111111-1111-4111-8111-111111111111",
    )
    verifier = TokenVerifier(settings)
    headers = verifier._mise_headers()

    assert headers["User-Agent"] == f"{MISE_SKU}/{MISE_VERSION}"
    assert headers["x-client-SKU"] == MISE_SKU
    assert headers["x-client-VER"] == MISE_VERSION
    assert headers["x-app-id"] == TEST_APP_ID
    assert headers["x-client-current-telemetry"] == f"2|1001,0|{TEST_APP_ID},0|"


def test_direct_key_discovery_uses_mise_headers(monkeypatch):
    settings = Settings(
        entra_audience="api://aiflux-test",
        entra_client_id=TEST_APP_ID,
        home_tenant_id="11111111-1111-4111-8111-111111111111",
    )
    verifier = TokenVerifier(settings)

    captured_headers = {}

    def mock_jwk_client_init(self, uri, **kwargs):
        captured_headers.update(kwargs.get("headers", {}))
        self.uri = uri

    monkeypatch.setattr("aiflux.auth.PyJWKClient.__init__", mock_jwk_client_init)
    mock_key = MagicMock()
    monkeypatch.setattr(
        "aiflux.auth.PyJWKClient.get_signing_key_from_jwt",
        lambda self, token: MagicMock(key=mock_key),
    )
    monkeypatch.setattr("jwt.decode", lambda *args, **kwargs: {"ok": True})

    verifier.verify("sample.jwt.token", "11111111-1111-4111-8111-111111111111")
    assert captured_headers["x-client-SKU"] == "MISE_Python"
    assert captured_headers["x-client-VER"] == "2.4.1"
    assert captured_headers["x-app-id"] == TEST_APP_ID


def test_mise_sidecar_validation_success():
    settings = Settings(
        entra_audience="api://aiflux-test",
        entra_client_id=TEST_APP_ID,
        home_tenant_id="11111111-1111-4111-8111-111111111111",
        mise_validation_endpoint="http://127.0.0.1:8081/Validate",
    )
    now = datetime.now(UTC)
    claims = {
        "tid": CUSTOMER,
        "oid": CUSTOMER_USER,
        "iss": f"https://login.microsoftonline.com/{CUSTOMER}/v2.0",
        "aud": settings.entra_audience,
        "exp": (now + timedelta(minutes=10)).timestamp(),
        "iat": now.timestamp(),
        "nbf": now.timestamp(),
        "scp": "access_as_user",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://127.0.0.1:8081/Validate"
        assert request.headers["Authorization"] == "Bearer test-token-123"
        assert request.headers["x-client-SKU"] == "MISE_Python"
        assert request.headers["x-client-VER"] == "2.4.1"
        assert request.headers["x-app-id"] == TEST_APP_ID
        return httpx.Response(200, json={"claims": claims})

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    verifier = TokenVerifier(settings, http_client=http_client)

    verified = verifier.verify("test-token-123", CUSTOMER)
    assert verified["oid"] == CUSTOMER_USER
    assert verified["tid"] == CUSTOMER


def test_mise_sidecar_validation_expired_token():
    settings = Settings(
        entra_audience="api://aiflux-test",
        entra_client_id=TEST_APP_ID,
        home_tenant_id="11111111-1111-4111-8111-111111111111",
        mise_validation_endpoint="http://127.0.0.1:8081/Validate",
    )
    now = datetime.now(UTC)
    expired_claims = {
        "tid": CUSTOMER,
        "oid": CUSTOMER_USER,
        "iss": f"https://login.microsoftonline.com/{CUSTOMER}/v2.0",
        "aud": settings.entra_audience,
        "exp": (now - timedelta(minutes=5)).timestamp(),
    }

    transport = httpx.MockTransport(lambda req: httpx.Response(200, json={"claims": expired_claims}))
    verifier = TokenVerifier(settings, http_client=httpx.Client(transport=transport))

    with pytest.raises(jwt.ExpiredSignatureError):
        verifier.verify("expired-token", CUSTOMER)


def test_mise_sidecar_validation_audience_and_issuer_checks():
    settings = Settings(
        entra_audience="api://aiflux-test",
        entra_client_id=TEST_APP_ID,
        home_tenant_id="11111111-1111-4111-8111-111111111111",
        mise_validation_endpoint="http://127.0.0.1:8081/Validate",
    )
    now = datetime.now(UTC)
    base_claims = {
        "tid": CUSTOMER,
        "oid": CUSTOMER_USER,
        "iss": f"https://login.microsoftonline.com/{CUSTOMER}/v2.0",
        "aud": settings.entra_audience,
        "exp": (now + timedelta(minutes=10)).timestamp(),
    }

    # Wrong audience
    bad_aud = {**base_claims, "aud": "api://wrong"}
    verifier = TokenVerifier(
        settings,
        http_client=httpx.Client(
            transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"claims": bad_aud}))
        ),
    )
    with pytest.raises(jwt.InvalidAudienceError):
        verifier.verify("token", CUSTOMER)

    # Wrong issuer
    bad_iss = {**base_claims, "iss": "https://login.microsoftonline.com/wrong/v2.0"}
    verifier = TokenVerifier(
        settings,
        http_client=httpx.Client(
            transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"claims": bad_iss}))
        ),
    )
    with pytest.raises(jwt.InvalidIssuerError):
        verifier.verify("token", CUSTOMER)


def test_mise_sidecar_validation_rejection_and_errors():
    settings = Settings(
        entra_audience="api://aiflux-test",
        entra_client_id=TEST_APP_ID,
        home_tenant_id="11111111-1111-4111-8111-111111111111",
        mise_validation_endpoint="http://127.0.0.1:8081/Validate",
    )

    # 401 Unauthorized from sidecar
    transport_401 = httpx.MockTransport(lambda req: httpx.Response(401, json={"error": "invalid_token"}))
    verifier = TokenVerifier(settings, http_client=httpx.Client(transport=transport_401))
    with pytest.raises(jwt.PyJWTError):
        verifier.verify("token", CUSTOMER)

    # Sidecar unreachable / connection failure
    def failing_transport(req):
        raise httpx.ConnectError("Connection refused to 127.0.0.1:8081")

    mock_transport = httpx.MockTransport(failing_transport)
    verifier = TokenVerifier(settings, http_client=httpx.Client(transport=mock_transport))
    with pytest.raises(jwt.PyJWKClientConnectionError):
        verifier.verify("token", CUSTOMER)


def test_end_to_end_control_plane_with_mise_sidecar(tmp_path):
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        '{"models":[{"id":"test-alias","provider":"test","capabilities":'
        '["chat","stream"],"enabled":true,"backend_model":"test-model","region":"test-region"}]}'
    )
    db_file = tmp_path / "test.db"
    settings = Settings(
        environment="testing",
        database_url=f"sqlite:///{db_file}",
        entra_audience="api://aiflux-test",
        entra_client_id=TEST_APP_ID,
        home_tenant_id="11111111-1111-4111-8111-111111111111",
        catalog_path=catalog,
        catalog_configured=True,
        apim_resource_id="/subscriptions/11111111-1111-4111-8111-111111111111/"
        "resourceGroups/test/providers/Microsoft.ApiManagement/service/test",
        log_workspace_id="11111111-1111-4111-8111-111111111111",
        mise_validation_endpoint="http://127.0.0.1:8081/Validate",
    )

    engine = engine_for(settings.database_url)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        customer_org = Organization(name="Customer", tenant_id=CUSTOMER)
        db.add(customer_org)
        db.flush()
        db.add(Member(organization_id=customer_org.id, object_id=CUSTOMER_USER, role="customer"))
        db.commit()

    now = datetime.now(UTC)
    claims = {
        "tid": CUSTOMER,
        "oid": CUSTOMER_USER,
        "iss": f"https://login.microsoftonline.com/{CUSTOMER}/v2.0",
        "aud": settings.entra_audience,
        "exp": (now + timedelta(minutes=10)).timestamp(),
        "iat": now.timestamp(),
        "nbf": now.timestamp(),
        "scp": "access_as_user",
    }

    mock_client = httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"claims": claims}))
    )

    app = create_app(settings)
    app.state.token_verifier = TokenVerifier(settings, http_client=mock_client)
    app.state.apim = FakeApim()

    raw_token = jwt.encode(
        {"tid": CUSTOMER, "oid": CUSTOMER_USER},
        "dummy-secret",
        algorithm="HS256",
    )

    with TestClient(app) as client:
        resp = client.get("/api/me", headers={"Authorization": f"Bearer {raw_token}"})
        assert resp.status_code == 200
        assert resp.json()["organization_id"] == customer_org.id
        assert resp.json()["role"] == "customer"
