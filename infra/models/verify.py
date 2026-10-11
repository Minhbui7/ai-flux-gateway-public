"""Collect sanitized ARM readiness and optional minimal Entra inference evidence."""

import argparse
import json
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def az(*args):
    return json.loads(subprocess.check_output(["az.cmd", *args, "-o", "json"]))


def get_json(url, token, body=None):
    headers = {"Authorization": f"Bearer {token}"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=90) as response:
        return response.status, json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subscription", required=True)
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--eastus-account", required=True)
    parser.add_argument("--sweden-account", required=True)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    management_token = az(
        "account", "get-access-token", "--resource", "https://management.azure.com/"
    )["accessToken"]
    inference_token = None
    if args.smoke:
        inference_token = az(
            "account", "get-access-token", "--resource",
            "https://cognitiveservices.azure.com/"
        )["accessToken"]
    evidence = {
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "subscription_id": args.subscription,
        "backends": [],
        "blocked": [{
            "model": "claude-sonnet-5-5",
            "provider": "Anthropic",
            "catalog_latest_version": "2",
            "regions": ["eastus", "swedencentral"],
            "reason": "Required Anthropic industry declaration and any applicable legal/marketplace onboarding have not been authorized; no terms accepted and no deployment attempted.",
        }],
        "gateway_ready": False,
    }
    for region, account in (
        ("eastus", args.eastus_account),
        ("swedencentral", args.sweden_account),
    ):
        resource_id = (
            f"/subscriptions/{args.subscription}/resourceGroups/{args.resource_group}"
            f"/providers/Microsoft.CognitiveServices/accounts/{account}"
        )
        _, account_data = get_json(
            f"https://management.azure.com{resource_id}?api-version=2025-06-01",
            management_token,
        )
        assert account_data["location"] == region
        assert account_data["properties"]["disableLocalAuth"] is True
        for model in ("gpt-5.6-luna", "gpt-5.6-sol"):
            deployment_id = f"{resource_id}/deployments/{model}"
            try:
                _, deployment = get_json(
                    f"https://management.azure.com{deployment_id}?api-version=2025-06-01",
                    management_token,
                )
            except urllib.error.HTTPError as error:
                evidence["backends"].append({
                    "alias": model, "region": region, "ready": False,
                    "management_http_status": error.code,
                })
                continue
            properties = deployment["properties"]
            native_model = properties["model"]
            assert native_model["name"] == model
            assert native_model["version"] == "2026-07-09"
            endpoint = f"https://{account}.openai.azure.com"
            item = {
                "alias": model,
                "provider": native_model["format"],
                "account_resource_id": resource_id,
                "deployment_resource_id": deployment_id,
                "account_name": account,
                "deployment_name": model,
                "model_name": native_model["name"],
                "model_version": native_model["version"],
                "region": region,
                "sku": deployment["sku"]["name"],
                "capacity": deployment["sku"]["capacity"],
                "provisioning_state": properties["provisioningState"],
                "rai_policy": properties.get("raiPolicyName"),
                "endpoint": endpoint,
                "endpoint_format": "Azure OpenAI v1",
                "native_operation": "POST /openai/v1/chat/completions",
                "api_version": "v1 (path; no api-version query required)",
                "request_contract": {
                    "model": model,
                    "messages": "OpenAI messages array",
                    "max_completion_tokens": "positive integer",
                },
                "auth": {
                    "type": "Entra bearer token",
                    "audience": "https://cognitiveservices.azure.com/",
                    "gateway_role": "Cognitive Services OpenAI User",
                },
                "ready": properties["provisioningState"] == "Succeeded",
            }
            if inference_token and item["ready"]:
                try:
                    status, result = get_json(
                        endpoint + "/openai/v1/chat/completions", inference_token,
                        {"model": model,
                         "messages": [{"role": "user", "content": "Reply OK."}],
                         "max_completion_tokens": 32},
                    )
                    usage = result.get("usage", {})
                    item["operator_smoke"] = {
                        "http_status": status,
                        "choices_schema_present": isinstance(result.get("choices"), list),
                        "usage": {key: value for key, value in usage.items()
                                  if key in ("prompt_tokens", "completion_tokens", "total_tokens")},
                    }
                except urllib.error.HTTPError as error:
                    item["operator_smoke"] = {"http_status": error.code}
                except (TimeoutError, urllib.error.URLError):
                    item["operator_smoke"] = {"status": "network_or_timeout_error"}
            evidence["backends"].append(item)
    destination = Path(__file__).with_name("model-backends.json")
    destination.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "evidence": str(destination),
        "backends": [{
            "alias": item["alias"], "region": item["region"],
            "ready": item["ready"], "smoke": item.get("operator_smoke")
        } for item in evidence["backends"]],
        "blocked": evidence["blocked"],
    }, indent=2))


if __name__ == "__main__":
    main()
