from datetime import UTC, datetime, timedelta
from uuid import uuid4

from aiflux.app import create_app
from aiflux.config import Settings
from aiflux.models import AuditEvent, Member, TeamSubscription
from conftest import CUSTOMER_USER
from sqlalchemy import select
from sqlalchemy.orm import Session


def create_key(env, name="Platform"):
    response = env.client.post(
        "/api/subscriptions",
        json={"name": name, "team": "Engineering"},
        headers=env.customer | {"Idempotency-Key": env.idempotency()},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_unconfigured_server_is_fail_closed():
    from fastapi.testclient import TestClient

    with TestClient(create_app(Settings())) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 503
        assert client.get("/api/me").status_code == 503


def test_identity_membership_and_admin_isolation(env):
    assert env.client.get("/api/me").status_code == 401
    me = env.client.get("/api/me", headers=env.customer)
    assert me.status_code == 200
    assert me.json()["organization_id"] == env.orgs["customer"]
    assert env.client.get("/api/admin/organizations", headers=env.customer).status_code == 403
    assert env.client.get("/api/admin/organizations", headers=env.admin).status_code == 200
    assert env.client.get("/api/me", headers=env.token(object_id=str(uuid4()))).status_code == 403
    assert env.client.get("/api/me", headers=env.token(tenant=str(uuid4()))).status_code == 403


def test_issuer_audience_scope_and_expiry_are_verified(env):
    for override, expected in [
        ({"aud": "different"}, 401),
        ({"iss": "https://attacker.invalid"}, 401),
        ({"exp": datetime.now(UTC) - timedelta(minutes=5)}, 401),
        ({"scp": "different"}, 403),
    ]:
        assert env.client.get("/api/me", headers=env.token(**override)).status_code == expected


def test_customer_tenant_cannot_hold_ids_role(env):
    with Session(env.db_engine) as db:
        member = db.scalar(select(Member).where(Member.object_id == CUSTOMER_USER))
        member.role = "ids_admin"
        db.commit()
    assert env.client.get("/api/admin/organizations", headers=env.customer).status_code == 403


def test_catalog_requires_explicit_validation(env):
    assert env.client.get("/api/models", headers=env.customer).json()["items"][0]["id"] == "test-alias"
    env.settings.catalog_configured = False
    assert env.client.get("/api/models", headers=env.customer).status_code == 503


def test_idempotent_subscription_and_conflicting_replay(env):
    headers = env.customer | {"Idempotency-Key": env.idempotency()}
    payload = {"name": "Platform", "team": "Team"}
    first = env.client.post("/api/subscriptions", headers=headers, json=payload)
    second = env.client.post("/api/subscriptions", headers=headers, json=payload)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert len(env.apim.calls) == 1
    assert (
        env.client.post("/api/subscriptions", headers=headers, json=payload | {"team": "Other"}).status_code
        == 409
    )
    assert env.client.post("/api/subscriptions", headers=env.customer, json=payload).status_code == 422


def test_provision_failure_is_visible_and_recoverable(env):
    env.apim.fail = True
    headers = env.customer | {"Idempotency-Key": env.idempotency()}
    body = {"name": "Team", "team": "Team"}
    assert env.client.post("/api/subscriptions", json=body, headers=headers).status_code == 502
    listed = env.client.get("/api/subscriptions", headers=env.customer).json()
    assert listed["items"][0]["state"] == "failed"
    env.apim.fail = False
    retry = env.client.post("/api/subscriptions", json=body, headers=headers)
    assert retry.status_code == 201 and retry.json()["state"] == "active"


def test_keys_reveal_rotate_suspend_and_cross_org_denial(env):
    row = create_key(env)
    sid = row["id"]
    for action in ("reveal", "rotate"):
        response = env.client.post(
            f"/api/subscriptions/{sid}/{action}", json={"key": "primary"}, headers=env.admin
        )
        assert response.status_code == 404
    revealed = env.client.post(f"/api/subscriptions/{sid}/reveal", headers=env.customer, json={})
    assert revealed.status_code == 200
    assert revealed.headers["cache-control"] == "no-store"
    assert revealed.json()["key"] == "synthetic-test-key"
    assert (
        env.client.post(
            f"/api/subscriptions/{sid}/rotate", headers=env.customer, json={"key": "secondary"}
        ).status_code
        == 200
    )
    assert (
        env.client.put(
            f"/api/subscriptions/{sid}/state", headers=env.customer, json={"state": "suspended"}
        ).json()["state"]
        == "suspended"
    )
    assert (
        env.client.post(f"/api/subscriptions/{sid}/reveal", headers=env.customer, json={}).status_code == 409
    )
    with Session(env.db_engine) as db:
        assert "synthetic-test-key" not in repr(db.scalars(select(AuditEvent)).all())
        assert not any(
            "key" in column.name
            for column in TeamSubscription.__table__.columns
            if column.name != "idempotency_key"
        )


def test_org_disable_suspends_team_keys_and_membership(env):
    row = create_key(env)
    response = env.client.put(
        f"/api/admin/organizations/{env.orgs['customer']}", headers=env.admin, json={"enabled": False}
    )
    assert response.status_code == 200
    assert ("ensure", row["id"], "suspended") in env.apim.calls
    assert env.client.get("/api/me", headers=env.customer).status_code == 403
    assert (
        env.client.put(
            f"/api/admin/organizations/{env.orgs['admin']}", headers=env.admin, json={"enabled": False}
        ).status_code
        == 409
    )


def test_org_disable_partial_failure_explicit_and_retryable(env):
    create_key(env)
    env.apim.fail = True
    path = f"/api/admin/organizations/{env.orgs['customer']}"
    assert env.client.put(path, headers=env.admin, json={"enabled": False}).status_code == 502
    assert env.client.get("/api/me", headers=env.customer).status_code == 403
    env.apim.fail = False
    assert env.client.put(path, headers=env.admin, json={"enabled": False}).status_code == 200


def test_organization_and_membership_admin_api(env):
    response = env.client.post(
        "/api/admin/organizations", headers=env.admin, json={"name": "Opco", "tenant_id": str(uuid4())}
    )
    assert response.status_code == 201
    oid = response.json()["id"]
    response = env.client.post(
        "/api/admin/members",
        headers=env.admin,
        json={"organization_id": oid, "object_id": str(uuid4()), "role": "ids_admin"},
    )
    assert response.status_code == 422
    member = env.client.post(
        "/api/admin/members", headers=env.admin, json={"organization_id": oid, "object_id": str(uuid4())}
    )
    assert member.status_code == 201
    assert env.client.get(f"/api/admin/members?organization_id={oid}", headers=env.admin).json()["total"] == 1
    assert (
        env.client.put(
            f"/api/admin/members/{member.json()['id']}", headers=env.admin, json={"enabled": False}
        ).json()["enabled"]
        is False
    )


def test_customer_usage_and_exports_are_organization_scoped(env):
    row = create_key(env)
    query = f"?subscription_id={row['id']}"
    assert env.client.get("/api/usage" + query, headers=env.customer).status_code == 200
    assert env.client.get("/api/usage" + query, headers=env.admin).status_code == 404
    assert env.client.get("/api/usage/export" + query, headers=env.admin).status_code == 404
    export = env.client.get("/api/usage/export", headers=env.customer)
    assert export.status_code == 200 and "subscription_id" in export.text
    summary = env.client.get("/api/usage", headers=env.customer).json()["summary"]
    assert summary["known_cost"] is None and summary["ttft_supported"] is False


def test_price_input_boundaries_and_overlaps(env):
    start = datetime.now(UTC)
    payload = {
        "model": "test-alias",
        "provider": "test",
        "region": "test-region",
        "effective_from": start.isoformat(),
        "currency": "USD",
        "input_per_million": "2",
        "output_per_million": "4",
    }
    assert env.client.post("/api/admin/prices", headers=env.customer, json=payload).status_code == 403
    assert env.client.post("/api/admin/prices", headers=env.admin, json=payload).status_code == 201
    assert env.client.post("/api/admin/prices", headers=env.admin, json=payload).status_code == 409
    assert (
        env.client.post(
            "/api/admin/prices", headers=env.admin, json=payload | {"effective_from": "2020-01-01T00:00:00"}
        ).status_code
        == 422
    )
    assert (
        env.client.post(
            "/api/admin/prices", headers=env.admin, json=payload | {"input_per_million": "-1"}
        ).status_code
        == 422
    )
    assert env.client.get("/api/admin/prices", headers=env.admin).json()["total"] == 1
    price_id = env.client.get("/api/admin/prices", headers=env.admin).json()["items"][0]["id"]
    end = (start + timedelta(days=1)).isoformat()
    assert (
        env.client.put(
            f"/api/admin/prices/{price_id}/end",
            headers=env.customer,
            json={"effective_to": end},
        ).status_code
        == 403
    )
    assert (
        env.client.put(
            f"/api/admin/prices/{price_id}/end",
            headers=env.admin,
            json={"effective_to": end},
        ).status_code
        == 200
    )
    assert (
        env.client.post(
            "/api/admin/prices",
            headers=env.admin,
            json=payload | {"effective_from": end},
        ).status_code
        == 201
    )
