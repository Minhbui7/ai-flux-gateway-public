import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from azure.identity import DefaultAzureCredential
from azure.monitor.query import LogsQueryClient, LogsQueryStatus
from sqlalchemy.orm import Session

from aiflux.catalog import Catalog
from aiflux.config import Settings, get_settings
from aiflux.db import engine_for
from aiflux.finops import aware, calculate_cost, price_for
from aiflux.models import IngestionState, SafetyEvent, TeamSubscription, UsageRecord

log = logging.getLogger(__name__)
SAFE_CATEGORIES = {
    "Hate",
    "SelfHarm",
    "Sexual",
    "Violence",
    "PromptInjection",
    "ContentSafety",
    "PiiFailure",
    "SafetyFailure",
}
SAFE_ACTIONS = {"blocked", "stream_stopped", "dependency_failed"}


def nonnegative(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float) or int(value) != value or value < 0:
        raise ValueError(f"Invalid native telemetry field: {field}")
    return int(value)


def record_id(resource: str, correlation_id: str) -> str:
    return hashlib.sha256(f"{resource.lower()}:{correlation_id}".encode()).hexdigest()


def trace_metadata(records: Any) -> list[dict]:
    if isinstance(records, str):
        records = json.loads(records)
    if records is None:
        return []
    if not isinstance(records, list):
        raise ValueError("Native trace_records must be a list")
    items = []
    for record in records:
        if not isinstance(record, dict) or record.get("source") != "aiflux":
            continue
        metadata = record.get("metadata", {})
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        if not isinstance(metadata, dict):
            raise ValueError("AIFLUX safety trace metadata is invalid")
        items.append(metadata)
    return items


def extract_safety(records: Any) -> list[tuple[str, str]]:
    return [
        (metadata["category"], metadata["action"])
        for metadata in trace_metadata(records)
        if metadata.get("category") in SAFE_CATEGORIES and metadata.get("action") in SAFE_ACTIONS
    ]


def extract_usage(records: Any) -> dict[str, Any] | None:
    events = [
        metadata for metadata in trace_metadata(records)
        if metadata.get("category") == "usage"
    ]
    if not events:
        return None
    if len(events) != 1:
        raise ValueError("Provider usage trace must be unique")
    payload = events[0].get("payload")
    if not isinstance(payload, str):
        raise ValueError("Provider usage trace payload is invalid")
    usage = json.loads(payload)
    if not isinstance(usage, dict) or usage.get("schema") != "finops-v1":
        raise ValueError("Provider usage trace schema is invalid")
    if not isinstance(usage.get("model"), str) or not usage["model"]:
        raise ValueError("Provider usage trace model is invalid")
    attempts = nonnegative(usage.get("attempts"), "attempts")
    if attempts not in (1, 2):
        raise ValueError("Provider usage trace attempts is invalid")
    for field in ("input_tokens", "output_tokens", "cached_input_tokens", "cache_write_tokens"):
        usage[field] = nonnegative(usage.get(field), field)
    return usage


def ingest_rows(db: Session, rows: list[dict[str, Any]], catalog: Catalog) -> int:
    count = 0
    for source in rows:
        sid = source.get("subscription_id")
        subscription = db.get(TeamSubscription, sid) if isinstance(sid, str) else None
        if subscription is None:
            # Do not advance a watermark past unresolved ownership; replay after reconciliation.
            raise ValueError("Native usage has an unknown APIM subscription; reconcile ownership")
        correlation = source.get("correlation_id")
        resource = source.get("resource_id")
        if not isinstance(correlation, str) or not correlation or not isinstance(resource, str):
            raise ValueError("Native usage correlation is missing")
        rid = record_id(resource, correlation)
        occurred = source["occurred_at"]
        if isinstance(occurred, str):
            occurred = datetime.fromisoformat(occurred.replace("Z", "+00:00"))
        if not isinstance(occurred, datetime):
            raise ValueError("Native usage timestamp is invalid")
        occurred = aware(occurred)
        usage = extract_usage(source.get("trace_records"))
        actual_model = (
            (usage["model"] if usage else None) or source.get("model") or source.get("deployment") or ""
        )
        identifiers = {
            value
            for value in (source.get("model"), source.get("deployment"), usage["model"] if usage else None)
            if isinstance(value, str) and value
        }
        matches = [
            model
            for model in catalog.models
            if model.backend_model in identifiers
            or model.id in identifiers
            or any(backend.model in identifiers for backend in model.backends if backend.model)
        ]
        model = matches[0] if len(matches) == 1 else None
        provider, region = (model.provider, model.region) if model else ("", "")
        if model and model.backends:
            endpoints = [backend for backend in model.backends if backend.id == source.get("backend_id")]
            endpoint = endpoints[0] if len(endpoints) == 1 else None
            region = endpoint.region if endpoint else ""
            provider = (endpoint.provider or model.provider) if endpoint else ""
        alias = model.id if model else actual_model
        # A gateway region is not a backend region. Missing attribution remains visibly incomplete.
        row = db.get(UsageRecord, rid)
        if row is None:
            row = UsageRecord(id=rid, organization_id=subscription.organization_id, subscription_id=sid)
            db.add(row)
        row.occurred_at = occurred
        row.model, row.provider, row.region = alias, provider, region
        row.status_code = nonnegative(source.get("status_code"), "status_code") or 0
        row.e2e_ms = nonnegative(source.get("e2e_ms"), "e2e_ms")
        row.input_tokens = nonnegative((usage or source).get("input_tokens"), "input_tokens")
        row.output_tokens = nonnegative((usage or source).get("output_tokens"), "output_tokens")
        row.cached_input_tokens = usage["cached_input_tokens"] if usage else None
        row.cache_write_tokens = usage["cache_write_tokens"] if usage else None
        row.ttft_ms = None
        row.ingested_at = datetime.now(UTC)
        with db.no_autoflush:
            price = price_for(db, row) if provider and region else None
        row.cost, row.completeness = calculate_cost(row, price)
        if not provider or not region:
            row.cost, row.completeness = None, "backend_attribution_missing"
        if row.status_code == 0:
            row.cost, row.completeness = None, "status_missing"
        if row.completeness == "complete" and any(
            metadata.get("retry") == "transient_backend"
            for metadata in trace_metadata(source.get("trace_records"))
        ):
            row.cost, row.completeness = None, "retry_usage_unknown"
        if source.get("multiple_backend_requests") is True or (usage and usage["attempts"] > 1):
            row.cost, row.completeness = None, "retry_usage_unknown"
        row.currency = price.currency if price and row.cost is not None else None
        for category, action in extract_safety(source.get("trace_records")):
            event_id = record_id(resource, f"{correlation}:{category}:{action}")
            event = db.get(SafetyEvent, event_id)
            if event is None:
                db.add(
                    SafetyEvent(
                        id=event_id,
                        organization_id=subscription.organization_id,
                        subscription_id=sid,
                        occurred_at=occurred,
                        category=category,
                        action=action,
                        correlation_id=correlation,
                    )
                )
        count += 1
    return count


