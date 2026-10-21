"""A gated, resumable customer pilot launcher. No credentials are persisted here."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
PHASES = ("prerequisites", "models", "platform", "edge-bootstrap", "candidate", "pilot", "ingestion")
ALIASES = ("gpt-5.6-luna", "gpt-5.6-sol", "claude-haiku-5-5")
BUDGET_ALIASES = ("DeepSeek-V4-Flash", "gpt-5.4-nano")
ATTESTATIONS = {
    "cost_network_and_permissions_reviewed",
    "model_terms_and_quota_reviewed",
    "private_sql_initialized",
    "tls_and_renewal_reviewed",
    "guarded_smoke_and_signed_in_accepted",
    "ingestion_ownership_and_telemetry_accepted",
}
FIELDS = {
    "tenant_id",
    "subscription_id",
    "resource_group_name",
    "name_prefix",
    "publisher_name",
    "publisher_email",
    "bootstrap_object_id",
    "sql_admin_login",
    "sql_admin_object_id",
    "sql_location",
    "network_profile",
    "operator_ip",
    "dns_label",
    "certificate_secret_id",
    "admin_settings_enabled",
    "ingestion_start_at",
    "attestations",
}
PROVIDERS = (
    "Microsoft.ApiManagement",
    "Microsoft.CognitiveServices",
    "Microsoft.Network",
    "Microsoft.Web",
    "Microsoft.Sql",
    "Microsoft.Storage",
    "Microsoft.KeyVault",
    "Microsoft.ContainerRegistry",
    "Microsoft.Insights",
    "Microsoft.OperationalInsights",
    "Microsoft.ManagedIdentity",
)
BUILD_ROOTS = {
    "apps",
    "services",
    "packages",
    "gateway",
    "package.json",
    "package-lock.json",
    "pyproject.toml",
    "tsconfig.base.json",
    ".dockerignore",
}


class DeploymentError(RuntimeError):
    """An actionable, nonsecret deployment failure."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise DeploymentError(message)


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise DeploymentError(f"Cannot read valid JSON: {path.name}") from error


