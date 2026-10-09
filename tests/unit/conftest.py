from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from aiflux.app import create_app
from aiflux.config import Settings
from aiflux.db import engine_for
from aiflux.models import Base, Member, Organization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

HOME = "11111111-1111-4111-8111-111111111111"
CUSTOMER = "22222222-2222-4222-8222-222222222222"
ADMIN_USER = "33333333-3333-4333-8333-333333333333"
CUSTOMER_USER = "44444444-4444-4444-8444-444444444444"


class FakeApim:
    def __init__(self):
        self.calls = []
        self.fail = False

    def ensure(self, sid, name, state):
        self.calls.append(("ensure", sid, state))
        self._check()

    def set_state(self, sid, state):
        self.calls.append(("state", sid, state))
        self._check()

    def _check(self):
        from aiflux.apim import ApimError

        if self.fail:
            raise ApimError(429)

    def reveal(self, sid, key):
        self.calls.append(("reveal", sid, key))
        self._check()
        return "synthetic-test-key"

    def rotate(self, sid, key):
        self.calls.append(("rotate", sid, key))
        self._check()


@pytest.fixture
def env(tmp_path):
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        '{"models":[{"id":"test-alias","provider":"test","capabilities":'
        '["chat","stream"],"enabled":true,"backend_model":"test-model","region":"test-region"}]}'
    )
    settings = Settings(
        environment="testing",
        database_url="sqlite:///:memory:",
        entra_audience="api://aiflux-test",
        home_tenant_id=HOME,
        catalog_path=catalog,
        catalog_configured=True,
        apim_resource_id="/subscriptions/11111111-1111-4111-8111-111111111111/"
        "resourceGroups/test/providers/Microsoft.ApiManagement/service/test",
        log_workspace_id=HOME,
    )
    engine = engine_for(settings.database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        admin_org = Organization(name="IDS", tenant_id=HOME)
        customer_org = Organization(name="Customer", tenant_id=CUSTOMER)
        db.add_all([admin_org, customer_org])
        db.flush()
        db.add_all(
            [
                Member(organization_id=admin_org.id, object_id=ADMIN_USER, role="ids_admin"),
                Member(organization_id=customer_org.id, object_id=CUSTOMER_USER, role="customer"),
            ]
        )
        db.commit()
        orgs = {"admin": admin_org.id, "customer": customer_org.id}
    app = create_app(settings)
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    for tenant in (HOME, CUSTOMER):
        app.state.token_verifier.clients[tenant] = SimpleNamespace(
            get_signing_key_from_jwt=lambda token: SimpleNamespace(key=private.public_key()),
        )
    fake = FakeApim()
    app.state.apim = fake

    def token(tenant=CUSTOMER, object_id=CUSTOMER_USER, **overrides):
        now = datetime.now(UTC)
        claims = {
            "tid": tenant,
            "oid": object_id,
            "iss": f"https://login.microsoftonline.com/{tenant}/v2.0",
            "aud": settings.entra_audience,
            "exp": now + timedelta(minutes=5),
            "iat": now,
            "nbf": now,
            "scp": "access_as_user",
        } | overrides
        return {
            "Authorization": "Bearer "
            + jwt.encode(claims, private, algorithm="RS256", headers={"kid": "test"})
        }

    with TestClient(app) as client:
        yield SimpleNamespace(
            client=client,
            db_engine=engine,
            settings=settings,
            apim=fake,
            token=token,
            customer=token(),
            admin=token(HOME, ADMIN_USER),
            orgs=orgs,
            app=app,
            idempotency=lambda: str(uuid4()),
        )
