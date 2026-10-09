"""Offline checks of the deliberately disabled gateway, not Azure capability proof."""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
GATES = frozenset({
    "native_iac", "subscription_bearer", "private_edge",
    "pii_structure_unicode", "pii_fail_closed", "original_redacted_safety",
    "prompt_shields", "response_safety", "sse_sliding_window",
    "tools_inspection", "json_schema_inspection", "model_region_access",
    "pool_retry_after", "subscription_model_limits", "metadata_correlation",
    "no_sensitive_logs",
})
CAPABILITIES = frozenset({"chat", "stream", "tools", "json_schema"})


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate_catalog(catalog: dict, manifest: dict) -> None:
    require(isinstance(catalog, dict) and isinstance(catalog.get("models"), list),
            "Catalog must contain a models array.")
    seen: set[str] = set()
    for model in catalog["models"]:
        require(isinstance(model, dict), "Model entries must be objects.")
        alias = model.get("id")
        require(isinstance(alias, str) and bool(re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}", alias)),
                "Invalid model alias.")
        require(alias not in seen, "Duplicate model alias.")
        seen.add(alias)
        for name in ("provider", "backend_model"):
            require(isinstance(model.get(name), str) and bool(model[name].strip()),
                    f"Model {name} must be supplied by the operator.")
        require(type(model.get("enabled")) is bool, "Model enabled must be boolean.")
        caps = model.get("capabilities")
        require(isinstance(caps, list) and all(isinstance(c, str) for c in caps)
                and len(caps) == len(set(caps)) and set(caps) <= CAPABILITIES,
                "Invalid/duplicate model capabilities.")
        require(not caps or "chat" in caps, "Chat capability is required for derived capabilities.")
        require(not model["enabled"], "This implementation cannot activate native models.")
        require(not manifest["inference_enabled"], "Inference must remain disabled.")
        backends = model.get("backends", [])
        require(isinstance(backends, list), "Backends must be an array.")
        backend_ids: set[str] = set()
        for backend in backends:
            require(isinstance(backend, dict), "Backends must be objects.")
            backend_id = backend.get("id")
            require(isinstance(backend_id, str) and bool(re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}", backend_id)),
                    "Invalid backend ID.")
            require(backend_id not in backend_ids, "Duplicate model backend ID.")
            backend_ids.add(backend_id)
            require(isinstance(backend.get("region"), str) and bool(backend["region"].strip()),
                    "Every endpoint needs an operator-supplied region.")
            endpoint = urlsplit(backend.get("url", ""))
            require(endpoint.scheme == "https" and bool(endpoint.hostname)
                    and not endpoint.username and not endpoint.password and not endpoint.query and not endpoint.fragment,
                    "Endpoint URL must use HTTPS without credentials/query/fragment.")
            require(backend.get("api_format") in ("openai-chat-completions", "anthropic-messages"),
                    "Unsupported endpoint API format.")
            for name in ("priority", "weight"):
                require(type(backend.get(name)) is int and 1 <= backend[name] <= 100,
                        "Backend priority/weight must be integers from 1 to 100.")
            auth = backend.get("auth")
            require(isinstance(auth, dict), "Backend authentication reference is required.")
            if set(auth) == {"managed_identity_resource"}:
                require(isinstance(auth["managed_identity_resource"], str) and bool(auth["managed_identity_resource"].strip()),
                        "Managed identity audience must be supplied.")
            else:
                require(set(auth) == {"key_vault_secret_id", "header"},
                        "Only managed identity or Key Vault references are allowed; never inline credentials.")
                secret = urlsplit(auth["key_vault_secret_id"])
                require(secret.scheme == "https" and bool(secret.hostname) and secret.hostname.endswith(".vault.azure.net")
                        and not secret.username and not secret.password and not secret.query and not secret.fragment
                        and secret.path.startswith("/secrets/") and len(secret.path.split("/")) >= 3,
                        "Invalid Key Vault secret reference.")
                require(isinstance(auth["header"], str) and bool(auth["header"].strip()), "Secret header name required.")
        if "limits" in model:
            limits = model["limits"]
            require(isinstance(limits, dict), "Limits must be an object.")
            for name in ("rpm", "tpm", "token_quota", "max_response_tokens"):
                require(type(limits.get(name)) is int and limits[name] > 0, "All limits must be explicit positive integers.")
            require(limits.get("quota_period") in ("Hourly", "Daily", "Weekly", "Monthly", "Yearly"),
                    "Quota period must match native documented policy values.")


def validate_disabled_bundle(root: Path = ROOT) -> dict:
    manifest = json.loads((root / "gateway" / "capabilities.json").read_text(encoding="utf-8"))
    catalog = json.loads((root / "gateway" / "catalog" / "models.json").read_text(encoding="utf-8"))
    require(manifest.get("schema_version") == 1, "Unsupported manifest version.")
    require(manifest.get("inference_enabled") is False and manifest.get("product_published") is False,
            "No native activation contract is implemented; inference/product must be disabled.")
    require(isinstance(manifest.get("gates"), dict) and set(manifest["gates"]) == GATES,
            "Missing/unknown native gates.")
    require(all(status in ("unverified", "blocked") for status in manifest["gates"].values()),
            "Local checks must not mark native gates passed.")
    require(manifest.get("native_artifact") is None and manifest.get("attestation") is None,
            "Reviewed native artifacts require a new reviewed implementation, not a JSON toggle.")
    validate_catalog(catalog, manifest)
    policy = ET.parse(root / "gateway" / "policies" / "disabled.xml").getroot()
    require(policy.tag == "policies", "Invalid policy root.")
    inbound = policy.find("inbound")
    require(inbound is not None and len(inbound) == 1 and inbound[0].tag == "return-response",
            "Inbound must unconditionally return before any inference.")
    for section in ("inbound", "on-error"):
        status = policy.find(f"./{section}/return-response/set-status")
        require(status is not None and status.attrib.get("code") == "503", "Disabled policy must return 503.")
        body = policy.find(f"./{section}/return-response/set-body")
        require(body is not None and json.loads(body.text or "")["error"]["type"] == "service_unavailable",
                "Disabled error must be OpenAI-shaped.")
    forbidden = {"forward-request", "send-request", "set-backend-service", "retry", "trace", "log-to-eventhub"}
    require(not any(element.tag in forbidden for element in policy.iter()), "Disabled policy must not forward or log payloads.")
    for section in ("backend", "outbound"):
        element = policy.find(section)
        require(element is not None and len(element) == 0, "Disabled backend/outbound must be empty.")
    return {
        "scope": "local_disabled_bundle",
        "local_valid": True,
        "inference_enabled": False,
        "live_validated": False,
        "unverified_gates": sorted(GATES),
        "model_count": len(catalog["models"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", action="store_true", help="Fail until a reviewed native implementation exists.")
    args = parser.parse_args()
    try:
        report = validate_disabled_bundle()
    except (ValueError, OSError, ET.ParseError, KeyError, TypeError):
        print("Disabled bundle validation failed; inspect catalog/manifest/policy locally.", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True))
    if args.release:
        print("RELEASE BLOCKED: reviewed reproducible native artifact and live capability attestation are absent.",
              file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
