import xml.etree.ElementTree as ET
from pathlib import Path

from aiflux.gateway_settings import render_fragment
from aiflux.schemas import GatewayConfiguration

ROOT = Path(__file__).resolve().parents[2]


def test_fragment_contains_only_typed_settings_and_native_limits():
    config = GatewayConfiguration(
        safety_threshold=0, rpm=1, tpm=2048, token_quota=10000, quota_period="Daily",
    )
    for scope in ("dev-openai", "dev-unified"):
        fragment = ET.fromstring(render_fragment(scope, config))
        assert [node.tag for node in fragment] == ["set-variable", "rate-limit-by-key", "llm-token-limit"]
        assert fragment.find("set-variable").get("name") == "aiflux-safety-threshold"
        limit = fragment.find("llm-token-limit")
        assert limit.get("id") == "aiflux-managed-token-limit"
        assert limit.get("estimate-prompt-tokens") == "true"
        assert limit.get("token-quota-period") == "Daily"
        assert scope in limit.get("counter-key")
        assert "version" not in limit.get("counter-key")


def test_runtime_owns_only_fragment_values_not_invariant_policy():
    terraform = (ROOT / "infra" / "terraform" / "gateway-settings.tf").read_text()
    assert "ignore_changes = [body.properties.value]" in terraform
    assert "scope              = azapi_resource.gateway_settings[each.key].id" in terraform
    assert '"Microsoft.ApiManagement/service/policyFragments/write"' in terraform
    assert "/policies/write" not in terraform
    assert "/backends/write" not in terraform
    assert "default     = false" in terraform
    bootstrap = ET.parse(ROOT / "gateway" / "policies" / "settings-unconfigured.xml")
    assert bootstrap.find("./return-response/set-status").get("code") == "503"


def test_managed_path_keeps_three_safety_passes_and_explicit_denials():
    policy = ET.parse(ROOT / "gateway" / "policies" / "dev-openai.xml.tftpl")
    assert len(policy.findall(".//llm-content-safety")) == 3
    assert len(policy.findall(".//include-fragment")) == 1
    for file in ("apim.tf", "dev-unified.tf"):
        source = (ROOT / "infra" / "terraform" / file).read_text()
        assert "aiflux-safety-threshold" in source
        assert "admin_settings_enabled       = var.dev_admin_settings_enabled" in source
    error_xml = ET.tostring(policy.find("on-error"), encoding="unicode")
    assert "token_quota_exceeded" in error_xml
    assert "content_safety_rejected" in error_xml
    assert "rate_limit_exceeded" in error_xml
    assert "gateway_unavailable" in error_xml


def test_request_scoped_threshold_remains_valid_xml_at_every_safety_pass():
    source = (ROOT / "gateway" / "policies" / "dev-openai.xml.tftpl").read_text()
    expression = "@((int)context.Variables[&quot;aiflux-safety-threshold&quot;])"
    policy = ET.fromstring(source.replace("${safety_threshold}", expression))
    categories = policy.findall(".//llm-content-safety/categories/category")
    assert len(categories) == 12
    assert all(
        category.get("threshold") == '@((int)context.Variables["aiflux-safety-threshold"])'
        for category in categories
    )
