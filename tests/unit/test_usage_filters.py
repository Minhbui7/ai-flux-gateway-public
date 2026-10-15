import csv
import io
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from aiflux.models import TeamSubscription, UsageRecord
from sqlalchemy import event, insert
from sqlalchemy.dialects import mssql
from sqlalchemy.orm import Session
from test_control_plane import create_key

MODEL = "=retired, model/+&"
CSV_FIELDS = [
    "id", "subscription_id", "model", "provider", "region", "occurred_at",
    "input_tokens", "output_tokens", "cached_input_tokens", "cache_write_tokens",
    "cost", "currency", "status_code", "e2e_ms", "ttft_ms", "completeness",
]


def row(org, sub, model=MODEL, **values):
    return {
        "id": str(uuid4()), "organization_id": org, "subscription_id": sub,
        "model": model, "provider": "@provider", "region": "test-region",
        "occurred_at": datetime.now(UTC) - timedelta(hours=1),
        "input_tokens": 10, "output_tokens": 2, "cached_input_tokens": None,
        "cache_write_tokens": None, "cost": Decimal("0.1"), "currency": "USD",
        "status_code": 200, "e2e_ms": 100, "ttft_ms": None, "completeness": "complete",
        **values,
    }


@pytest.fixture
def usage_data(env):
    first = create_key(env)["id"]
    second = create_key(env, "Other team")["id"]
    foreign = str(uuid4())
    minute = (datetime.now(UTC) - timedelta(hours=1)).replace(second=0, microsecond=0)
    org = env.orgs["customer"]
    matching = [
        row(org, first, occurred_at=minute, cached_input_tokens=0),
        row(org, first, occurred_at=minute + timedelta(seconds=1), input_tokens=20,
            output_tokens=3, e2e_ms=200, status_code=429, cost=Decimal("0.2"), ttft_ms=25),
        row(org, first, occurred_at=minute + timedelta(seconds=2), input_tokens=None,
            output_tokens=5, e2e_ms=None, status_code=500, cost=None, completeness="usage_missing"),
    ]
    with Session(env.db_engine) as db:
        db.add(TeamSubscription(id=foreign, organization_id=env.orgs["admin"], name="IDS",
                                team="IDS", idempotency_key=str(uuid4()), state="active"))
        db.flush()
        db.execute(insert(UsageRecord), [
            *matching,
            row(org, first, "other", e2e_ms=100_000, currency="SGD"),
            row(org, second, "second-only"),
            row(org, second, e2e_ms=10_000),
            row(org, first, "old-only", occurred_at=minute - timedelta(days=10)),
            row(org, first, occurred_at=minute - timedelta(days=10), e2e_ms=50_000),
            row(env.orgs["admin"], foreign, e2e_ms=1_000_000),
            row(env.orgs["admin"], foreign, "foreign-only"),
        ])
        db.commit()
    return first, second, foreign, matching


@pytest.mark.parametrize("admin", [False, True])
def test_model_filter_consistent_across_summary_p95_series_rows_and_csv(env, usage_data, admin):
    first, _, _, matching = usage_data
    headers = env.admin if admin else env.customer
    base = "/api/admin/usage" if admin else "/api/usage"
    params = {"days": 7, "subscription_id": first, "model": MODEL}
    if admin:
        params["organization_id"] = env.orgs["customer"]
    response = env.client.get(base, params={**params, "limit": 1, "offset": 1}, headers=headers)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["total"] == 3 and len(result["items"]) == 1
    summary = result["summary"]
    assert summary["requests"] == 3
    assert summary["input_tokens"] == 30 and summary["output_tokens"] == 10
    assert Decimal(summary["known_cost"]) == Decimal("0.3")
    assert summary["currency"] == "USD" and summary["incomplete_requests"] == 1
    assert summary["failed_requests"] == 2 and summary["throttled_requests"] == 1
    assert summary["e2e_p95_ms"] == 200 and summary["cache_tokens_supported"] is True
    assert summary["ttft_supported"] is False
    series = env.client.get(base + "/timeseries", params=params, headers=headers).json()
    assert len(series["items"]) == 1
    assert series["items"][0] == {
        "minute": matching[0]["occurred_at"].isoformat().replace("+00:00", "Z"),
        "requests": 3, "input_tokens": 30, "output_tokens": 10, "total_tokens": 35,
        "avg_e2e_seconds": 0.15, "missing_token_requests": 1, "latency_samples": 2,
    }
    exported = env.client.get(base + "/export", params=params, headers=headers)
    assert exported.status_code == 200
    reader = csv.DictReader(io.StringIO(exported.text))
    records = list(reader)
    assert reader.fieldnames == CSV_FIELDS
    assert {r["id"] for r in records} == {r["id"] for r in matching}
    assert {r["model"] for r in records} == {"'" + MODEL}
    assert {r["provider"] for r in records} == {"'@provider"}
    assert {r["e2e_ms"] for r in records} == {"100", "200", ""}
    assert {r["ttft_ms"] for r in records} == {"", "25"}
    assert sum(r["cost"] == "" for r in records) == 1
    other = env.client.get(base, params={**params, "model": "other"}, headers=headers).json()
    assert other["total"] == 1 and other["summary"]["cache_tokens_supported"] is False
    unfiltered = env.client.get(base, params={k: v for k, v in params.items() if k != "model"},
                                headers=headers).json()
    assert unfiltered["total"] == 4
    assert unfiltered["summary"]["known_cost"] is None  # Never combine USD and SGD.
    empty = env.client.get(base, params={**params, "model": "not-in-catalog"}, headers=headers).json()
    assert empty["total"] == 0 and empty["summary"]["known_cost"] is None
    assert empty["summary"]["e2e_p95_ms"] is None


