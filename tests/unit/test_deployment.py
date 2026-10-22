import importlib.util
import json
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from aiflux.catalog import Catalog
from aiflux.ingestion import ingest_rows
from aiflux.models import ModelPrice, UsageRecord
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_control_plane import create_key

from scripts.deployment.launcher import (
    ALIASES,
    ATTESTATIONS,
    ROOT,
    DeploymentError,
    Launcher,
    Runner,
    environment_lock,
    load_config,
    read_json,
    write_json,
)


@pytest.fixture
def config(tmp_path):
    value = read_json(ROOT / "infra" / "deployment" / "customer.example.json")
    for index, key in enumerate(
        ("tenant_id", "subscription_id", "bootstrap_object_id", "sql_admin_object_id"), 1
    ):
        value[key] = f"00000000-0000-0000-0000-{index:012d}"
    value.update(operator_ip="8.8.8.8", dns_label="customer-pilot")
    value["backend"] = {
        "resource_group_name": "backend-rg", "storage_account_name": "existingstate",
        "container_name": "tfstate", "main_key": value["name_prefix"] + "/main.tfstate",
        "models_key": value["name_prefix"] + "/models.tfstate",
    }
    value["attestations"] = dict.fromkeys(ATTESTATIONS, True)
    value["manual_rbac_verified"] = True
    path = tmp_path / "customer.json"
    write_json(path, value)
    return load_config(path)


class FakeRunner:
    def __init__(self):
        self.commands = []
        self.changes = []
        self.fail_apply = False

    def __call__(self, args, *, json_output=True):
        self.commands.append(args)
        if args[:4] == ["az", "storage", "blob", "exists"]:
            return {"exists": False}
        if args[0] == "terraform":
            if args[2] == "plan":
                Path(next(arg.removeprefix("-out=") for arg in args if arg.startswith("-out="))).write_bytes(
                    b"binary-saved-plan"
                )
            if args[2] == "show":
                return {"resource_changes": self.changes}
            if args[2] == "apply" and self.fail_apply:
                raise DeploymentError("apply failed")
        return {} if json_output else b""


@pytest.fixture
def launcher(config, tmp_path, monkeypatch):
    runner = FakeRunner()
    instance = Launcher(config, tmp_path, runner)
    monkeypatch.setattr(instance, "preflight", lambda: None)
    monkeypatch.setattr(instance, "source_fingerprint", lambda: "source-v1")
    return instance


def test_example_fails_before_any_cloud_access(tmp_path):
    with pytest.raises(DeploymentError, match="Replace tenant_id"):
        load_config(ROOT / "infra" / "deployment" / "customer.example.json")


def test_powershell_entry_point_without_approval_reaches_configuration_validation():
    powershell = shutil.which("powershell")
    if powershell is None:
        pytest.skip("Windows PowerShell is unavailable")
    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "scripts" / "deploy.ps1"),
            "-Config",
            str(ROOT / "infra" / "deployment" / "customer.example.json"),
            "-Action",
            "preflight",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "Replace tenant_id" in result.stdout + result.stderr
    assert "expected one argument" not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "changes",
    [
        {"operator_ip": "0.0.0.0"},
        {"operator_ip": "10.1.1.1"},
        {"operator_ip": "8.8.8.8/32"},
        {"operator_ip": "224.0.0.1"},
        {"sql_location": "unverified"},
        {"network_profile": "10.242"},
        {"admin_settings_enabled": 1},
        {"admin_settings_provisioned": "true"},
        {"gateway_controls_v2_enabled": 1},
        {"gateway_controls_v2_enabled": True},
        {"protected_material_available": "false"},
        {"monthly_request_quota_available": 1},
        {"safety_relaxation_allowed": None},
        {"gateway_max_rpm": True},
        {"gateway_max_rpm": 0},
        {"gateway_max_rpm": 100001},
        {"mise_direct_jwt_enabled": "true"},
        {"dev_openai_content_safety_threshold": True},
        {"dev_openai_content_safety_threshold": "1"},
        {"dev_openai_content_safety_threshold": -1},
        {"dev_openai_content_safety_threshold": 8},
        {"dev_openai_content_safety_threshold": 1.5},
        {"certificate_secret_id": "https://other.vault.azure.net/secrets/cert"},
        {"certificate_secret_id": "https://aifluxpilotkv.vault.azure.net/secrets/cert/version"},
        {"client_secret": "do-not-allow"},
        {"attestations": {}},
        {"dns_label": "https://injection.invalid"},
        {"name_prefix": "../../other"},
        {"app_gateway_existing_nsg_name": "../other/nsg"},
        {"app_gateway_existing_nsg_name": 123},
        {"ingestion_start_at": "2026-10-15T00:00:00"},
        {"additional_model_aliases": None},
        {"additional_model_aliases": "gpt-5.4-nano"},
        {"additional_model_aliases": ["gpt-5.4-nano"]},
        {"additional_model_aliases": [{}]},
        {"app_always_on": None},
        {"app_always_on": {"unknown": False}},
        {"app_always_on": {"customer": "false"}},
        {"app_always_on": {"admin": 0}},
        {"monthly_budget": []},
        {"monthly_budget": {}},
    ],
)
def test_configuration_rejects_unsafe_inputs(config, tmp_path, changes):
    config.update(changes)
    path = tmp_path / "invalid.json"
    write_json(path, config)
    with pytest.raises(DeploymentError):
        load_config(path)


def test_local_lock_prevents_two_writers_and_cleans_up(tmp_path):
    with environment_lock(tmp_path):
        with pytest.raises(DeploymentError, match="locked"):
            with environment_lock(tmp_path):
                pytest.fail("second writer entered")
    assert not (tmp_path / "deployment.lock").exists()


def test_lock_survives_unrelated_existing_file(tmp_path):
    path = tmp_path / "deployment.lock"
    path.write_text("existing operator")
    with pytest.raises(DeploymentError):
        with environment_lock(tmp_path):
            pass
    assert path.read_text() == "existing operator"


def test_prerequisite_profile_preserves_private_data_and_release_gates(launcher):
    values = launcher.main_inputs("prerequisites")
    assert values["location"] == "eastus"
    assert values["app_service_sku"] == "B1"
    assert values["network"]["app_service_integration_subnet"] == "10.240.4.0/24"
    assert values["hybrid_private_data_enabled"]
    for name in ("sql", "key_vault", "function_storage"):
        assert values[name + "_public_network_access_enabled"] is False
    assert "public_edge_live_gates_approved" not in values
    assert "dev_openai_inference_enabled" not in values
    assert Path(values["model_backends_file"]).parent == launcher.directory


