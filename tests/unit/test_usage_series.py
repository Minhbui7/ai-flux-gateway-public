from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from aiflux.finops import usage_series_query
from aiflux.models import TeamSubscription, UsageRecord
from sqlalchemy.dialects import mssql
from sqlalchemy.orm import Session
from test_control_plane import create_key


def add_usage(db, org, sub, when, *, inputs=10, outputs=5, latency=1500, status=200):
    db.add(UsageRecord(
        id=str(uuid4()), organization_id=org, subscription_id=sub,
        model="test-alias", provider="test", region="test-region", occurred_at=when,
        input_tokens=inputs, output_tokens=outputs, e2e_ms=latency,
        status_code=status, completeness="complete" if inputs is not None else "usage_missing",
    ))


def test_series_aggregates_all_rows_and_measured_latency_in_seconds(env):
    sub = create_key(env)["id"]
    minute = (datetime.now(UTC) - timedelta(hours=1)).replace(second=0, microsecond=0)
    with Session(env.db_engine) as db:
        for i in range(60):
            add_usage(db, env.orgs["customer"], sub, minute + timedelta(seconds=i),
                      inputs=100_000_000, outputs=5, latency=1500, status=429 if i == 1 else 200)
        add_usage(db, env.orgs["customer"], sub, minute + timedelta(minutes=1),
                  inputs=None, outputs=7, latency=None, status=500)
        add_usage(db, env.orgs["customer"], sub, minute + timedelta(minutes=1, seconds=1),
                  inputs=2, outputs=3, latency=500)
        add_usage(db, env.orgs["customer"], sub, minute + timedelta(minutes=1, seconds=2),
                  inputs=2, outputs=3, latency=3500)
        db.commit()
    table = env.client.get("/api/usage?limit=1&offset=10", headers=env.customer).json()
    assert len(table["items"]) == 1
    response = env.client.get("/api/usage/timeseries", headers=env.customer)
    assert response.status_code == 200, response.text
    series = response.json()
    assert series["interval_seconds"] == 60
    assert len(series["items"]) == 2
    first, second = series["items"]
    assert first == {
        "minute": minute.isoformat().replace("+00:00", "Z"), "requests": 60,
        "input_tokens": 6_000_000_000, "output_tokens": 300, "total_tokens": 6_000_000_300,
        "avg_e2e_seconds": 1.5, "missing_token_requests": 0, "latency_samples": 60,
    }
    assert second["requests"] == 3
    assert second["avg_e2e_seconds"] == 2.0
    assert second["latency_samples"] == 2
    assert second["missing_token_requests"] == 1
    assert second["input_tokens"] == 4
    assert second["output_tokens"] == 13
    assert second["total_tokens"] == 10


