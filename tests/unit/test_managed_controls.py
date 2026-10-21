import copy
import json
import xml.etree.ElementTree as ET
from uuid import uuid4

import pytest
from aiflux.apim import ApimError
from aiflux.managed_controls import render_managed
from aiflux.models import GatewaySettingsRevision, Team, TeamSubscription
from aiflux.schemas import ManagedGatewayConfiguration
from aiflux.subscriptions import team_identity
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_gateway_settings import FragmentApim

URL = "/api/admin/gateway-settings"
SAFETY = "/api/admin/content-safety-settings"
LIMITS = {
    "rpm": 2, "tpm": 1024, "token_quota": 10000, "quota_period": "Daily",
    "concurrency": 2, "request_quota": 25, "request_quota_period": "Daily",
}
CUSTOM = {
    "profile": "Custom", "hate": 1, "violence": 1, "sexual": 1, "self_harm": 1,
    "prompt_attack": True, "protected_material": False, "input_filtering": True, "output_filtering": True,
}


@pytest.fixture
def managed(env):
    env.settings.gateway_settings_scopes = ["dev-openai", "dev-unified"]
    env.settings.gateway_controls_v2_enabled = True
    env.app.state.apim = FragmentApim()
    subscriptions = []
    with Session(env.db_engine) as db:
        for org in (env.orgs["admin"], env.orgs["customer"]):
            for label in ("Engineering", "engineering"):
                tid = team_identity(org, label)
                db.add(Team(id=tid, organization_id=org, name=label))
                db.flush()
                for _ in range(2):
                    sid = str(uuid4())
                    db.add(TeamSubscription(
                        id=sid, organization_id=org, team=label, team_id=tid,
                        name="Test subscription", idempotency_key=str(uuid4()), state="active",
                    ))
                    subscriptions.append({"organization_id": org, "team_id": tid, "subscription_id": sid})
        db.commit()
    return subscriptions


def configuration():
    return {
        "schema_version": 2, "defaults": copy.deepcopy(LIMITS), "teams": [], "subscriptions": [],
        "safety": copy.deepcopy(CUSTOM),
    }


@pytest.mark.parametrize("overrides", ["none", "team", "subscription", "both"])
def test_compiled_choose_requires_at_least_one_when(overrides):
    target = {"organization_id": str(uuid4()), "team_id": str(uuid4()), "subscription_id": str(uuid4())}
    config = configuration()
    if overrides in ("team", "both"):
        config["teams"] = [{
            "organization_id": target["organization_id"], "team_id": target["team_id"], "limits": LIMITS,
        }]
    if overrides in ("subscription", "both"):
        config["subscriptions"] = [{
            "organization_id": target["organization_id"],
            "subscription_id": target["subscription_id"], "limits": LIMITS,
        }]
    policy = ET.fromstring(render_managed(ManagedGatewayConfiguration.model_validate(config), [target]))
    assert all(node.find("when") is not None for node in policy.findall(".//choose"))
    assert policy.find(".//llm-token-limit") is not None


def save(env, config=None, version=0, scope="dev-openai"):
    return env.client.put(f"{URL}/{scope}", headers=env.admin, json={
        "configuration": config or configuration(), "expected_version": version,
        "reason": "Reviewed controls",
    })


def safety(env, config, version=1, acknowledge=False, scope="dev-unified"):
    return env.client.put(f"{SAFETY}/{scope}", headers=env.admin, json={
        "configuration": config, "expected_version": version,
        "reason": "Reviewed safety profile", "acknowledge_relaxation": acknowledge,
    })