def test_cost_approval_is_required(launcher):
    launcher.config["attestations"]["cost_network_and_permissions_reviewed"] = False
    with pytest.raises(DeploymentError, match="cost_network"):
        launcher.plan("prerequisites")
    assert not launcher.run.commands


def monthly_budget():
    return {
        "name": "pilot-monthly",
        "amount": 1000,
        "start_date": "2026-10-01T00:00:00Z",
        "end_date": "2027-10-01T00:00:00Z",
        "contact_emails": ["operator@example.com"],
        "import_existing": False,
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"name": "../other"},
        {"amount": 0},
        {"amount": -1},
        {"amount": True},
        {"amount": "1000"},
        {"amount": float("inf")},
        {"amount": float("nan")},
        {"start_date": "2026-10-02T00:00:00Z"},
        {"start_date": "2026-13-01T00:00:00Z"},
        {"start_date": "2026-10-01"},
        {"end_date": "2026-10-01T00:00:00Z"},
        {"end_date": "2025-10-01T00:00:00Z"},
        {"end_date": None},
        {"contact_emails": []},
        {"contact_emails": ["not-an-email"]},
        {"contact_emails": ["operator@example.com", "operator@example.com"]},
        {"contact_emails": [{}]},
        {"contact_emails": [f"operator{i}@example.com" for i in range(6)]},
        {"import_existing": "true"},
        {"extra": "unexpected"},
    ],
)
def test_monthly_budget_rejects_invalid_configuration(config, tmp_path, changes):
    config["monthly_budget"] = monthly_budget() | changes
    path = tmp_path / "invalid-budget.json"
    write_json(path, config)
    with pytest.raises(DeploymentError, match="monthly_budget"):
        load_config(path)


@pytest.mark.parametrize("import_existing", [False, True])
def test_monthly_budget_configuration_is_passed_to_every_phase(launcher, tmp_path, import_existing):
    launcher.config["monthly_budget"] = monthly_budget() | {"import_existing": import_existing}
    path = tmp_path / "valid-budget.json"
    write_json(path, launcher.config)
    launcher.config = load_config(path)
    install_build_evidence(launcher)
    launcher.config["ingestion_start_at"] = "2026-10-15T00:00:00Z"
    for phase in ("prerequisites", "platform", "edge-bootstrap", "candidate", "pilot", "ingestion"):
        values = launcher.main_inputs(phase)
        assert values["monthly_budget"] == launcher.config["monthly_budget"]
        assert "dev_price_bootstrap_enabled" not in values


def test_budget_and_always_on_preserve_legacy_defaults_when_omitted(launcher):
    launcher.config.pop("monthly_budget", None)
    launcher.config.pop("app_always_on", None)
    install_build_evidence(launcher)
    assert "monthly_budget" not in launcher.main_inputs("prerequisites")
    values = launcher.main_inputs("platform")
    assert "monthly_budget" not in values
    assert all(app["always_on"] for app in values["apps"].values())


def test_per_app_always_on_preserves_reviewed_values_and_omitted_app_default(launcher):
    launcher.config["app_always_on"] = {"customer": False, "admin": False}
    install_build_evidence(launcher)
    launcher.config["ingestion_start_at"] = "2026-10-15T00:00:00Z"
    for phase in ("platform", "edge-bootstrap", "candidate", "pilot", "ingestion"):
        values = launcher.main_inputs(phase)
        assert {name: app["always_on"] for name, app in values["apps"].items()} == {
            "api": True, "customer": False, "admin": False,
        }


def test_saved_plan_is_isolated_and_requires_exact_approval(launcher):
    approval = launcher.plan("prerequisites")
    with pytest.raises(DeploymentError, match="approval token"):
        launcher.apply("prerequisites", "wrong")
    launcher.apply("prerequisites", approval)
    command = launcher.run.commands[-1]
    assert "-parallelism=1" in command
    assert not any(arg.startswith("-state=") for arg in command)
    backend = (launcher.directory / "terraform.backend.hcl").read_text()
    assert 'key = "' + launcher.config["backend"]["main_key"] + '"' in backend
    assert read_json(launcher.directory / "progress.json")["phase"] == "prerequisites"
    assert not (launcher.directory / "plan-review.json").exists()


@pytest.mark.parametrize("mutation", ["config", "plan", "inputs", "source", "evidence"])
def test_changed_approval_binding_requires_replan(launcher, monkeypatch, mutation):
    approval = launcher.plan("prerequisites")
    if mutation == "config":
        launcher.config["publisher_name"] = "changed"
    elif mutation == "plan":
        (launcher.directory / "prerequisites.tfplan").write_bytes(b"tampered")
    elif mutation == "inputs":
        path = launcher.directory / "prerequisites.tfvars.json"
        inputs = read_json(path)
        inputs["location"] = "unapproved"
        write_json(path, inputs)
    elif mutation == "source":
        monkeypatch.setattr(launcher, "source_fingerprint", lambda: "source-v2")
    else:
        write_json(launcher.directory / "model-backends.json", {"changed": True})
    with pytest.raises(DeploymentError, match="changed"):
        launcher.apply("prerequisites", approval)
    assert not any(command[2] == "apply" for command in launcher.run.commands)


def test_failed_apply_invalidates_approval_without_claiming_progress(launcher):
    approval = launcher.plan("prerequisites")
    launcher.run.fail_apply = True
    with pytest.raises(DeploymentError, match="apply failed"):
        launcher.apply("prerequisites", approval)
    assert not (launcher.directory / "plan-review.json").exists()
    assert not (launcher.directory / "progress.json").exists()
    with pytest.raises(DeploymentError, match="Cannot read"):
        launcher.apply("prerequisites", approval)


@pytest.mark.parametrize("actions", [["delete"], ["delete", "create"], ["create", "delete"]])
def test_deletes_and_replacements_never_receive_approval(launcher, actions):
    launcher.run.changes = [{"address": "some.resource", "change": {"actions": actions}}]
    with pytest.raises(DeploymentError, match="deletes/replaces"):
        launcher.plan("prerequisites")
    assert not (launcher.directory / "plan-review.json").exists()