def test_series_nulls_are_not_zero_and_empty_window_is_sparse(env):
    sub = create_key(env)["id"]
    minute = (datetime.now(UTC) - timedelta(hours=1)).replace(second=0, microsecond=0)
    with Session(env.db_engine) as db:
        add_usage(db, env.orgs["customer"], sub, minute, inputs=None, outputs=None, latency=None)
        db.commit()
    response = env.client.get("/api/usage/timeseries", headers=env.customer).json()
    item = response["items"][0]
    assert item["input_tokens"] is item["output_tokens"] is item["total_tokens"] is None
    assert item["avg_e2e_seconds"] is None
    assert item["latency_samples"] == 0
    assert item["missing_token_requests"] == 1
    params = {"start": (minute - timedelta(minutes=2)).isoformat(),
              "end": (minute - timedelta(minutes=1)).isoformat()}
    response = env.client.get("/api/usage/timeseries", params=params, headers=env.customer)
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_series_subscription_and_tenant_isolation_and_admin_filters(env):
    first = create_key(env)["id"]
    second = create_key(env, "Other team")["id"]
    foreign = str(uuid4())
    now = datetime.now(UTC) - timedelta(minutes=10)
    with Session(env.db_engine) as db:
        db.add(TeamSubscription(
            id=foreign, organization_id=env.orgs["admin"], name="IDS", team="IDS",
            idempotency_key=str(uuid4()), state="active",
        ))
        db.flush()
        add_usage(db, env.orgs["customer"], first, now)
        add_usage(db, env.orgs["customer"], second, now)
        add_usage(db, env.orgs["admin"], foreign, now)
        db.commit()
    response = env.client.get("/api/usage/timeseries", headers=env.customer)
    assert response.json()["items"][0]["requests"] == 2
    filtered = env.client.get(
        "/api/usage/timeseries", params={"subscription_id": first}, headers=env.customer,
    )
    assert filtered.json()["items"][0]["requests"] == 1
    for sid in (foreign, str(uuid4())):
        assert env.client.get("/api/usage/timeseries", params={"subscription_id": sid},
                              headers=env.customer).status_code == 404
    assert env.client.get("/api/admin/usage/timeseries", headers=env.customer).status_code == 403
    assert env.client.get("/api/usage/timeseries").status_code == 401
    all_orgs = env.client.get("/api/admin/usage/timeseries", headers=env.admin)
    assert all_orgs.json()["items"][0]["requests"] == 3
    filtered = env.client.get("/api/admin/usage/timeseries",
                              params={"organization_id": env.orgs["customer"]}, headers=env.admin)
    assert filtered.json()["items"][0]["requests"] == 2
    mismatch = env.client.get("/api/admin/usage/timeseries",
                              params={"organization_id": env.orgs["customer"], "subscription_id": foreign},
                              headers=env.admin)
    assert mismatch.status_code == 404


def test_series_viewport_uses_utc_and_half_open_boundaries(env):
    sub = create_key(env)["id"]
    start = (datetime.now(UTC) - timedelta(hours=1)).replace(second=0, microsecond=0)
    end = start + timedelta(minutes=1)
    with Session(env.db_engine) as db:
        for when in (start - timedelta(microseconds=1), start, end - timedelta(microseconds=1), end):
            add_usage(db, env.orgs["customer"], sub, when)
        db.commit()
    params = {"start": start.isoformat(), "end": end.isoformat()}
    result = env.client.get("/api/usage/timeseries", params=params, headers=env.customer).json()
    assert len(result["items"]) == 1
    assert result["items"][0]["requests"] == 2
    params["start"] = start.astimezone(timezone(timedelta(hours=8))).isoformat()
    assert env.client.get("/api/usage/timeseries", params=params, headers=env.customer).json() == result


@pytest.mark.parametrize("params", [
    {"days": 0}, {"days": 367}, {"start": "bad", "end": "bad"},
    {"start": "2026-01-01T00:00:00Z"},
    {"start": "2026-01-01T00:00:00", "end": "2026-01-02T00:00:00"},
    {"start": "2000-01-01T00:00:00Z", "end": "2000-01-02T00:00:00Z"},
    {"start": "2100-01-01T00:00:00Z", "end": "2100-01-02T00:00:00Z"},
])
def test_series_invalid_ranges_are_explicit(env, params):
    response = env.client.get("/api/usage/timeseries", params=params, headers=env.customer)
    assert response.status_code == 422
    assert response.json()["detail"]


def test_series_query_compiles_for_sql_server_with_safe_aggregates():
    start = datetime(2026, 10, 1, tzinfo=UTC)
    query = usage_series_query("mssql", "tenant", "subscription", start, start + timedelta(days=1))
    sql = str(query.compile(dialect=mssql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "dateadd(minute, datediff(minute," in sql
    assert "GROUP BY dateadd(minute" in sql
    assert "avg(CAST(usage_records.e2e_ms AS FLOAT))" in sql
    assert "CAST(usage_records.input_tokens AS BIGINT)" in sql
    assert "CAST(usage_records.output_tokens AS BIGINT)" in sql
    assert "usage_records.organization_id = 'tenant'" in sql
    assert "usage_records.subscription_id = 'subscription'" in sql
    assert " IS 1" not in sql and "strftime" not in sql
    bound_sql = str(query.compile(dialect=mssql.dialect()))
    assert bound_sql.count("CONVERT(datetime2, '20000101', 112)") == 6
