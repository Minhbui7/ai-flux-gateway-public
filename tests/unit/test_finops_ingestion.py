import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from aiflux.catalog import BackendEntry, Catalog
from aiflux.finops import calculate_cost
from aiflux.ingestion import extract_safety, extract_usage, ingest_rows, nonnegative, run_once
from aiflux.models import IngestionState, ModelPrice, SafetyEvent, UsageRecord
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_control_plane import create_key


def record(**kwargs):
    return UsageRecord(
        input_tokens=100, output_tokens=20, cached_input_tokens=40, cache_write_tokens=10, **kwargs
    )


def price(**kwargs):
    return ModelPrice(
        input_per_million=Decimal(2),
        output_per_million=Decimal(4),
        cached_input_per_million=Decimal(1),
        cache_write_per_million=Decimal(3),
        input_includes_cached=True,
        **kwargs,
    )


def test_cache_reads_and_writes_are_not_double_counted():
    cost, completeness = calculate_cost(record(), price())
    assert cost == Decimal("0.00025") and completeness == "complete"
    row = record()
    row.cached_input_tokens = None
    assert calculate_cost(row, price()) == (None, "cache_usage_missing")


def test_missing_usage_price_and_inconsistent_categories():
    row = record()
    assert calculate_cost(row, None) == (None, "price_missing")
    row.output_tokens = None
    assert calculate_cost(row, price()) == (None, "usage_missing")
    row = record()
    row.cached_input_tokens = 200
    assert calculate_cost(row, price()) == (None, "cache_accounting_unknown")


def test_telemetry_deduplication_and_metadata_only_safety(env):
    key = create_key(env)
    now = datetime.now(UTC)
    source = {
        "subscription_id": key["id"],
        "correlation_id": "correlation-test",
        "resource_id": env.settings.apim_resource_id,
        "occurred_at": now,
        "model": "test-model",
        "input_tokens": 50,
        "output_tokens": 5,
        "status_code": 403,
        "e2e_ms": 20,
        "trace_records": [
            {
                "source": "aiflux",
                "metadata": {"category": "PromptInjection", "action": "blocked", "body": "DO NOT STORE"},
            }
        ],
    }
    with Session(env.db_engine) as db:
        db.add(
            ModelPrice(
                model="test-alias",
                provider="test",
                region="test-region",
                effective_from=now,
                currency="USD",
                input_per_million=Decimal(2),
                output_per_million=Decimal(4),
                input_includes_cached=True,
            )
        )
        db.commit()
        for _ in range(2):
            assert ingest_rows(db, [source], Catalog.load(env.settings.catalog_path)) == 1
            db.commit()
        rows = db.scalars(select(UsageRecord)).all()
        assert len(rows) == 1 and rows[0].cost == Decimal("0.00012")
        assert rows[0].ttft_ms is None and rows[0].cached_input_tokens is None
        assert len(db.scalars(select(SafetyEvent)).all()) == 1
    response = env.client.get("/api/usage", headers=env.customer).json()
    assert response["total"] == 1 and "DO NOT STORE" not in str(response)
    assert response["summary"]["e2e_p95_ms"] == 20
    safety = env.client.get("/api/admin/safety", headers=env.admin).json()
    assert safety["total"] == 1 and "DO NOT STORE" not in str(safety)


def test_gateway_region_never_substitutes_for_backend_region(env):
    key = create_key(env)
    catalog = Catalog.load(env.settings.catalog_path)
    catalog.models[0].region = ""
    source = {
        "subscription_id": key["id"],
        "correlation_id": "corr",
        "resource_id": "resource",
        "occurred_at": datetime.now(UTC),
        "model": "test-model",
        "input_tokens": None,
        "output_tokens": None,
        "status_code": 200,
        "gateway_region": "not-a-backend-region",
    }
    with Session(env.db_engine) as db:
        ingest_rows(db, [source], catalog)
        db.commit()
        row = db.scalar(select(UsageRecord))
        assert row.region == "" and row.cost is None and row.completeness == "backend_attribution_missing"


def test_unknown_ownership_blocks_ingestion(env):
    with Session(env.db_engine) as db, pytest.raises(ValueError, match="unknown APIM subscription"):
        ingest_rows(db, [{"subscription_id": "not-owned"}], Catalog.load(env.settings.catalog_path))


@pytest.mark.parametrize("value", [-1, True, 1.2, "100"])
def test_invalid_native_token_values_are_rejected(value):
    with pytest.raises(ValueError):
        nonnegative(value, "input_tokens")


def test_safety_trace_allowlist():
    assert (
        extract_safety([{"source": "aiflux", "metadata": {"category": "raw-prompt", "action": "blocked"}}])
        == []
    )