def test_runtime_settings_fragment_cannot_be_updated_by_launcher(launcher):
    launcher.run.changes = [
        {
            "address": 'azapi_resource.gateway_settings["dev-unified"]',
            "change": {"actions": ["update"]},
        }
    ]
    with pytest.raises(DeploymentError, match="preserve runtime"):
        launcher.plan("prerequisites")


def test_backward_and_skipped_phases_are_rejected(launcher):
    write_json(
        launcher.directory / "progress.json",
        {
            "subscription_id": launcher.config["subscription_id"],
            "prefix": launcher.prefix,
            "phase": "platform",
        },
    )
    with pytest.raises(DeploymentError, match="backward"):
        launcher.plan("prerequisites")
    with pytest.raises(DeploymentError, match="preceding"):
        launcher.plan("pilot")
    launcher.check_progress("edge-bootstrap")
    launcher.check_progress("platform")


def test_no_existing_progress_cannot_adopt_resources(launcher):
    with pytest.raises(DeploymentError, match="Start with prerequisites"):
        launcher.plan("pilot")


def test_model_root_has_separate_state_and_original_pinned_subset(launcher, monkeypatch):
    write_json(
        launcher.directory / "progress.json",
        {
            "subscription_id": launcher.config["subscription_id"],
            "prefix": launcher.prefix,
            "phase": "prerequisites",
        },
    )
    monkeypatch.setattr(
        launcher,
        "outputs",
        lambda: {
            "identity_principal_ids": {"value": {"gateway": "gateway-object-id"}},
        },
    )
    approval = launcher.plan("models")
    inputs = read_json(launcher.directory / "models.tfvars.json")
    assert inputs["model_aliases"] == list(ALIASES[:2])
    launcher.apply("models", approval)
    assert not any(arg.startswith("-state=") for arg in launcher.run.commands[-1])
    backend = (launcher.directory / "models.backend.hcl").read_text()
    assert 'key = "' + launcher.config["backend"]["models_key"] + '"' in backend
    assert "-parallelism=1" in launcher.run.commands[-1]


def install_build_evidence(launcher):
    identifiers = {
        component: f"00000000-0000-0000-0000-{index:012d}"
        for index, component in enumerate(("api", "customer", "admin"), 10)
    }
    write_json(
        launcher.directory / "identity.json",
        {
            "tenant_id": launcher.config["tenant_id"],
            "bootstrap_object_id": launcher.config["bootstrap_object_id"],
            "audience": identifiers["api"],
            "scope": f"api://{identifiers['api']}/access_as_user",
            "deployment_prefix": launcher.prefix,
            "applications": {app: {"client_id": identifier} for app, identifier in identifiers.items()},
        },
    )
    registry = launcher.prefix.replace("-", "") + "acr.azurecr.io"
    write_json(
        launcher.directory / "images.json",
        {
            "build_fingerprint": launcher.build_fingerprint(),
            "images": {
                app: registry + "/aiflux-" + app + "@sha256:" + "a" * 64
                for app in ("api", "customer", "admin", "ingestion")
            },
        },
    )
    launcher.config["certificate_secret_id"] = (
        f"https://{launcher.prefix.replace('-', '')}kv.vault.azure.net/secrets/pilot-tls"
    )
    write_json(
        launcher.directory / "model-backends.json",
        {
            "subscription_id": launcher.config["subscription_id"],
            "blocked": [],
        },
    )


def test_candidate_and_pilot_keep_production_blocked_and_ingestion_separate(launcher):
    install_build_evidence(launcher)
    candidate = launcher.main_inputs("candidate")
    assert candidate["deployment_stage"] == "edge-candidate"
    assert candidate["dev_direct_portals_enabled"]
    assert candidate["dev_portals_operator_only"]
    assert candidate["dev_unified_max_completion_tokens"] == 4096
    assert "dev_catalog_accepted" not in candidate
    assert "ingestion_enabled" not in candidate
    pilot = launcher.main_inputs("pilot")
    assert pilot["dev_catalog_accepted"]
    assert "public_edge_live_gates_approved" not in pilot
    assert "ingestion_enabled" not in pilot


@pytest.mark.parametrize("phase", ["edge-bootstrap", "candidate", "pilot", "ingestion"])
def test_edge_phases_preserve_governance_nsg(launcher, phase):
    install_build_evidence(launcher)
    launcher.config["app_gateway_existing_nsg_name"] = "governance-nsg"
    launcher.config["ingestion_start_at"] = "2026-10-15T00:00:00Z"
    assert launcher.main_inputs(phase)["app_gateway_existing_nsg_name"] == "governance-nsg"


@pytest.mark.parametrize("phase", ["candidate", "pilot", "ingestion"])
def test_approved_safety_threshold_persists_through_phases(launcher, phase):
    install_build_evidence(launcher)
    launcher.config["ingestion_start_at"] = "2026-10-15T00:00:00Z"
    launcher.config.pop("dev_openai_content_safety_threshold", None)
    assert launcher.main_inputs(phase)["dev_openai_content_safety_threshold"] == 0
    launcher.config["dev_openai_content_safety_threshold"] = 1
    assert launcher.main_inputs(phase)["dev_openai_content_safety_threshold"] == 1


def test_legacy_config_does_not_require_existing_nsg(config, tmp_path):
    config.pop("app_gateway_existing_nsg_name", None)
    path = tmp_path / "legacy.json"
    write_json(path, config)
    assert "app_gateway_existing_nsg_name" not in load_config(path)


def test_direct_jwt_mode_is_explicit_and_preserves_sidecar_resource(launcher):
    assert launcher.main_inputs("prerequisites")["mise_direct_jwt_enabled"] is False
    launcher.config["mise_direct_jwt_enabled"] = True
    inputs = launcher.main_inputs("prerequisites")
    assert inputs["mise_direct_jwt_enabled"] is True
    assert inputs["mise_sidecar_enabled"] is True


@pytest.mark.parametrize(
    "approval",
    [
        "private_sql_initialized",
        "tls_and_renewal_reviewed",
        "model_terms_and_quota_reviewed",
    ],
)
def test_candidate_cannot_bypass_manual_checkpoints(launcher, approval):
    install_build_evidence(launcher)
    launcher.config["attestations"][approval] = False
    with pytest.raises(DeploymentError, match=approval):
        launcher.main_inputs("candidate")


