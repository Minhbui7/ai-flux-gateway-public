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
        assert "gateway_legacy_threshold" in source
        assert "admin_settings_enabled       = var.dev_admin_settings_enabled" in source
    error_xml = ET.tostring(policy.find("on-error"), encoding="unicode")
    assert "token_quota_exceeded" in error_xml
    assert "content_safety_rejected" in error_xml
    assert "rate_limit_exceeded" in error_xml
    assert "gateway_unavailable" in error_xml


def test_request_scoped_threshold_remains_valid_xml_at_every_safety_pass():
    source = (ROOT / "gateway" / "policies" / "dev-openai.xml.tftpl").read_text()
    expression = "@((int)context.Variables[&quot;aiflux-safety-threshold&quot;])"
    for name in ("hate", "selfharm", "sexual", "violence"):
        source = source.replace("${%s_threshold}" % name, expression)
    policy = ET.fromstring(source)
    categories = policy.findall(".//llm-content-safety/categories/category")
    assert len(categories) == 12
    assert all(
        category.get("threshold") == '@((int)context.Variables["aiflux-safety-threshold"])'
        for category in categories
    )


def test_managed_v2_templates_have_literal_non_nested_fragments_and_tiers():
    policies = ROOT / "gateway" / "policies"
    forward = ET.parse(policies / "forward-fragment.xml.tftpl")
    assert not forward.findall(".//include-fragment")
    tree = (policies / "concurrency-tree.xml.tftpl").read_text()
    assert "for team in [16, 8, 4, 2, 1, 0]" in tree and "for sub in [16, 8, 4, 2]" in tree
    assert 'max-count="1"' in tree
    assert 'fragment-id="${fragment_id}"' in tree
    assert tree.count("<limit-concurrency") == tree.count("</limit-concurrency>") == 3
    assert "aiflux-conc:team:" in tree and "aiflux-conc:sub:" in tree
    assert "aiflux-model" not in tree and "context.Api" not in tree and "Operation" not in tree
    dev = (policies / "dev-openai.xml.tftpl").read_text()
    assert "aiflux-protected-material" in dev and "${protected_material_url}" in dev
    assert "aiflux-safety-threshold" not in dev


def test_protected_material_scans_all_choices_and_fails_closed():
    policy = ET.parse(ROOT / "gateway" / "policies" / "dev-openai.xml.tftpl")
    generator = policy.find(".//set-variable[@name='aiflux-protected-chunks']").get("value")
    assert 'foreach (var choice in choices)' in generator
    assert 'choice as JObject' in generator
    assert 'message["content"].Type != JTokenType.String' in generator
    assert '"tool_calls", "function_call", "audio"' in generator
    assert 'text.Length > 36000' in generator
    assert 'catch { return ""; }' in generator
    assert 'Char.IsHighSurrogate' in generator and 'Char.IsLowSurrogate' in generator
    assert 'offsets.Add(i + 1)' in generator
    assert 'start += 8800' in generator and 'start + 9000' in generator
    assert 'text.Substring(offsets[start], offsets[end] - offsets[start])' in generator
    assert 'chunks.Count > 5' in generator
    source = (ROOT / "gateway" / "policies" / "dev-openai.xml.tftpl").read_text()
    assert 'for chunk in range(5)' in source
    assert '["text"] = (string)chunks[${chunk}]' in source
    state = policy.find(".//set-variable[@name='aiflux-protected-state']").get("value")
    assert '== "" ? "error" : "clear"' in state
    # The request allowlist excludes n, but a backend returning multiple choices is still fully scanned.
    assert 'p.Name == "n"' not in source


