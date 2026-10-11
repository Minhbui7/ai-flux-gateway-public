import unittest
import json
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
POLICIES = ROOT / "gateway" / "policies"


class GuardedDevelopmentPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dev_policy = ET.parse(POLICIES / "dev-openai.xml.tftpl").getroot()
        cls.global_gate = ET.parse(POLICIES / "global-dev-gate.xml.tftpl").getroot()
        cls.dev_source = (POLICIES / "dev-openai.xml.tftpl").read_text(encoding="utf-8")
        cls.openapi = json.loads((ROOT / "gateway" / "openapi-dev.json").read_text(encoding="utf-8"))
        cls.apim_source = (ROOT / "infra" / "terraform" / "apim.tf").read_text(encoding="utf-8")
        cls.variables_source = (ROOT / "infra" / "terraform" / "variables.tf").read_text(encoding="utf-8")

    def test_policy_is_subscription_product_scoped(self):
        inbound = self.dev_policy.find("inbound")
        self.assertEqual(inbound[0].tag, "base")
        policy = ET.tostring(inbound, encoding="unicode")
        self.assertIn("context.Product.Id", policy)
        self.assertIn("aiflux-dev-openai", policy)
        self.assertIn('subscription_required = true', self.apim_source)
        self.assertIn('header = "Ocp-Apim-Subscription-Key"', self.apim_source)
        self.assertIn('query  = "subscription-key"', self.apim_source)
        self.assertIn('subscriptions_limit   = 1', self.apim_source)
        self.assertIn('published             = true', self.apim_source)

    def test_only_bounded_plain_text_chat_is_accepted(self):
        conditions = " ".join(node.get("condition", "") for node in self.dev_policy.findall(".//when"))
        self.assertIn('p.Name == "model"', conditions)
        self.assertIn('item["content"].Type != JTokenType.String', conditions)
        self.assertIn("totalCharacters > 8000", conditions)
        self.assertIn('max-size="16384"', self.dev_source)
        self.assertIn('set-variable name="aiflux-request-json"', self.dev_source)
        self.assertNotIn('set-variable name="aiflux-request" value="@(context.Request.Body.As&lt;JObject&gt;', self.dev_source)
        self.assertIn("context.Request.Url.Query.Keys.Any", conditions)
        self.assertIn('set-query-parameter name="subscription-key" exists-action="delete"', self.dev_source)
        for unsupported in ("tools", "images", "structured output"):
            self.assertIn(unsupported, self.dev_source.lower())
        self.assertIn("streaming", self.dev_source.lower())
        self.assertNotIn('"stream"', self.openapi["paths"]["/chat/completions"]["post"]["requestBody"]["content"]["application/json"]["schema"]["properties"])
        self.assertNotIn("text/event-stream", self.openapi["paths"]["/chat/completions"]["post"]["responses"]["200"]["content"])

    def test_openapi_import_is_bounded_and_default_backend_is_non_routable(self):
        self.assertEqual(set(self.openapi["paths"]), {"/models", "/chat/completions"})
        self.assertEqual(self.openapi["servers"][0]["url"], "https://aiflux-disabled.invalid")
        body = self.openapi["paths"]["/chat/completions"]["post"]["requestBody"]["content"]["application/json"]["schema"]
        self.assertFalse(body["additionalProperties"])
        self.assertEqual(set(body["required"]), {"model", "messages", "max_completion_tokens"})
        self.assertIn('content_format = "openapi+json"', self.apim_source)
        self.assertIn('service_url           = "https://aiflux-disabled.invalid"', self.apim_source)
        backend = self.dev_policy.find("./backend")
        self.assertEqual([child.tag for child in backend], ["forward-request"])
        self.assertEqual(backend.find("forward-request").get("timeout"), "90")

    def test_original_redacted_and_completion_safety_are_present(self):
        safety_policies = self.dev_policy.findall(".//llm-content-safety")
        self.assertEqual(len(safety_policies), 3)
        self.assertTrue(all(policy.get("backend-id") == "${safety_backend_id}" for policy in safety_policies))
        self.assertTrue(all(category.get("threshold") == "${safety_threshold}"
                            for policy in safety_policies
                            for category in policy.findall("./categories/category")))
        self.assertIn("dev_openai_content_safety_threshold != null", self.apim_source)
        self.assertIn("default     = null", self.variables_source)
        self.assertNotIn('threshold="4"', self.dev_source)
        self.assertIn('"Microsoft.ApiManagement/service/backends@2024-06-01-preview"', self.apim_source)
        self.assertIn('managedIdentity = {', self.apim_source)
        self.assertIn('resource = "https://cognitiveservices.azure.com"', self.apim_source)
        self.assertIn('clientId = azurerm_user_assigned_identity.identity["gateway"].client_id', self.apim_source)
        self.assertNotIn("X-Aiflux-Debug-", self.dev_source)

    def test_pii_and_model_auth_are_fail_closed_and_keys_are_not_forwarded(self):
        send_request = self.dev_policy.find(".//send-request")
        self.assertIsNotNone(send_request)
        self.assertEqual(send_request.get("ignore-error"), "false")
        self.assertEqual(send_request.find("authentication-managed-identity").get("ignore-error"), "false")
        deleted = {header.get("name") for header in self.dev_policy.findall(".//set-header[@exists-action='delete']")}
        self.assertTrue({"Authorization", "api-key", "Ocp-Apim-Subscription-Key"} <= deleted)
        self.assertIn("https://cognitiveservices.azure.com/", self.dev_source)

    def test_non_dev_apis_remain_globally_denied(self):
        gate = self.global_gate.find("./inbound/choose/when")
        self.assertIsNotNone(gate)
        self.assertIn('context.Request.OriginalUrl.Path != "/dev/v1/models"', gate.get("condition"))
        self.assertIn('context.Request.OriginalUrl.Path != "/dev/v1/chat/completions"', gate.get("condition"))
        self.assertIn("${enabled} == false", gate.get("condition"))
        self.assertEqual(self.global_gate.findall(".//base"), [])
        self.assertIn("set-status", [node.tag for node in gate.iter()])
        self.assertIn("depends_on = [azapi_resource.dev_openai_policy]", self.apim_source)
        self.assertIn('format = "rawxml"', self.apim_source)

    def test_prompt_and_completion_body_logging_is_not_enabled(self):
        self.assertNotIn("GatewayLlmLogs", self.apim_source)
        self.assertNotIn("largeLanguageModel =", self.apim_source)
        self.assertIn('category = "GatewayLogs"', self.apim_source)


if __name__ == "__main__":
    unittest.main()