def test_admin_opt_in_preserved_in_candidate(launcher):
    install_build_evidence(launcher)
    launcher.config["admin_settings_enabled"] = True
    assert launcher.main_inputs("candidate")["dev_admin_settings_enabled"] is True


def test_ingestion_requires_explicit_cutoff(launcher):
    install_build_evidence(launcher)
    with pytest.raises(DeploymentError, match="cutoff"):
        launcher.main_inputs("ingestion")
    launcher.config["ingestion_start_at"] = "2026-10-15T00:00:00Z"
    values = launcher.main_inputs("ingestion")
    assert values["ingestion_enabled"] and values["ingestion_timer_enabled"]


@pytest.mark.parametrize("profile", ["legacy", "australiaeast-luna"])
def test_catalog_is_customer_specific_and_does_not_publish_other_models(launcher, profile):
    launcher.config["deployment_profile"] = profile
    catalog = launcher.catalog()
    assert {item["id"] for item in catalog["models"]} == set(launcher.aliases)
    assert "aiflux-example-dev" not in json.dumps(catalog)
    assert len(catalog["models"][0]["backends"]) == (1 if launcher.australian else 2)
    if launcher.australian:
        assert catalog["models"][0]["backends"][0]["region"] == "australiaeast"
        assert "swedencentral" not in json.dumps(catalog)
        assert "eastus" not in json.dumps(catalog)


@pytest.mark.parametrize("profile", ["legacy", "australiaeast-luna"])
def test_catalog_backend_ids_match_physical_apim_backend_names(launcher, profile):
    launcher.config["deployment_profile"] = profile
    if launcher.australian:
        launcher.config["additional_model_aliases"] = ["DeepSeek-V4-Flash", "gpt-5.4-nano"]
    for model in launcher.catalog()["models"]:
        for backend in model["backends"]:
            expected = f"dev-{model['id']}-{backend['region']}".lower().replace(".", "-")
            assert backend["id"] == expected


@pytest.mark.parametrize(
    "alias,backend_id,provider,expected_cost",
    [
        ("gpt-5.4-nano", "dev-gpt-5-4-nano-australiaeast", "OpenAI", "0.00001010"),
        ("DeepSeek-V4-Flash", "dev-deepseek-v4-flash-australiaeast", "DeepSeek", "0.00000553"),
    ],
)
def test_generated_catalog_attributes_and_prices_native_usage(
    launcher, env, alias, backend_id, provider, expected_cost
):
    launcher.config.update(
        deployment_profile="australiaeast-luna",
        additional_model_aliases=["DeepSeek-V4-Flash", "gpt-5.4-nano"],
    )
    catalog = Catalog.model_validate(launcher.catalog())
    reviewed_price = next(item for item in launcher.prices() if item["model"] == alias)
    now = datetime.now(UTC)
    subscription = create_key(env)
    source = {
        "subscription_id": subscription["id"],
        "correlation_id": f"catalog-attribution-{alias}",
        "resource_id": env.settings.apim_resource_id,
        "occurred_at": now,
        "model": alias,
        "deployment": alias,
        "backend_id": backend_id,
        "gateway_region": "not-the-backend-region",
        "status_code": 200,
        "trace_records": [{
            "source": "aiflux",
            "metadata": {
                "category": "usage",
                "payload": json.dumps({
                    "schema": "finops-v1", "model": alias, "attempts": 1,
                    "input_tokens": 13, "output_tokens": 6,
                    "cached_input_tokens": 0, "cache_write_tokens": None,
                }),
            },
        }],
    }
    with Session(env.db_engine) as db:
        db.add(ModelPrice(
            model=alias, provider=provider, region="australiaeast", currency="USD",
            effective_from=now - timedelta(minutes=1),
            input_per_million=Decimal(str(reviewed_price["input_per_million"])),
            output_per_million=Decimal(str(reviewed_price["output_per_million"])),
            cached_input_per_million=Decimal(str(reviewed_price["cached_input_per_million"])),
            input_includes_cached=reviewed_price["input_includes_cached"],
        ))
        db.commit()
        ingest_rows(db, [source], catalog)
        db.commit()
        row = db.scalar(select(UsageRecord))
        assert (row.provider, row.region) == (provider, "australiaeast")
        assert row.completeness == "complete"
        assert row.currency == "USD" and row.cost == Decimal(expected_cost)
        source["backend_id"] = "unreviewed-backend"
        ingest_rows(db, [source], catalog)
        db.commit()
        assert row.cost is None and row.completeness == "backend_attribution_missing"


def test_runner_redacts_failure_output(monkeypatch):
    class Result:
        returncode = 1
        stdout = b"secret-key"
        stderr = b"token-secret"

    monkeypatch.setattr("shutil.which", lambda name: name)
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: Result())
    with pytest.raises(DeploymentError) as failure:
        Runner()(["az", "rest"])
    assert "secret" not in str(failure.value)


def test_australian_configuration_is_explicit_and_requires_local_sql(config, tmp_path):
    config.pop("deployment_profile", None)
    path = tmp_path / "config.json"
    write_json(path, config)
    assert load_config(path).get("deployment_profile", "legacy") == "legacy"
    config.update(deployment_profile="unreviewed")
    write_json(path, config)
    with pytest.raises(DeploymentError, match="deployment_profile"):
        load_config(path)
    config.update(deployment_profile="australiaeast-luna", sql_location="eastus")
    write_json(path, config)
    with pytest.raises(DeploymentError, match="requires SQL"):
        load_config(path)
    config["sql_location"] = "australiaeast"
    write_json(path, config)
    assert load_config(path)["deployment_profile"] == "australiaeast-luna"


