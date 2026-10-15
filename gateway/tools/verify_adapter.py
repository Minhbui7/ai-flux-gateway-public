"""Verify the guarded development adapter without retaining keys or model text."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from azure.identity import AzureCliCredential

ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = ROOT / "gateway" / "catalog" / "dev-models.json"


def model_catalog() -> tuple[dict[str, dict], dict[str, dict]]:
    entries = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))["models"]
    return (
        {item["id"]: item for item in entries if item.get("enabled") is True},
        {item["id"]: item for item in entries if item.get("placeholder") is True},
    )


def is_completion(payload: Any, *, max_completion_tokens: int = 64) -> bool:
    if not isinstance(payload, dict):
        return False
    choices = payload.get("choices")
    usage = payload.get("usage")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return False
    message = choices[0].get("message")
    return (
        isinstance(message, dict)
        and message.get("role") == "assistant"
        and isinstance(message.get("content"), str)
        and bool(message["content"])
        and choices[0].get("finish_reason") in ("stop", "length")
        and isinstance(usage, dict)
        and all(
            type(usage.get(k)) is int and usage[k] >= 0
            for k in ("prompt_tokens", "completion_tokens", "total_tokens")
        )
        and usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]
        and usage["completion_tokens"] <= max_completion_tokens
    )


def verify(
    base: str, key: str, origins: list[str], *, smoke: bool, candidate_aliases: list[str] | None = None
) -> dict:
    enabled, placeholders = model_catalog()
    candidates = set(candidate_aliases or [])
    if not candidates <= placeholders.keys():
        raise ValueError("Candidate routes must be currently disabled catalog placeholders.")
    if candidates and not smoke:
        raise ValueError("Candidate route acceptance requires --smoke.")
    results = []

    def record(name: str, response: httpx.Response, passed: bool) -> None:
        results.append({"name": name, "http_status": response.status_code, "passed": passed})

    with httpx.Client(timeout=120) as client:
        for name, headers in (
            ("missing_key", {}),
            ("invalid_key", {"Ocp-Apim-Subscription-Key": "invalid-fixture"}),
        ):
            response = client.get(base + "/models", headers=headers)
            record(name, response, response.status_code == 401)
        headers = {"Ocp-Apim-Subscription-Key": key}
        response = client.get(base + "/models", headers=headers)
        payload = response.json()
        entries = payload.get("data", []) if isinstance(payload, dict) else []
        record(
            "approved_aliases",
            response,
            response.status_code == 200 and {m.get("id") for m in entries} == enabled.keys(),
        )
        for origin in origins:
            response = client.options(
                base + "/chat/completions",
                headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "content-type,ocp-apim-subscription-key",
                },
            )
            allowed_headers = response.headers.get("access-control-allow-headers", "").lower()
            record(
                "preflight:" + origin,
                response,
                response.is_success
                and response.headers.get("access-control-allow-origin") == origin
                and "content-type" in allowed_headers
                and "ocp-apim-subscription-key" in allowed_headers
                and "access-control-allow-credentials" not in response.headers,
            )
            response = client.get(base + "/models", headers={**headers, "Origin": origin})
            record(
                "actual_cors:" + origin,
                response,
                response.status_code == 200 and response.headers.get("access-control-allow-origin") == origin,
            )
        response = client.options(
            base + "/chat/completions",
            headers={
                "Origin": "https://untrusted.invalid",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,ocp-apim-subscription-key",
            },
        )
        record("untrusted_origin", response, "access-control-allow-origin" not in response.headers)
        request = {
            "model": "gpt-5.6-luna",
            "messages": [{"role": "user", "content": "Reply OK."}],
            "max_completion_tokens": 64,
            "stream": False,
        }
        for name, extra in (
            ("stream_rejected", {"stream": True}),
            ("tools_rejected", {"tools": []}),
            ("unknown_model", {"model": "not-deployed"}),
        ):
            response = client.post(base + "/chat/completions", headers=headers, json={**request, **extra})
            record(name, response, response.status_code == 400)
        response = client.post(base + "/chat/completions", headers=headers, content="{")
        record("malformed_json", response, response.status_code in (400, 415))
        if smoke:
            for alias in sorted(enabled.keys() | candidates):
                limit = min(
                    4096,
                    int(enabled.get(alias, placeholders.get(alias, {})).get("max_completion_tokens", 64)),
                )
                response = client.post(
                    base + "/chat/completions",
                    headers=headers,
                    json={**request, "model": alias, "max_completion_tokens": limit},
                )
                try:
                    payload = response.json()
                except ValueError:
                    payload = None
                record(
                    "completion:" + alias,
                    response,
                    response.status_code == 200 and is_completion(payload, max_completion_tokens=limit),
                )
                if isinstance(payload, dict) and is_completion(payload, max_completion_tokens=limit):
                    results[-1]["usage"] = {
                        k: payload["usage"][k] for k in ("prompt_tokens", "completion_tokens", "total_tokens")
                    }
    return {
        "checked_at": datetime.now(UTC).isoformat(),
        "base_url": base,
        "passed": all(item["passed"] for item in results),
        "checks": results,
        "accepted_aliases": sorted(enabled.keys()),
        "candidate_aliases_smoked": sorted(candidates),
        "gateway_ready": bool(candidates)
        and all(
            item["passed"]
            for item in results
            if item["name"].startswith("completion:") and item["name"].split(":", 1)[1] in candidates
        ),
        "unverified": [
            "signed-in browser journey",
            "regional failover",
            "live FinOps",
            "native unified translation",
            "streaming",
            "tools",
            "structured output",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subscription", required=True)
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--apim", required=True)
    parser.add_argument("--test-subscription", required=True)
    parser.add_argument("--portal-origin", action="append", required=True)
    parser.add_argument("--smoke", action="store_true", help="Make bounded paid synthetic model calls")
    parser.add_argument(
        "--candidate-alias",
        action="append",
        default=[],
        help="Temporarily routed but hidden alias to direct-smoke through the guarded adapter.",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    resource = (
        f"/subscriptions/{args.subscription}/resourceGroups/{args.resource_group}"
        f"/providers/Microsoft.ApiManagement/service/{args.apim}"
    )
    token = AzureCliCredential().get_token("https://management.azure.com/.default").token
    with httpx.Client(headers={"Authorization": "Bearer " + token}, timeout=60) as client:
        url = "https://management.azure.com" + resource + "/subscriptions/" + args.test_subscription
        response = client.get(url, params={"api-version": "2024-05-01"})
        response.raise_for_status()
        properties = response.json()["properties"]
        expected_scope = resource + "/products/aiflux-dev-unified"
        if properties["state"] != "active" or properties["scope"] != expected_scope:
            raise ValueError("An active approved adapter-product test subscription is required")
        response = client.post(url + "/listSecrets", params={"api-version": "2024-05-01"})
        response.raise_for_status()
        key = response.json()["primaryKey"]
    report = verify(
        f"https://{args.apim}.azure-api.net/dev/llm/v1",
        key,
        args.portal_origin,
        smoke=args.smoke,
        candidate_aliases=args.candidate_alias,
    )
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
