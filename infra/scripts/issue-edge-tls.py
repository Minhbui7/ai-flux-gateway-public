"""Run staging, then production HTTP-01 from the private API container."""

import argparse
import json
import subprocess
import time
from pathlib import Path

import requests


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
    args = parser.parse_args()
    root = Path(args.evidence_directory)
    root.mkdir(parents=True, exist_ok=True)

    def az(*arguments: str) -> object:
        result = subprocess.run(
            ["az.cmd", *arguments, "--subscription", args.subscription, "--only-show-errors", "-o", "json"],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(result.stdout) if result.stdout.strip() else None

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
    snapshot_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    startup_changed = False
    script_uploaded = False
    marker = f"aiflux-tls-{args.environment}.json"
    script_name = f"aiflux-tls-{args.environment}.py"

    def set_startup(command: str) -> None:
        response = session.patch(web, json={"properties": {"appCommandLine": command}}, timeout=90)
        response.raise_for_status()
        subprocess.run(
            [
                "az.cmd", "webapp", "restart", "-g", args.resource_group, "-n", args.api_app,
                "--subscription", args.subscription, "--only-show-errors",
            ],
            check=True,
            capture_output=True,
        )

    try:
        if args.environment == "production":
            role = az(
                "role", "assignment", "create",
                "--assignee-object-id", args.api_principal,
                "--assignee-principal-type", "ServicePrincipal",
                "--role", "Key Vault Secrets Officer",
                "--scope", secret_scope,
            )
            snapshot["temporary_role_ids"].append(role["id"])
            snapshot_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")

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
        response = session.put(
            scm + "/api/vfs/" + script_name,
            data=script.encode("utf-8"),
            headers={"If-Match": "*", "Content-Type": "application/octet-stream"},
            timeout=60,
        )
        response.raise_for_status()
        script_uploaded = True
        response = session.delete(scm + "/api/vfs/" + marker, headers={"If-Match": "*"}, timeout=30)
        if response.status_code not in (200, 204, 404):
            response.raise_for_status()

        # Only staging makes no vault changes; restore normal startup before
        # installing HTTPS. Production uploads only the approved TLS secret.
        startup_changed = True
        set_startup("/usr/local/bin/python /home/" + script_name)
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            response = session.get(scm + "/api/vfs/" + marker, timeout=45)
            if response.ok:
                result = response.json()
                (root / (args.environment + "-certificate.json")).write_text(
                    json.dumps(result, indent=2), encoding="utf-8",
                )
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
        snapshot["restored"] = not restoration_errors
        snapshot["restoration_errors"] = restoration_errors
        snapshot_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
        if restoration_errors:
            raise RuntimeError("Restoration incomplete; inspect protected local evidence")


if __name__ == "__main__":
    main()