def test_protected_chunk_reference_covers_unicode_with_200_scalar_overlap():
    def chunks(text):
        # Mirror the policy offsets over UTF-16, including explicit malformed-surrogate rejection.
        raw = text.encode("utf-16-le", errors="surrogatepass")
        units = [int.from_bytes(raw[i:i + 2], "little") for i in range(0, len(raw), 2)]
        if len(units) > 36000:
            raise ValueError("cap")
        offsets, i = [0], 0
        while i < len(units):
            if 0xD800 <= units[i] <= 0xDBFF:
                if i + 1 >= len(units) or not 0xDC00 <= units[i + 1] <= 0xDFFF:
                    raise ValueError("surrogate")
                i += 1
            elif 0xDC00 <= units[i] <= 0xDFFF:
                raise ValueError("surrogate")
            i += 1
            offsets.append(i)
        result = []
        for start in range(0, len(offsets) - 1, 8800):
            end = min(start + 9000, len(offsets) - 1)
            result.append(raw[2 * offsets[start]:2 * offsets[end]].decode("utf-16-le"))
            if end == len(offsets) - 1:
                break
        assert len(result) <= 5
        return result

    for text in ("a" * 36000, "😀" * 18000, "a" * 8799 + "😀" + "b" * 17999,
                 "a" * 8999 + "😀" + "b" * 17999, "", "last choice\n" + "😀" * 12000):
        scans = chunks(text)
        assert all(len(scan) <= 9000 < 10000 for scan in scans)
        assert all(left[-200:] == right[:200] for left, right in zip(scans, scans[1:]))
        rebuilt = "".join([scans[0]] + [scan[200:] for scan in scans[1:]]) if scans else ""
        assert rebuilt == text
    import pytest
    for text in ("a" * 36001, "\ud800", "\udc00", "ok\ud800bad"):
        with pytest.raises(ValueError):
            chunks(text)


def test_managed_native_keys_errors_and_environment_contract():
    tree = (ROOT / "gateway" / "policies" / "concurrency-tree.xml.tftpl").read_text()
    for line in tree.splitlines():
        if '<limit-concurrency key=' in line:
            assert '"aiflux-organization-id"' in line and '"aiflux-team-id"' in line
            assert ('context.Subscription.Id' in line) == ('aiflux-conc:sub:' in line)
    policy = ET.parse(ROOT / "gateway" / "policies" / "dev-openai.xml.tftpl")
    errors = ET.tostring(policy.find("on-error"), encoding="unicode")
    for native in ("QuotaExceeded", "TokenLimitExceeded", "TokenQuotaExceeded",
                   "llm-token-limit", "quota-by-key", "StatusCode == 403", "StatusCode == 429"):
        assert native in errors
    quota = next(node for node in policy.findall("./on-error/choose/when")
                 if 'quota-by-key' in node.get("condition", ""))
    retry = quota.find(".//set-header[@name='Retry-After']/value").text
    assert 'GetValueOrDefault<int>("aiflux-request-quota-retry-after", 60)' in retry
    assert 'Math.Max(1,' in retry and 'context.Response.Headers' not in retry
    apps = (ROOT / "infra" / "terraform" / "apps.tf").read_text()
    for field in ("gateway_controls_v2_enabled", "gateway_protected_material_available",
                  "gateway_monthly_request_quota_available", "gateway_safety_relaxation_allowed",
                  "gateway_max_rpm", "gateway_enforcement_enabled"):
        assert "AIFLUX_" + field.upper() in apps
    assert 'AIFLUX_GATEWAY_INITIAL_SAFETY_THRESHOLD' in apps
    assert 'tostring(coalesce(var.dev_openai_content_safety_threshold, 1))' in apps


def test_invariant_safety_floor_overrides_stale_runtime_opt_outs():
    source = (ROOT / "gateway" / "policies" / "dev-openai.xml.tftpl").read_text()
    assert source.count('@(!${safety_relaxation_allowed} || (${input_filter_expr}))') == 2
    assert source.count('shield-prompt="@(!${safety_relaxation_allowed} || (${prompt_shield}))"') == 2
    assert '(!${safety_relaxation_allowed} || (${output_filter_expr}))' in source
    terraform = (ROOT / "infra" / "terraform" / "gateway-settings.tf").read_text()
    assert 'safety_relaxation_allowed    = var.dev_safety_relaxation_allowed' in terraform
    # Substitute stale false toggles: the Terraform floor is outside runtime expressions.
    for allowed in (False, True):
        rendered = source.replace("${safety_relaxation_allowed}", str(allowed).lower())
        for variable in ("input_filter_expr", "output_filter_expr", "prompt_shield"):
            rendered = rendered.replace("${" + variable + "}", "false")
        policy = ET.fromstring(rendered)
        expected = f'!{str(allowed).lower()} || (false)'
        assert sum(expected in node.get("condition", "") for node in policy.findall(".//when")) == 3
        assert all(node.get("shield-prompt") == f"@({expected})"
                   for node in policy.findall(".//llm-content-safety")[:2])
    # Protected material remains separately configurable, not forced by the floor.
    protected = source[source.index('%{ if protected_material_available'):source.index('%{ if protected_material_available') + 500]
    assert 'aiflux-protected-material' in protected
    assert 'safety_relaxation_allowed' not in protected