def test_shared_publication_and_versions_prevent_cross_route_bypass(env, managed):
    result = save(env)
    assert result.status_code == 200, result.text
    values = env.app.state.apim.values
    assert values["dev-openai"] == values["dev-unified"]
    assert len(env.app.state.apim.writes) == 2
    items = env.client.get(URL, headers=env.admin).json()["items"]
    assert all(row["version"] == row["published_version"] == 1 for row in items)
    assert all(row["max_tpm"] == 2048 for row in items)
    assert items[0]["desired"]["configuration"] == configuration()
    assert items[0]["capabilities"]["enforcement_enabled"] is False
    assert save(env, version=0, scope="dev-unified").status_code == 409
    assert save(env, version=1, scope="dev-unified").status_code == 200
    history = env.client.get(f"{SAFETY}/dev-unified/history", headers=env.admin).json()
    assert [row["version"] for row in history["items"]] == [2, 1]


def test_targets_are_stable_tenant_scoped_paginated_and_admin_only(env, managed):
    url = "/api/admin/gateway-targets"
    assert env.client.get(url).status_code == 401
    assert env.client.get(url, headers=env.customer).status_code == 403
    result = env.client.get(url + "?limit=2", headers=env.admin).json()
    assert result["total"] == 8 and len(result["items"]) == 2
    result = env.client.get(
        url + f"?organization_id={env.orgs['customer']}", headers=env.admin,
    ).json()
    assert len(result["items"]) == 4
    assert len({row["team_id"] for row in result["items"]}) == 2
    assert (
        team_identity(env.orgs["customer"], "Engineering") != team_identity(env.orgs["admin"], "Engineering")
    )
    assert env.client.get(url + "?organization_id=bad", headers=env.admin).status_code == 422


def test_team_aggregate_and_subscription_override_are_both_compiled(env, managed):
    target = managed[0]
    config = configuration()
    config["teams"] = [{
        "organization_id": target["organization_id"], "team_id": target["team_id"],
        "limits": LIMITS | {"concurrency": 4, "request_quota": 100},
    }]
    config["subscriptions"] = [{
        "organization_id": target["organization_id"], "subscription_id": target["subscription_id"],
        "limits": LIMITS | {"concurrency": 1, "request_quota": 10},
    }]
    assert save(env, config).status_code == 200
    text = env.app.state.apim.values["dev-openai"]
    policy = ET.fromstring(text)
    assert policy.find(".//set-variable[@name='aiflux-team-concurrency'][@value='@(4)']") is not None
    assert policy.find(".//set-variable[@name='aiflux-subscription-concurrency'][@value='@(1)']") is not None
    assert {node.get("calls") for node in policy.findall(".//quota-by-key")} == {"10", "25", "100"}
    keys = [node.get("counter-key") for node in policy.findall(".//*[@counter-key]")]
    assert all("aiflux-model" not in key and "dev-" not in key and "version" not in key for key in keys)
    assert "subscription_controls_unpublished" in text
    assert "primary" not in text and "secondary" not in text


@pytest.mark.parametrize("kind", ["teams", "subscriptions"])
def test_foreign_and_duplicate_target_rejected_before_arm_writes(env, managed, kind):
    target = managed[0]
    field = "team_id" if kind == "teams" else "subscription_id"
    config = configuration()
    entry = {"organization_id": env.orgs["customer"], field: target[field], "limits": LIMITS}
    config[kind] = [entry]
    assert save(env, config).status_code == 422
    entry["organization_id"] = target["organization_id"]
    config[kind] = [entry, entry]
    assert save(env, config).status_code == 422
    assert env.app.state.apim.writes == []


@pytest.mark.parametrize(("field", "value"), [
    ("rpm", 3), ("rpm", True), ("tpm", 2049), ("request_quota", 0),
    ("request_quota", 1.5), ("concurrency", 3), ("concurrency", True), ("concurrency", "2"),
])
def test_operator_bounds_and_typed_input(env, managed, field, value):
    config = configuration()
    config["defaults"][field] = value
    assert save(env, config).status_code == 422
    assert env.app.state.apim.writes == []


