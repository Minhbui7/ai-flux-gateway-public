import json
from datetime import UTC, datetime
from uuid import UUID

import pytest
from aiflux import price_bootstrap
from aiflux.models import AuditEvent, ModelPrice
from aiflux.price_bootstrap import import_prices
from sqlalchemy import func, select
from sqlalchemy.orm import Session

ACTOR = UUID("11111111-1111-4111-8111-111111111111")


def test_startup_executes_api_only_after_successful_import(env, tmp_path, monkeypatch):
    path = rules(tmp_path)
    monkeypatch.setattr(price_bootstrap, "get_settings", lambda: env.settings)
    monkeypatch.setattr(price_bootstrap, "engine_for", lambda url: env.db_engine)
    monkeypatch.setattr(price_bootstrap.sys, "argv", [
        "bootstrap", "--file", str(path), "--actor-object-id", str(ACTOR), "--serve",
    ])
    executed = []
    monkeypatch.setattr(price_bootstrap.os, "execv", lambda executable, args: executed.append(args))
    price_bootstrap.main()
    assert executed[0][1:] == [
        "-m", "uvicorn", "aiflux.app:app",
        "--host", "0.0.0.0", "--port", "8000", "--no-access-log",
    ]
    executed.clear()
    rules(tmp_path, output_per_million="6")
    with pytest.raises(ValueError, match="overlap"):
        price_bootstrap.main()
    assert not executed


def rules(tmp_path, **overrides):
    path = tmp_path / "prices.json"
    path.write_text(json.dumps([{
        "model": "test-alias", "provider": "test", "region": "test-region",
        "effective_from": datetime(2026, 10, 12, tzinfo=UTC).isoformat(),
        "currency": "USD", "input_per_million": "1", "output_per_million": "5",
        **overrides,
    }]))
    return path


def test_import_is_idempotent_and_audited(env, tmp_path):
    with Session(env.db_engine) as db:
        path = rules(tmp_path)
        assert import_prices(db, env.settings, path, ACTOR) == 1
        assert import_prices(db, env.settings, path, ACTOR) == 0
        assert db.scalar(select(func.count()).select_from(ModelPrice)) == 1
        audit = db.scalars(select(AuditEvent)).one()
        assert audit.object_id == str(ACTOR)
        assert audit.action == "price.deployment.created"


def test_import_rejects_overwriting_existing_period(env, tmp_path):
    with Session(env.db_engine) as db:
        import_prices(db, env.settings, rules(tmp_path), ACTOR)
        with pytest.raises(ValueError, match="overlap"):
            import_prices(db, env.settings, rules(tmp_path, output_per_million="6"), ACTOR)
        db.rollback()
        assert db.scalars(select(ModelPrice)).one().output_per_million == 5


def test_import_rejects_unaccepted_or_unknown_catalog(env, tmp_path):
    with Session(env.db_engine) as db:
        with pytest.raises(ValueError, match="enabled catalog endpoint"):
            import_prices(db, env.settings, rules(tmp_path, model="unknown"), ACTOR)
        with pytest.raises(ValueError, match="accepted catalog"):
            import_prices(
                db, env.settings.model_copy(update={"catalog_configured": False}),
                rules(tmp_path), ACTOR,
            )
        assert db.scalar(select(func.count()).select_from(ModelPrice)) == 0
