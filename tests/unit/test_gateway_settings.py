import xml.etree.ElementTree as ET
from types import SimpleNamespace

import httpx
import pytest
from aiflux.apim import ApimClient, ApimError
from aiflux.gateway_settings import BOOTSTRAP, fingerprint, render_fragment
from aiflux.models import AuditEvent, GatewaySettingsRevision
from aiflux.schemas import GatewayConfiguration
from sqlalchemy import event, select
from sqlalchemy.dialects import mssql
from sqlalchemy.orm import Session

URL = "/api/admin/gateway-settings"
CONFIG = {"safety_threshold": 3, "rpm": 2, "tpm": 1024, "token_quota": 10000, "quota_period": "Daily"}


class FragmentApim:
    def __init__(self):
        self.values = {scope: BOOTSTRAP.read_text() for scope in ("dev-openai", "dev-unified")}
        self.versions = dict.fromkeys(self.values, 1)
        self.writes = []
        self.fail = False
        self.uncertain = False
        self.bad_readback = False

    def get_settings_fragment(self, scope):
        return self.values[scope], f'"{self.versions[scope]}"'

    def put_settings_fragment(self, scope, value, etag):
        self.writes.append((scope, value, etag))
        if self.fail:
            raise ApimError(429)
        if etag != f'"{self.versions[scope]}"':
            raise ApimError(412)
        if not self.bad_readback:
            self.values[scope] = value
            self.versions[scope] += 1
        if self.uncertain:
            raise ApimError()


@pytest.fixture
def gateway(env):
    env.settings.gateway_settings_scopes = ["dev-openai", "dev-unified"]
    apim = FragmentApim()
    env.app.state.apim = apim
    return apim


def save(env, config=None, version=0, scope="dev-openai", **overrides):
    return env.client.put(
        f"{URL}/{scope}", headers=env.admin,
        json={
            "expected_version": version, "configuration": config or CONFIG,
            "reason": "Reviewed safety and budget", **overrides,
        },
    )


def test_settings_require_home_tenant_admin_and_opt_in(env):
    assert env.client.get(URL).status_code == 401
    assert env.client.get(URL, headers=env.customer).status_code == 403
    assert env.client.get(URL, headers=env.admin).json() == {"items": [], "total": 0}
    assert save(env).status_code == 409
    for method, path, body in [
        ("put", f"{URL}/dev-openai", {"expected_version": 0, "configuration": CONFIG, "reason": "review"}),
        ("post", f"{URL}/dev-openai/reconcile", {"expected_version": 1}),
        ("get", f"{URL}/dev-openai/history", None),
    ]:
        assert env.client.request(method, path, headers=env.customer, json=body).status_code == 403


def test_missing_bootstrap_artifact_is_an_explicit_readiness_failure(env, gateway, monkeypatch, tmp_path):
    monkeypatch.setattr("aiflux.gateway_settings.BOOTSTRAP", tmp_path / "missing.xml")
    assert env.client.get("/ready").status_code == 503
    assert save(env).status_code == 503
    assert gateway.writes == []


def test_save_readback_history_and_new_revision_rollback(env, gateway):
    assert env.client.get(URL, headers=env.admin).json()["items"][0]["desired"] is None
    response = save(env)
    assert response.status_code == 200, response.text
    row = response.json()
    assert row["version"] == row["published_version"] == 1
    assert row["desired"]["configuration"] == CONFIG
    assert row["desired"]["state"] == "published"
    xml = ET.fromstring(gateway.values["dev-openai"])
    assert xml.find("set-variable").get("value") == "@(3)"
    limit = xml.find("llm-token-limit")
    assert limit.get("tokens-per-minute") == "1024"
    assert limit.get("token-quota") == "10000"
    assert limit.get("token-quota-period") == "Daily"
    assert "dev-openai:" in limit.get("counter-key")
    assert save(env, version=0).status_code == 409
    assert len(gateway.writes) == 1
    assert save(env, CONFIG | {"safety_threshold": 2}, version=1).status_code == 200
    assert save(env, CONFIG, version=2, reason="Revert to reviewed revision 1").status_code == 200
    history = env.client.get(f"{URL}/dev-openai/history?limit=2", headers=env.admin).json()
    assert history["total"] == 3
    assert [item["version"] for item in history["items"]] == [3, 2]
    assert history["items"][1]["configuration"]["safety_threshold"] == 2
    with Session(env.db_engine) as db:
        events = list(db.scalars(select(AuditEvent)))
    assert len(events) == 6
    assert {event.action for event in events} == {
        "gateway.settings.requested", "gateway.settings.published",
    }


