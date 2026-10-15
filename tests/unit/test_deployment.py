import importlib.util
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

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
    value["attestations"] = dict.fromkeys(ATTESTATIONS, True)
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
        {"certificate_secret_id": "https://other.vault.azure.net/secrets/cert"},
        {"certificate_secret_id": "https://aifluxpilotkv.vault.azure.net/secrets/cert/version"},
        {"client_secret": "do-not-allow"},
        {"attestations": {}},
        {"dns_label": "https://injection.invalid"},
        {"name_prefix": "../../other"},
        {"ingestion_start_at": "2026-10-15T00:00:00"},
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


def test_saved_plan_is_isolated_and_requires_exact_approval(launcher):
    approval = launcher.plan("prerequisites")
    with pytest.raises(DeploymentError, match="approval token"):
        launcher.apply("prerequisites", "wrong")
    launcher.apply("prerequisites", approval)
    command = launcher.run.commands[-1]
    assert "-parallelism=1" in command
    assert f"-state={launcher.main_state}" in command
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
    assert f"-state={launcher.models_state}" in launcher.run.commands[-1]
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
    assert candidate["dev_unified_max_completion_tokens"] == 4096
    assert "dev_catalog_accepted" not in candidate
    assert "ingestion_enabled" not in candidate
    pilot = launcher.main_inputs("pilot")
    assert pilot["dev_catalog_accepted"]
    assert "public_edge_live_gates_approved" not in pilot
    assert "ingestion_enabled" not in pilot


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


def test_catalog_is_customer_specific_and_does_not_publish_other_models(launcher):
    catalog = launcher.catalog()
    assert {item["id"] for item in catalog["models"]} == set(ALIASES)
    assert "aiflux-fdpo-dev" not in json.dumps(catalog)
    assert len(catalog["models"][0]["backends"]) == 2


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
def test_rendered_customer_profile_passes_terraform_mock_plan(launcher, tmp_path, phase):
    terraform = shutil.which("terraform")
    root = ROOT / "infra" / "terraform"
    if terraform is None or not (root / ".terraform" / "providers").exists():
        pytest.skip("Terraform and initialized main-root providers are required for mock planning")
    install_build_evidence(launcher)
    launcher.config["ingestion_start_at"] = "2026-10-15T00:00:00Z"
    specification = read_json(ROOT / "infra" / "models" / "model-spec.json")
    backends = []
    for model in specification["models"]:
        if model["id"] not in ALIASES[:2]:
            continue
        for region in ("eastus", "swedencentral"):
            account = launcher.prefix + "-foundry" + ("-swc" if region == "swedencentral" else "")
            resource_id = (
                f"/subscriptions/{launcher.config['subscription_id']}"
                f"/resourceGroups/{launcher.config['resource_group_name']}"
                f"/providers/Microsoft.CognitiveServices/accounts/{account}"
            )
            backends.append(
                {
                    "alias": model["id"],
                    "provider": "OpenAI",
                    "region": region,
                    "account_name": account,
                    "account_resource_id": resource_id,
                    "deployment_resource_id": resource_id + "/deployments/" + model["id"],
                    "deployment_name": model["id"],
                    "model_name": model["id"],
                    "model_version": model["version"],
                    "endpoint": f"https://{account}.openai.azure.com",
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
    mocks = (root / "tests" / "disabled.tftest.hcl").read_text().split("\nvariables {", 1)[0]
    mocks = mocks.replace("4d75ed7f-75ab-4db6-b1f3-263f240d1450", launcher.config["subscription_id"])
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
            mocks + '\nrun "customer_rendered_profile" {\n  command = plan\n}\n'
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
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0002"
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
