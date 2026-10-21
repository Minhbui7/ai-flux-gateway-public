import json
from unittest.mock import MagicMock

import pytest

from scripts.deployment.launcher import DeploymentError, Launcher, Runner, read_json
from scripts.deployment.sql_init import credential_for, migration_lock, private_route
from scripts.deployment.sql_runner import (
    PrivateSqlRunner,
    check_execution,
    restore_target,
    validate_result,
)


def test_managed_credential_is_explicit_and_separate(monkeypatch):
    factory = MagicMock()
    monkeypatch.setattr("scripts.deployment.sql_init.ManagedIdentityCredential", factory)
    document = {
        "credential_mode": "managed-identity",
        "runner_client_id": "10000000-0000-0000-0000-000000000001",
        "API_CLIENT_ID": "10000000-0000-0000-0000-000000000002",
        "INGESTION_CLIENT_ID": "10000000-0000-0000-0000-000000000003",
    }
    credential_for(document)
    factory.assert_called_once_with(client_id=document["runner_client_id"])
    document["runner_client_id"] = document["API_CLIENT_ID"]
    with pytest.raises(DeploymentError, match="separate"):
        credential_for(document)


def test_operator_credential_remains_default(monkeypatch):
    factory = MagicMock()
    monkeypatch.setattr("scripts.deployment.sql_init.AzureCliCredential", factory)
    credential_for({"settings": {"AIFLUX_HOME_TENANT_ID": "tenant"}, "subscription_id": "subscription"})
    factory.assert_called_once_with(tenant_id="tenant", subscription="subscription")
    with pytest.raises(DeploymentError, match="Unsupported"):
        credential_for({"credential_mode": "default"})


@pytest.mark.parametrize("suffix", ["&TrustServerCertificate=yes", "&Encrypt=no"])
def test_route_rejects_disabled_tls_before_resolution(suffix):
    url = "mssql+pyodbc://@server.database.windows.net/aiflux?driver=ODBC+Driver+18+for+SQL+Server"
    with pytest.raises(DeploymentError, match="encrypted"):
        private_route({"settings": {"AIFLUX_DATABASE_URL": url + suffix}})


def test_route_rejects_mixed_public_private_dns(monkeypatch):
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *args: [(0, 0, 0, 0, (ip, 1433)) for ip in ("10.240.3.4", "8.8.8.8")],
    )
    with pytest.raises(DeploymentError, match="private endpoint"):
        private_route(
            {
                "settings": {
                    "AIFLUX_DATABASE_URL": (
                        "mssql+pyodbc://@server.database.windows.net/aiflux?Encrypt=yes&TrustServerCertificate=no"
                    )
                },
                "private_endpoint_subnet": "10.240.3.0/24",
            }
        )


def test_migration_lock_rejects_contention_and_releases_on_failure():
    connection = MagicMock()
    connection.exec_driver_sql.return_value.scalar.return_value = -1
    with pytest.raises(DeploymentError, match="migration lock"):
        with migration_lock(connection):
            pytest.fail("entered contended lock")
    connection.reset_mock()
    connection.exec_driver_sql.return_value.scalar.return_value = 0
    with pytest.raises(RuntimeError):
        with migration_lock(connection):
            assert any(
                call.args[0] == "SET NOCOUNT OFF" for call in connection.exec_driver_sql.call_args_list
            )
            raise RuntimeError("migration failed")
    assert "sp_releaseapplock" in connection.exec_driver_sql.call_args.args[0]


@pytest.mark.parametrize("state", ["Failed", "TimedOut", "Canceled"])
def test_run_command_failure_is_not_success(state):
    with pytest.raises(DeploymentError, match="failed"):
        check_execution({"instanceView": {"executionState": state, "exitCode": 0}})


def test_run_command_requires_execution_not_provisioning_success():
    assert check_execution({"provisioningState": "Succeeded"}) is None
    with pytest.raises(DeploymentError, match="exit code"):
        check_execution({"instanceView": {"executionState": "Succeeded", "exitCode": 3}})
    assert (
        check_execution({"instanceView": {"executionState": "Succeeded", "exitCode": 0, "output": "done"}})
        == "done"
    )


@pytest.mark.parametrize(
    "output",
    [
        "",
        "AIFLUX_SQL_RESULT={}",
        'AIFLUX_SQL_RESULT={"status":"initialized","run_id":"other","revision":"0002"}',
    ],
)
def test_result_rejects_missing_wrong_run_or_revision(output):
    with pytest.raises(DeploymentError):
        validate_result(output, "this-run")