@pytest.mark.parametrize(("field", "value"), [
    ("safety_threshold", -1), ("safety_threshold", 8), ("safety_threshold", None),
    ("safety_threshold", True), ("safety_threshold", "4"), ("rpm", 0), ("rpm", 3),
    ("tpm", 0), ("tpm", 2049), ("token_quota", 0), ("token_quota", 2147483648),
    ("token_quota", 1.5), ("quota_period", "Never"),
])
def test_invalid_settings_never_publish(env, gateway, field, value):
    assert save(env, CONFIG | {field: value}).status_code == 422
    assert gateway.writes == []


@pytest.mark.parametrize(("scope", "tpm"), [("dev-openai", 2048), ("dev-unified", 20000)])
@pytest.mark.parametrize("threshold", [0, 7])
def test_exact_bounds_and_api_counter_isolation(env, gateway, scope, tpm, threshold):
    config = CONFIG | {"tpm": tpm, "rpm": 1, "safety_threshold": threshold, "token_quota": 1}
    assert save(env, config, scope=scope).status_code == 200
    assert f"tpm:{scope}:" in gateway.values[scope]
    assert f"rpm:{scope}:" in gateway.values[scope]
    assert 'value="@(' + str(threshold) + ')"' in gateway.values[scope]


def test_unknown_fields_scope_and_missing_quota_are_rejected(env, gateway):
    assert save(env, CONFIG | {"shield_prompt": False}).status_code == 422
    assert save(env, scope="production").status_code == 422
    assert save(env, expected_version=True).status_code == 422
    assert save(env, reason="  ").status_code == 422
    assert save(env, {k: v for k, v in CONFIG.items() if k != "token_quota"}).status_code == 422
    assert gateway.writes == []


def test_publication_failure_is_durable_and_retry_is_idempotent(env, gateway):
    gateway.fail = True
    assert save(env).status_code == 502
    row = env.client.get(URL, headers=env.admin).json()["items"][0]
    assert row["version"] == 1 and row["published_version"] is None
    assert row["desired"]["state"] == "failed"
    assert save(env, version=1).status_code == 409
    gateway.fail = False
    retry = env.client.post(f"{URL}/dev-openai/reconcile", headers=env.admin, json={"expected_version": 1})
    assert retry.status_code == 200
    assert retry.json()["published_version"] == 1
    writes = len(gateway.writes)
    assert env.client.post(
        f"{URL}/dev-openai/reconcile", headers=env.admin, json={"expected_version": 1},
    ).status_code == 200
    assert len(gateway.writes) == writes
    assert env.client.post(
        f"{URL}/dev-openai/reconcile", headers=env.admin, json={"expected_version": 2},
    ).status_code == 409


def test_timeout_after_remote_success_reconciles_without_overwrite(env, gateway):
    gateway.uncertain = True
    assert save(env).status_code == 502
    assert env.client.post(
        f"{URL}/dev-openai/reconcile", headers=env.admin, json={"expected_version": 1},
    ).status_code == 200
    assert len(gateway.writes) == 1


def test_drift_and_etag_conflict_are_not_overwritten(env, gateway):
    gateway.values["dev-openai"] = "<fragment><set-variable name='unexpected' value='yes'/></fragment>"
    assert save(env).status_code == 409
    assert gateway.writes == []
    gateway.values["dev-openai"] = BOOTSTRAP.read_text()
    gateway.fail = True
    assert save(env).status_code == 502
    gateway.fail = False
    gateway.versions["dev-openai"] += 1
    assert env.client.post(
        f"{URL}/dev-openai/reconcile", headers=env.admin, json={"expected_version": 1},
    ).status_code == 502
    assert len(gateway.writes) == 1


def test_readback_is_required_and_pending_revision_survives_restart(env, gateway):
    gateway.bad_readback = True
    assert save(env).status_code == 502
    with Session(env.db_engine) as db:
        row = db.scalars(select(GatewaySettingsRevision)).one()
        assert row.state == "failed"
    gateway.bad_readback = False
    assert env.client.post(
        f"{URL}/dev-openai/reconcile", headers=env.admin, json={"expected_version": 1},
    ).status_code == 200


