"""Collect sanitized deployment, RBAC, endpoint, and optional direct-smoke evidence."""

from __future__ import annotations

import argparse
import json
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

SPEC_PATH = Path(__file__).with_name("model-spec.json")
EVIDENCE_PATH = Path(__file__).with_name("model-backends.json")
COGNITIVE_SERVICES_USER = "a97b65f3-24c7-4388-baec-2e87135dc908"
OPENAI_USER = "5e0bd9bd-7b93-4f28-af87-19fc36ad61bd"
MAX_DIRECT_SMOKE_COMPLETION_TOKENS = 4096


def az(*args: str) -> dict[str, Any]:
    return json.loads(subprocess.check_output(["az.cmd", *args, "-o", "json"]))


def get_json(
    url: str, token: str, body: dict | None = None, extra_headers: dict[str, str] | None = None
) -> tuple[int, dict]:
    headers = {"Authorization": f"Bearer {token}"}
    if extra_headers:
        headers.update(extra_headers)
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            parsed = json.load(response)
            return response.status, parsed if isinstance(parsed, dict) else {}
    except urllib.error.HTTPError as error:
        return error.code, {}


def model_spec() -> dict[str, dict[str, Any]]:
    document = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if document.get("schema_version") != 1:
        raise ValueError("Unsupported model specification version")
    return {model["id"]: model for model in document["models"]}


def endpoint_from_account(
    account_data: dict, spec: dict, previous: dict, region: str
) -> tuple[str | None, str | None]:
    endpoints = account_data.get("properties", {}).get("endpoints", {})
    if not isinstance(endpoints, dict):
        endpoints = {}

    if spec["endpoint_source"] == "model_inference_endpoint":
        endpoint = next(
            (
                value
                for key, value in endpoints.items()
                if "model inference" in key.lower() and isinstance(value, str)
            ),
            None,
        )
    elif spec["endpoint_source"] == "openai_endpoint":
        candidates = [
            item
            for item in previous.get("backends", [])
            if item.get("region") == region
            and item.get("provider") == "OpenAI"
            and isinstance(item.get("endpoint"), str)
        ]
        endpoint = (
            candidates[0]["endpoint"]
            if candidates
            else next(
                (
                    value
                    for value in endpoints.values()
                    if isinstance(value, str)
                    and urlsplit(value).hostname
                    and urlsplit(value).hostname.endswith(".openai.azure.com")
                ),
                None,
            )
        )
    else:
        candidates = [
            item
            for item in previous.get("anthropic_backends", [])
            if item.get("region") == region and isinstance(item.get("endpoint"), str)
        ]
        endpoint = None
        if candidates:
            parts = urlsplit(candidates[0]["endpoint"])
            endpoint = f"{parts.scheme}://{parts.netloc}"
        else:
            endpoint = next(
                (
                    value.rstrip("/")
                    for value in endpoints.values()
                    if isinstance(value, str)
                    and urlsplit(value).hostname
                    and urlsplit(value).hostname.endswith(".services.ai.azure.com")
                ),
                None,
            )

    if not isinstance(endpoint, str):
        return None, "The account ARM response did not expose the verified provider endpoint."
    parts = urlsplit(endpoint)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
    ):
        return None, "The account/provider endpoint was not a credential-free HTTPS endpoint."

    if spec["endpoint_source"] == "model_inference_endpoint":
        if not parts.hostname.endswith(".services.ai.azure.com") or parts.path.rstrip("/") not in (
            "",
            "/models",
        ):
            return None, "The account model-inference endpoint has an unexpected host or path."
        # ARM advertises the service root; the documented REST operation is under /models.
        return f"{parts.scheme}://{parts.netloc}/models", None

    if spec["endpoint_source"] == "openai_endpoint":
        if not parts.hostname.endswith(".openai.azure.com"):
            return None, "No verified Azure OpenAI v1 endpoint was found for this region."
        return f"{parts.scheme}://{parts.netloc}", None

    if not parts.hostname.endswith(".services.ai.azure.com"):
        return None, "No verified Foundry Anthropic endpoint was found for this region."
    return f"{parts.scheme}://{parts.netloc}", None


