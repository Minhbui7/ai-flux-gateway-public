import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("verify_dev", ROOT / "gateway" / "tools" / "verify_dev.py")
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)
ERROR = {"error": {"message": "Rejected.", "type": "invalid_request_error", "code": "fixture"}}


def fixture_response(url, **kwargs):
    if "/v1/models" in url and "/dev/" not in url:
        return 503, ERROR
    if kwargs.get("key") and kwargs.get("bearer"):
        return 400, ERROR
    if (kwargs.get("key") or kwargs.get("bearer")) in (None, "invalid-acceptance-fixture"):
        return 401, ERROR
    if url.endswith("/models"):
        return 200, {"data": [{"id": "gpt-5.6-luna"}, {"id": "gpt-5.6-sol"}]}
    if kwargs.get("content_type") == "text/plain":
        return 415, ERROR
    body = kwargs.get("body", {})
    if body.get("max_completion_tokens") == 64:
        return 200, {
            "choices": [{"message": {"content": "synthetic-completion-marker"}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16},
        }
    return 400, ERROR


def test_live_report_contains_only_metadata_and_discloses_unverified_scope():
    with patch.object(verifier, "request", side_effect=fixture_response):
        report = verifier.checks("https://example.azure-api.net/dev/v1", "synthetic-secret", smoke=True)
    assert report["passed"]
    assert len(report["checks"]) == 21
    assert "synthetic-secret" not in json.dumps(report)
    assert "synthetic-completion-marker" not in json.dumps(report)
    assert "pii_provider_capture" in report["not_verified"]


def test_failure_cannot_be_reported_as_success():
    with patch.object(verifier, "request", return_value=(503, {})):
        report = verifier.checks("https://example.azure-api.net/dev/v1", "synthetic-secret")
    assert not report["passed"]


def test_missing_usage_fails_completion_acceptance():
    def response(url, **kwargs):
        if kwargs.get("body", {}).get("max_completion_tokens") == 64:
            return 200, {"choices": []}
        return fixture_response(url, **kwargs)

    with patch.object(verifier, "request", side_effect=response):
        report = verifier.checks("https://example.azure-api.net/dev/v1", "synthetic-secret", smoke=True)
    assert not report["passed"]


def test_unsupported_native_bearer_is_an_explicit_failed_probe():
    def response(url, **kwargs):
        if kwargs.get("bearer") and not kwargs.get("key"):
            return 401, ERROR
        return fixture_response(url, **kwargs)

    with patch.object(verifier, "request", side_effect=response):
        report = verifier.checks(
            "https://example.azure-api.net/dev/v1", "synthetic-secret", probe_bearer=True
        )
    assert not report["passed"]
    assert "subscription_bearer" in report["not_verified"]


def test_bounded_rate_check_records_observed_overshoot():
    calls = 0

    def response(url, **kwargs):
        nonlocal calls
        body = kwargs.get("body", {})
        if body.get("max_completion_tokens") == 64:
            if body["model"] == "gpt-5.6-luna":
                calls += 1
                return (429 if calls > 3 else 200), ERROR if calls > 3 else {}
            if body["messages"][0]["content"].startswith("Ignore"):
                return 403, ERROR
            return 200, {}
        return fixture_response(url, **kwargs)

    with patch.object(verifier.time, "sleep"), patch.object(verifier, "request", side_effect=response):
        report = verifier.checks("https://example.azure-api.net/dev/v1", "synthetic-secret", limits=True)
    assert report["passed"]
    rate = next(item for item in report["checks"] if item["name"] == "rpm_bounded_burst")
    assert rate["allowed_before_first_block"] == 3
    assert rate["observed_overshoot"] == 1


def test_unenforced_rate_limit_fails_after_bounded_requests():
    with (
        patch.object(verifier.time, "sleep"),
        patch.object(verifier, "request", side_effect=fixture_response),
    ):
        report = verifier.checks("https://example.azure-api.net/dev/v1", "synthetic-secret", limits=True)
    rate = next(item for item in report["checks"] if item["name"] == "rpm_bounded_burst")
    assert not report["passed"]
    assert not rate["passed"]
    assert rate["allowed_before_first_block"] == 8


def test_network_failure_is_explicit_not_success_shaped():
    with patch.object(
        verifier.urllib.request,
        "urlopen",
        side_effect=verifier.urllib.error.URLError("synthetic network failure"),
    ):
        status, response = verifier.request("https://example.azure-api.net/dev/v1/models")
    assert status == 0
    assert response["error"]["code"] == "network_or_timeout"


def test_non_openai_error_shape_fails_acceptance():
    with patch.object(verifier, "request", return_value=(401, {"message": "Rejected"})):
        report = verifier.checks("https://example.azure-api.net/dev/v1", "synthetic-secret")
    assert not report["passed"]
    assert not report["checks"][0]["passed"]


def test_missing_production_route_is_not_disabled_policy_proof():
    def response(url, **kwargs):
        if "/v1/models" in url and "/dev/" not in url:
            return 404, ERROR
        return fixture_response(url, **kwargs)

    with patch.object(verifier, "request", side_effect=response):
        report = verifier.checks("https://example.azure-api.net/dev/v1", "synthetic-secret")
    assert not report["passed"]
    assert not next(item for item in report["checks"] if item["name"] == "production_denied")["passed"]


def test_malformed_completion_fails_without_crashing_report():
    def response(url, **kwargs):
        if kwargs.get("body", {}).get("max_completion_tokens") == 64:
            return 200, {"choices": [None], "usage": None}
        return fixture_response(url, **kwargs)

    with patch.object(verifier, "request", side_effect=response):
        report = verifier.checks("https://example.azure-api.net/dev/v1", "synthetic-secret", smoke=True)
    assert not report["passed"]


def test_inconsistent_or_excess_token_usage_fails_acceptance():
    def response(url, **kwargs):
        status, result = fixture_response(url, **kwargs)
        if kwargs.get("body", {}).get("max_completion_tokens") == 64:
            result["usage"] = {"prompt_tokens": 9, "completion_tokens": 65, "total_tokens": 13}
        return status, result

    with patch.object(verifier, "request", side_effect=response):
        report = verifier.checks("https://example.azure-api.net/dev/v1", "synthetic-secret", smoke=True)
    assert not report["passed"]