def test_model_options_are_distinct_authorized_history_in_period_and_scope(env, usage_data):
    first, second, foreign, _ = usage_data
    options = env.client.get("/api/usage/models", params={"days": 7}, headers=env.customer).json()
    assert options == {"items": sorted([MODEL, "other", "second-only"]), "total": 3}
    filtered = env.client.get("/api/usage/models",
                              params={"days": 7, "subscription_id": first, "model": MODEL, "limit": 1},
                              headers=env.customer).json()
    assert filtered == {"items": [MODEL, "other"], "total": 2}
    assert "old-only" in env.client.get("/api/usage/models", headers=env.customer).json()["items"]
    assert env.client.get("/api/usage/models", params={"subscription_id": second, "days": 7},
                          headers=env.customer).json()["items"] == [MODEL, "second-only"]
    admin = env.client.get("/api/admin/usage/models", params={"days": 7}, headers=env.admin).json()
    assert "foreign-only" in admin["items"]
    scoped = env.client.get("/api/admin/usage/models",
                            params={"days": 7, "organization_id": env.orgs["customer"],
                                    "subscription_id": first}, headers=env.admin).json()
    assert scoped == filtered
    assert env.client.get("/api/admin/usage/models", params={"subscription_id": foreign, "days": 7},
                          headers=env.admin).json()["items"] == [MODEL, "foreign-only"]
    with Session(env.db_engine) as db:
        db.execute(insert(UsageRecord), [
            row(env.orgs["customer"], first, f"historical-{i:02}") for i in range(65)
        ])
        db.commit()
    large = env.client.get("/api/usage/models", params={"days": 7, "subscription_id": first},
                           headers=env.customer).json()
    assert large["total"] == 67 and large["items"] == sorted(large["items"])
    assert "historical-64" in large["items"]


@pytest.mark.parametrize("suffix", ["", "/models", "/timeseries", "/export"])
def test_model_endpoints_preserve_authorization(env, usage_data, suffix):
    first, _, foreign, _ = usage_data
    base = "/api/usage" + suffix
    assert env.client.get(base).status_code == 401
    assert env.client.get("/api/admin/usage" + suffix, headers=env.customer).status_code == 403
    for sub in (foreign, str(uuid4())):
        assert env.client.get(base, params={"model": MODEL, "subscription_id": sub},
                              headers=env.customer).status_code == 404
    assert env.client.get("/api/admin/usage" + suffix,
                          params={"organization_id": env.orgs["admin"], "subscription_id": first,
                                  "model": MODEL}, headers=env.admin).status_code == 404
    customer = env.client.get(base, params={"model": "foreign-only"}, headers=env.customer)
    assert customer.status_code == 200
    assert "foreign-only" not in customer.text


def test_export_boundary_counts_only_matching_model_subscription_and_tenant(env):
    first = create_key(env)["id"]
    second = create_key(env, "Other team")["id"]
    org = env.orgs["customer"]
    with Session(env.db_engine) as db:
        db.execute(insert(UsageRecord), [
            *(row(org, first) for _ in range(10_000)),
            row(org, first, "excluded-model"),
            row(org, second),
        ])
        db.commit()
    params = {"model": MODEL, "subscription_id": first}
    response = env.client.get("/api/usage/export", params=params, headers=env.customer)
    assert response.status_code == 200
    assert len(list(csv.DictReader(io.StringIO(response.text)))) == 10_000
    with Session(env.db_engine) as db:
        db.execute(insert(UsageRecord), [row(org, first)])
        db.commit()
    response = env.client.get("/api/usage/export", params=params, headers=env.customer)
    assert response.status_code == 413 and "10000" in response.json()["detail"]


def test_filtered_queries_compile_with_bound_models_for_sql_server(env, usage_data):
    first, _, _, _ = usage_data
    queries = []

    def capture(connection, clause, multiparams, params, execution_options):
        queries.append(clause.compile(dialect=mssql.dialect()))

    event.listen(env.db_engine, "before_execute", capture)
    try:
        for suffix in ("", "/models", "/export"):
            response = env.client.get("/api/usage" + suffix,
                                      params={"model": MODEL, "subscription_id": first, "days": 7},
                                      headers=env.customer)
            assert response.status_code == 200
    finally:
        event.remove(env.db_engine, "before_execute", capture)
    model_queries = [q for q in queries if MODEL in q.params.values()]
    assert len(model_queries) >= 10  # Aggregates, p95, capability checks, rows and export.
    assert all("usage_records.model = :" in str(q) for q in model_queries)
    assert all(MODEL not in str(q) for q in model_queries)
    assert any("SELECT DISTINCT usage_records.model" in str(q) for q in queries)
    assert all(" IS 1" not in str(q) and " IS 0" not in str(q) for q in queries)