def operation_url(endpoint: str, spec: dict) -> str:
    operation = spec["operation"]
    if spec["endpoint_source"] == "model_inference_endpoint":
        # ARM advertises the provider's /models base; append only the relative chat operation.
        operation = operation.removeprefix("/models")
    url = endpoint.rstrip("/") + operation
    if spec.get("api_version"):
        url += "?" + urllib.parse.urlencode({"api-version": spec["api_version"]})
    return url


def smoke_request(endpoint: str, spec: dict, alias: str, token: str) -> dict:
    requested = min(spec["max_completion_tokens"], MAX_DIRECT_SMOKE_COMPLETION_TOKENS)
    if spec["wire_api"] == "anthropic-messages":
        body = {
            "model": alias,
            "messages": [{"role": "user", "content": "Reply OK."}],
            "max_tokens": requested,
        }
        headers = {"anthropic-version": "2023-06-01"}
    else:
        body = {
            "model": alias,
            "messages": [{"role": "user", "content": "Reply OK."}],
            spec["request_token_parameter"]: requested,
        }
        headers = {}

    status, result = get_json(operation_url(endpoint, spec), token, body, headers)
    smoke: dict[str, Any] = {"http_status": status}
    usage = result.get("usage")
    if spec["wire_api"] == "anthropic-messages":
        content = result.get("content")
        valid = (
            isinstance(content, list)
            and any(
                isinstance(block, dict)
                and block.get("type") == "text"
                and isinstance(block.get("text"), str)
                and bool(block["text"])
                for block in content
            )
            and isinstance(usage, dict)
            and type(usage.get("output_tokens")) is int
            and 0 <= usage["output_tokens"] <= requested
            and type(usage.get("input_tokens")) is int
            and usage["input_tokens"] >= 0
        )
        smoke["content_schema_present"] = isinstance(content, list)
        if valid:
            smoke["usage"] = {key: usage[key] for key in ("input_tokens", "output_tokens")}
    else:
        choices = result.get("choices")
        first = choices[0] if isinstance(choices, list) and choices else None
        message = first.get("message") if isinstance(first, dict) else None
        valid = (
            isinstance(message, dict)
            and isinstance(message.get("content"), str)
            and bool(message["content"])
            and isinstance(usage, dict)
            and all(
                type(usage.get(key)) is int and usage[key] >= 0
                for key in ("prompt_tokens", "completion_tokens", "total_tokens")
            )
            and usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]
            and usage["completion_tokens"] <= requested
        )
        smoke["choices_schema_present"] = isinstance(choices, list)
        if valid:
            smoke["usage"] = {
                key: usage[key] for key in ("prompt_tokens", "completion_tokens", "total_tokens")
            }
    smoke["passed"] = status == 200 and bool(valid)
    return smoke


