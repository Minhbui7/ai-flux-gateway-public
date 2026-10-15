import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = json.loads((ROOT / "infra" / "models" / "model-spec.json").read_text(encoding="utf-8"))
BY_ID = {model["id"]: model for model in SPEC["models"]}
spec = importlib.util.spec_from_file_location("model_verifier", ROOT / "infra" / "models" / "verify.py")
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


def test_original_deployment_capacities_and_model_root_addresses_are_preserved():
    assert BY_ID["gpt-5.6-luna"]["capacity"] == 120
    assert BY_ID["gpt-5.6-sol"]["capacity"] == 120
    main_tf = (ROOT / "infra" / "models" / "main.tf").read_text(encoding="utf-8")
    assert 'resource "azapi_resource" "openai"' in main_tf
    assert 'key      = "${region}-${model.id}"' in main_tf
    assert "prevent_destroy = true" in main_tf


def test_approved_regions_capacities_versions_and_shared_quota_budgets():
    for alias in ("gpt-6-astra", "gpt-6-luna", "gpt-6-sol", "DeepSeek-V4-Flash-0731", "DeepSeek-V4-Pro"):
        model = BY_ID[alias]
        assert model["capacity"] == 100
        assert model["regions"] if "regions" in model else SPEC["regions"]
        target_regions = model.get("regions", SPEC["regions"])
        assert model["capacity"] * len(target_regions) <= model["shared_quota_limit_units"]
        assert model["capacity"] * model["tpm_per_capacity_unit"] >= 100_000
        assert model["max_completion_tokens"] == 4096

    assert BY_ID["Kimi-K2.6"]["regions"] == ["eastus"]
    assert BY_ID["claude-sonnet-5-5"]["regions"] == ["eastus"]
    assert BY_ID["claude-opus-5-5"]["regions"] == ["eastus"]
    assert BY_ID["claude-sonnet-5-5"]["capacity"] == 50
    assert BY_ID["claude-opus-5-5"]["capacity"] == 40
    assert BY_ID["claude-haiku-5-5"]["region_capacities"] == {"eastus": 50, "swedencentral": 30}
    assert BY_ID["DeepSeek-V4-Flash-0731"]["deprecation_date"] == "2026-12-03"


def test_foundry_direct_endpoint_is_read_from_arm_and_request_contract_is_exact():
    model = BY_ID["Kimi-K2.6"]
    account = {
        "properties": {
            "endpoints": {"Azure AI Model Inference API": "https://foundry.services.ai.azure.com/"}
        }
    }
    endpoint, error = verifier.endpoint_from_account(account, model, {}, "eastus")
    assert error is None
    assert endpoint == "https://foundry.services.ai.azure.com/models"
    assert verifier.operation_url(endpoint, model) == (
        "https://foundry.services.ai.azure.com/models/chat/completions?api-version=2024-05-01-preview"
    )
    assert model["request_token_parameter"] == "max_tokens"
    missing, error = verifier.endpoint_from_account({"properties": {"endpoints": {}}}, model, {}, "eastus")
    assert missing is None
    assert "did not expose" in error


def test_gateway_catalog_matches_acceptance_state_for_new_aliases():
    catalog = json.loads((ROOT / "gateway" / "catalog" / "dev-models.json").read_text(encoding="utf-8"))
    by_id = {model["id"]: model for model in catalog["models"]}
    requested = set(BY_ID) - {"gpt-5.6-luna", "gpt-5.6-sol", "claude-haiku-5-5"}
    assert requested == {
        "gpt-6-astra",
        "gpt-6-luna",
        "gpt-6-sol",
        "Kimi-K2.6",
        "DeepSeek-V4-Flash-0731",
        "DeepSeek-V4-Pro",
        "claude-sonnet-5-5",
        "claude-opus-5-5",
    }
    for alias in requested:
        assert BY_ID[alias]["acceptance_required"] is True
        assert by_id[alias]["max_completion_tokens"] == 4096
        if by_id[alias]["enabled"]:
            assert by_id[alias]["placeholder"] is False
            assert by_id[alias]["capabilities"] == ["chat"]
            assert by_id[alias]["backends"]
            assert all(
                backend["model"] == alias
                and backend["auth"]["managed_identity_resource"] == BY_ID[alias]["auth_audience"]
                for backend in by_id[alias]["backends"]
            )
        else:
            assert by_id[alias]["placeholder"] is True
            assert by_id[alias]["capabilities"] == []
            assert by_id[alias]["backends"] == []
    assert "claude-sonnet-5.5" not in by_id
    assert "claude-opus-5.5" not in by_id


def test_new_model_routes_are_separate_from_original_dev_v1_gate():
    terraform = (ROOT / "infra" / "terraform" / "apim.tf").read_text(encoding="utf-8")
    policy = (ROOT / "gateway" / "policies" / "dev-openai.xml.tftpl").read_text(encoding="utf-8")
    assert '"gpt-5.6-luna", "gpt-5.6-sol"' in terraform
    assert "dev_unified_candidate_model_aliases" in terraform
    assert "dev_unified_accepted_model_aliases" in terraform
    assert "%{ for alias in openai_aliases" in policy
    assert "%{ for alias in anthropic_aliases" in policy
    assert 'request.Remove("max_completion_tokens")' in policy