def test_result_accepts_bound_revision():
    result = {"status": "initialized", "run_id": "this-run", "revision": "0002"}
    assert validate_result("noise\nAIFLUX_SQL_RESULT=" + json.dumps(result), "this-run") == result


def test_restore_only_overwrites_expected_runner():
    original = {"sid": "operator", "login": "admin", "tenantId": "tenant"}
    assert not restore_target(original, original, "runner")
    assert restore_target({**original, "sid": "runner"}, original, "runner")
    with pytest.raises(DeploymentError, match="third-party"):
        restore_target({**original, "sid": "other"}, original, "runner")
    with pytest.raises(DeploymentError, match="metadata"):
        restore_target({**original, "login": "other"}, original, "runner")


def test_administrator_restored_even_when_migration_fails(tmp_path, monkeypatch):
    config = {
        "name_prefix": "pilot",
        "subscription_id": "subscription",
        "resource_group_name": "group",
        "sql_admin_object_id": "operator",
        "sql_admin_login": "admin",
        "tenant_id": "tenant",
    }
    launcher = Launcher(config, tmp_path)
    runner = PrivateSqlRunner(
        launcher,
        {
            "vm_id": "/subscriptions/subscription/resourceGroups/group/providers/"
            "Microsoft.Compute/virtualMachines/pilot-sql-init",
            "client_id": "client",
            "principal_id": "runner",
        },
        "pilotacr.azurecr.io/aiflux-sql-init@sha256:" + "a" * 64,
    )
    monkeypatch.setattr(
        runner, "administrator", lambda: {"sid": "operator", "login": "admin", "tenantId": "tenant"}
    )
    monkeypatch.setattr(runner, "prepare", lambda document: None)
    monkeypatch.setattr(runner, "set_administrator", lambda admin: None)
    restore = MagicMock()
    monkeypatch.setattr(runner, "restore", restore)
    monkeypatch.setattr(runner, "command", MagicMock(side_effect=DeploymentError("migration failed")))
    with pytest.raises(DeploymentError, match="migration failed"):
        runner.execute({})
    restore.assert_called_once()
    assert read_json(runner.journal)["stage"] == "elevated"
    with pytest.raises(DeploymentError, match="recovery"):
        runner.execute({})


def test_launcher_looks_up_actual_identity_names(tmp_path, monkeypatch):
    config = {
        "name_prefix": "pilot",
        "resource_group_name": "group",
        "subscription_id": "subscription",
        "network_profile": "10.240",
    }
    launcher = Launcher(config, tmp_path, MagicMock())
    monkeypatch.setattr(launcher, "preflight", lambda: None)
    monkeypatch.setattr(launcher, "approved", lambda name: None)
    monkeypatch.setattr(
        launcher,
        "outputs",
        lambda: {
            "control_plane_settings": {"value": {"configured": "yes"}},
            "identity_principal_ids": {"value": {"api": "api-object", "ingestion": "ingestion-object"}},
        },
    )
    names = []

    def az(*args):
        name = args[-1]
        names.append(name)
        component = "api" if name == "pilot-api-identity" else "ingestion"
        return {"principalId": component + "-object", "clientId": component + "-client"}

    monkeypatch.setattr(launcher, "az", az)
    launcher.sql_init()
    assert names == ["pilot-api-identity", "pilot-ingestion-identity"]


def test_windows_cli_python_preserves_url_metacharacters(tmp_path, monkeypatch):
    import os

    if os.name != "nt":
        pytest.skip("Windows Azure CLI launcher regression")
    cli = tmp_path / "CLI2"
    (cli / "wbin").mkdir(parents=True)
    (cli / "python.exe").touch()
    monkeypatch.setattr("shutil.which", lambda name: str(cli / "wbin" / "az.cmd"))
    run = MagicMock(return_value=MagicMock(returncode=0, stdout=b"{}"))
    monkeypatch.setattr("subprocess.run", run)
    url = "https://management.azure.com/resource?api-version=2024-11-01&$expand=instanceView"
    Runner()(["az", "rest", "--url", url])
    assert run.call_args.args[0] == [str(cli / "python.exe"), "-IBm", "azure.cli", "rest", "--url", url]
