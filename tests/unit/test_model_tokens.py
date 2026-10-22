import math
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from aiflux.finops import TOKEN_BUCKET_EPOCH, model_token_query, token_bucket_interval
from aiflux.models import TeamSubscription, UsageRecord
from sqlalchemy.dialects import mssql
from sqlalchemy.orm import Session
from test_control_plane import create_key

ENDPOINT = "/api/usage/model-tokens"


def record(db, org, sub, when, model="alpha", inputs=10, outputs=5):
    db.add(UsageRecord(
        id=str(uuid4()), organization_id=org, subscription_id=sub,
        model=model, provider="test", region="test", occurred_at=when,
        input_tokens=inputs, output_tokens=outputs, status_code=200,
        completeness="complete" if inputs is not None and outputs is not None else "usage_missing",
    ))


def test_model_tokens_complete_scope_partial_data_boundaries_and_pagination(env):
    first = create_key(env)["id"]
    second = create_key(env, "Second")["id"]
    start = (datetime.now(UTC) - timedelta(hours=2)).replace(minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=1)
    params = {"start": start.isoformat(), "end": end.isoformat()}
    with Session(env.db_engine) as db:
        for _ in range(60):
            record(db, env.orgs["customer"], first, start, inputs=100_000_000, outputs=5)
        record(db, env.orgs["customer"], second, start, "beta", inputs=7, outputs=3)
        record(db, env.orgs["customer"], first, start, inputs=None, outputs=200)
        record(db, env.orgs["customer"], first, start + timedelta(minutes=1), "beta", None, None)
        record(db, env.orgs["customer"], first, start + timedelta(minutes=2), "zero", 0, 0)
        record(db, env.orgs["customer"], first, start - timedelta(microseconds=1))
        record(db, env.orgs["customer"], first, end)
        db.commit()
    result = env.client.get(ENDPOINT, params=params, headers=env.customer)
    assert result.status_code == 200, result.text
    series = result.json()
    assert series["interval_seconds"] == 60
    assert len(series["items"]) == 4
    alpha, beta, missing, zero = series["items"]
    assert alpha["total_tokens"] == 6_000_000_300
    assert alpha["requests"] == 61 and alpha["missing_token_requests"] == 1
    assert beta["total_tokens"] == 10
    assert missing["total_tokens"] is None and missing["missing_token_requests"] == 1
    assert zero["total_tokens"] == 0 and zero["missing_token_requests"] == 0
    assert sum(item["requests"] for item in series["items"]) == 64
    assert len(env.client.get("/api/usage?limit=1", headers=env.customer).json()["items"]) == 1
    assert env.client.get(ENDPOINT, params=params, headers=env.customer).json() == series
    filtered = env.client.get(ENDPOINT, params={**params, "subscription_id": second}, headers=env.customer)
    assert len(filtered.json()["items"]) == 1 and filtered.json()["items"][0]["total_tokens"] == 10
    filtered = env.client.get(ENDPOINT, params={**params, "model": "beta"}, headers=env.customer).json()
    assert {item["model"] for item in filtered["items"]} == {"beta"}
    empty = env.client.get(ENDPOINT, params={**params, "model": "absent"}, headers=env.customer)
    assert empty.json()["items"] == []


def test_model_tokens_tenant_isolation_and_ownership(env):
    sub = create_key(env)["id"]
    foreign = str(uuid4())
    now = datetime.now(UTC) - timedelta(minutes=10)
    with Session(env.db_engine) as db:
        db.add(TeamSubscription(
            id=foreign, organization_id=env.orgs["admin"], name="Foreign", team="Foreign",
            idempotency_key=str(uuid4()), state="active",
        ))
        db.flush()
        record(db, env.orgs["customer"], sub, now)
        record(db, env.orgs["admin"], foreign, now, "foreign-model")
        db.commit()
    assert env.client.get(ENDPOINT).status_code == 401
    items = env.client.get(ENDPOINT, headers=env.customer).json()["items"]
    assert len(items) == 1 and items[0]["model"] == "alpha"
    for sid in (foreign, str(uuid4())):
        response = env.client.get(ENDPOINT, params={"subscription_id": sid}, headers=env.customer)
        assert response.status_code == 404


@pytest.mark.parametrize("params", [
    {"days": 0}, {"days": 367}, {"start": "invalid", "end": "invalid"},
    {"start": "2026-01-01T00:00:00Z"},
    {"start": "2026-01-01T00:00:00", "end": "2026-01-02T00:00:00"},
    {"start": "2000-01-01T00:00:00Z", "end": "2000-01-02T00:00:00Z"},
    {"start": "2100-01-01T00:00:00Z", "end": "2100-01-02T00:00:00Z"},
])
def test_model_tokens_reject_invalid_viewports(env, params):
    result = env.client.get(ENDPOINT, params=params, headers=env.customer)
    assert result.status_code == 422 and result.json()["detail"]


@pytest.mark.parametrize("days", [1, 7, 30, 90, 366])
def test_model_tokens_bucket_bound_and_clipped_edges(env, days):
    sub = create_key(env)["id"]
    end = (datetime.now(UTC) - timedelta(minutes=5)).replace(second=17, microsecond=0)
    start = end - timedelta(days=days, minutes=-10)
    interval = token_bucket_interval(start, end)
    with Session(env.db_engine) as db:
        record(db, env.orgs["customer"], sub, start)
        record(db, env.orgs["customer"], sub, end - timedelta(microseconds=1))
        db.commit()
    result = env.client.get(ENDPOINT, params={
        "days": days, "start": start.isoformat(), "end": end.isoformat(),
    }, headers=env.customer)
    assert result.status_code == 200, result.text
    series = result.json()
    assert series["interval_seconds"] == interval
    assert series["items"][0]["start"] == start.isoformat().replace("+00:00", "Z")
    assert series["items"][-1]["end"] == end.isoformat().replace("+00:00", "Z")
    assert sum(item["total_tokens"] for item in series["items"]) == 30
    assert (
        math.ceil((end - TOKEN_BUCKET_EPOCH).total_seconds() / interval)
        - math.floor((start - TOKEN_BUCKET_EPOCH).total_seconds() / interval)
    ) <= 120


def test_model_tokens_sql_server_compilation_and_unsupported_dialect():
    start = datetime(2026, 10, 1, tzinfo=UTC)
    query = model_token_query("mssql", "org", "sub", start, start + timedelta(days=1), 3600, "model")
    sql = str(query.compile(dialect=mssql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "GROUP BY floor(" in sql and "usage_records.model" in sql
    assert "datediff(minute, CONVERT(datetime2, '20000101', 112)" in sql
    assert "CAST(usage_records.input_tokens AS BIGINT) + CAST(usage_records.output_tokens AS BIGINT)" in sql
    assert "usage_records.organization_id = 'org'" in sql
    assert "usage_records.subscription_id = 'sub'" in sql and "usage_records.model = 'model'" in sql
    assert "strftime" not in sql
    positional = str(query.compile(dialect=mssql.dialect(paramstyle="qmark")))
    grouping = positional.split(" GROUP BY ")[1]
    assert "?" not in grouping
    assert "CAST(60 AS NUMERIC)" in grouping
    with pytest.raises(ValueError, match="Unsupported model token bucket interval"):
        model_token_query("mssql", "org", None, start, start + timedelta(days=1), 61)
    with pytest.raises(ValueError, match="does not support"):
        model_token_query("unsupported", "org", None, start, start + timedelta(days=1), 60)