def test_australian_profile_wires_location_dns_identity_and_separate_root(launcher, monkeypatch):
    launcher.config.update(deployment_profile="australiaeast-luna", sql_location="australiaeast")
    values = launcher.main_inputs("prerequisites")
    assert values["location"] == values["sql_location"] == "australiaeast"
    assert values["gateway_origin_hostname"] == launcher.config["dns_label"] + (
        ".australiaeast.cloudapp.azure.com"
    )
    assert values["deployment_profile"] == "australiaeast-luna"
    install_build_evidence(launcher)
    launcher.identities()
    assert launcher.hostname in launcher.run.commands[-1]
    monkeypatch.setattr(launcher, "check_progress", lambda phase: None)
    monkeypatch.setattr(launcher, "outputs", lambda: {"identity_principal_ids": {"value": {"gateway": "id"}}})
    approval = launcher.plan("models")
    inputs = read_json(launcher.directory / "models.tfvars.json")
    assert set(inputs) == {"subscription_id", "resource_group_name", "account_name", "gateway_principal_id"}
    assert inputs["account_name"] == launcher.prefix + "-foundry"
    assert read_json(launcher.directory / "plan-review.json")["root"] == "models-australiaeast"
    launcher.apply("models", approval)
    assert not any(arg.startswith("-state=") for arg in launcher.run.commands[-1])
    backend = (launcher.directory / "models-australiaeast.backend.hcl").read_text()
    assert 'key = "' + launcher.config["backend"]["models_key"] + '"' in backend


def australian_evidence(launcher):
    account = (
        f"/subscriptions/{launcher.config['subscription_id']}"
        f"/resourceGroups/{launcher.config['resource_group_name']}"
        f"/providers/Microsoft.CognitiveServices/accounts/{launcher.prefix}-foundry"
    )
    return {
        "subscription_id": launcher.config["subscription_id"],
        "blocked": [],
        "anthropic_backends": [],
        "backends": [
            {
                "alias": "gpt-5.6-luna",
                "region": "australiaeast",
                "account_resource_id": account,
                "deployment_resource_id": account + "/deployments/gpt-5.6-luna",
                "model_name": "gpt-5.6-luna",
                "model_version": "2026-07-09",
                "sku": "GlobalStandard",
                "capacity": 120,
                "endpoint": f"https://{launcher.prefix}-foundry.openai.azure.com",
                "ready": True,
                "auth": {"gateway_role_assigned": True},
                "operator_smoke": {"passed": True, "http_status": 200, "choices_schema_present": True},
            }
        ],
    }


@pytest.mark.parametrize(
    "change",
    [
        {"region": "eastus"},
        {"alias": "gpt-5.6-sol"},
        {"model_version": "wrong"},
        {"capacity": 119},
        {"sku": "DataZoneStandard"},
        {"ready": False},
        {"account_resource_id": "/other-account"},
        {"operator_smoke": {"passed": False}},
        {"auth": {"gateway_role_assigned": False}},
    ],
)
def test_australian_evidence_rejects_unreviewed_backends(launcher, change):
    evidence = australian_evidence(launcher)
    launcher.validate_australian_evidence(evidence)
    evidence["backends"][0].update(change)
    with pytest.raises(DeploymentError, match="evidence|exactly"):
        launcher.validate_australian_evidence(evidence)


@pytest.mark.parametrize("field", ["backends", "anthropic_backends", "blocked"])
def test_australian_evidence_rejects_extra_or_blocked_models(launcher, field):
    evidence = australian_evidence(launcher)
    evidence[field].append(evidence["backends"][0])
    with pytest.raises(DeploymentError, match="exactly the opted-in"):
        launcher.validate_australian_evidence(evidence)


def test_australian_verification_selects_only_luna_and_checks_evidence(launcher, monkeypatch):
    launcher.config["deployment_profile"] = "australiaeast-luna"
    monkeypatch.setattr(launcher, "outputs", lambda: {"identity_principal_ids": {"value": {"gateway": "id"}}})
    write_json(launcher.directory / "model-backends.json", australian_evidence(launcher))
    launcher.models_verify()
    command = launcher.run.commands[-1]
    assert "--australiaeast-account" in command
    assert "--eastus-account" not in command and "--sweden-account" not in command
    assert command.count("--model-alias") == 1
    assert command[-1] == "gpt-5.6-luna"


def test_profile_changes_invalidate_builds_and_plan_approvals(launcher):
    install_build_evidence(launcher)
    original = launcher.build_fingerprint()
    approval = launcher.plan("prerequisites")
    launcher.config.update(deployment_profile="australiaeast-luna", sql_location="australiaeast")
    assert launcher.build_fingerprint() != original
    with pytest.raises(DeploymentError, match="changed"):
        launcher.apply("prerequisites", approval)


@pytest.mark.parametrize("aliases", [[], ["gpt-5.4-nano"], ["DeepSeek-V4-Flash", "gpt-5.4-nano"]])
def test_australian_existing_models_are_explicit_and_provider_endpoints_are_preserved(launcher, aliases):
    launcher.config.update(deployment_profile="australiaeast-luna", additional_model_aliases=aliases)
    catalog = {model["id"]: model for model in launcher.catalog()["models"]}
    assert set(catalog) == {"gpt-5.6-luna", *aliases}
    for alias in aliases:
        model = catalog[alias]
        assert model["enabled"] and not model["placeholder"]
        assert model["capabilities"] == ["chat"]
        backend = model["backends"][0]
        assert len(model["backends"]) == 1 and backend["region"] == "australiaeast"
        assert backend["model"] == alias
        expected = (
            f"https://{launcher.prefix}-foundry.services.ai.azure.com/models"
            if alias.startswith("DeepSeek")
            else f"https://{launcher.prefix}-foundry.openai.azure.com/openai/v1"
        )
        assert backend["url"] == expected
    install_build_evidence(launcher)
    evidence = australian_evidence(launcher)
    specs = {
        model["id"]: model
        for model in read_json(ROOT / "infra" / "models" / "model-spec.json")["models"]
    }
    for alias in aliases:
        base = evidence["backends"][0]
        evidence["backends"].append({
            **base,
            "alias": alias,
            "model_name": alias,
            "deployment_resource_id": base["account_resource_id"] + "/deployments/" + alias,
            "model_version": specs[alias]["version"],
            "capacity": 250,
            "endpoint": (
                f"https://{launcher.prefix}-foundry.services.ai.azure.com/models"
                if alias.startswith("DeepSeek")
                else base["endpoint"]
            ),
        })
    write_json(launcher.directory / "model-backends.json", evidence)
    inputs = launcher.main_inputs("candidate")
    assert inputs["dev_unified_accepted_model_aliases"] == aliases
    launcher.config["additional_model_aliases"] = ["gpt-5.4-nano"] if not aliases else []
    with pytest.raises(DeploymentError, match="build"):
        launcher.main_inputs("candidate")


