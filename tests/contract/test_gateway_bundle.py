import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import patch
import urllib.error

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "gateway" / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bundle = load("validate_bundle")
probe = load("live_probe")


class GatewayContractTests(unittest.TestCase):
    def test_disabled_bundle(self):
        report = bundle.validate_disabled_bundle(ROOT)
        self.assertTrue(report["local_valid"])
        self.assertFalse(report["inference_enabled"])
        self.assertFalse(report["live_validated"])
        self.assertEqual(report["model_count"], 0)

    def test_catalog_denies_enabled_models(self):
        model = {"id": "synthetic-test", "provider": "synthetic", "backend_model": "synthetic",
                 "capabilities": ["chat"], "enabled": True}
        with self.assertRaisesRegex(ValueError, "cannot activate"):
            bundle.validate_catalog({"models": [model]}, {"inference_enabled": False})

    def test_catalog_denies_duplicate_aliases(self):
        model = {"id": "synthetic-test", "provider": "synthetic", "backend_model": "synthetic",
                 "capabilities": ["chat"], "enabled": False}
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            bundle.validate_catalog({"models": [model, model]}, {"inference_enabled": False})

    def test_catalog_denies_unknown_capabilities(self):
        model = {"id": "synthetic-test", "provider": "synthetic", "backend_model": "synthetic",
                 "capabilities": ["audio"], "enabled": False}
        with self.assertRaisesRegex(ValueError, "capabilities"):
            bundle.validate_catalog({"models": [model]}, {"inference_enabled": False})

    def test_schema_allows_no_fake_model_defaults(self):
        catalog = json.loads((ROOT / "gateway" / "catalog" / "models.json").read_text())
        self.assertEqual(catalog, {"models": []})
        schema = json.loads((ROOT / "gateway" / "catalog" / "catalog.schema.json").read_text())
        self.assertEqual(schema["required"], ["models"])
        self.assertNotIn("default", schema["properties"]["models"])

    def test_catalog_rejects_inline_backend_credentials(self):
        model = {"id": "synthetic-test", "provider": "synthetic", "backend_model": "synthetic",
                 "capabilities": ["chat"], "enabled": False,
                 "backends": [{"id": "synthetic-endpoint", "region": "synthetic-region",
                               "url": "https://endpoint.example.invalid", "api_format": "openai-chat-completions",
                               "priority": 1, "weight": 1, "auth": {"api_key": "not-a-real-key"}}]}
        with self.assertRaisesRegex(ValueError, "inline credentials"):
            bundle.validate_catalog({"models": [model]}, {"inference_enabled": False})

    def test_catalog_rejects_credential_endpoint_url(self):
        model = {"id": "synthetic-test", "provider": "synthetic", "backend_model": "synthetic",
                 "capabilities": ["chat"], "enabled": False,
                 "backends": [{"id": "synthetic-endpoint", "region": "synthetic-region",
                               "url": "https://key@endpoint.example.invalid", "api_format": "openai-chat-completions",
                               "priority": 1, "weight": 1, "auth": {"managed_identity_resource": "https://example.invalid"}}]}
        with self.assertRaisesRegex(ValueError, "without credentials"):
            bundle.validate_catalog({"models": [model]}, {"inference_enabled": False})

    def test_disabled_openapi_does_not_claim_inference_success(self):
        contract = json.loads((ROOT / "gateway" / "openapi.json").read_text())
        self.assertEqual(set(contract["paths"]), {"/models", "/chat/completions"})
        for path in contract["paths"].values():
            for operation in path.values():
                self.assertFalse(any(status.startswith("2") for status in operation["responses"]))

    def test_live_probe_rejects_untrusted_url_shapes(self):
        for url in ("http://example.invalid/v1", "https://key@example.invalid/v1",
                    "https://example.invalid/v1?key=secret", "https://example.invalid/v1#key",
                    "https://example.invalid", "https://example.invalid/api"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                probe.validate_base_url(url)

    def test_live_probe_no_secret_or_response_logging(self):
        class Opener:
            def open(self, request, timeout):
                code = 503 if request.get_header("Ocp-apim-subscription-key") == "sensitive-test-key" else 401
                raise urllib.error.HTTPError(request.full_url, code, "secret-response-not-logged", {}, None)

        with patch.object(probe.urllib.request, "build_opener", return_value=Opener()):
            report = probe.run_probe("https://example.invalid/v1", "sensitive-test-key")
        self.assertTrue(report["passed"])
        self.assertFalse(report["full_native_acceptance"])
        self.assertEqual(len(report["cases"]), 4)
        self.assertNotIn("sensitive-test-key", json.dumps(report))
        self.assertNotIn("secret-response", json.dumps(report))

    def test_native_telemetry_gaps_not_zero(self):
        manifest = json.loads((ROOT / "gateway" / "capabilities.json").read_text())
        for field in ("cached_read_tokens", "cache_write_tokens", "ttft_ms"):
            self.assertEqual(manifest["telemetry"][field], "unsupported_native_log")

    def test_acceptance_checklist_covers_all_manifest_gates(self):
        scenarios = json.loads((ROOT / "gateway" / "validation" / "scenarios.json").read_text())
        self.assertEqual(scenarios["status"], "not_run")
        self.assertEqual(set(scenarios["gates"]), bundle.GATES)


if __name__ == "__main__":
    unittest.main()
