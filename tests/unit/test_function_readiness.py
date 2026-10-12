import importlib.util
import json
from pathlib import Path

import azure.functions as func

ROOT = Path(__file__).resolve().parents[2]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_function_indexes_without_connecting_to_sql(monkeypatch):
    folder = ROOT / "services" / "usage-ingestion"
    monkeypatch.syspath_prepend(str(folder))
    module = load_module("usage_function_test", folder / "handlers.py")
    functions = {
        path.parent.name: json.loads(path.read_text())
        for path in folder.glob("*/function.json")
    }
    assert set(functions) == {"ingest_usage", "ingestion_ready"}
    for name, metadata in functions.items():
        assert (folder / name / metadata["scriptFile"]).resolve() == folder / "handlers.py"
        assert callable(getattr(module, metadata["entryPoint"]))
    bindings = functions["ingestion_ready"]["bindings"]
    trigger = next(binding for binding in bindings if binding["type"] == "httpTrigger")
    assert trigger["authLevel"].lower() == func.AuthLevel.FUNCTION.value
    assert trigger["name"] == "request"
    assert trigger["route"] == "ingestion-ready"
    timer = functions["ingest_usage"]["bindings"][0]
    assert timer["name"] == "timer"
    assert timer["schedule"] == "0 */5 * * * *"
    assert timer["runOnStartup"] is False and timer["useMonitor"] is True


def test_readiness_handler_returns_noncacheable_json(monkeypatch):
    folder = ROOT / "services" / "usage-ingestion"
    monkeypatch.syspath_prepend(str(folder))
    module = load_module("usage_handler_test", folder / "handlers.py")
    seen = []
    monkeypatch.setattr(
        module, "verify_runtime", lambda subscription: seen.append(subscription) or {"odbc18": True}
    )
    response = module.ingestion_ready(
        func.HttpRequest("GET", "/api/ingestion-ready", params={"subscription_id": "test"}, body=b"")
    )
    assert seen == ["test"]
    assert json.loads(response.get_body()) == {"odbc18": True}
    assert response.headers["Cache-Control"] == "no-store"


def test_runtime_readiness_checks_sql_and_driver(env, monkeypatch):
    folder = ROOT / "services" / "usage-ingestion"
    module = load_module("runtime_check_test", folder / "runtime_check.py")
    monkeypatch.setattr(module, "get_settings", lambda: env.settings)
    monkeypatch.setattr(module, "engine_for", lambda url: env.db_engine)
    monkeypatch.setattr(module.pyodbc, "drivers", lambda: ["ODBC Driver 18 for SQL Server"])
    result = module.verify_runtime()
    assert result["sql_tables_readable"] is True and result["odbc18"] is True
    assert result["price_rules"] == 0
    result = module.verify_runtime("00000000-0000-0000-0000-000000000001")
    assert result["subscription_active"] is False
