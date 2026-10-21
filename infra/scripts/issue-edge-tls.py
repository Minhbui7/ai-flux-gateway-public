"""Run staging, then production HTTP-01 from the private API container."""

import argparse
import json
import sys
import time
from pathlib import Path
from uuid import uuid4

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.deployment.launcher import Runner, read_json, write_json  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--subscription", required=True)
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--api-app", required=True)
    parser.add_argument("--api-principal", required=True)
    parser.add_argument("--vault-name", required=True)
    parser.add_argument("--hostname", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--environment", choices=("staging", "production"), required=True)
    parser.add_argument("--evidence-directory", required=True)
    parser.add_argument("--approve-secret-scoped-temporary-writer", action="store_true", required=True)
    parser.add_argument("--agree-terms", action="store_true", required=True)
    args = parser.parse_args()
    root = Path(args.evidence_directory)
    root.mkdir(parents=True, exist_ok=True)

    def az(*arguments: str) -> object:
        return Runner()(
            ["az", *arguments, "--subscription", args.subscription, "--only-show-errors", "-o", "json"],
            json_output=arguments[:2] != ("webapp", "restart")
            and arguments[:3] != ("role", "assignment", "delete"),
        )

    token = az("account", "get-access-token", "--resource", "https://management.azure.com/")["accessToken"]
    session = requests.Session()
    session.headers["Authorization"] = "Bearer " + token
    provider_path = (
        f"/subscriptions/{args.subscription}/resourceGroups/{args.resource_group}/providers"
    )
    app_id = f"{provider_path}/Microsoft.Web/sites/{args.api_app}"
    web = f"https://management.azure.com{app_id}/config/web?api-version=2024-04-01"
    vault = f"{provider_path}/Microsoft.KeyVault/vaults/{args.vault_name}"
    secret_scope = vault + "/secrets/aiflux-dev-tls"
    scm = f"https://{args.api_app}.scm.azurewebsites.net"

    identity = az("webapp", "identity", "show", "-g", args.resource_group, "-n", args.api_app)
    if not any(
        item["principalId"].lower() == args.api_principal.lower()
        for item in identity["userAssignedIdentities"].values()
    ):
        raise RuntimeError("The approved API principal is not attached to this app; no changes made")
    inherited = az("role", "assignment", "list", "--scope", vault, "--include-inherited")
    for assignment in inherited:
        scope = assignment["scope"].lower()
        if assignment["principalId"].lower() == args.api_principal.lower() and (
            scope == vault.lower() or scope.startswith(vault.lower() + "/")
        ):
            raise RuntimeError("Existing vault or secret access requires separate review; no changes made")

    config_response = session.get(web, timeout=60)
    config_response.raise_for_status()
    startup = config_response.json()["properties"]["appCommandLine"]
    snapshot = {
        "startup": startup,
        "temporary_role_ids": [],
        "api_principal": args.api_principal,
        "secret_scope": secret_scope,
    }
    snapshot_path = root / (args.environment + "-restoration.json")
    if snapshot_path.exists() and not read_json(snapshot_path).get("restored"):
        raise RuntimeError("Recover the previous incomplete TLS operation before retrying")
    run_id = str(uuid4())
    snapshot["run_id"] = run_id
    snapshot["app_id"] = app_id
    write_json(snapshot_path, snapshot)
    startup_changed = False
    script_uploaded = False
    marker = f"aiflux-tls-{args.environment}-{run_id}.json"
    script_name = f"aiflux-tls-{args.environment}-{run_id}.py"
    snapshot["script_name"] = script_name
    snapshot["marker"] = marker
    write_json(snapshot_path, snapshot)

    def set_startup(command: str) -> None:
        response = session.patch(web, json={"properties": {"appCommandLine": command}}, timeout=90)
        response.raise_for_status()
        az("webapp", "restart", "-g", args.resource_group, "-n", args.api_app)

    try:
        if args.environment == "production":
            role_name = str(uuid4())
            snapshot["temporary_role_ids"].append(
                secret_scope + "/providers/Microsoft.Authorization/roleAssignments/" + role_name
            )
            write_json(snapshot_path, snapshot)
            az(
                "role", "assignment", "create",
                "--name", role_name,
                "--assignee-object-id", args.api_principal,
                "--assignee-principal-type", "ServicePrincipal",
                "--role", "Key Vault Secrets Officer",
                "--scope", secret_scope,
            )

        command_args = [
            "--environment", args.environment,
            "--hostname", args.hostname,
            "--email", args.email,
            "--vault", f"https://{args.vault_name}.vault.azure.net",
            "--marker", "/home/" + marker,
            "--agree-terms",
        ]
        script = (
            "import sys,threading,time\n"
            "from aiflux.tls import main\n"
            f"sys.argv=['aiflux-tls']+{command_args!r}\n"
            "def issue():\n"
            " time.sleep(30)\n"
            " main()\n"
            "threading.Thread(target=issue,daemon=True).start()\n"
            "from uvicorn import run\n"
            "run('aiflux.app:app',host='0.0.0.0',port=8000,access_log=False)\n"
        )
        script_uploaded = True
        response = session.put(
            scm + "/api/vfs/" + script_name,
            data=script.encode("utf-8"),
            headers={"If-Match": "*", "Content-Type": "application/octet-stream"},
            timeout=180,
        )
        response.raise_for_status()
        response = session.delete(scm + "/api/vfs/" + marker, headers={"If-Match": "*"}, timeout=30)
        if response.status_code not in (200, 204, 404):
            response.raise_for_status()

        # Only staging makes no vault changes; restore normal startup before
        # installing HTTPS. Production uploads only the approved TLS secret.
        startup_changed = True
        set_startup("/usr/local/bin/python /home/" + script_name)
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            try:
                response = session.get(scm + "/api/vfs/" + marker, timeout=45)
            except (requests.ConnectionError, requests.Timeout) as exc:
                print("Waiting for restarted SCM: " + type(exc).__name__, flush=True)
                time.sleep(15)
                continue
            if response.ok:
                result = response.json()
                result["run_id"] = run_id
                write_json(root / (args.environment + "-certificate.json"), result)
                print(json.dumps(result), flush=True)
                expected_status = "validated" if args.environment == "staging" else "issued"
                if result.get("status") != expected_status:
                    raise RuntimeError("Certificate operation failed: " + str(result.get("error_type")))
                break
            if response.status_code not in (404, 502, 503):
                response.raise_for_status()
            time.sleep(15)
        else:
            raise RuntimeError("Certificate operation timed out")

    finally:
        restoration_errors = []
        if script_uploaded:
            try:
                response = session.delete(
                    scm + "/api/vfs/" + script_name,
                    headers={"If-Match": "*"},
                    timeout=30,
                )
                if response.status_code not in (200, 204, 404):
                    response.raise_for_status()
            except Exception as exc:
                restoration_errors.append("script:" + type(exc).__name__)
        if startup_changed:
            try:
                set_startup(startup)
            except Exception as exc:
                restoration_errors.append("startup:" + type(exc).__name__)
        for role_id in reversed(snapshot["temporary_role_ids"]):
            try:
                az("role", "assignment", "delete", "--ids", role_id)
            except Exception as exc:
                restoration_errors.append("role:" + type(exc).__name__)
        try:
            response = session.get(web, timeout=60)
            response.raise_for_status()
            if response.json()["properties"]["appCommandLine"] != startup:
                raise RuntimeError("Startup restoration readback mismatch")
            remaining_roles = az("role", "assignment", "list", "--scope", secret_scope)
            if any(role["id"] in snapshot["temporary_role_ids"] for role in remaining_roles):
                raise RuntimeError("Temporary certificate role remains assigned")
        except Exception as exc:
            restoration_errors.append("verification:" + type(exc).__name__)
        snapshot["restored"] = not restoration_errors
        snapshot["restoration_errors"] = restoration_errors
        write_json(snapshot_path, snapshot)
        if restoration_errors:
            raise RuntimeError("Restoration incomplete; inspect protected local evidence")


if __name__ == "__main__":
    main()