def test_live_native_trace_metadata_json_string_is_supported():
    assert extract_safety(
        [
            {
                "source": "aiflux",
                "metadata": '{"category":"ContentSafety","action":"blocked"}',
            }
        ]
    ) == [("ContentSafety", "blocked")]


def usage_trace(**changes):
    return [{
        "source": "aiflux",
        "metadata": {
            "category": "usage",
            "payload": json.dumps({
                "schema": "finops-v1", "model": "test-alias", "attempts": 1,
                "input_tokens": 100, "output_tokens": 20,
                "cached_input_tokens": 40, "cache_write_tokens": 10, **changes,
            }),
        },
    }]


def test_provider_usage_trace_prices_cache_and_reports_support(env):
    key = create_key(env)
    now = datetime.now(UTC)
    source = {
        "subscription_id": key["id"], "correlation_id": "provider-usage",
        "resource_id": env.settings.apim_resource_id, "occurred_at": now,
        "status_code": 200, "trace_records": usage_trace(),
    }
    with Session(env.db_engine) as db:
        db.add(price(model="test-alias", provider="test", region="test-region",
                     effective_from=now, currency="USD"))
        db.commit()
        ingest_rows(db, [source], Catalog.load(env.settings.catalog_path))
        db.commit()
        row = db.scalar(select(UsageRecord))
        assert row.cost == Decimal("0.00025") and row.completeness == "complete"
        assert row.cached_input_tokens == 40 and row.cache_write_tokens == 10
        source["trace_records"] = usage_trace(attempts=2)
        ingest_rows(db, [source], Catalog.load(env.settings.catalog_path))
        db.commit()
        assert row.cost is None and row.completeness == "retry_usage_unknown"
    response = env.client.get("/api/usage", headers=env.customer).json()
    assert response["summary"]["cache_tokens_supported"] is True


@pytest.mark.parametrize("changes", [
    {"schema": "unsupported"}, {"attempts": 0}, {"attempts": True},
    {"cached_input_tokens": -1}, {"output_tokens": "20"}, {"model": None},
])
def test_invalid_provider_usage_trace_is_rejected(changes):
    with pytest.raises(ValueError):
        extract_usage(usage_trace(**changes))


def test_duplicate_usage_trace_is_rejected_and_missing_counters_stay_unknown():
    with pytest.raises(ValueError, match="unique"):
        extract_usage(usage_trace() * 2)
    assert extract_usage(usage_trace(cached_input_tokens=None))["cached_input_tokens"] is None
    assert extract_usage([]) is None


@pytest.mark.parametrize("metadata", ['{"category":', '["ContentSafety"]'])
def test_invalid_native_safety_metadata_is_not_silently_dropped(metadata):
    with pytest.raises(ValueError):
        extract_safety([{"source": "aiflux", "metadata": metadata}])


def test_retry_usage_is_not_presented_as_complete_billing(env):
    key = create_key(env)
    now = datetime.now(UTC)
    source = {
        "subscription_id": key["id"],
        "correlation_id": "retry",
        "resource_id": env.settings.apim_resource_id,
        "occurred_at": now,
        "model": "test-model",
        "input_tokens": 9,
        "output_tokens": 4,
        "status_code": 200,
        "trace_records": [
            {"source": "aiflux", "metadata": '{"retry":"transient_backend","previous_status":"500"}'}
        ],
    }
    with Session(env.db_engine) as db:
        db.add(
            ModelPrice(
                model="test-alias",
                provider="test",
                region="test-region",
                effective_from=now,
                currency="USD",
                input_per_million=Decimal(2),
                output_per_million=Decimal(4),
                input_includes_cached=True,
            )
        )
        db.commit()
        ingest_rows(db, [source], Catalog.load(env.settings.catalog_path))
        db.commit()
        row = db.scalar(select(UsageRecord))
        assert row.cost is None and row.completeness == "retry_usage_unknown"
        assert db.scalar(select(SafetyEvent)) is None


def test_usage_query_includes_the_deployed_chat_operation():
    query = (
        Path(__file__).resolve().parents[2]
        / "services"
        / "control-plane"
        / "src"
        / "aiflux"
        / "queries"
        / "usage.kql"
    ).read_text(encoding="utf-8")
    assert 'OperationId in ("chat", "chat-completions")' in query
    assert "ProductId == {product}" in query


def test_generic_native_safety_event_does_not_invent_harm_category():
    assert extract_safety(
        [
            {
                "source": "aiflux",
                "metadata": {"category": "ContentSafety", "action": "blocked"},
            }
        ]
    ) == [("ContentSafety", "blocked")]