@pytest.mark.parametrize("aliases", [
    ["DeepSeek-V4-Flash-0731"], ["gpt-5.6-sol"], ["gpt-5.4-nano", "gpt-5.4-nano"], [1], [{}],
])
def test_australian_existing_models_reject_unreviewed_aliases(config, tmp_path, aliases):
    config.update(deployment_profile="australiaeast-luna", sql_location="australiaeast",
                  additional_model_aliases=aliases)
    path = tmp_path / "customer.json"
    write_json(path, config)
    with pytest.raises(DeploymentError, match="additional_model_aliases"):
        load_config(path)


def test_customer_prices_are_exact_catalog_scoped_and_do_not_invent_australian_luna_rates(launcher):
    assert len(launcher.prices()) == 5
    launcher.config["deployment_profile"] = "australiaeast-luna"
    assert launcher.prices() == []
    launcher.config["additional_model_aliases"] = ["DeepSeek-V4-Flash", "gpt-5.4-nano"]
    prices = {price["model"]: price for price in launcher.prices()}
    assert set(prices) == {"DeepSeek-V4-Flash", "gpt-5.4-nano"}
    assert all(p["region"] == "australiaeast" and p["currency"] == "USD" for p in prices.values())
    assert prices["gpt-5.4-nano"]["input_per_million"] == "0.20"
    assert prices["gpt-5.4-nano"]["output_per_million"] == "1.25"
    assert prices["DeepSeek-V4-Flash"]["cached_input_per_million"] == "0.028"


def test_azure_ad_commands_do_not_receive_subscription_but_arm_commands_do(launcher):
    launcher.az("ad", "signed-in-user", "show")
    assert "--subscription" not in launcher.run.commands[-1]
    launcher.az("group", "show", "--name", "test")
    assert "--subscription" in launcher.run.commands[-1]


def test_provider_registration_check_is_case_insensitive(launcher):
    from scripts.deployment.launcher import PROVIDERS

    def run(args, **kwargs):
        if args[:2] == ["terraform", "version"]:
            return {"terraform_version": "1.16.0"}
        if args[1:3] == ["account", "show"]:
            return {"tenantId": launcher.config["tenant_id"], "id": launcher.config["subscription_id"]}
        if args[1:4] == ["ad", "signed-in-user", "show"]:
            return {"id": launcher.config["bootstrap_object_id"]}
        if args[1:3] == ["provider", "list"]:
            return [{"namespace": name.lower(), "registrationState": "Registered"} for name in PROVIDERS]
        return {}

    launcher.run = run
    Launcher.preflight(launcher)