def test_fragment_management_is_allowlisted_and_conditional(env, monkeypatch):
    env.settings.gateway_settings_scopes = ["dev-openai"]
    client = ApimClient(env.settings)
    client._credential = SimpleNamespace(get_token=lambda scope: SimpleNamespace(token="synthetic"))
    requests = []

    def request(method, url, **kwargs):
        requests.append((method, url, kwargs))
        return httpx.Response(
            200, json={"properties": {"value": "<fragment />"}}, headers={"ETag": '"etag"'},
        )

    monkeypatch.setattr(httpx, "request", request)
    value, etag = client.get_settings_fragment("dev-openai")
    client.put_settings_fragment("dev-openai", value, etag)
    assert "/policyFragments/aiflux-dev-openai-settings?" in requests[0][1]
    assert requests[0][1].endswith("&format=rawxml")
    assert "If-Match" not in requests[0][2]["headers"]
    assert requests[1][2]["headers"]["If-Match"] == '"etag"'
    assert requests[1][2]["json"]["properties"]["format"] == "rawxml"
    for scope in ("dev-unified", "../policies"):
        with pytest.raises(ApimError):
            client.get_settings_fragment(scope)
    with pytest.raises(ApimError):
        client.put_settings_fragment("dev-openai", value, "*")


def test_xml_fingerprint_ignores_whitespace_and_attribute_order():
    assert fingerprint('<fragment><set-variable name="x" value="1"/></fragment>') == fingerprint(
        '<fragment>\n<set-variable value="1" name="x" />\n</fragment>',
    )
    config = GatewayConfiguration.model_validate(CONFIG)
    assert fingerprint(render_fragment("dev-openai", config)) != fingerprint(
        render_fragment("dev-unified", config),
    )


@pytest.mark.parametrize("state", ["Succeeded", "Failed", "Canceled", "unexpected"])
def test_fragment_publication_waits_for_arm_validation(env, monkeypatch, state):
    env.settings.gateway_settings_scopes = ["dev-openai"]
    client = ApimClient(env.settings)
    operation = client._fragment_url("dev-openai") + "&azure-asyncId=test"
    requests = []
    responses = iter([
        httpx.Response(200, headers={"Azure-AsyncOperation": operation}),
        httpx.Response(200, json={"status": "InProgress"}),
        httpx.Response(200, json={"status": state}),
    ])

    def send(method, url, *args):
        requests.append((method, url))
        return next(responses)

    monkeypatch.setattr(client, "_send", send)
    monkeypatch.setattr("aiflux.apim.time.sleep", lambda _: None)
    if state == "Succeeded":
        client.put_settings_fragment("dev-openai", "<fragment />", '"etag"')
    else:
        with pytest.raises(ApimError):
            client.put_settings_fragment("dev-openai", "<fragment />", '"etag"')
    assert requests[1:] == [("GET", operation), ("GET", operation)]


@pytest.mark.parametrize("operation", [
    "https://untrusted.invalid/policyFragments/aiflux-dev-openai-settings",
    "https://management.azure.com/another-resource",
])
def test_fragment_operation_cannot_redirect_management_token(env, monkeypatch, operation):
    env.settings.gateway_settings_scopes = ["dev-openai"]
    client = ApimClient(env.settings)
    calls = []

    def send(method, url, *args):
        calls.append(url)
        return httpx.Response(200, headers={"Azure-AsyncOperation": operation})

    monkeypatch.setattr(client, "_send", send)
    with pytest.raises(ApimError):
        client.put_settings_fragment("dev-openai", "<fragment />", '"etag"')
    assert len(calls) == 1


def test_settings_queries_compile_for_mssql_with_publication_lock(env, gateway):
    queries = []

    def capture(connection, clause, multiparams, params, execution_options):
        queries.append(str(clause.compile(dialect=mssql.dialect())))

    event.listen(env.db_engine, "before_execute", capture)
    try:
        assert save(env).status_code == 200
    finally:
        event.remove(env.db_engine, "before_execute", capture)
    assert any("WITH (UPDLOCK, HOLDLOCK)" in query for query in queries)
    assert any("UPDATE gateway_settings SET version=" in query for query in queries)
    assert all(" IS 1" not in query and " IS 0" not in query for query in queries)


def test_settings_migration_supports_existing_databases_and_repeated_upgrade(env, monkeypatch):
    from aiflux.models import GatewaySettings
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    GatewaySettingsRevision.__table__.drop(env.db_engine)
    GatewaySettings.__table__.drop(env.db_engine)
    config = Config("services/control-plane/alembic.ini")
    monkeypatch.setattr("aiflux.config.get_settings", lambda: env.settings)
    command.stamp(config, "0001")
    command.upgrade(config, "head")
    assert "gateway_settings_revisions" in inspect(env.db_engine).get_table_names()
    command.downgrade(config, "0001")
    assert "gateway_settings_revisions" not in inspect(env.db_engine).get_table_names()
    command.upgrade(config, "head")
    assert "gateway_settings" in inspect(env.db_engine).get_table_names()