def write_json(path: Path, data: Any) -> None:
    pending = path.with_suffix(path.suffix + ".pending")
    pending.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    pending.replace(path)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_config(path: Path) -> dict[str, Any]:
    config = read_json(path)
    require(
        isinstance(config, dict)
        and set(config)
        - {
            "deployment_profile",
            "app_gateway_existing_nsg_name",
            "mise_direct_jwt_enabled",
            "dev_openai_content_safety_threshold",
            "additional_model_aliases",
            "app_always_on",
            "monthly_budget",
            "admin_settings_provisioned",
            "gateway_controls_v2_enabled",
            "protected_material_available",
            "monthly_request_quota_available",
            "safety_relaxation_allowed",
            "gateway_max_rpm",
        }
        == FIELDS,
        "Use exactly the example configuration fields.",
    )
    require(
        config.get("deployment_profile", "legacy") in ("legacy", "australiaeast-luna"),
        "deployment_profile must be legacy or australiaeast-luna.",
    )
    existing_nsg = config.get("app_gateway_existing_nsg_name", "")
    for field in (
        "admin_settings_provisioned", "gateway_controls_v2_enabled", "protected_material_available",
        "monthly_request_quota_available", "safety_relaxation_allowed",
    ):
        require(type(config.get(field, False)) is bool, f"{field} must be Boolean.")
    require(
        type(config.get("gateway_max_rpm", 2)) is int and 1 <= config.get("gateway_max_rpm", 2) <= 100000,
        "gateway_max_rpm must be an operator-approved integer from 1 through 100000.",
    )
    require(
        not config.get("gateway_controls_v2_enabled", False)
        or config.get("admin_settings_provisioned", False) or config.get("admin_settings_enabled", False),
        "Versioned gateway controls require provisioned admin settings fragments.",
    )
    additional = config.get("additional_model_aliases", [])
    require(
        isinstance(additional, list)
        and all(isinstance(alias, str) and alias in BUDGET_ALIASES for alias in additional)
        and len(additional) == len(set(additional))
        and (not additional or config.get("deployment_profile") == "australiaeast-luna"),
        "additional_model_aliases must contain unique approved existing budget aliases for Australia East.",
    )
    threshold = config.get("dev_openai_content_safety_threshold", 0)
    require(
        type(threshold) is int and 0 <= threshold <= 7,
        "dev_openai_content_safety_threshold must be an explicitly approved integer from 0 through 7.",
    )
    require(
        type(config.get("mise_direct_jwt_enabled", False)) is bool,
        "mise_direct_jwt_enabled must be Boolean.",
    )
    always_on = config.get("app_always_on", {})
    require(
        isinstance(always_on, dict)
        and set(always_on) <= {"api", "customer", "admin"}
        and all(type(value) is bool for value in always_on.values()),
        "app_always_on must map api/customer/admin to Boolean values; omitted apps default to true.",
    )
    budget = config.get("monthly_budget")
    if budget is not None:
        require(
            isinstance(budget, dict)
            and set(budget) == {
                "name", "amount", "start_date", "end_date", "contact_emails", "import_existing",
            },
            "monthly_budget requires exactly name, amount, start_date, end_date, "
            "contact_emails and import_existing.",
        )
        require(
            isinstance(budget["name"], str)
            and bool(re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,62}", budget["name"]))
            and type(budget["amount"]) in (int, float)
            and math.isfinite(budget["amount"])
            and budget["amount"] > 0
            and type(budget["import_existing"]) is bool,
            "monthly_budget requires a valid name, positive finite amount and Boolean import_existing.",
        )
        dates = []
        for key in ("start_date", "end_date"):
            value = budget[key]
            require(
                isinstance(value, str)
                and bool(re.fullmatch(r"\d{4}-\d{2}-01T00:00:00Z", value)),
                f"monthly_budget.{key} must be first-of-month UTC, YYYY-MM-01T00:00:00Z.",
            )
            try:
                dates.append(datetime.fromisoformat(value.replace("Z", "+00:00")))
            except ValueError as error:
                raise DeploymentError(f"monthly_budget.{key} must be a valid date.") from error
        require(dates[1] > dates[0], "monthly_budget.end_date must follow start_date.")
        emails = budget["contact_emails"]
        require(
            isinstance(emails, list)
            and 1 <= len(emails) <= 5
            and all(
                isinstance(email, str) and bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email))
                for email in emails
            )
            and len(set(emails)) == len(emails),
            "monthly_budget.contact_emails must contain 1-5 unique email addresses.",
        )
    require(
        isinstance(existing_nsg, str)
        and (
            existing_nsg == ""
            or bool(re.fullmatch(r"[A-Za-z0-9_](?:[A-Za-z0-9_.-]{0,78}[A-Za-z0-9_])?", existing_nsg))
        ),
        "app_gateway_existing_nsg_name must be an existing NSG name in this resource group, or empty.",
    )
    for key in FIELDS - {"admin_settings_enabled", "attestations"}:
        require(isinstance(config[key], str), f"{key} must be a string.")
    for key in ("tenant_id", "subscription_id", "bootstrap_object_id", "sql_admin_object_id"):
        try:
            identifier = UUID(config[key])
        except ValueError as error:
            raise DeploymentError(f"{key} must be a UUID.") from error
        require(
            identifier.int != 0 and str(identifier) == config[key], f"Replace {key} with a lowercase UUID."
        )
    require(bool(re.fullmatch(r"[a-z][a-z0-9-]{2,18}", config["name_prefix"])), "Invalid name_prefix.")
    require(bool(re.fullmatch(r"[A-Za-z0-9_.()-]{1,90}", config["resource_group_name"])), "Invalid RG name.")
    require(
        config["sql_location"] in ("eastus", "australiaeast"), "SQL region must be eastus or australiaeast."
    )
    require(
        config.get("deployment_profile") != "australiaeast-luna" or config["sql_location"] == "australiaeast",
        "The Australia East profile requires SQL in australiaeast.",
    )
    require(config["network_profile"] in ("10.240", "10.241"), "Network profile must be 10.240 or 10.241.")
    require(
        bool(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", config["dns_label"])), "Invalid DNS label."
    )
    try:
        address = ipaddress.ip_address(config["operator_ip"])
    except ValueError as error:
        raise DeploymentError("operator_ip must be an exact reviewed public IPv4, without CIDR.") from error
    require(
        address.version == 4 and address.is_global and not address.is_multicast and not address.is_reserved,
        "operator_ip must be a globally routable IPv4.",
    )
    require(type(config["admin_settings_enabled"]) is bool, "admin_settings_enabled must be Boolean.")
    attestations = config["attestations"]
    require(
        isinstance(attestations, dict)
        and set(attestations) == ATTESTATIONS
        and all(type(value) is bool for value in attestations.values()),
        "Supply all named Boolean attestations; these are customer approvals, not automated evidence.",
    )
    require(
        bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", config["publisher_email"])),
        "publisher_email must be a contact address.",
    )
    require(
        all(config[key].strip() and len(config[key]) <= 100 for key in ("publisher_name", "sql_admin_login")),
        "Provide publisher_name and sql_admin_login.",
    )
    certificate = config["certificate_secret_id"]
    vault = config["name_prefix"].replace("-", "") + "kv"
    require(
        not certificate
        or bool(
            re.fullmatch(rf"https://{re.escape(vault)}\.vault\.azure\.net/secrets/[A-Za-z0-9-]+", certificate)
        ),
        "Certificate must be a versionless secret URI in this deployment's private vault.",
    )
    if config["ingestion_start_at"]:
        try:
            start = datetime.fromisoformat(config["ingestion_start_at"].replace("Z", "+00:00"))
        except ValueError as error:
            raise DeploymentError("ingestion_start_at must be RFC3339.") from error
        require(start.tzinfo is not None, "ingestion_start_at must include a timezone.")
    return config


class Runner:
    def __call__(self, args: list[str], *, json_output: bool = True) -> Any:
        executable = shutil.which(args[0])
        if executable is None:
            raise DeploymentError(f"Missing tool: {args[0]}. See docs/deployment.md.")
        # Do not print command output on failure: CLI/Graph/Terraform may include secrets.
        command = [executable, *args[1:]]
        if os.name == "nt" and args[0] == "az" and Path(executable).suffix.lower() == ".cmd":
            cli_python = Path(executable).parent.parent / "python.exe"
            require(
                cli_python.is_file(), "Cannot locate Azure CLI Python; repair the Azure CLI installation."
            )
            command = [str(cli_python), "-IBm", "azure.cli", *args[1:]]
        result = subprocess.run(command, capture_output=True, check=False)
        require(
            result.returncode == 0,
            f"{args[0]} {args[1]} failed (exit {result.returncode}); "
            "inspect securely with the equivalent runbook command, then retry.",
        )
        if not json_output:
            return result.stdout
        try:
            return json.loads(result.stdout)
        except ValueError as error:
            raise DeploymentError(f"{args[0]} returned invalid JSON.") from error


@contextmanager
def environment_lock(directory: Path) -> Iterator[None]:
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / "deployment.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise DeploymentError(
            "Environment is locked. Check its owning process before manual lock recovery."
        ) from error
    try:
        with os.fdopen(descriptor, "w", encoding="ascii") as handle:
            handle.write(str(os.getpid()))
        yield
    finally:
        lock.unlink()


