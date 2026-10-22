import json
from uuid import uuid4

import pytest
from aiflux.models import AuditEvent, GatewaySettings, GatewaySettingsRevision, Organization
from conftest import ADMIN_USER
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_gateway_settings import FragmentApim
from test_managed_controls import configuration

URL = "/api/admin/subscriptions"


class SubscriptionApim(FragmentApim):
    def ensure(self, sid, name, state):
        pass

    def reveal(self, sid, key):
        return "synthetic-admin-key"

    def rotate(self, sid, key):
        pass


def create(env, *, idem=None, org=None):
    return env.client.post(
        URL, headers=env.admin | {"Idempotency-Key": idem or env.idempotency()},
        json={"organization_id": org or env.orgs["customer"], "name": "Team key", "team": "Finance"},
    )


def initialize(env):
    env.settings.gateway_controls_v2_enabled = True
    env.settings.gateway_settings_scopes = ["dev-openai", "dev-unified"]
    env.app.state.apim = SubscriptionApim()
    response = env.client.put("/api/admin/gateway-settings/dev-openai", headers=env.admin, json={
        "expected_version": 0, "configuration": configuration(), "reason": "Initial approved settings",
    })
    assert response.status_code == 200, response.text
    return env.app.state.apim


@pytest.mark.parametrize("prefix", ["/api/subscriptions", URL])
def test_customer_cannot_manage_but_retains_scoped_list_and_reveal(env, prefix):
    row = create(env).json()
    assert env.client.post(prefix, headers=env.customer, json={}).status_code == 403
    for action in ("rotate", "reconcile"):
        assert env.client.post(
            f"{prefix}/{row['id']}/{action}", headers=env.customer, json={},
        ).status_code == 403
    assert env.client.put(
        f"{prefix}/{row['id']}/state", headers=env.customer, json={"state": "suspended"},
    ).status_code == 403
    assert env.client.get(URL, headers=env.customer).status_code == 403
    assert env.client.get(URL).status_code == 401
    assert env.client.get("/api/subscriptions", headers=env.customer).json()["total"] == 1
    assert env.client.get("/api/subscriptions", headers=env.admin).json()["total"] == 0
    assert env.client.post(
        f"/api/subscriptions/{row['id']}/reveal", headers=env.customer, json={},
    ).status_code == 200


def test_admin_cross_org_listing_audit_and_disabled_targets(env):
    first = create(env).json()
    second = create(env, org=env.orgs["admin"]).json()
    listed = env.client.get(URL + "?limit=1", headers=env.admin).json()
    assert listed["total"] == 2 and len(listed["items"]) == 1
    filtered = env.client.get(
        URL + "?organization_id=" + env.orgs["customer"], headers=env.admin,
    ).json()
    assert [item["id"] for item in filtered["items"]] == [first["id"]]
    reveal = env.client.post(f"{URL}/{first['id']}/reveal", headers=env.admin, json={})
    assert reveal.status_code == 200 and reveal.headers["cache-control"] == "no-store"
    assert env.client.post(
        f"/api/subscriptions/{second['id']}/reveal", headers=env.customer, json={},
    ).status_code == 404
    assert create(env, org=str(uuid4())).status_code == 403
    with Session(env.db_engine) as db:
        events = db.scalars(select(AuditEvent).where(AuditEvent.target_id == first["id"])).all()
        assert events and all(e.organization_id == env.orgs["customer"] for e in events)
        assert all(e.object_id == ADMIN_USER for e in events)
        org = db.get(Organization, env.orgs["customer"])
        org.enabled = False
        db.commit()
    assert create(env).status_code == 403
    assert env.client.post(f"{URL}/{first['id']}/reveal", headers=env.admin, json={}).status_code == 403


def test_creation_refreshes_all_scopes_with_unchanged_config_and_no_duplicate_revision(env):
    apim = initialize(env)
    idem = env.idempotency()
    first = create(env, idem=idem)
    assert first.status_code == 201, first.text
    assert first.json()["gateway_access"] == "ready"
    sid = first.json()["id"]
    assert apim.values["dev-openai"] == apim.values["dev-unified"]
    with Session(env.db_engine) as db:
        head = db.get(GatewaySettings, "dev-openai")
        assert head.version == head.published_version == 2
        revision = db.scalar(select(GatewaySettingsRevision).where(GatewaySettingsRevision.version == 2))
        stored = json.loads(revision.configuration)
        assert stored["configuration"] == configuration()
        assert stored["binding_refresh"] == sid
        assert any(item["subscription_id"] == sid for item in stored["bindings"])
    assert create(env, idem=idem).json()["gateway_access"] == "ready"
    assert env.client.post(f"{URL}/{sid}/reconcile", headers=env.admin).json()["gateway_access"] == "ready"
    with Session(env.db_engine) as db:
        assert db.get(GatewaySettings, "dev-openai").version == 2