def test_monthly_request_quota_capability_and_calendar_counter(env, managed):
    config = configuration()
    config["defaults"]["request_quota_period"] = "Monthly"
    assert save(env, config).status_code == 409
    env.settings.gateway_monthly_request_quota_available = True
    assert save(env, config).status_code == 200
    policy = ET.fromstring(env.app.state.apim.values["dev-openai"])
    quota = policy.find(".//quota-by-key")
    assert quota.get("renewal-period") == "0"
    assert 'context.Variables["aiflux-quota-now"]).ToString("yyyyMM")' in quota.get("counter-key")
    assert "2592000" not in quota.get("counter-key")


def test_safety_separate_publication_capabilities_and_relaxation_audit(env, managed):
    assert save(env).status_code == 200
    relaxed = CUSTOM | {"hate": 4}
    assert safety(env, relaxed).status_code == 422
    assert safety(env, relaxed, acknowledge=True).status_code == 200
    # A stale gateway form cannot restore the old safety configuration.
    assert save(env, version=1).status_code == 409
    assert save(env, version=2).status_code == 409
    config = configuration() | {"safety": relaxed}
    assert save(env, config, version=2).status_code == 200
    strict = CUSTOM | {"profile": "Strict", "protected_material": True}
    assert safety(env, strict, version=3).status_code == 409
    env.settings.gateway_protected_material_available = True
    assert safety(env, strict, version=3).status_code == 200
    values = env.app.state.apim.values
    assert values["dev-openai"] == values["dev-unified"]
    assert 'name="aiflux-protected-material" value="@(true)"' in values["dev-openai"]
    assert safety(env, strict | {"hate": 2}, version=4).status_code == 422


def test_operator_safety_floor_and_contradictory_controls(env, managed):
    assert save(env).status_code == 200
    disabled = CUSTOM | {"input_filtering": False, "prompt_attack": False}
    assert safety(env, disabled, acknowledge=True).status_code == 422
    env.settings.gateway_safety_relaxation_allowed = True
    assert safety(env, disabled, acknowledge=True).status_code == 200
    assert safety(env, CUSTOM | {
        "protected_material": True, "output_filtering": False,
    }, version=2, acknowledge=True).status_code == 422


def test_partial_multi_scope_failure_is_durable_and_reconciliation_safe(env, managed):
    apim = env.app.state.apim
    put = apim.put_settings_fragment

    def fail_second(scope, value, etag):
        if scope == "dev-unified":
            raise ApimError(429)
        put(scope, value, etag)

    apim.put_settings_fragment = fail_second
    assert save(env).status_code == 502
    items = env.client.get(URL, headers=env.admin).json()["items"]
    assert all(row["desired"]["state"] == "failed" for row in items)
    assert save(env, version=1).status_code == 409
    apim.put_settings_fragment = put
    retry = env.client.post(
        f"{SAFETY}/dev-unified/reconcile", headers=env.admin, json={"expected_version": 1},
    )
    assert retry.status_code == 200
    assert len(apim.writes) == 2
    assert apim.values["dev-openai"] == apim.values["dev-unified"]


def test_legacy_writes_and_drift_cannot_destroy_new_contract(env, managed):
    legacy = {"safety_threshold": 1, "rpm": 2, "tpm": 1024, "token_quota": 50, "quota_period": "Daily"}
    assert save(env, legacy).status_code == 409
    env.app.state.apim.values["dev-unified"] = "<fragment />"
    assert save(env).status_code == 409
    assert env.app.state.apim.writes == []


def test_publication_freezes_membership_for_deterministic_reconciliation(env, managed):
    assert save(env).status_code == 200
    with Session(env.db_engine) as db:
        row = db.scalars(select(GatewaySettingsRevision)).one()
        stored = json.loads(row.configuration)
        assert len(stored["bindings"]) == 8
        assert sorted(stored["bases"]) == ["dev-openai", "dev-unified"]
        rendered = render_managed(ManagedGatewayConfiguration.model_validate(stored["configuration"]),
                                  stored["bindings"])
    assert rendered == env.app.state.apim.values["dev-openai"]


