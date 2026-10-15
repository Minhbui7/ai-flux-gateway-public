"""Enable only aliases with both direct-backend and guarded-adapter smoke evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = Path(__file__).with_name("model-spec.json")
EVIDENCE_PATH = Path(__file__).with_name("model-backends.json")
CATALOG_PATH = ROOT / "gateway" / "catalog" / "dev-models.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--direct-evidence", type=Path, default=EVIDENCE_PATH)
    parser.add_argument("--gateway-evidence", type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--render-disabled",
        action="store_true",
        help="Restore all eight requested aliases to hidden, non-callable placeholders.",
    )
    mode.add_argument(
        "--accept", action="append", help="Exact alias that passed direct and guarded adapter smoke checks."
    )
    args = parser.parse_args()

    spec_document = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    specs = {item["id"]: item for item in spec_document["models"]}
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    models = {item["id"]: item for item in catalog["models"]}
    if args.render_disabled:
        requested = {
            alias for alias, spec in specs.items() if spec.get("acceptance_required") is True
        }
        for alias in requested:
            model = models[alias]
            model.update(
                {
                    "backend_model": alias,
                    "capabilities": [],
                    "enabled": False,
                    "placeholder": True,
                    "max_completion_tokens": specs[alias]["max_completion_tokens"],
                    "model_version": specs[alias]["version"],
                    "api_format": specs[alias]["wire_api"],
                    "backends": [],
                }
            )
    else:
        direct = json.loads(args.direct_evidence.read_text(encoding="utf-8"))
        requested = set(args.accept or [])
        require(args.gateway_evidence is not None, "--gateway-evidence is required with --accept.")
        gateway = json.loads(args.gateway_evidence.read_text(encoding="utf-8"))
        require(len(requested) == len(args.accept), "Accepted aliases must be unique.")
        require(requested and requested <= models.keys(), "Each accepted alias must exist in the catalog.")
        require(
            all(specs[alias].get("acceptance_required") is True for alias in requested),
            "Only aliases explicitly gated for acceptance may be enabled.",
        )
        require(
            all(
                models[alias].get("placeholder") is True and models[alias].get("enabled") is False
                for alias in requested
            ),
            "Only currently disabled placeholders can be accepted.",
        )
        require(
            direct.get("acceptance") == "direct_backend_only",
            "Direct evidence has an unexpected acceptance scope.",
        )
        quota_checks = {
            item.get("model"): item for item in direct.get("quota_preflight", []) if isinstance(item, dict)
        }
        require(
            gateway.get("passed") is True and gateway.get("gateway_ready") is True,
            "The guarded adapter report must pass its complete check set and candidate smoke.",
        )
        require(
            requested <= set(gateway.get("candidate_aliases_smoked", [])),
            "Every accepted alias must have an explicit candidate smoke in the gateway report.",
        )
        gateway_checks = {
            item.get("name"): item for item in gateway.get("checks", []) if isinstance(item, dict)
        }

        for alias in sorted(requested):
            spec = specs[alias]
            require(
                quota_checks.get(alias, {}).get("passed") is True,
                f"{alias} did not pass the cross-region shared-quota preflight.",
            )
            regions = spec.get("regions", spec_document["regions"])
            collection = (
                direct["anthropic_backends"] if spec["arm_format"] == "Anthropic" else direct["backends"]
            )
            evidence = [
                item
                for item in collection
                if item.get("alias", item.get("model")) == alias and item.get("region") in regions
            ]
            require(
                len(evidence) == len(regions),
                f"{alias} is missing one or more expected regional deployments.",
            )
            for item in evidence:
                smoke = item.get("operator_smoke", {})
                require(
                    item.get("ready") is True
                    and smoke.get("http_status") == 200
                    and smoke.get("passed") is True
                    and item.get("auth", {}).get("gateway_role_assigned") is True,
                    f"{alias}/{item.get('region')} lacks successful direct inference "
                    "and gateway role evidence.",
                )
                require(
                    item.get("capacity") == spec["capacity"]
                    and item.get("model_version", item.get("version")) == spec["version"],
                    f"{alias}/{item.get('region')} does not match the "
                    "approved capacity/version.",
                )
            require(
                gateway_checks.get(f"completion:{alias}", {}).get("passed") is True,
                f"{alias} lacks a successful guarded adapter completion check.",
            )
            model = models[alias]
            model.update(
                {
                    "backend_model": alias,
                    "capabilities": ["chat"],
                    "enabled": True,
                    "placeholder": False,
                    "max_completion_tokens": spec["max_completion_tokens"],
                    "model_version": spec["version"],
                    "api_format": spec["wire_api"],
                    "backends": [],
                }
            )
            wire_format = {
                "azure-openai-v1": "openai-chat-completions",
                "foundry-model-inference": "foundry-openai-compatible",
                "anthropic-messages": "anthropic-messages",
            }[spec["wire_api"]]
            for item in evidence:
                endpoint = item["endpoint"].rstrip("/")
                if spec["wire_api"] == "azure-openai-v1":
                    endpoint += "/openai/v1"
                elif spec["wire_api"] == "anthropic-messages":
                    endpoint += "/anthropic/v1"
                model["backends"].append(
                    {
                        "id": f"dev-{alias.lower().replace('.', '-')}-{item['region']}",
                        "region": item["region"],
                        "url": endpoint,
                        "api_format": wire_format,
                        "priority": 1,
                        "weight": 1,
                        "model": alias,
                        "provider": spec["arm_format"],
                        "auth": {"managed_identity_resource": spec["auth_audience"]},
                    }
                )

    CATALOG_PATH.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "catalog": str(CATALOG_PATH),
                "rendered_mode": "disabled" if args.render_disabled else "accepted",
                "accepted_aliases": sorted(requested),
                "enabled_aliases": sorted(item["id"] for item in catalog["models"] if item["enabled"]),
                "prices": "unchanged; no price was invented",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