def test_failed_publication_is_explicit_and_owned_reconcile_recovers(env):
    apim = initialize(env)
    apim.fail = True
    first = create(env)
    assert first.status_code == 201
    row = first.json()
    assert row["state"] == "active" and row["gateway_access"] == "pending"
    assert "Publication incomplete" in row["gateway_message"]
    other = create(env).json()
    assert other["gateway_access"] == "pending"
    apim.fail = False
    blocked = env.client.post(f"{URL}/{other['id']}/reconcile", headers=env.admin).json()
    assert blocked["gateway_access"] == "pending"
    recovered = env.client.post(f"{URL}/{row['id']}/reconcile", headers=env.admin).json()
    assert recovered["gateway_access"] == "ready"
    assert env.client.post(
        f"{URL}/{other['id']}/reconcile", headers=env.admin,
    ).json()["gateway_access"] == "ready"


def test_uninitialized_and_unrelated_pending_settings_are_never_auto_approved(env):
    env.settings.gateway_controls_v2_enabled = True
    env.settings.gateway_settings_scopes = ["dev-openai", "dev-unified"]
    row = create(env).json()
    assert row["gateway_access"] == "pending"
    apim = initialize(env)
    apim.fail = True
    changed = configuration()
    changed["defaults"]["request_quota"] = 99
    response = env.client.put("/api/admin/gateway-settings/dev-openai", headers=env.admin, json={
        "expected_version": 1, "configuration": changed, "reason": "Unrelated administrator edit",
    })
    assert response.status_code == 502
    apim.fail = False
    new_row = create(env).json()
    assert new_row["gateway_access"] == "pending"
    assert "Another gateway revision" in new_row["gateway_message"]
    with Session(env.db_engine) as db:
        revision = db.scalar(select(GatewaySettingsRevision).where(GatewaySettingsRevision.version == 2))
        assert revision.state == "failed"


def test_uncertain_remote_write_recovers_without_new_revision_or_lost_bindings(env):
    apim = initialize(env)
    apim.uncertain = True
    row = create(env).json()
    assert row["gateway_access"] == "pending"
    apim.uncertain = False
    recovered = env.client.post(f"{URL}/{row['id']}/reconcile", headers=env.admin)
    assert recovered.json()["gateway_access"] == "ready"
    assert apim.values["dev-openai"] == apim.values["dev-unified"]
    second = create(env).json()
    assert second["gateway_access"] == "ready"
    with Session(env.db_engine) as db:
        head = db.get(GatewaySettings, "dev-openai")
        assert head.version == head.published_version == 3
        current = db.scalar(select(GatewaySettingsRevision).where(GatewaySettingsRevision.version == 3))
        stored = json.loads(current.configuration)
        assert {r["subscription_id"] for r in stored["bindings"]} == {row["id"], second["id"]}
        assert stored["configuration"] == configuration()


def test_drift_and_unprovisioned_scopes_leave_access_pending(env):
    apim = initialize(env)
    apim.values["dev-unified"] = "<fragment />"
    row = create(env).json()
    assert row["gateway_access"] == "pending"
    assert "drift" in row["gateway_message"]
    with Session(env.db_engine) as db:
        assert db.get(GatewaySettings, "dev-openai").version == 1
    env.settings.gateway_settings_scopes = []
    assert create(env).json()["gateway_access"] == "pending"


@pytest.mark.parametrize("action", ["reveal", "rotate", "reconcile", "state"])
def test_admin_actions_reject_unknown_target_and_customer_org_reveal(env, action):
    method = env.client.put if action == "state" else env.client.post
    payload = {"state": "active"} if action == "state" else {}
    assert method(f"{URL}/{uuid4()}/{action}", headers=env.admin, json=payload).status_code == 404