def test_fragment_size_is_checked_before_durable_save(env, managed, monkeypatch):
    monkeypatch.setattr("aiflux.managed_controls.MAX_FRAGMENT_BYTES", 100)
    assert save(env).status_code == 422
    assert env.app.state.apim.writes == []
    with Session(env.db_engine) as db:
        assert db.scalar(select(GatewaySettingsRevision)) is None


def test_migration_backfills_real_legacy_rows_without_case_or_tenant_merging(env, monkeypatch):
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text

    monkeypatch.setattr("aiflux.config.get_settings", lambda: env.settings)
    config = Config(str(Path("services") / "control-plane" / "alembic.ini"))
    command.stamp(config, "0003")
    command.downgrade(config, "0002")
    identities = []
    with env.db_engine.begin() as connection:
        for org in (env.orgs["admin"], env.orgs["customer"]):
            for label in ("Engineering", "engineering"):
                for _ in range(2):
                    identity = str(uuid4())
                    identities.append((identity, org, label))
                    connection.execute(text(
                        "INSERT INTO team_subscriptions "
                        "(id,organization_id,name,team,state,desired_state,idempotency_key,created_at) "
                        "VALUES (:id,:org,'Test',:team,'active','active',:idem,CURRENT_TIMESTAMP)"
                    ), {"id": identity, "org": org, "team": label, "idem": str(uuid4())})
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    with Session(env.db_engine) as db:
        assert len(list(db.scalars(select(Team)))) == 4
        for identity, org, label in identities:
            subscription = db.get(TeamSubscription, identity)
            assert subscription.team_id == team_identity(org, label)
            assert db.get(Team, subscription.team_id).organization_id == org
            assert subscription.team == label and subscription.state == "active"


def test_explicit_operator_initial_threshold_is_preserved(env, managed):
    env.settings.gateway_initial_safety_threshold = 0
    assert save(env).status_code == 409
    config = configuration()
    config["safety"].update(hate=0, violence=0, sexual=0, self_harm=0)
    assert save(env, config).status_code == 200
    response = env.client.get(URL, headers=env.admin).json()
    assert response["items"][0]["capabilities"]["initial_safety_threshold"] == 0


def test_new_subscription_remains_denied_until_explicit_republication(env, managed):
    assert save(env).status_code == 200
    published = env.app.state.apim.values["dev-openai"]
    new_id = str(uuid4())
    with Session(env.db_engine) as db:
        db.add(TeamSubscription(
            id=new_id, organization_id=managed[0]["organization_id"], name="New key",
            team="Engineering", team_id=managed[0]["team_id"],
            state="active", idempotency_key=str(uuid4()),
        ))
        db.commit()
    assert new_id not in published
    assert "subscription_controls_unpublished" in published
    assert save(env, version=1).status_code == 200
    assert new_id in env.app.state.apim.values["dev-openai"]


@pytest.mark.parametrize("value", [True, 2.0, "2"])
def test_contract_version_is_a_json_integer(env, managed, value):
    config = configuration() | {"schema_version": value}
    assert save(env, config).status_code == 422
    assert env.app.state.apim.writes == []


@pytest.mark.parametrize("secondary_threshold", [2, 3])
def test_legacy_cutover_preserves_safety_or_requires_operator_alignment(env, managed, secondary_threshold):
    env.settings.gateway_controls_v2_enabled = False
    legacy = {"safety_threshold": 2, "rpm": 2, "tpm": 1024, "token_quota": 50, "quota_period": "Daily"}
    assert save(env, legacy).status_code == 200
    result = save(env, legacy | {"safety_threshold": secondary_threshold}, scope="dev-unified")
    assert result.status_code == 200
    env.settings.gateway_controls_v2_enabled = True
    config = configuration()
    config["safety"].update(hate=2, violence=2, sexual=2, self_harm=2)
    response = save(env, config, version=1)
    assert response.status_code == (200 if secondary_threshold == 2 else 409), response.text
    if secondary_threshold == 2:
        assert response.json()["version"] == 2
        assert env.app.state.apim.values["dev-openai"] == env.app.state.apim.values["dev-unified"]