def test_customer_registration_refuses_unmarked_owned_application(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "bootstrap_entra", ROOT / "infra/scripts/bootstrap-entra.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls = []

    def az(*args):
        calls.append(args)
        if args[:3] == ("ad", "app", "list"):
            return [{"id": "existing", "notes": "unrelated application"}]
        return [{"id": "operator"}]

    monkeypatch.setattr(module, "az", az)
    with pytest.raises(RuntimeError, match="ownership marker"):
        module.registration("api", "customer-pilot", "operator", True)
    assert not any("PATCH" in command or "create" in command for command in calls)


def test_real_terraform_saved_plan_uses_isolated_local_state(tmp_path):
    terraform = shutil.which("terraform")
    if terraform is None:
        pytest.skip("Terraform executable is not installed in this test job")
    root = tmp_path / "root"
    root.mkdir()
    (root / "main.tf").write_text(
        'terraform {\n backend "local" {}\n}\n'
        'resource "terraform_data" "test" { input = "local-only" }\n'
        'output "value" { value = terraform_data.test.output }\n'
    )
    state = tmp_path / "isolated.tfstate"
    plan = tmp_path / "isolated.tfplan"
    commands = [
        ["init", "-input=false"],
        ["plan", "-input=false", f"-state={state}", f"-out={plan}"],
        ["apply", "-input=false", "-parallelism=1", f"-state={state}", str(plan)],
        ["output", f"-state={state}", "-json"],
    ]
    for command in commands:
        result = subprocess.run(
            [terraform, f"-chdir={root}", *command],
            capture_output=True,
            check=True,
        )
    assert json.loads(result.stdout)["value"]["value"] == "local-only"
    assert state.exists()
    assert not (root / "terraform.tfstate").exists()


@pytest.mark.parametrize(
    "phase", ["prerequisites", "platform", "edge-bootstrap", "candidate", "pilot", "ingestion"]
)
@pytest.mark.parametrize(
    "profile", [
        "legacy", "australiaeast-luna", "australiaeast-budget", "australiaeast-reconciled",
        "australiaeast-controls",
    ],
)
def test_rendered_customer_profile_passes_terraform_mock_plan(launcher, tmp_path, phase, profile):
    terraform = shutil.which("terraform")
    root = ROOT / "infra" / "terraform"
    if terraform is None or not (root / ".terraform" / "providers").exists():
        pytest.skip("Terraform and initialized main-root providers are required for mock planning")
    launcher.config["deployment_profile"] = (
        "australiaeast-luna" if profile in (
            "australiaeast-budget", "australiaeast-reconciled", "australiaeast-controls",
        ) else profile
    )
    if profile in ("australiaeast-budget", "australiaeast-reconciled"):
        launcher.config["additional_model_aliases"] = ["DeepSeek-V4-Flash", "gpt-5.4-nano"]
    if profile == "australiaeast-reconciled":
        launcher.config["app_always_on"] = {"api": True, "customer": False, "admin": False}
        launcher.config["monthly_budget"] = monthly_budget()
    if profile == "australiaeast-controls":
        launcher.config.update(
            admin_settings_provisioned=True, gateway_controls_v2_enabled=True,
            protected_material_available=True, monthly_request_quota_available=True,
            safety_relaxation_allowed=False, gateway_max_rpm=2,
        )
    if launcher.australian:
        launcher.config["sql_location"] = "australiaeast"
    install_build_evidence(launcher)
    launcher.config["ingestion_start_at"] = "2026-10-15T00:00:00Z"
    specification = read_json(ROOT / "infra" / "models" / "model-spec.json")
    backends = []
    for model in specification["models"]:
        if model["id"] not in (launcher.aliases if launcher.australian else launcher.aliases[:2]):
            continue
        for region in ("australiaeast",) if launcher.australian else ("eastus", "swedencentral"):
            account = launcher.prefix + "-foundry" + ("-swc" if region == "swedencentral" else "")
            resource_id = (
                f"/subscriptions/{launcher.config['subscription_id']}"
                f"/resourceGroups/{launcher.config['resource_group_name']}"
                f"/providers/Microsoft.CognitiveServices/accounts/{account}"
            )
            backends.append(
                {
                    "alias": model["id"],
                    "provider": model["arm_format"],
                    "region": region,
                    "account_name": account,
                    "account_resource_id": resource_id,
                    "deployment_resource_id": resource_id + "/deployments/" + model["id"],
                    "deployment_name": model["id"],
                    "model_name": model["id"],
                    "model_version": model["version"],
                    "endpoint": (
                        f"https://{account}.services.ai.azure.com/models"
                        if model["endpoint_source"] == "model_inference_endpoint"
                        else f"https://{account}.openai.azure.com"
                    ),
                    "endpoint_verified": True,
                    "api_version": model["api_version"],
                    "required_tpm": model["capacity"] * model["tpm_per_capacity_unit"],
                    "request_contract": {
                        "token_parameter": model["request_token_parameter"],
                        "max_completion_tokens": model["max_completion_tokens"],
                    },
                    "wire_api": model["wire_api"],
                    "operation": model["operation"],
                    "capacity": model["capacity"],
                    "sku": "GlobalStandard",
                    "provisioning_state": "Succeeded",
                    "ready": True,
                    "auth": {
                        "type": "Entra bearer token",
                        "audience": model["auth_audience"],
                        "gateway_role": model["gateway_role"],
                        "gateway_role_definition_id": model["gateway_role_definition_id"],
                        "gateway_role_assigned": True,
                    },
                    "operator_smoke": {
                        "http_status": 200,
                        "passed": True,
                        "choices_schema_present": True,
                    },
                }
            )
    write_json(
        launcher.directory / "model-backends.json",
        {"subscription_id": launcher.config["subscription_id"], "blocked": [], "backends": backends},
    )
    mocks = (root / "tests" / "disabled.tftest.hcl").read_text().split("\nrun ", 1)[0]
    mocks = mocks.replace("00000000-0000-0000-0000-000000000000", launcher.config["subscription_id"])
    arm_root = (
        f"/subscriptions/{launcher.config['subscription_id']}"
        f"/resourceGroups/{launcher.config['resource_group_name']}/providers"
    )
    mocks = mocks.replace(
        'mock_resource "azurerm_linux_web_app" {\n    defaults = {',
        'mock_resource "azurerm_linux_web_app" {\n    defaults = {'
        f'\n      id = "{arm_root}/Microsoft.Web/sites/mock"',
    )
    mocks = mocks.replace(
        'mock_provider "azapi" {}',
        """mock_provider "azapi" {
  override_during = plan
  mock_resource "azapi_resource" {
    defaults = {
      id = "MOCK_ARM_ROOT/Microsoft.CognitiveServices/accounts/mock"
      output = { properties = { endpoint = "https://mock.cognitiveservices.azure.com/" } }
    }
  }
  mock_data "azapi_resource" {
    defaults = {
      output = {
        properties = {
          provisioningState = "Succeeded"
          model = { name = "claude-haiku-5-5" }
        }
      }
    }
  }
}""",
    )
    mocks = mocks.replace("MOCK_ARM_ROOT", arm_root)
    inputs = tmp_path / "customer.tfvars.json"
    write_json(inputs, launcher.main_inputs(phase))
    with tempfile.TemporaryDirectory(dir=root / ".terraform", prefix="customer-tests-") as temporary:
        test_directory = Path(temporary)
        (test_directory / "customer.tftest.hcl").write_text(
            mocks
            + '\nrun "customer_rendered_profile" {\n  command = plan\n'
            + (
                """
  assert {
    condition = (local.dev_accepted_aliases == toset(["DeepSeek-V4-Flash", "gpt-5.4-nano"]) &&
      local.dev_policy_foundry_aliases == toset(["DeepSeek-V4-Flash"]) &&
      local.dev_policy_openai_pool_ids["gpt-5.4-nano"] == "dev-gpt-5-4-nano-australiaeast" &&
      local.dev_policy_openai_pool_ids["DeepSeek-V4-Flash"] == "dev-deepseek-v4-flash-australiaeast")
    error_message = "Both external models must route individually with DeepSeek's Foundry wire contract."
  }
"""
                if profile in ("australiaeast-budget", "australiaeast-reconciled")
                and phase in ("candidate", "pilot", "ingestion")
                else ""
            )
            + (
                """
  assert {
    condition = (azurerm_consumption_budget_resource_group.main["main"].amount == 1000 &&
      local.monthly_budgets["main"].import_existing == false)
    error_message = "The reviewed budget must be wired through every launcher phase."
  }
"""
                if profile == "australiaeast-reconciled"
                else ""
            )
            + (
                """
  assert {
    condition = (azurerm_linux_web_app.main["api"].site_config[0].always_on &&
      !azurerm_linux_web_app.main["customer"].site_config[0].always_on &&
      !azurerm_linux_web_app.main["admin"].site_config[0].always_on &&
      azurerm_linux_function_app.ingestion[0].site_config[0].always_on)
    error_message = "Launcher hosting overrides must preserve the exact per-app desired state."
  }
"""
                if profile == "australiaeast-reconciled" and phase != "prerequisites"
                else ""
            )
            + (
                """
  assert {
    condition = alltrue([for app in values(azurerm_linux_web_app.main) :
      app.site_config[0].ip_restriction_default_action == "Deny"])
    error_message = "Customer phases must not silently open direct App Service origins."
  }
"""
                if phase != "prerequisites"
                else ""
            )
            + (
                """
  assert {
    condition = (length(data.azapi_resource.dev_haiku) == 0 &&
      length(azapi_resource.dev_anthropic_backend) == 0)
    error_message = "Australia East must not require or route Haiku."
  }
  assert {
    condition = (local.dev_aliases == toset(["gpt-5.6-luna"]) &&
      local.dev_base_regions == tolist(["australiaeast"]))
    error_message = "Only the Australian Luna backend is permitted."
  }
"""
                if launcher.australian
                else ""
            )
            + (
                """
  assert {
    condition = (!strcontains(azapi_resource.dev_unified_policy[0].body.properties.value, "gpt-5.6-sol") &&
      !strcontains(azapi_resource.dev_unified_policy[0].body.properties.value, "claude-haiku-5-5") &&
      strcontains(azapi_resource.dev_unified_policy[0].body.properties.value, "gpt-5.6-luna"))
    error_message = "The unified policy must preserve Luna and exclude legacy aliases."
  }
  assert {
    condition = (local.dev_policy_openai_pool_ids["gpt-5.6-luna"] == "dev-gpt-5-6-luna-australiaeast" &&
      length(azapi_resource.dev_model_pool) == 0)
    error_message = "The single Australian backend must not route through a regional failover pool."
  }
"""
                if launcher.australian and phase in ("candidate", "pilot", "ingestion")
                else ""
            )
            + "}\n"
        )
        result = subprocess.run(
            [
                terraform,
                f"-chdir={root}",
                "test",
                "-no-color",
                f"-test-directory={test_directory.relative_to(root)}",
                f"-var-file={inputs}",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("address", ["8.8.8.8", "127.0.0.1", "169.254.1.1", "10.241.3.4"])
def test_sql_initialization_rejects_wrong_network_before_connecting(monkeypatch, address):
    from scripts.deployment.sql_init import initialize

    monkeypatch.setattr("socket.getaddrinfo", lambda *args: [(None, None, None, None, (address, 1433))])
    with pytest.raises(DeploymentError, match="private endpoint subnet"):
        initialize(
            {
                "settings": {
                    "AIFLUX_DATABASE_URL": (
                        "mssql+pyodbc://@customer.database.windows.net/database"
                        "?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes&TrustServerCertificate=no"
                    )
                },
                "private_endpoint_subnet": "10.240.3.0/24",
            }
        )


def test_build_wires_customer_identity_origins_and_four_digests(launcher, monkeypatch):
    install_build_evidence(launcher)
    registry = {
        "name": "aifluxpilotacr",
        "login_server": "aifluxpilotacr.azurecr.io",
    }
    monkeypatch.setattr(launcher, "outputs", lambda: {"container_registry": {"value": registry}})
    az_calls = []

    def run(args, *, json_output=True):
        if args[0] == "git":
            if "--others" in args:
                return b""
            return (
                b"gateway/catalog/dev-models.json\0"
                b"services/control-plane/Dockerfile\0apps/customer-portal/Dockerfile\0"
            )
        az_calls.append(args)
        if args[1:3] == ["acr", "build"]:
            context = Path(args[args.index("--subscription") - 1])
            catalog = read_json(context / "gateway" / "catalog" / "dev-models.json")
            assert {item["id"] for item in catalog["models"]} == set(ALIASES)
            assert not (context / ".deployment").exists()
            assert not (context / "infra").exists()
            return {}
        return {"digest": "sha256:" + "b" * 64}

    launcher.run = run
    launcher.build()
    builds = [call for call in az_calls if call[1:3] == ["acr", "build"]]
    assert len(builds) == 4
    for component in ("customer", "admin"):
        build = next(call for call in builds if f"aiflux-{component}:" in " ".join(call))
        identifier = launcher.identity()["applications"][component]["client_id"]
        assert f"VITE_ENTRA_CLIENT_ID={identifier}" in build
        assert "VITE_CONTROL_API_URL=https://aiflux-pilot-api.azurewebsites.net/api" in build
        assert "VITE_GATEWAY_URL=https://aiflux-pilot-apim.azure-api.net/dev/llm/v1" in build
    images = read_json(launcher.directory / "images.json")["images"]
    assert set(images) == {"api", "customer", "admin", "ingestion"}
    assert all("@sha256:" in image for image in images.values())


def test_bootstrap_uses_customer_organization_name(env, monkeypatch):
    from aiflux.bootstrap import main
    from aiflux.config import Settings
    from aiflux.models import Organization
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    settings = Settings(
        database_url="sqlite://",
        entra_audience="test-audience",
        home_tenant_id="00000000-0000-0000-0000-000000000123",
        bootstrap_object_id="00000000-0000-0000-0000-000000000124",
        home_organization_name="Customer pilot",
    )
    monkeypatch.setattr("aiflux.bootstrap.get_settings", lambda: settings)
    monkeypatch.setattr("aiflux.bootstrap.engine_for", lambda url: env.db_engine)
    main()
    main()
    with Session(env.db_engine) as db:
        organizations = db.scalars(
            select(Organization).where(Organization.tenant_id == settings.home_tenant_id)
        ).all()
        assert len(organizations) == 1 and organizations[0].name == "Customer pilot"


def test_migrations_use_supplied_operator_connection_without_default_credential(monkeypatch):
    from aiflux.config import Settings
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    settings = Settings(database_url="sqlite://")
    monkeypatch.setattr("aiflux.config.get_settings", lambda: settings)

    def refuse_default_engine(url):
        pytest.fail("Migration attempted to use the default runtime credential")

    monkeypatch.setattr("aiflux.db.engine_for", refuse_default_engine)
    engine = create_engine("sqlite://")
    migration = Config(str(ROOT / "services" / "control-plane" / "alembic.ini"))
    with engine.begin() as connection:
        migration.attributes["connection"] = connection
        command.upgrade(migration, "head")
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0003"
        command.upgrade(migration, "head")
    engine.dispose()


def test_sql_engine_uses_explicit_operator_token_without_connecting():
    import struct
    from types import SimpleNamespace

    from aiflux.db import engine_for

    calls = []

    class OperatorCredential:
        def get_token(self, scope, **kwargs):
            calls.append(scope)
            return SimpleNamespace(token="synthetic-operator-token")

    engine = engine_for(
        "mssql+pyodbc://@customer.database.windows.net/database?driver=ODBC+Driver+18+for+SQL+Server",
        OperatorCredential(),
    )
    arguments = ["SERVER=customer.database.windows.net;Trusted_Connection=Yes"]
    parameters = {}
    for callback in engine.dialect.dispatch.do_connect:
        callback(engine.dialect, None, arguments, parameters)
    assert calls == ["https://database.windows.net/.default"]
    assert "Trusted_Connection" not in arguments[0]
    token = parameters["attrs_before"][1256]
    assert struct.unpack("<I", token[:4])[0] == len(token[4:])
    assert token[4:].decode("utf-16-le") == "synthetic-operator-token"
    engine.dispose()
