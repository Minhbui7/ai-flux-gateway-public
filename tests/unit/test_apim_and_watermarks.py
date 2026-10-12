from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from aiflux.apim import ApimClient, ApimError
from aiflux.ingestion import query_rows, run_once
from aiflux.models import IngestionState
from sqlalchemy.orm import Session


def test_apim_uses_scoped_arm_identity_and_does_not_store_secrets(env, monkeypatch):
    requests = []

    def request(method, url, **kwargs):
        requests.append((method, url, kwargs))
        return httpx.Response(
            200, json={"primaryKey": "synthetic-primary", "secondaryKey": "synthetic-secondary"}
        )

    monkeypatch.setattr(httpx, "request", request)
    client = ApimClient(env.settings)
    client._credential = SimpleNamespace(get_token=lambda scope: SimpleNamespace(token="synthetic-arm-token"))
    sid = str(uuid4())
    client.ensure(sid, "Team", "active")
    assert requests[0][2]["json"]["properties"]["scope"].endswith("/products/aiflux")
    assert requests[0][2]["json"]["properties"]["allowTracing"] is False
    assert client.reveal(sid, "secondary") == "synthetic-secondary"
    assert "/listSecrets?api-version=2024-05-01" in requests[-1][1]
    client.rotate(sid, "primary")
    assert "/regeneratePrimaryKey?" in requests[-1][1]
    assert all("synthetic-primary" not in request[1] for request in requests)


def test_apim_failure_is_not_a_success_response(env, monkeypatch):
    monkeypatch.setattr(httpx, "request", lambda *args, **kwargs: httpx.Response(429, json={"error": {}}))
    client = ApimClient(env.settings)
    client._credential = SimpleNamespace(get_token=lambda scope: SimpleNamespace(token="synthetic"))
    with pytest.raises(ApimError) as error:
        client.ensure(str(uuid4()), "Team", "active")
    assert error.value.status_code == 429


def test_watermark_advances_after_complete_transaction_only(env, monkeypatch):
    client = SimpleNamespace()
    monkeypatch.setattr("aiflux.ingestion.query_rows", lambda *args: [])
    assert run_once(env.settings, client) == 0
    with Session(env.db_engine) as db:
        state = db.get(IngestionState, "native-llm")
        initial = state.watermark

    def failed_query(*args):
        raise RuntimeError("partial data")

    monkeypatch.setattr("aiflux.ingestion.query_rows", failed_query)
    with pytest.raises(RuntimeError, match="partial data"):
        run_once(env.settings, client)
    with Session(env.db_engine) as db:
        assert db.get(IngestionState, "native-llm").watermark == initial


def test_unknown_ownership_does_not_advance_watermark(env, monkeypatch):
    monkeypatch.setattr("aiflux.ingestion.query_rows", lambda *args: [{"subscription_id": str(uuid4())}])
    with pytest.raises(ValueError, match="unknown APIM subscription"):
        run_once(env.settings, SimpleNamespace())
    with Session(env.db_engine) as db:
        assert db.get(IngestionState, "native-llm") is None


def test_partial_and_truncated_monitor_results_are_rejected(env):
    from azure.monitor.query import LogsQueryStatus

    now = datetime.now(UTC)
    client = SimpleNamespace(query_workspace=lambda *args, **kwargs: SimpleNamespace(status="Partial"))
    with pytest.raises(RuntimeError, match="partial usage"):
        query_rows(client, env.settings, now - timedelta(hours=1), now)
    table = SimpleNamespace(columns=["correlation_id"], rows=[["a"], ["b"]])
    env.settings.ingestion_max_rows = 1
    client = SimpleNamespace(
        query_workspace=lambda *args, **kwargs: SimpleNamespace(
            status=LogsQueryStatus.SUCCESS,
            tables=[table],
        )
    )
    with pytest.raises(RuntimeError, match="exceeds row limit"):
        query_rows(client, env.settings, now - timedelta(hours=1), now)
