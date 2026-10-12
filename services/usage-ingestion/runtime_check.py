"""Read-only startup verification inside the Function's private network."""

import json
import logging
from pathlib import Path
from uuid import UUID

import pyodbc
from aiflux.catalog import Catalog
from aiflux.config import get_settings
from aiflux.db import engine_for
from aiflux.finops import aware, usage_response
from aiflux.models import IngestionState, ModelPrice, SafetyEvent, TeamSubscription, UsageRecord
from sqlalchemy import func, select
from sqlalchemy.orm import Session


def verify_runtime(subscription_id: str | None = None) -> dict:
    settings = get_settings()
    if "ODBC Driver 18 for SQL Server" not in pyodbc.drivers():
        raise RuntimeError("Required SQL Server ODBC Driver 18 is unavailable")
    catalog = Catalog.load(Path(settings.catalog_path))
    with Session(engine_for(settings.database_url)) as db:
        for table in (TeamSubscription, ModelPrice, UsageRecord, IngestionState, SafetyEvent):
            db.execute(select(1).select_from(table).limit(1)).all()
        owned = db.scalar(select(func.count()).select_from(TeamSubscription))
        prices = db.scalar(select(func.count()).select_from(ModelPrice))
        subscription = db.get(TeamSubscription, str(UUID(subscription_id))) if subscription_id else None
        result = {
            "sql_tables_readable": True, "odbc18": True,
            "enabled_models": sum(model.enabled for model in catalog.models),
            "owned_subscriptions": owned, "price_rules": prices,
        }
        if subscription_id:
            result["subscription_active"] = subscription is not None and subscription.state == "active"
            if subscription is not None:
                result["subscription_usage"] = usage_response(
                    db, subscription.organization_id, 1, subscription.id, 0, 1,
                )["summary"]
        state = db.get(IngestionState, "native-llm")
        result["watermark"] = aware(state.watermark).isoformat() if state else None
    logging.getLogger(__name__).warning(
        "FinOps runtime readiness %s",
        json.dumps({key: value for key, value in result.items() if key != "subscription_usage"}),
    )
    return result
