import json
from pathlib import Path

import pytest
from aiflux.catalog import Catalog


def test_dev_catalog_keeps_unaccepted_placeholders_uncallable():
    catalog = Catalog.load(Path(__file__).resolve().parents[2] / "gateway/catalog/dev-models.json")
    requested = {
        "gpt-5.4-nano",
        "DeepSeek-V4-Flash",
        "gpt-6-astra",
        "gpt-6-luna",
        "gpt-6-sol",
        "Kimi-K2.6",
        "DeepSeek-V4-Flash-0731",
        "DeepSeek-V4-Pro",
        "claude-sonnet-5-5",
        "claude-opus-5-5",
    }
    enabled = {m.id for m in catalog.models if m.enabled}
    assert {"gpt-5.6-luna", "gpt-5.6-sol", "claude-haiku-5-5"} <= enabled
    accepted = requested & enabled
    placeholders = requested - accepted
    assert accepted | placeholders == requested
    assert {m.id for m in catalog.models if m.placeholder} == placeholders
    assert all(not m.enabled and not m.capabilities for m in catalog.models if m.placeholder)
    assert all(m.max_completion_tokens == 4096 for m in catalog.models if m.placeholder)
    assert not any("." in m.id for m in catalog.models if m.provider == "Anthropic")
    assert all(
        model.placeholder is False
        and model.capabilities == ["chat"]
        and model.max_completion_tokens == 4096
        and model.backends
        for model in catalog.models
        if model.id in accepted
    )
    assert all(
        m.max_completion_tokens == 100000 and m.capabilities == ["chat"]
        for m in catalog.models
        if m.enabled and m.id not in requested
    )


def test_enabled_placeholder_is_rejected(tmp_path):
    path = tmp_path / "catalog.json"
    path.write_text(
        json.dumps(
            {
                "models": [
                    {
                        "id": "preview",
                        "provider": "OpenAI",
                        "capabilities": [],
                        "enabled": True,
                        "placeholder": True,
                    }
                ]
            }
        )
    )
    with pytest.raises(ValueError, match="placeholders cannot be enabled"):
        Catalog.load(path)


def test_catalog_api_exposes_models_with_catalog_acceptance_state(env):
    catalog_path = Path(__file__).resolve().parents[2] / "gateway/catalog/dev-models.json"
    catalog = Catalog.load(catalog_path)
    env.settings.catalog_path = catalog_path
    response = env.client.get("/api/models", headers=env.customer)
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 13
    assert {m["id"] for m in items} == {m.id for m in catalog.models}
    assert {m["id"] for m in items if m["enabled"]} == {m.id for m in catalog.models if m.enabled}
    assert {m["id"] for m in items if m["placeholder"] and not m["enabled"]} == {
        m.id for m in catalog.models if m.placeholder
    }
    assert all(m["max_completion_tokens"] == 4096 for m in items if m["id"] in {
        "gpt-6-astra",
        "gpt-6-luna",
        "gpt-6-sol",
        "Kimi-K2.6",
        "DeepSeek-V4-Flash-0731",
        "DeepSeek-V4-Pro",
        "claude-sonnet-5-5",
        "claude-opus-5-5",
    })


def test_catalog_api_never_advertises_more_than_configured_gateway_limit(env):
    env.settings.catalog_path = Path(__file__).resolve().parents[2] / "gateway/catalog/dev-models.json"
    env.settings.gateway_max_completion_tokens = 50000
    response = env.client.get("/api/models", headers=env.customer)
    assert response.status_code == 200
    assert all(
        model["max_completion_tokens"] <= 50000 for model in response.json()["items"] if model["enabled"]
    )
