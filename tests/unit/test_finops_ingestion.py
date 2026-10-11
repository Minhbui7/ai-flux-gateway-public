import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from aiflux.catalog import BackendEntry, Catalog
from aiflux.finops import calculate_cost
from aiflux.ingestion import extract_safety, ingest_rows, nonnegative
from aiflux.models import ModelPrice, SafetyEvent, UsageRecord
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