def query_rows(client: LogsQueryClient, settings: Settings, start: datetime, end: datetime) -> list[dict]:
    query = Path(__file__).with_name("queries").joinpath("usage.kql").read_text(encoding="utf-8")
    query = query.format(
        start=start.isoformat(),
        end=end.isoformat(),
        resource=json.dumps(settings.apim_resource_id),
        product=json.dumps(settings.apim_product_id),
        row_limit=settings.ingestion_max_rows + 1,
    )
    response = client.query_workspace(settings.log_workspace_id, query, timespan=(start, end))
    if response.status != LogsQueryStatus.SUCCESS:
        raise RuntimeError("Azure Monitor returned partial usage data; watermark was not advanced")
    rows: list[dict] = []
    for table in response.tables:
        rows.extend(dict(zip(table.columns, values, strict=True)) for values in table.rows)
    if len(rows) > settings.ingestion_max_rows:
        raise RuntimeError("Usage window exceeds row limit; reduce ingestion_batch_minutes")
    return rows


def run_once(settings: Settings, client: LogsQueryClient) -> int:
    if not settings.database_url or not settings.log_workspace_id or not settings.apim_resource_id:
        raise ValueError("Configure database, Monitor workspace and APIM resource ID before ingestion")
    if not settings.catalog_configured:
        raise ValueError("Catalog must pass capability validation before usage ingestion")
    if (
        min(settings.ingestion_batch_minutes, settings.ingestion_max_rows, settings.ingestion_initial_days)
        <= 0
    ):
        raise ValueError("Ingestion batch, row limit and initial lookback must be positive")
    if settings.ingestion_overlap_minutes < 0 or settings.ingestion_delay_minutes < 0:
        raise ValueError("Ingestion overlap and delay must be nonnegative")
    cutoff = settings.ingestion_start_at
    if cutoff is not None:
        if cutoff.tzinfo is None or cutoff.utcoffset() is None:
            raise ValueError("Ingestion activation cutoff requires an explicit timezone")
        cutoff = aware(cutoff)
    catalog = Catalog.load(settings.catalog_path)
    now = datetime.now(UTC)
    ceiling = now - timedelta(minutes=settings.ingestion_delay_minutes)
    with Session(engine_for(settings.database_url)) as db:
        state = db.get(IngestionState, "native-llm")
        watermark = aware(state.watermark) if state else (
            cutoff if cutoff is not None else now - timedelta(days=settings.ingestion_initial_days)
        )
        if state and cutoff is not None and watermark < cutoff:
            raise ValueError("Activation cutoff exceeds existing watermark; explicit reconciliation required")
        # Replay preceding windows to recover late-arriving LLM records and missing usage.
        start = watermark - timedelta(minutes=settings.ingestion_overlap_minutes)
        if cutoff is not None:
            start = max(start, cutoff)
        end = min(watermark + timedelta(minutes=settings.ingestion_batch_minutes), ceiling)
        if end <= start:
            return 0
        rows = query_rows(client, settings, start, end)
        count = ingest_rows(db, rows, catalog)
        if state is None:
            state = IngestionState(id="native-llm", watermark=end, last_success_at=now)
            db.add(state)
        else:
            state.watermark = max(watermark, end)
            state.last_success_at = now
        db.commit()
        log.info("Usage ingestion completed records=%s", count)
        return count


def main() -> None:
    settings = get_settings()
    with DefaultAzureCredential() as credential, LogsQueryClient(credential) as client:
        run_once(settings, client)


if __name__ == "__main__":
    main()
