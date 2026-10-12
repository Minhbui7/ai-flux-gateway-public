"""Bounded blocked-posture smoke probe. Never reports full release acceptance."""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_base_url(value: str) -> str:
    url = urllib.parse.urlsplit(value)
    if (url.scheme != "https" or not url.hostname or url.username or url.password
            or url.query or url.fragment or url.path.rstrip("/") != "/v1"):
        raise ValueError("Supply an HTTPS public edge base URL ending /v1, with no credentials/query/fragment.")
    return value.rstrip("/")


def run_probe(base_url: str, key: str | None = None) -> dict:
    base_url = validate_base_url(base_url)
    opener = urllib.request.build_opener(
        NoRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    cases = [
        ("missing_key", "/models", "GET", {}, None, {401}),
        ("invalid_key", "/models", "GET", {"Ocp-Apim-Subscription-Key": "invalid-validation-key"}, None, {401}),
    ]
    if key:
        cases.extend([
            ("valid_native_header_models_blocked", "/models", "GET",
             {"Ocp-Apim-Subscription-Key": key}, None, {503}),
            ("valid_native_header_chat_blocked", "/chat/completions", "POST",
             {"Ocp-Apim-Subscription-Key": key},
             {"model": "validation-only-not-a-real-model", "messages": [{"role": "user", "content": "hello"}]},
             {503}),
        ])
    results = []
    for name, path, method, headers, body, expected in cases:
        req = urllib.request.Request(base_url + path, method=method, headers={
            "Content-Type": "application/json", **headers,
        }, data=None if body is None else json.dumps(body).encode())
        try:
            with opener.open(req, timeout=10) as response:
                status = response.status
                # Responses are deliberately not collected or printed.
        except urllib.error.HTTPError as error:
            status = error.code
            error.close()
        except (urllib.error.URLError, TimeoutError, OSError):
            results.append({"case": name, "passed": False, "status": None, "failure": "transport_error"})
            continue
        results.append({"case": name, "passed": status in expected, "status": status})
    return {
        "scope": "live_blocked_posture_only",
        "passed": all(result["passed"] for result in results),
        "full_native_acceptance": False,
        "cases": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output", type=Path, help="Metadata-only JSON path under gateway or infra.")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    if args.output:
        output = args.output.resolve()
        if not any(output.is_relative_to(root / scope) for scope in ("infra", "gateway")):
            parser.error("Output must be inside infra or gateway.")
    try:
        report = run_probe(args.base_url, os.environ.get("AIFLUX_VALIDATION_SUBSCRIPTION_KEY"))
    except ValueError as error:
        parser.error(str(error))
    text = json.dumps(report, indent=2)
    print(text)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
