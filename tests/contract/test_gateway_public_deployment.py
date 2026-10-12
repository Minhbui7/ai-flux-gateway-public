import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class PublicDeploymentContractTests(unittest.TestCase):
    def test_hybrid_root_has_no_operator_compute_or_private_state(self):
        root = ROOT / "infra" / "terraform"
        source = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.tf"))
        resource_types = set(re.findall(r'resource\s+"([^"]+)"', source))
        self.assertTrue(resource_types.isdisjoint({
            "azurerm_linux_virtual_machine", "azurerm_network_interface",
            "azurerm_nat_gateway", "azurerm_nat_gateway_public_ip_association",
            "azurerm_subnet_nat_gateway_association",
        }))
        self.assertNotIn("operator_network", source)
        self.assertNotIn("terraform_remote_state", source)
        self.assertIn('backend "local"', source)
        self.assertNotIn('backend "azurerm"', source)
        self.assertNotIn("apim_private_access", source)
        self.assertIn('variable "hybrid_private_data_enabled"', source)
        private_data = (root / "private-data.tf").read_text(encoding="utf-8")
        self.assertNotIn("azurerm_api_management", private_data)
        self.assertNotIn("azapi_resource.ai", private_data)
        self.assertIn('group = "sqlServer"', private_data)

    def test_public_origin_acceptance_is_not_private_network_evidence(self):
        manifest = json.loads((ROOT / "gateway" / "capabilities.json").read_text(encoding="utf-8"))
        scenarios = json.loads(
            (ROOT / "gateway" / "validation" / "scenarios.json").read_text(encoding="utf-8")
        )
        self.assertEqual(set(manifest["gates"]), set(scenarios["gates"]))
        self.assertNotIn("private_edge", manifest["gates"])
        self.assertEqual(manifest["gates"]["public_edge_origin"], "unverified")
        cases = " ".join(scenarios["gates"]["public_edge_origin"])
        self.assertIn("native APIM origin control", cases)
        self.assertIn("direct public bypass denial", cases)
        self.assertIn("never 0.0.0.0", cases)
        self.assertIn("no shared keys or anonymous", cases)
        self.assertFalse(manifest["inference_enabled"])
        self.assertFalse(manifest["product_published"])

    def test_deployment_ci_is_disabled_not_private_runner_dependent(self):
        workflow = (ROOT / ".github" / "workflows" / "deploy-control-plane.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("if: ${{ false }}", workflow)
        self.assertIn("runs-on: ubuntu-latest", workflow)
        self.assertNotIn("self-hosted", workflow)
        self.assertNotIn("id-token: write", workflow)
        self.assertIn("docs/infrastructure.md", workflow)

    def test_remote_build_context_excludes_deployment_credentials(self):
        exclusions = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        for pattern in ("infra", ".deployment", "**/*.tfplan", "**/*.tfvars", "**/*.tfstate*"):
            self.assertIn(pattern, exclusions)

    def test_approved_dev_entra_bootstrap_does_not_create_secrets(self):
        source = (ROOT / "infra" / "scripts" / "bootstrap-entra.py").read_text(encoding="utf-8")
        self.assertIn("AzureADMyOrg", source)
        self.assertNotIn("AzureADMultipleOrgs", source)
        self.assertNotIn("addPassword", source)
        self.assertNotIn("oauth2PermissionGrants", source)
        self.assertIn("displayName eq", source)
        self.assertIn("Ambiguous exact-name registration", source)
        self.assertIn('"requestedAccessTokenVersion": 2', source)


if __name__ == "__main__":
    unittest.main()
