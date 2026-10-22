"""Execute an approved private SQL runner with persistent administrator recovery evidence."""

from __future__ import annotations

import argparse
import base64
import json
import re
import shlex
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .launcher import (
    DeploymentError,
    Launcher,
    environment_lock,
    load_config,
    read_json,
    require,
    write_json,
)


def check_execution(properties: dict[str, Any]) -> str | None:
    view = properties.get("instanceView", {})
    state = view.get("executionState")
    require(
        state not in ("Failed", "TimedOut", "Canceled") and properties.get("provisioningState") != "Failed",
        "Private Run Command failed; inspect the protected execution evidence.",
    )
    if state == "Succeeded":
        require(view.get("exitCode") == 0, "Private Run Command returned a nonzero exit code.")
        return str(view.get("output", ""))
    return None


def validate_result(output: str, run_id: str) -> dict[str, Any]:
    results = [
        line.removeprefix("AIFLUX_SQL_RESULT=")
        for line in output.splitlines()
        if line.startswith("AIFLUX_SQL_RESULT=")
    ]
    require(len(results) == 1, "SQL execution did not return exactly one initialization result.")
    result = json.loads(results[0])
    require(
        result.get("status") == "initialized"
        and result.get("run_id") == run_id
        and isinstance(result.get("revision"), str)
        and bool(result["revision"]),
        "SQL initialization result is not bound to this run.",
    )
    return result


def restore_target(current: dict[str, Any], original: dict[str, Any], runner_principal: str) -> bool:
    if current["sid"].lower() == original["sid"].lower():
        require(
            current["tenantId"].lower() == original["tenantId"].lower()
            and current["login"] == original["login"],
            "Original SQL administrator metadata changed; manual recovery required.",
        )
        return False
    require(
        current["sid"].lower() == runner_principal.lower()
        and current["tenantId"].lower() == original["tenantId"].lower(),
        "Unexpected SQL administrator change; refusing to overwrite a third-party administrator.",
    )
    return True