class Launcher:
    def __init__(self, config: dict[str, Any], directory: Path, runner: Any = None) -> None:
        self.config = config
        self.directory = directory.resolve()
        self.run = runner or Runner()
        self.main_state = self.directory / "main.tfstate"
        self.models_state = self.directory / "models.tfstate"

    @property
    def prefix(self) -> str:
        return self.config["name_prefix"]

    @property
    def australian(self) -> bool:
        return self.config.get("deployment_profile", "legacy") == "australiaeast-luna"

    @property
    def location(self) -> str:
        return "australiaeast" if self.australian else "eastus"

    @property
    def aliases(self) -> tuple[str, ...]:
        return (
            ALIASES[:1] + tuple(self.config.get("additional_model_aliases", []))
            if self.australian
            else ALIASES
        )

    @property
    def model_root(self) -> str:
        return "models-australiaeast" if self.australian else "models"

    @property
    def hostname(self) -> str:
        return self.config["dns_label"] + f".{self.location}.cloudapp.azure.com"

    def az(self, *args: str) -> Any:
        # `az ad` commands are tenant-scoped and reject --subscription.
        scope = [] if args and args[0] == "ad" else ["--subscription", self.config["subscription_id"]]
        return self.run(
            [
                "az",
                *args,
                *scope,
                "--only-show-errors",
                "--output",
                "json",
            ]
        )

    def tf(self, root: str, *args: str, json_output: bool = False) -> Any:
        # TF_DATA_DIR isolates providers/backend metadata between customers and roots.
        old = os.environ.get("TF_DATA_DIR")
        os.environ["TF_DATA_DIR"] = str(self.directory / (root + "-data"))
        try:
            return self.run(["terraform", f"-chdir={ROOT / 'infra' / root}", *args], json_output=json_output)
        finally:
            if old is None:
                os.environ.pop("TF_DATA_DIR", None)
            else:
                os.environ["TF_DATA_DIR"] = old

    def approved(self, name: str) -> None:
        require(self.config["attestations"][name], f"Manual checkpoint: {name}. See docs/deployment.md.")

    def identity(self) -> dict[str, Any]:
        identity = read_json(self.directory / "identity.json")
        require(
            isinstance(identity, dict)
            and {"tenant_id", "bootstrap_object_id", "audience", "scope", "applications", "deployment_prefix"}
            <= identity.keys(),
            "Identity evidence incomplete; rerun the customer Entra helper or correct its approved handoff.",
        )
        require(
            identity["tenant_id"] == self.config["tenant_id"]
            and identity["bootstrap_object_id"] == self.config["bootstrap_object_id"]
            and identity["deployment_prefix"] == self.prefix,
            "Identity evidence does not match this deployment.",
        )
        require(
            isinstance(identity["applications"], dict)
            and set(identity["applications"]) == {"api", "customer", "admin"},
            "Provide all three dedicated application identifiers.",
        )
        try:
            for application in identity["applications"].values():
                require(isinstance(application, dict), "Invalid application evidence.")
                require(
                    isinstance(application.get("client_id"), str), "Application client IDs must be UUIDs."
                )
                client_id = UUID(application["client_id"])
                require(
                    client_id.int != 0 and str(client_id) == application["client_id"],
                    "Application client IDs must be UUIDs.",
                )
        except ValueError as error:
            raise DeploymentError("Application client IDs must be UUIDs.") from error
        require(
            identity["audience"] == identity["applications"]["api"]["client_id"]
            and identity["scope"] == f"api://{identity['audience']}/access_as_user"
            and len({app["client_id"] for app in identity["applications"].values()}) == 3,
            "API audience and delegated scope do not match the dedicated API registration.",
        )
        return identity

    def preflight(self) -> None:
        version = self.run(["terraform", "version", "-json"])
        require(bool(re.fullmatch(r"1\.16\.\d+", version["terraform_version"])), "Use Terraform 1.16.x.")
        require(sys.version_info >= (3, 11), "Use Python 3.11 or newer.")
        account = self.az("account", "show")
        require(
            account["tenantId"] == self.config["tenant_id"]
            and account["id"] == self.config["subscription_id"],
            "Wrong tenant or subscription.",
        )
        user = self.az("ad", "signed-in-user", "show")
        require(
            user["id"] == self.config["bootstrap_object_id"], "Sign in as the configured bootstrap operator."
        )
        self.az("group", "show", "--name", self.config["resource_group_name"])
        providers = self.az("provider", "list")
        registered = {
            item["namespace"].lower() for item in providers if item["registrationState"] == "Registered"
        }
        missing = sorted(name for name in PROVIDERS if name.lower() not in registered)
        require(not missing, "Ask the subscription owner to register providers: " + ", ".join(missing))
        print("Read-only preflight passed. It does not prove directory/RBAC, quota or private data access.")

    def identities(self) -> None:
        self.approved("cost_network_and_permissions_reviewed")
        self.preflight()
        self.run(
            [
                sys.executable,
                str(ROOT / "infra" / "scripts" / "bootstrap-entra.py"),
                "--tenant",
                self.config["tenant_id"],
                "--subscription",
                self.config["subscription_id"],
                "--bootstrap-object-id",
                self.config["bootstrap_object_id"],
                "--prefix",
                self.prefix,
                "--hostname",
                self.hostname,
                "--customer",
                "--output",
                str(self.directory / "identity.json"),
            ],
            json_output=False,
        )
        self.identity()
        print("Dedicated registrations configured. Directory consent remains subject to customer policy.")

    def outputs(self) -> dict[str, Any]:
        return self.tf("terraform", "output", f"-state={self.main_state}", "-json", json_output=True)

    def main_inputs(self, phase: str) -> dict[str, Any]:
        self.approved("cost_network_and_permissions_reviewed")
        c = self.config
        base = c["network_profile"]
        values: dict[str, Any] = {
            "subscription_id": c["subscription_id"],
            "resource_group_name": c["resource_group_name"],
            "name_prefix": self.prefix,
            "location": self.location,
            "sql_location": c["sql_location"],
            "publisher_name": c["publisher_name"],
            "publisher_email": c["publisher_email"],
            "deployment_approved": True,
            "deployment_stage": "prerequisites",
            "gateway_origin_hostname": self.hostname,
            "network": {
                "address_space": base + ".0.0/16",
                "app_gateway_subnet": base + ".1.0/24",
                "private_endpoint_subnet": base + ".3.0/24",
                "app_service_integration_subnet": base + ".4.0/24",
            },
            "operator_ip": c["operator_ip"],
            "sql_admin": {
                "login": c["sql_admin_login"],
                "object_id": c["sql_admin_object_id"],
                "tenant_id": c["tenant_id"],
            },
            "hybrid_private_data_enabled": True,
            "sql_public_network_access_enabled": False,
            "key_vault_public_network_access_enabled": False,
            "function_storage_public_network_access_enabled": False,
            "create_container_registry": True,
            "app_service_sku": "B1",
            "sql_sku": "S0",
            "apim_capacity": 1,
            "log_retention_days": 30,
            "mise_sidecar_enabled": True,
            "mise_direct_jwt_enabled": c.get("mise_direct_jwt_enabled", False),
            "protection_language_enabled": True,
            "model_backends_file": str(self.directory / "model-backends.json"),
        }
        if self.australian:
            values["deployment_profile"] = "australiaeast-luna"
        if c.get("monthly_budget") is not None:
            values["monthly_budget"] = c["monthly_budget"]
        if phase == "prerequisites":
            return values
        identity = self.identity()
        images = read_json(self.directory / "images.json")
        require(
            images["build_fingerprint"] == self.build_fingerprint(), "Source/config changed; rebuild images."
        )
        registry = self.prefix.replace("-", "") + "acr.azurecr.io"
        require(
            set(images["images"]) == {"api", "customer", "admin", "ingestion"}, "Four images are required."
        )
        for image in images["images"].values():
            require(
                bool(re.fullmatch(rf"{re.escape(registry)}/aiflux-[a-z]+@sha256:[0-9a-f]{{64}}", image)),
                "All four images must have customer ACR SHA-256 digests.",
            )
        values.update(
            {
                "deployment_stage": "platform",
                "entra": {
                    "audience": identity["audience"],
                    "client_id": identity["audience"],
                    "home_tenant_id": c["tenant_id"],
                    "bootstrap_object_id": c["bootstrap_object_id"],
                },
                "apps": {
                    component: {
                        "image": images["images"][component].removeprefix(registry + "/"),
                        "registry_url": "https://" + registry,
                        "port": 8000 if component == "api" else 8080,
                        "health_path": "/health" if component == "api" else "/healthz",
                        "always_on": c.get("app_always_on", {}).get(component, True),
                    }
                    for component in ("api", "customer", "admin")
                },
                "ingestion_container_image": images["images"]["ingestion"],
            }
        )
        if phase in ("edge-bootstrap", "candidate", "pilot", "ingestion"):
            values.update(
                {
                    "deployment_stage": "edge-bootstrap" if phase == "edge-bootstrap" else "edge-candidate",
                    "app_gateway_existing_nsg_name": c.get("app_gateway_existing_nsg_name") or None,
                    "edge": {
                        "dns_label": c["dns_label"],
                        "origin_hostname": self.hostname,
                        "certificate_secret_id": c["certificate_secret_id"],
                        "certificate_vault_id": (
                            f"/subscriptions/{c['subscription_id']}/resourceGroups/{c['resource_group_name']}"
                            f"/providers/Microsoft.KeyVault/vaults/{self.prefix.replace('-', '')}kv"
                        ),
                        "app_gateway_timeout_seconds": 240,
                        "waf_body_limit_kb": 128,
                        "waf_inspection_limit_kb": 128,
                        "zones": ["1", "2"],
                    },
                }
            )
        if phase in ("candidate", "pilot", "ingestion"):
            self.approved("private_sql_initialized")
            self.approved("tls_and_renewal_reviewed")
            self.approved("model_terms_and_quota_reviewed")
            require(
                bool(c["certificate_secret_id"]),
                "Import the new TLS certificate and set its versionless URI.",
            )
            evidence = read_json(self.directory / "model-backends.json")
            require(evidence["subscription_id"] == c["subscription_id"], "Wrong model evidence subscription.")
            require(not evidence.get("blocked"), "Direct model verification has blockers.")
            if self.australian:
                self.validate_australian_evidence(evidence)
            values.update(
                {
                    "dev_openai_inference_enabled": True,
                    "dev_unified_inference_enabled": True,
                    "dev_direct_portals_enabled": True,
                    "dev_portals_operator_only": True,
                    "dev_openai_content_safety_threshold": c.get("dev_openai_content_safety_threshold", 0),
                    "dev_unified_accepted_model_aliases": c.get("additional_model_aliases", []),
                    "dev_portal_origins": [
                        f"https://{self.prefix}-{app}.azurewebsites.net" for app in ("customer", "admin")
                    ],
                    "dev_admin_settings_enabled": c["admin_settings_enabled"],
                    "dev_admin_settings_provisioned": c.get("admin_settings_provisioned", False),
                    "dev_gateway_controls_v2_enabled": c.get("gateway_controls_v2_enabled", False),
                    "dev_protected_material_available": c.get("protected_material_available", False),
                    "dev_monthly_request_quota_available": c.get("monthly_request_quota_available", False),
                    "dev_safety_relaxation_allowed": c.get("safety_relaxation_allowed", False),
                    "dev_gateway_max_rpm": c.get("gateway_max_rpm", 2),
                    "dev_unified_max_completion_tokens": 4096,
                    "private_sql_connectivity_accepted": True,
                }
            )
        if phase in ("pilot", "ingestion"):
            self.approved("guarded_smoke_and_signed_in_accepted")
            values["dev_catalog_accepted"] = True
        if phase == "ingestion":
            self.approved("ingestion_ownership_and_telemetry_accepted")
            require(bool(c["ingestion_start_at"]), "Set a reviewed ingestion activation cutoff.")
            values.update(
                {
                    "ingestion_enabled": True,
                    "ingestion_timer_enabled": True,
                    "ingestion_start_at": c["ingestion_start_at"],
                }
            )
        return values

    def source_fingerprint(self) -> str:
        paths = self.run(
            ["git", "-C", str(ROOT), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            json_output=False,
        )
        hasher = hashlib.sha256()
        for name in sorted(paths.decode().split("\0")):
            if name and name.split("/")[0] in {
                "infra",
                "gateway",
                "scripts",
                "apps",
                "services",
                "packages",
                "pyproject.toml",
                "package.json",
                "package-lock.json",
                "tsconfig.base.json",
                ".dockerignore",
            }:
                path = ROOT / name
                require(
                    path.is_file() and not path.is_symlink(),
                    "Tracked deployment source is missing or symlinked.",
                )
                hasher.update(name.encode())
                hasher.update(path.read_bytes())
        return hasher.hexdigest()

    def build_fingerprint(self) -> str:
        # Certificate/acceptance changes do not alter compiled portal settings or the catalog.
        compiled = {
            key: self.config[key]
            for key in (
                "tenant_id",
                "subscription_id",
                "name_prefix",
                "bootstrap_object_id",
                "dns_label",
            )
        }
        if self.australian:
            compiled["deployment_profile"] = self.config["deployment_profile"]
            compiled["additional_model_aliases"] = sorted(self.config.get("additional_model_aliases", []))
        return digest(
            json.dumps(
                {
                    "source": self.source_fingerprint(),
                    "compiled": compiled,
                    "identity": self.identity(),
                },
                sort_keys=True,
            ).encode()
        )

    def binding(self, inputs: dict[str, Any]) -> str:
        return digest(
            json.dumps(
                {
                    "config": self.config,
                    "inputs": inputs,
                    "source": self.source_fingerprint(),
                    "identity": read_json(self.directory / "identity.json")
                    if (self.directory / "identity.json").exists()
                    else None,
                    "model_evidence": digest((self.directory / "model-backends.json").read_bytes())
                    if (self.directory / "model-backends.json").exists()
                    else None,
                },
                sort_keys=True,
            ).encode()
        )

    def check_progress(self, phase: str) -> None:
        journal = self.directory / "progress.json"
        if journal.exists():
            previous = read_json(journal)
            require(
                previous["subscription_id"] == self.config["subscription_id"]
                and previous["prefix"] == self.prefix,
                "Environment state belongs to a different deployment.",
            )
            require(
                PHASES.index(phase) >= PHASES.index(previous["phase"]),
                "Refusing a backward phase that could remove resources or disable accepted settings.",
            )
            require(
                PHASES.index(phase) <= PHASES.index(previous["phase"]) + 1,
                "Complete the preceding phase first.",
            )
        else:
            require(
                phase == "prerequisites",
                "Start with prerequisites; adoption requires a separate state review.",
            )

    def plan(self, phase: str) -> str:
        self.preflight()
        self.check_progress(phase)
        (self.directory / "plan-review.json").unlink(missing_ok=True)
        root = self.model_root if phase == "models" else "terraform"
        if phase == "models":
            self.approved("model_terms_and_quota_reviewed")
            outputs = self.outputs()
            inputs = {
                "subscription_id": self.config["subscription_id"],
                "resource_group_name": self.config["resource_group_name"],
                "eastus_account_name": self.prefix + "-foundry",
                "sweden_account_name": self.prefix + "-foundry-swc",
                "gateway_principal_id": outputs["identity_principal_ids"]["value"]["gateway"],
                "model_aliases": list(ALIASES[:2]),
            }
            if self.australian:
                inputs = {
                    "subscription_id": self.config["subscription_id"],
                    "resource_group_name": self.config["resource_group_name"],
                    "account_name": self.prefix + "-foundry",
                    "gateway_principal_id": outputs["identity_principal_ids"]["value"]["gateway"],
                }
        else:
            inputs = self.main_inputs(phase)
        self.tf(root, "init", "-input=false")
        var_file = self.directory / (phase + ".tfvars.json")
        plan_file = self.directory / (phase + ".tfplan")
        write_json(var_file, inputs)
        self.tf(
            root,
            "plan",
            "-input=false",
            "-lock-timeout=30s",
            f"-state={self.models_state if phase == 'models' else self.main_state}",
            f"-var-file={var_file}",
            f"-out={plan_file}",
        )
        plan = self.tf(root, "show", "-json", str(plan_file), json_output=True)
        changes = [
            {"address": resource["address"], "actions": resource["change"]["actions"]}
            for resource in plan.get("resource_changes", [])
            if resource["change"]["actions"] != ["no-op"]
        ]
        require(
            not any("delete" in change["actions"] for change in changes),
            "Plan deletes/replaces resources. Nothing applied; obtain a separate migration review.",
        )
        # Runtime-owned fragment content must never be included in a deployment update.
        for resource in plan.get("resource_changes", []):
            if resource["address"].startswith("azapi_resource.gateway_settings["):
                require(
                    resource["change"]["actions"] in (["no-op"], ["create"]),
                    "Settings fragment update needs separate review; preserve runtime administrator values.",
                )
        binding = self.binding(inputs)
        plan_hash = digest(plan_file.read_bytes())
        approval = digest((binding + plan_hash).encode())
        write_json(
            self.directory / "plan-review.json",
            {
                "phase": phase,
                "root": root,
                "binding": binding,
                "plan_hash": plan_hash,
                "approval": approval,
                "changes": changes,
            },
        )
        print(json.dumps({"changes": changes, "approval": approval}, indent=2))
        print("Inspect the complete plan securely with terraform show; summary is not full review.")
        return approval

    def apply(self, phase: str, approval: str) -> None:
        self.preflight()
        self.check_progress(phase)
        review_path = self.directory / "plan-review.json"
        review = read_json(review_path)
        require(review["phase"] == phase, "Plan belongs to a different phase.")
        plan_file = self.directory / (phase + ".tfplan")
        inputs = read_json(self.directory / (phase + ".tfvars.json"))
        require(
            review["binding"] == self.binding(inputs), "Inputs/source/evidence changed; create a new plan."
        )
        require(review["plan_hash"] == digest(plan_file.read_bytes()), "Saved plan changed; replan.")
        require(approval == review["approval"], "Explicit complete-plan approval token is required.")
        # A failed/interrupted apply invalidates approval; partial state must be refreshed/replanned.
        review_path.unlink()
        self.tf(
            review["root"],
            "apply",
            "-input=false",
            "-lock-timeout=30s",
            "-parallelism=1",
            f"-state={self.models_state if phase == 'models' else self.main_state}",
            str(plan_file),
        )
        write_json(
            self.directory / "progress.json",
            {
                "subscription_id": self.config["subscription_id"],
                "prefix": self.prefix,
                "phase": phase,
                "applied_at": datetime.now(UTC).isoformat(),
                "readiness": "provisioned-only; run runtime acceptance",
            },
        )
        print(f"{phase} provisioned. This is not a readiness or production release assertion.")

    def catalog(self) -> dict[str, Any]:
        source = read_json(ROOT / "gateway" / "catalog" / "dev-models.json")
        selected = []
        for item in source["models"]:
            if item["id"] not in self.aliases:
                continue
            item["backends"] = []
            if item["id"] in BUDGET_ALIASES:
                item.update(enabled=True, placeholder=False, capabilities=["chat"])
            regions = ("eastus",) if item["provider"] == "Anthropic" else ("eastus", "swedencentral")
            if self.australian:
                regions = ("australiaeast",)
            for region in regions:
                account = self.prefix + "-foundry" + ("-swc" if region == "swedencentral" else "")
                endpoint = (
                    f"https://{account}.services.ai.azure.com/anthropic/v1"
                    if item["provider"] == "Anthropic"
                    else (
                        f"https://{account}.services.ai.azure.com/models"
                        if item["provider"] == "DeepSeek"
                        else f"https://{account}.openai.azure.com/openai/v1"
                    )
                )
                item["backends"].append(
                    {
                        "id": f"dev-{item['id']}-{region}".lower().replace(".", "-"),
                        "region": region,
                        "url": endpoint,
                        "model": item["id"],
                        "provider": item["provider"],
                        "auth": {"managed_identity_resource": "https://cognitiveservices.azure.com/"},
                    }
                )
            selected.append(item)
        require({item["id"] for item in selected} == set(self.aliases), "Pinned pilot catalog is incomplete.")
        return {"models": selected}

    def prices(self) -> list[dict[str, Any]]:
        allowed = {
            (model["id"], backend.get("provider") or model["provider"], backend["region"])
            for model in self.catalog()["models"]
            for backend in model["backends"]
            if model["enabled"]
        }
        return [
            price for price in read_json(ROOT / "gateway" / "catalog" / "dev-prices.json")
            if (price["model"], price["provider"], price["region"]) in allowed
        ]

    def build(self) -> None:
        self.preflight()
        self.approved("cost_network_and_permissions_reviewed")
        identity = self.identity()
        registry = self.outputs()["container_registry"]["value"]
        require(registry["name"] == self.prefix.replace("-", "") + "acr", "Unexpected registry ownership.")
        untracked = self.run(
            ["git", "-C", str(ROOT), "ls-files", "--others", "--exclude-standard", "-z"],
            json_output=False,
        )
        require(
            not any(name and name.split("/")[0] in BUILD_ROOTS for name in untracked.decode().split("\0")),
            "Untracked application source would be omitted. Review/track it before building.",
        )
        fingerprint = self.build_fingerprint()
        images = {}
        dockerfiles = {
            "api": "services/control-plane/Dockerfile",
            "ingestion": "services/usage-ingestion/Dockerfile",
            "customer": "apps/customer-portal/Dockerfile",
            "admin": "apps/admin-portal/Dockerfile",
        }
        # Only tracked application source is uploaded. Never upload .deployment, state, plans or .env.
        tracked = self.run(["git", "-C", str(ROOT), "ls-files", "-z"], json_output=False)
        with tempfile.TemporaryDirectory(prefix="aiflux-build-") as temporary:
            context = Path(temporary)
            for name in tracked.decode().split("\0"):
                if not name or name.split("/")[0] not in BUILD_ROOTS:
                    continue
                source = ROOT / name
                require(source.is_file() and not source.is_symlink(), "Invalid build source.")
                target = context / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
            write_json(context / "gateway" / "catalog" / "dev-models.json", self.catalog())
            write_json(context / "gateway" / "catalog" / "dev-prices.json", self.prices())
            write_json(self.directory / "catalog.json", self.catalog())
            for component, dockerfile in dockerfiles.items():
                repository = "aiflux-" + component
                tag = fingerprint[:20]
                arguments = [
                    "acr",
                    "build",
                    "--registry",
                    registry["name"],
                    "--resource-group",
                    self.config["resource_group_name"],
                    "--image",
                    f"{repository}:{tag}",
                    "--file",
                    dockerfile,
                    "--no-logs",
                ]
                if component in ("customer", "admin"):
                    for name, value in {
                        "VITE_ENTRA_CLIENT_ID": identity["applications"][component]["client_id"],
                        "VITE_ENTRA_AUTHORITY": "https://login.microsoftonline.com/"
                        + self.config["tenant_id"],
                        "VITE_API_SCOPE": identity["scope"],
                        "VITE_CONTROL_API_URL": f"https://{self.prefix}-api.azurewebsites.net/api",
                        "VITE_GATEWAY_URL": f"https://{self.prefix}-apim.azure-api.net/dev/llm/v1",
                    }.items():
                        arguments.extend(["--build-arg", name + "=" + value])
                self.az(*arguments, str(context))
                manifest = self.az(
                    "acr", "repository", "show", "--name", registry["name"], "--image", f"{repository}:{tag}"
                )
                require(bool(re.fullmatch(r"sha256:[0-9a-f]{64}", manifest["digest"])), "ACR digest missing.")
                images[component] = registry["login_server"] + "/" + repository + "@" + manifest["digest"]
        require(
            fingerprint == self.build_fingerprint(),
            "Source changed while building; rebuild before deploying.",
        )
        write_json(self.directory / "images.json", {"build_fingerprint": fingerprint, "images": images})
        print("Four customer-specific images built and pinned by digest.")

    def models_verify(self) -> None:
        self.preflight()
        self.approved("model_terms_and_quota_reviewed")
        arguments = [
            sys.executable,
            str(ROOT / "infra" / "models" / "verify.py"),
            "--subscription",
            self.config["subscription_id"],
            "--resource-group",
            self.config["resource_group_name"],
            "--gateway-principal-id",
            self.outputs()["identity_principal_ids"]["value"]["gateway"],
            "--post-deploy",
            "--smoke",
            "--output",
            str(self.directory / "model-backends.json"),
        ]
        if self.australian:
            arguments.extend(["--australiaeast-account", self.prefix + "-foundry"])
        else:
            arguments.extend(
                [
                    "--eastus-account",
                    self.prefix + "-foundry",
                    "--sweden-account",
                    self.prefix + "-foundry-swc",
                ]
            )
        for alias in self.aliases:
            arguments.extend(["--model-alias", alias])
        self.run(arguments, json_output=False)
        evidence = read_json(self.directory / "model-backends.json")
        require(
            not evidence["blocked"],
            "Direct model checks blocked. Resolve access/Haiku/quota before continuing.",
        )
        if self.australian:
            self.validate_australian_evidence(evidence)
            print("Direct Australian model checks passed; guarded gateway acceptance remains separate.")
            return
        require(
            len(evidence["backends"]) == 4
            and all(
                item["ready"] and item.get("operator_smoke", {}).get("passed")
                for item in evidence["backends"]
            ),
            "All four pinned OpenAI deployments must pass direct smoke.",
        )
        haiku = [item for item in evidence["anthropic_backends"] if item.get("region") == "eastus"]
        require(
            bool(haiku)
            and all(item["ready"] and item.get("operator_smoke", {}).get("passed") for item in haiku),
            "Primary Haiku must pass direct smoke after customer entitlement/deployment.",
        )
        print("Direct model checks passed; guarded gateway acceptance remains separate.")

    def validate_australian_evidence(self, evidence: dict[str, Any]) -> None:
        expected_account = (
            f"/subscriptions/{self.config['subscription_id']}"
            f"/resourceGroups/{self.config['resource_group_name']}"
            f"/providers/Microsoft.CognitiveServices/accounts/{self.prefix}-foundry"
        )
        backends = evidence.get("backends", [])
        expected_aliases = {"gpt-5.6-luna", *self.config.get("additional_model_aliases", [])}
        require(
            evidence.get("subscription_id") == self.config["subscription_id"]
            and not evidence.get("blocked")
            and not evidence.get("anthropic_backends")
            and len(backends) == len(expected_aliases)
            and {item.get("alias") for item in backends} == expected_aliases,
            "Australia East requires exactly the opted-in aliases and no other regions/models.",
        )
        specification = read_json(ROOT / "infra" / "models" / "model-spec.json")["models"]
        for item in backends:
            alias = item["alias"]
            pinned = next(model for model in specification if model["id"] == alias)
            smoke = item.get("operator_smoke", {})
            endpoint = (
                f"https://{self.prefix}-foundry.services.ai.azure.com/models"
                if pinned["endpoint_source"] == "model_inference_endpoint"
                else f"https://{self.prefix}-foundry.openai.azure.com"
            )
            require(
                item.get("region") == "australiaeast"
                and item.get("account_resource_id") == expected_account
                and item.get("deployment_resource_id") == expected_account + "/deployments/" + alias
                and item.get("model_name") == alias
                and item.get("model_version") == pinned["version"]
                and item.get("sku") == "GlobalStandard"
                and item.get("capacity") == pinned["capacity"]
                and item.get("endpoint") == endpoint
                and item.get("ready") is True
                and item.get("auth", {}).get("gateway_role_assigned") is True
                and smoke.get("passed") is True
                and smoke.get("http_status") == 200
                and smoke.get("choices_schema_present") is True,
                "Australia East model evidence does not match the pinned deployment "
                "or successful direct smoke.",
            )

    def sql_init(self) -> None:
        self.preflight()
        self.approved("cost_network_and_permissions_reviewed")
        outputs = self.outputs()
        settings = outputs["control_plane_settings"]["value"]
        require(bool(settings), "Deploy platform before SQL initialization.")
        clients = {}
        for component in ("api", "ingestion"):
            identity = self.az(
                "identity",
                "show",
                "--resource-group",
                self.config["resource_group_name"],
                "--name",
                self.prefix + "-" + component + "-identity",
            )
            require(
                identity["principalId"] == outputs["identity_principal_ids"]["value"][component],
                "Runtime identity differs from Terraform outputs.",
            )
            clients[component.upper() + "_CLIENT_ID"] = identity["clientId"]
        inputs = self.directory / "sql-inputs.json"
        write_json(
            inputs,
            {
                "settings": settings,
                "subscription_id": self.config["subscription_id"],
                "private_endpoint_subnet": self.config["network_profile"] + ".3.0/24",
                **clients,
            },
        )
        self.run(
            [sys.executable, "-m", "scripts.deployment.sql_init", "--inputs", str(inputs)],
            json_output=False,
        )
        print("SQL operator initialization completed; verify application runtime access separately.")

    def verify(self) -> None:
        self.preflight()
        checks = {}
        endpoints = {
            "api_health": f"https://{self.prefix}-api.azurewebsites.net/health",
            "private_sql_readiness": f"https://{self.prefix}-api.azurewebsites.net/ready",
            "customer_health": f"https://{self.prefix}-customer.azurewebsites.net/healthz",
            "admin_health": f"https://{self.prefix}-admin.azurewebsites.net/healthz",
        }
        for name, url in endpoints.items():
            try:
                with urllib.request.urlopen(url, timeout=30) as response:
                    checks[name] = response.status == 200
            except (urllib.error.URLError, TimeoutError):
                checks[name] = False
        write_json(
            self.directory / "verification.json",
            {
                "checks": checks,
                "checked_at": datetime.now(UTC).isoformat(),
                "scope": "HTTP probes only; excludes signed-in, TLS, gateway and ingestion acceptance",
            },
        )
        require(all(checks.values()), "Platform probe failed; inspect verification.json. Not ready.")
        print("Platform probes passed; signed-in, TLS, gateway and ingestion acceptance remain separate.")

    def deploy(self) -> None:
        self.preflight()
        self.approved("cost_network_and_permissions_reviewed")
        if not (self.directory / "identity.json").exists():
            require(
                input("Create dedicated Entra registrations and initial IDS assignment? Type CREATE: ")
                == "CREATE",
                "Registration creation not approved.",
            )
            self.identities()
        for phase in PHASES[:-1]:
            progress_path = self.directory / "progress.json"
            if progress_path.exists() and PHASES.index(read_json(progress_path)["phase"]) > PHASES.index(
                phase
            ):
                continue
            if phase == "platform" and not (self.directory / "images.json").exists():
                require(
                    input("Build four customer images in ACR (paid)? Type BUILD: ") == "BUILD",
                    "Image build not approved.",
                )
                self.build()
            if phase == "candidate":
                print("Complete the runbook's private SQL, certificate/renewal and direct model checkpoints.")
                self.models_verify()
            approval = self.plan(phase)
            entered = input(f"Review {phase}.tfplan securely, then paste its approval token (Enter stops): ")
            require(entered == approval, "Plan not approved; nothing from this phase applied.")
            self.apply(phase, entered)
        self.verify()
        print("Provisioning finished. Customer acceptance records remain authoritative, not these probes.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "action",
        choices=(
            "deploy",
            "preflight",
            "identities",
            "build",
            "plan",
            "apply",
            "models-verify",
            "sql-init",
            "verify",
        ),
    )
    parser.add_argument("--phase", choices=PHASES, default="prerequisites")
    parser.add_argument("--approval", default="")
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        directory = ROOT / ".deployment" / config["name_prefix"]
        with environment_lock(directory):
            binding_path = directory / "environment.json"
            binding = {
                key: config[key]
                for key in ("tenant_id", "subscription_id", "resource_group_name", "name_prefix")
            }
            if config.get("deployment_profile", "legacy") != "legacy":
                binding["deployment_profile"] = config["deployment_profile"]
            if binding_path.exists():
                require(
                    read_json(binding_path) == binding,
                    "Local state directory belongs to another environment.",
                )
            else:
                write_json(binding_path, binding)
            launcher = Launcher(config, directory)
            if args.action == "plan":
                launcher.plan(args.phase)
            elif args.action == "apply":
                launcher.apply(args.phase, args.approval)
            elif args.action == "sql-init":
                require(
                    args.approval == "INITIALIZE", "Explicit -Approval INITIALIZE is required for SQL DDL."
                )
                launcher.sql_init()
            else:
                getattr(launcher, args.action.replace("-", "_"))()
    except (DeploymentError, KeyboardInterrupt, EOFError, OSError) as error:
        print(f"Deployment stopped: {error or 'cancelled; replan before retrying'}", file=sys.stderr)
        raise SystemExit(1) from None