def test_versioned_model_name_uses_exact_deployment_attribution(env):
    key = create_key(env)
    source = {
        "subscription_id": key["id"],
        "correlation_id": "versioned-model",
        "resource_id": env.settings.apim_resource_id,
        "occurred_at": datetime.now(UTC),
        "model": "test-model-2026-07-09",
        "deployment": "test-model",
        "input_tokens": 9,
        "output_tokens": 4,
        "status_code": 200,
    }
    with Session(env.db_engine) as db:
        ingest_rows(db, [source], Catalog.load(env.settings.catalog_path))
        db.commit()
        row = db.scalar(select(UsageRecord))
        assert row.model == "test-alias" and row.provider == "test" and row.region == "test-region"


@pytest.mark.parametrize(
    "backend_id,expected_region",
    [
        ("endpoint-east", "eastus"),
        ("endpoint-sweden", "swedencentral"),
        ("pool-id", ""),
        (None, ""),
    ],
)
def test_pooled_model_requires_exact_selected_endpoint_for_costing(env, backend_id, expected_region):
    key = create_key(env)
    catalog = Catalog.load(env.settings.catalog_path)
    catalog.models[0].backends = [
        BackendEntry(id="endpoint-east", region="eastus"),
        BackendEntry(id="endpoint-sweden", region="swedencentral"),
    ]
    source = {
        "subscription_id": key["id"],
        "correlation_id": "pooled-model",
        "resource_id": env.settings.apim_resource_id,
        "occurred_at": datetime.now(UTC),
        "model": "test-model",
        "backend_id": backend_id,
        "input_tokens": 9,
        "output_tokens": 4,
        "status_code": 200,
        "gateway_region": "not-the-model-region",
    }
    with Session(env.db_engine) as db:
        ingest_rows(db, [source], catalog)
        db.commit()
        row = db.scalar(select(UsageRecord))
        assert row.region == expected_region
        if not expected_region:
            assert row.provider == "" and row.completeness == "backend_attribution_missing"


def test_catalog_rejects_duplicate_endpoint_ids(env):
    payload = Catalog.load(env.settings.catalog_path).model_dump()
    payload["models"][0]["backends"] = [
        {"id": "duplicate", "region": "eastus"},
        {"id": "duplicate", "region": "swedencentral"},
    ]
    env.settings.catalog_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate backend endpoint"):
        Catalog.load(env.settings.catalog_path)


def test_activation_cutoff_clamps_initial_and_replayed_overlap(env, monkeypatch):
    from aiflux import ingestion

    cutoff = datetime.now(UTC) - timedelta(minutes=20)
    env.settings.ingestion_start_at = cutoff
    windows = []

    def query(client, settings, start, end):
        windows.append((start, end))
        return []

    monkeypatch.setattr(ingestion, "engine_for", lambda url: env.db_engine)
    monkeypatch.setattr(ingestion, "query_rows", query)
    assert run_once(env.settings, object()) == 0
    assert run_once(env.settings, object()) == 0
    assert len(windows) == 2
    assert all(start == cutoff and end > start for start, end in windows)
    with Session(env.db_engine) as db:
        state = db.get(IngestionState, "native-llm")
        assert state is not None


def test_activation_cutoff_cannot_skip_existing_watermark(env, monkeypatch):
    from aiflux import ingestion

    now = datetime.now(UTC)
    env.settings.ingestion_start_at = now
    with Session(env.db_engine) as db:
        db.add(IngestionState(id="native-llm", watermark=now - timedelta(hours=1), last_success_at=now))
        db.commit()
    monkeypatch.setattr(ingestion, "engine_for", lambda url: env.db_engine)
    with pytest.raises(ValueError, match="explicit reconciliation"):
        run_once(env.settings, object())


def test_activation_cutoff_requires_timezone(env):
    env.settings.ingestion_start_at = datetime(2026, 1, 1)
    with pytest.raises(ValueError, match="explicit timezone"):
        run_once(env.settings, object())


def test_future_activation_cutoff_does_not_query_or_advance(env, monkeypatch):
    from aiflux import ingestion

    env.settings.ingestion_start_at = datetime.now(UTC) + timedelta(days=1)
    monkeypatch.setattr(ingestion, "engine_for", lambda url: env.db_engine)
    assert run_once(env.settings, object()) == 0
    with Session(env.db_engine) as db:
        assert db.get(IngestionState, "native-llm") is None


def test_multiple_backend_requests_are_visibly_incomplete(env):
    key = create_key(env)
    source = {
        "subscription_id": key["id"], "correlation_id": "multiple-attempts",
        "resource_id": "resource", "occurred_at": datetime.now(UTC),
        "model": "test-model", "input_tokens": 9, "output_tokens": 4,
        "status_code": 200, "multiple_backend_requests": True,
    }
    with Session(env.db_engine) as db:
        ingest_rows(db, [source], Catalog.load(env.settings.catalog_path))
        db.commit()
        row = db.scalar(select(UsageRecord))
        assert row.cost is None and row.completeness == "retry_usage_unknown"