def role_is_assigned(resource_id: str, principal_id: str, role_id: str, management_token: str) -> bool:
    query = urllib.parse.urlencode({"api-version": "2022-04-01", "$filter": "atScope()"})
    url = (
        f"https://management.azure.com{resource_id}/providers/Microsoft.Authorization/roleAssignments?{query}"
    )
    _, result = get_json(url, management_token)
    return any(
        str(item.get("properties", {}).get("principalId", "")).lower() == principal_id.lower()
        and str(item.get("properties", {}).get("roleDefinitionId", "")).lower().endswith(role_id.lower())
        for item in result.get("value", [])
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subscription", required=True)
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--eastus-account", required=True)
    parser.add_argument("--sweden-account", required=True)
    parser.add_argument(
        "--gateway-principal-id",
        required=True,
        help="Object ID of the gateway UAMI whose account-scoped inference roles are verified.",
    )
    parser.add_argument(
        "--post-deploy",
        action="store_true",
        help="Verify expected new deployments after their reviewed model-root apply.",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Make one bounded, non-sensitive direct request per found deployment.",
    )
    args = parser.parse_args()

    management_token = az(
        "account",
        "get-access-token",
        "--subscription",
        args.subscription,
        "--resource",
        "https://management.azure.com/",
    )["accessToken"]
    inference_token = None
    if args.smoke:
        inference_token = az(
            "account",
            "get-access-token",
            "--subscription",
            args.subscription,
            "--resource",
            "https://cognitiveservices.azure.com/",
        )["accessToken"]

    specs = model_spec()
    try:
        previous = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        previous = {}
    evidence: dict[str, Any] = {
        "verified_at": datetime.now(UTC).isoformat(),
        "subscription_id": args.subscription,
        "backends": [],
        "anthropic_backends": [],
        "blocked": [],
        "gateway_ready": False,
        "acceptance": "direct_backend_only",
    }
    accounts = (
        ("eastus", args.eastus_account),
        ("swedencentral", args.sweden_account),
    )
    for region, account in accounts:
        resource_id = (
            f"/subscriptions/{args.subscription}/resourceGroups/{args.resource_group}"
            f"/providers/Microsoft.CognitiveServices/accounts/{account}"
        )
        _, account_data = get_json(
            f"https://management.azure.com{resource_id}?api-version=2025-06-01",
            management_token,
        )
        if (
            account_data.get("location") != region
            or account_data.get("properties", {}).get("disableLocalAuth") is not True
        ):
            raise ValueError(f"{region} account location or disabled-key-auth posture did not match.")

        for alias, spec in specs.items():
            if alias == "claude-haiku-5-5" or spec["arm_format"] == "Anthropic":
                continue
            deployment_id = f"{resource_id}/deployments/{alias}"
            status, deployment = get_json(
                f"https://management.azure.com{deployment_id}?api-version=2025-06-01",
                management_token,
            )
            if region not in spec.get("regions", ["eastus", "swedencentral"]):
                if status == 200:
                    evidence["blocked"].append(
                        {
                            "alias": alias,
                            "region": region,
                            "reason": "deployment_exists_outside_approved_regions",
                        }
                    )
                elif status not in (404, 200):
                    raise ValueError(f"Could not check unapproved region for {alias} (HTTP {status}).")
                continue
            if status == 404:
                evidence["blocked"].append(
                    {"alias": alias, "region": region, "reason": "deployment_not_found"}
                )
                evidence["backends"].append({"alias": alias, "region": region, "ready": False})
                continue
            if status != 200:
                raise ValueError(
                    f"Could not read deployment metadata for {alias} in {region} (HTTP {status})."
                )
            if (
                spec["terraform_managed"]
                and alias not in ("gpt-5.6-luna", "gpt-5.6-sol")
                and not args.post_deploy
            ):
                evidence["blocked"].append(
                    {
                        "alias": alias,
                        "region": region,
                        "reason": "preexisting_deployment_ownership_conflict",
                    }
                )
                evidence["backends"].append(
                    {
                        "alias": alias,
                        "region": region,
                        "capacity": deployment.get("sku", {}).get("capacity"),
                        "ready": False,
                    }
                )
                continue
            properties = deployment.get("properties", {})
            native_model = properties.get("model", {})
            capacity = deployment.get("sku", {}).get("capacity")
            expected_capacity = spec["capacity"]
            if (
                native_model.get("format") != spec["arm_format"]
                or native_model.get("name") != alias
                or native_model.get("version") != spec["version"]
                or deployment.get("sku", {}).get("name") != "GlobalStandard"
                or capacity != expected_capacity
            ):
                raise ValueError(f"{alias} in {region} did not match its approved ARM model/SKU/capacity.")
            endpoint, endpoint_error = endpoint_from_account(account_data, spec, previous, region)
            role_ok = role_is_assigned(
                resource_id,
                args.gateway_principal_id,
                spec["gateway_role_definition_id"],
                management_token,
            )
            item: dict[str, Any] = {
                "alias": alias,
                "provider": spec["arm_format"],
                "wire_api": spec["wire_api"],
                "account_resource_id": resource_id,
                "deployment_resource_id": deployment_id,
                "account_name": account,
                "deployment_name": alias,
                "model_name": native_model["name"],
                "model_version": native_model["version"],
                "region": region,
                "sku": deployment["sku"]["name"],
                "capacity": capacity,
                "required_tpm": capacity * spec["tpm_per_capacity_unit"],
                "provisioning_state": properties.get("provisioningState"),
                "endpoint": endpoint,
                "operation": spec["operation"],
                "api_version": spec.get("api_version"),
                "request_contract": {
                    "model": alias,
                    "messages": "OpenAI-compatible messages array",
                    "token_parameter": spec["request_token_parameter"],
                    "max_completion_tokens": spec["max_completion_tokens"],
                },
                "auth": {
                    "type": "Entra bearer token",
                    "audience": spec["auth_audience"],
                    "gateway_role": spec["gateway_role"],
                    "gateway_role_definition_id": spec["gateway_role_definition_id"],
                    "gateway_role_assigned": role_ok,
                },
                "endpoint_verified": endpoint is not None and endpoint_error is None,
                "ready": properties.get("provisioningState") == "Succeeded"
                and role_ok
                and endpoint is not None,
            }
            if endpoint_error:
                item["endpoint_error"] = endpoint_error
                evidence["blocked"].append({"alias": alias, "region": region, "reason": endpoint_error})
            if not role_ok:
                evidence["blocked"].append(
                    {
                        "alias": alias,
                        "region": region,
                        "reason": "gateway_role_assignment_missing",
                    }
                )
            if inference_token and item["ready"]:
                item["operator_smoke"] = smoke_request(endpoint, spec, alias, inference_token)
                if not item["operator_smoke"]["passed"]:
                    evidence["blocked"].append(
                        {
                            "alias": alias,
                            "region": region,
                            "reason": f"direct_smoke_failed_http_{item['operator_smoke']['http_status']}",
                        }
                    )
            evidence["backends"].append(item)

        for alias, spec in specs.items():
            if alias != "claude-haiku-5-5" and spec["arm_format"] != "Anthropic":
                continue
            deployment_id = f"{resource_id}/deployments/{alias}"
            status, deployment = get_json(
                f"https://management.azure.com{deployment_id}?api-version=2025-06-01",
                management_token,
            )
            if region not in spec.get("regions", ["eastus", "swedencentral"]):
                if status == 200:
                    evidence["blocked"].append(
                        {
                            "model": alias,
                            "region": region,
                            "reason": "deployment_exists_outside_approved_regions",
                        }
                    )
                elif status not in (404, 200):
                    raise ValueError(f"Could not check unapproved region for {alias} (HTTP {status}).")
                continue
            if status == 404:
                evidence["blocked"].append(
                    {"model": alias, "region": region, "reason": "deployment_not_found"}
                )
                continue
            if status != 200:
                raise ValueError(f"Could not read Anthropic deployment {alias} in {region} (HTTP {status}).")
            if spec["terraform_managed"] and not args.post_deploy:
                evidence["blocked"].append(
                    {
                        "model": alias,
                        "region": region,
                        "reason": "preexisting_deployment_ownership_conflict",
                    }
                )
                evidence["anthropic_backends"].append(
                    {
                        "alias": alias,
                        "model": alias,
                        "region": region,
                        "capacity": deployment.get("sku", {}).get("capacity"),
                        "ready": False,
                    }
                )
                continue
            properties = deployment.get("properties", {})
            native_model = properties.get("model", {})
            expected_capacity = spec["capacity"]
            capacity = deployment.get("sku", {}).get("capacity")
            if expected_capacity == "manual":
                expected_capacity = spec.get("region_capacities", {}).get(region)
            if (
                native_model != {"format": "Anthropic", "name": alias, "version": spec["version"]}
                or deployment.get("sku", {}).get("name") != "GlobalStandard"
                or capacity != expected_capacity
            ):
                raise ValueError(
                    f"Anthropic deployment {alias} in {region} did not match the approved metadata."
                )
            endpoint, endpoint_error = endpoint_from_account(account_data, spec, previous, region)
            role_ok = role_is_assigned(
                resource_id,
                args.gateway_principal_id,
                spec["gateway_role_definition_id"],
                management_token,
            )
            item = {
                "alias": alias,
                "model": alias,
                "provider": "Anthropic",
                "wire_api": spec["wire_api"],
                "account_name": account,
                "region": region,
                "version": spec["version"],
                "capacity": capacity,
                "required_tpm": capacity * spec["tpm_per_capacity_unit"],
                "endpoint": endpoint,
                "endpoint_verified": endpoint is not None and endpoint_error is None,
                "operation": spec["operation"],
                "api_version": None,
                "ready": properties.get("provisioningState") == "Succeeded"
                and role_ok
                and endpoint is not None,
                "ownership": "manual_not_managed_by_this_terraform_root"
                if alias == "claude-haiku-5-5"
                else "terraform",
                "gateway_routed": alias == "claude-haiku-5-5",
                "auth": {
                    "type": "Entra bearer token",
                    "audience": spec["auth_audience"],
                    "gateway_role": spec["gateway_role"],
                    "gateway_role_definition_id": spec["gateway_role_definition_id"],
                    "gateway_role_assigned": role_ok,
                },
                "request_contract": {
                    "model": alias,
                    "token_parameter": spec["request_token_parameter"],
                    "max_completion_tokens": spec["max_completion_tokens"],
                },
            }
            if endpoint_error:
                item["endpoint_error"] = endpoint_error
                evidence["blocked"].append({"model": alias, "region": region, "reason": endpoint_error})
            if not role_ok:
                evidence["blocked"].append(
                    {
                        "model": alias,
                        "region": region,
                        "reason": "gateway_role_assignment_missing",
                    }
                )
            if inference_token and item["ready"]:
                item["operator_smoke"] = smoke_request(endpoint, spec, alias, inference_token)
                if not item["operator_smoke"]["passed"]:
                    evidence["blocked"].append(
                        {
                            "model": alias,
                            "region": region,
                            "reason": f"direct_smoke_failed_http_{item['operator_smoke']['http_status']}",
                        }
                    )
            evidence["anthropic_backends"].append(item)

    quota_preflight = []
    for alias, spec in specs.items():
        limit = spec.get("shared_quota_limit_units")
        if limit is None:
            continue
        target_regions = spec.get("regions", ["eastus", "swedencentral"])
        entries = [
            item
            for collection in (evidence["backends"], evidence["anthropic_backends"])
            for item in collection
            if item.get("alias", item.get("model")) == alias and item.get("region") in target_regions
        ]
        expected_units = sum(
            next(
                (
                    item["capacity"]
                    for item in entries
                    if item["region"] == region and type(item.get("capacity")) is int
                ),
                spec["capacity"],
            )
            for region in target_regions
        )
        passed = expected_units <= limit
        quota_preflight.append(
            {
                "model": alias,
                "scope": "subscription_global_across_target_regions",
                "target_regions": target_regions,
                "capacity_units": expected_units,
                "shared_quota_limit_units": limit,
                "passed": passed,
            }
        )
        if not passed:
            evidence["blocked"].append(
                {
                    "model": alias,
                    "reason": "cross_region_shared_quota_budget_exceeded",
                }
            )
    evidence["quota_preflight"] = quota_preflight

    EVIDENCE_PATH.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "evidence": str(EVIDENCE_PATH),
                "direct_backend_evidence_only": True,
                "backends": [
                    {
                        "alias": item["alias"],
                        "region": item["region"],
                        "ready": item["ready"],
                        "smoke": item.get("operator_smoke"),
                    }
                    for item in evidence["backends"]
                ],
                "anthropic_backends": [
                    {
                        "alias": item["alias"],
                        "region": item["region"],
                        "ready": item["ready"],
                        "smoke": item.get("operator_smoke"),
                    }
                    for item in evidence["anthropic_backends"]
                ],
                "blocked": evidence["blocked"],
                "quota_preflight": quota_preflight,
                "gateway_ready": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
