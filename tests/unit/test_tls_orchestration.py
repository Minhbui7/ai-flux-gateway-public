import importlib.util
import sys
from unittest.mock import Mock

import pytest

from scripts.deployment.launcher import ROOT, read_json


@pytest.fixture
def helper():
    spec = importlib.util.spec_from_file_location(
        "issue_edge_tls", ROOT / "infra" / "scripts" / "issue-edge-tls.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("environment", ["staging", "production"])
@pytest.mark.parametrize("failed", [False, True])
def test_tls_orchestration_restores_startup_and_journals_roles(
    helper, monkeypatch, tmp_path, environment, failed,
):
    principal = "11111111-1111-4111-8111-111111111111"
    calls = []
    marker_reads = 0
    current_startup = ""
    granted = []
    journal = tmp_path / (environment + "-restoration.json")

    def runner(args, *, json_output=True):
        calls.append(args)
        if args[1:3] == ["account", "get-access-token"]:
            return {"accessToken": "not-a-real-token"}
        if args[1:4] == ["webapp", "identity", "show"]:
            return {"userAssignedIdentities": {"identity": {"principalId": principal}}}
        if args[1:4] == ["role", "assignment", "create"]:
            snapshot = read_json(journal)
            assert snapshot["temporary_role_ids"], "Role must be journaled before Azure mutation"
            granted.extend(snapshot["temporary_role_ids"])
            assert args[args.index("--scope") + 1].endswith("/secrets/aiflux-dev-tls")
            return {"id": granted[0]}
        if args[1:4] == ["role", "assignment", "delete"]:
            assert not json_output
            granted.remove(args[args.index("--ids") + 1])
        if args[1:3] == ["webapp", "restart"]:
            assert not json_output
        if args[1:4] == ["role", "assignment", "list"]:
            return [{"id": role} for role in granted]
        return {}

    def response(data=None):
        return Mock(ok=True, status_code=200, json=lambda: data)

    def get(url, **_):
        nonlocal marker_reads
        if "/config/web?" in url:
            return response({"properties": {"appCommandLine": current_startup}})
        marker_reads += 1
        if marker_reads == 1:
            raise helper.requests.Timeout("SCM restart in progress")
        return response({"status": "failed" if failed else (
            "validated" if environment == "staging" else "issued"
        )})

    def patch(_url, *, json, **_):
        nonlocal current_startup
        current_startup = json["properties"]["appCommandLine"]
        return response()

    session = Mock(headers={}, get=get, patch=patch, put=Mock(return_value=response()),
                   delete=Mock(return_value=response()))
    monkeypatch.setattr(helper, "Runner", lambda: runner)
    monkeypatch.setattr(helper.requests, "Session", lambda: session)
    monkeypatch.setattr(helper.time, "sleep", lambda _: None)
    argv = [
        "issue-edge-tls", "--subscription", "subscription", "--resource-group", "group",
        "--api-app", "api", "--api-principal", principal, "--vault-name", "vault",
        "--hostname", "gateway.example.com", "--email", "ops@example.com",
        "--environment", environment, "--evidence-directory", str(tmp_path),
        "--approve-secret-scoped-temporary-writer", "--agree-terms",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    if failed:
        with pytest.raises(RuntimeError, match="Certificate operation failed"):
            helper.main()
    else:
        helper.main()
    assert current_startup == ""
    assert not granted
    snapshot = read_json(journal)
    assert snapshot["restored"] is True
    assert snapshot["run_id"] in snapshot["script_name"]
    if environment == "production":
        assert len(snapshot["temporary_role_ids"]) == 1
    else:
        assert not snapshot["temporary_role_ids"]


def test_tls_orchestration_refuses_missing_terms(helper, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["issue-edge-tls"])
    with pytest.raises(SystemExit):
        helper.main()