class PrivateSqlRunner:
    def __init__(self, launcher: Launcher, runner: dict[str, str], image: str) -> None:
        self.launcher = launcher
        self.directory = launcher.directory
        self.runner = runner
        self.image = image
        self.journal = self.directory / "sql-runner-journal.json"
        registry = launcher.prefix.replace("-", "") + "acr.azurecr.io"
        require(
            bool(re.fullmatch(re.escape(registry) + r"/aiflux-sql-init@sha256:[0-9a-f]{64}", image)),
            "Use this deployment's digest-pinned SQL initialization image.",
        )
        expected_vm = (
            f"/subscriptions/{launcher.config['subscription_id']}"
            f"/resourceGroups/{launcher.config['resource_group_name']}"
            f"/providers/Microsoft.Compute/virtualMachines/{launcher.prefix}-sql-init"
        )
        require(runner["vm_id"].lower() == expected_vm.lower(), "Runner VM belongs to another deployment.")

    def administrator(self) -> dict[str, Any]:
        admins = self.launcher.az(
            "sql",
            "server",
            "ad-admin",
            "list",
            "--resource-group",
            self.launcher.config["resource_group_name"],
            "--server",
            self.launcher.prefix + "-sql",
        )
        require(len(admins) == 1, "Expected exactly one SQL Entra administrator.")
        return dict(admins[0])

    def set_administrator(self, admin: dict[str, Any]) -> None:
        self.launcher.az(
            "sql",
            "server",
            "ad-admin",
            "update",
            "--resource-group",
            self.launcher.config["resource_group_name"],
            "--server",
            self.launcher.prefix + "-sql",
            "--object-id",
            admin["sid"],
            "--display-name",
            admin["login"],
        )

    def command(self, name: str, script: str, timeout: int = 900) -> str:
        require(bool(re.fullmatch(r"[a-z0-9-]+", name)), "Invalid Run Command name.")
        body = self.directory / (name + ".request.json")
        write_json(
            body,
            {
                "location": self.launcher.location,
                "properties": {
                    "source": {"script": script},
                    "timeoutInSeconds": timeout,
                    "asyncExecution": False,
                    "treatFailureAsDeploymentFailure": True,
                },
            },
        )
        url = (
            "https://management.azure.com"
            + self.runner["vm_id"]
            + f"/runCommands/{name}?api-version=2024-11-01"
        )
        self.launcher.az("rest", "--method", "put", "--url", url, "--body", "@" + str(body))
        deadline = time.monotonic() + timeout + 180
        while time.monotonic() < deadline:
            result = self.launcher.az(
                "rest",
                "--method",
                "get",
                "--url",
                url + "&$expand=instanceView",
            )
            write_json(self.directory / (name + ".result.json"), result)
            output = check_execution(result.get("properties", {}))
            if output is not None:
                return output
            time.sleep(10)
        raise DeploymentError("Private Run Command monitoring timed out; recovery is required.")

    def container(self, arguments: list[str], *, name: str = "aiflux-sql-init") -> str:
        return shlex.join(
            [
                "docker",
                "--config",
                "/run/aiflux-docker",
                "run",
                "--rm",
                "--network",
                "host",
                "--name",
                name,
                "--volume",
                "/run/aiflux-inputs.json:/run/inputs.json:ro",
                *arguments,
            ]
        )

    def prepare(self, document: dict[str, Any]) -> None:
        registry = self.image.split("/")[0]
        encoded = base64.b64encode(json.dumps(document).encode()).decode()
        login_script = f"""
import json,subprocess,urllib.request,urllib.parse
def request(url, data=None, headers=None):
    req=urllib.request.Request(url,data=data,headers=headers or {{}})
    with urllib.request.urlopen(req,timeout=60) as r:
        return json.load(r)
token=request('http://169.254.169.254/metadata/identity/oauth2/token?'+urllib.parse.urlencode({{
    'api-version':'2018-02-01','resource':'https://management.azure.com/',
    'client_id':{self.runner["client_id"]!r}}}),headers={{'Metadata':'true'}})['access_token']
refresh=request('https://{registry}/oauth2/exchange',urllib.parse.urlencode({{
    'grant_type':'access_token','service':{registry!r},
    'tenant':{self.launcher.config["tenant_id"]!r},'access_token':token}}).encode(),
    {{'Content-Type':'application/x-www-form-urlencoded'}})['refresh_token']
subprocess.run(['docker','--config','/run/aiflux-docker','login',{registry!r},
    '--username','00000000-0000-0000-0000-000000000000','--password-stdin'],
    input=refresh.encode(),check=True,stdout=subprocess.DEVNULL)
"""
        route = (
            "import json,socket; from scripts.deployment.sql_init import private_route; "
            "d=json.load(open('/run/inputs.json')); private_route(d); "
            "from sqlalchemy.engine import make_url; "
            "s=socket.create_connection((make_url(d['settings']['AIFLUX_DATABASE_URL']).host,1433),15); "
            "s.close(); print('PRIVATE_ROUTE_READY')"
        )
        script = (
            "#!/bin/bash\nset -euo pipefail\nexport DEBIAN_FRONTEND=noninteractive\n"
            "apt-get update -qq\napt-get install -y -qq docker.io python3\nsystemctl start docker\n"
            "install -d -m 700 /run/aiflux-docker\n"
            f"printf %s {shlex.quote(encoded)} | base64 -d > /run/aiflux-inputs.json\n"
            "chmod 644 /run/aiflux-inputs.json\npython3 - <<'PY'\n"
            + login_script
            + "\nPY\n"
            + shlex.join(["docker", "--config", "/run/aiflux-docker", "pull", self.image])
            + "\n"
            + self.container(["--entrypoint", "python", self.image, "-c", route])
            + "\n"
        )
        output = self.command("sql-init-prepare", script, 1800)
        require("PRIVATE_ROUTE_READY" in output, "Private route preflight did not complete.")

    def restore(self, journal: dict[str, Any]) -> None:
        if restore_target(self.administrator(), journal["original"], self.runner["principal_id"]):
            self.set_administrator(journal["original"])
        require(
            not restore_target(self.administrator(), journal["original"], self.runner["principal_id"]),
            "Original SQL administrator restoration is unverified.",
        )
        journal["stage"] = "administrator-restored"
        journal["restored_at"] = datetime.now(UTC).isoformat()
        write_json(self.journal, journal)

    def stop_and_verify_revocation(self) -> None:
        probe = """
import json,time
import pyodbc
from scripts.deployment.sql_init import credential_for,private_route
from aiflux.db import engine_for
from sqlalchemy.exc import DBAPIError
d=json.load(open('/run/inputs.json')); private_route(d)
c=credential_for(d); engine=engine_for(d['settings']['AIFLUX_DATABASE_URL'],c)
try:
    for attempt in range(12):
        engine.dispose()
        try:
            with engine.connect() as connection:
                connection.exec_driver_sql('SELECT 1')
        except DBAPIError as error:
            if '18456' in str(error.orig) and '28000' in str(error.orig):
                print('RUNNER_SQL_LOGIN_REVOKED')
                break
            raise
        time.sleep(15)
    else:
        raise RuntimeError('Runner SQL login still succeeds after administrator restoration')
finally:
    engine.dispose(); c.close()
"""
        script = (
            "#!/bin/bash\nset -euo pipefail\n"
            "if docker container inspect aiflux-sql-init >/dev/null 2>&1; then "
            "docker rm -f aiflux-sql-init; fi\n"
            + self.container(
                ["--entrypoint", "python", self.image, "-c", probe], name="aiflux-sql-revocation"
            )
            + "\n"
            "rm -f /run/aiflux-docker/config.json /run/aiflux-inputs.json\n"
        )
        output = self.command("sql-init-revocation", script, 300)
        require("RUNNER_SQL_LOGIN_REVOKED" in output, "Runner SQL revocation was not verified.")

    def execute(self, document: dict[str, Any]) -> None:
        require(not self.journal.exists(), "Existing SQL journal requires recovery before another run.")
        original = self.administrator()
        config = self.launcher.config
        require(
            original["sid"].lower() == config["sql_admin_object_id"]
            and original["login"] == config["sql_admin_login"]
            and original["tenantId"].lower() == config["tenant_id"],
            "SQL administrator does not match the approved operator.",
        )
        document.update(
            credential_mode="managed-identity",
            runner_client_id=self.runner["client_id"],
            run_id=str(uuid4()),
        )
        self.prepare(document)
        journal = {
            "original": original,
            "runner": self.runner,
            "image": self.image,
            "subscription_id": config["subscription_id"],
            "prefix": self.launcher.prefix,
            "run_id": document["run_id"],
            "stage": "elevation-pending",
            "started_at": datetime.now(UTC).isoformat(),
        }
        write_json(self.journal, journal)
        try:
            self.set_administrator(
                {
                    "sid": self.runner["principal_id"],
                    "login": self.launcher.prefix + "-sql-init-identity",
                }
            )
            journal["stage"] = "elevated"
            write_json(self.journal, journal)
            # Connection/token propagation retries happen before executing DDL, never after it.
            preflight = """
import json,time
from scripts.deployment.sql_init import credential_for
from aiflux.db import engine_for
from sqlalchemy.exc import DBAPIError
d=json.load(open('/run/inputs.json')); c=credential_for(d)
engine=engine_for(d['settings']['AIFLUX_DATABASE_URL'],c)
try:
    for attempt in range(12):
        try:
            with engine.connect() as connection:
                assert connection.exec_driver_sql(
                    "SELECT HAS_PERMS_BY_NAME(DB_NAME(),'DATABASE','CONTROL')").scalar()==1
            break
        except DBAPIError as error:
            if '18456' not in str(error.orig) or attempt==11: raise
            time.sleep(10)
finally:
    engine.dispose(); c.close()
"""
            script = (
                "#!/bin/bash\nset -euo pipefail\n"
                + self.container(["--entrypoint", "python", self.image, "-c", preflight])
                + "\n"
                + self.container([self.image, "--inputs", "/run/inputs.json"])
                + "\n"
            )
            output = self.command("sql-init-migrate", script, 900)
            journal["result"] = validate_result(output, document["run_id"])
            write_json(self.journal, journal)
        finally:
            self.restore(journal)
        self.stop_and_verify_revocation()
        journal["stage"] = "revocation-verified"
        write_json(self.journal, journal)

    def recover(self) -> None:
        journal = read_json(self.journal)
        require(
            journal["runner"] == self.runner
            and journal["image"] == self.image
            and journal["subscription_id"] == self.launcher.config["subscription_id"]
            and journal["prefix"] == self.launcher.prefix,
            "Recovery evidence belongs to a different runner or deployment.",
        )
        self.restore(journal)
        self.stop_and_verify_revocation()
        journal["stage"] = "revocation-verified"
        write_json(self.journal, journal)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--environment", type=Path, required=True)
    parser.add_argument("--runner-output", type=Path, required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--recover", action="store_true")
    args = parser.parse_args()
    launcher = Launcher(load_config(args.config), args.environment)
    with environment_lock(launcher.directory):
        launcher.preflight()
        runner = PrivateSqlRunner(launcher, read_json(args.runner_output)["runner"]["value"], args.image)
        if args.recover:
            runner.recover()
        else:
            outputs = launcher.outputs()
            clients = {}
            for component in ("api", "ingestion"):
                identity = launcher.az(
                    "identity",
                    "show",
                    "--resource-group",
                    launcher.config["resource_group_name"],
                    "--name",
                    launcher.prefix + "-" + component + "-identity",
                )
                require(
                    identity["principalId"] == outputs["identity_principal_ids"]["value"][component],
                    "Runtime identity does not match Terraform evidence.",
                )
                clients[component.upper() + "_CLIENT_ID"] = identity["clientId"]
            runner.execute(
                {
                    "settings": outputs["control_plane_settings"]["value"],
                    "subscription_id": launcher.config["subscription_id"],
                    "private_endpoint_subnet": launcher.config["network_profile"] + ".3.0/24",
                    **clients,
                }
            )
    print("SQL initialization/recovery completed; original administrator restored and runner revoked.")


if __name__ == "__main__":
    try:
        main()
    except (DeploymentError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error)) from error
