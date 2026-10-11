# Capability matrix and launch blockers

Public-dev architecture revised on 2026-10-11. **No live Azure gateway or model
tests have been run.** A synthetic Foundry Language PII endpoint smoke test passed
with an operator AAD token; it does not validate gateway identity or policy. Region/RG
metadata is not feature evidence. The machine-readable
manifest is `gateway\capabilities.json`; acceptance cases are
`gateway\validation\scenarios.json`.

| Requirement | Current implementation/evidence | Release status |
| --- | --- | --- |
| Public development edge | Public Basic v2 APIM, public authenticated data/apps, sole AppGW subnet/service endpoint, local protected state, then public WAF_v2 HTTPS; no private endpoints/integration/VM/runner dependency | Certificate/ACME renewal, Entra/images, WAF/backend/SQL firewall acceptance and native direct-APIM origin-bypass proof remain unverified |
| APIM-only inference | Unpublished Product, two subscription-required placeholder operations, unconditional 503/no backend | **Blocked**, not an inference API |
| Native unified OpenAI interface | Documentation promises Chat Completions/Anthropic translation; portal-only instructions | Reproducible native ARM/IaC artifact absent |
| OpenAI SDK bearer key | Native unified docs contain SDK example; placeholder accepts only native header validation | Native validation order/extraction/conflicts/product scope unverified |
| Foundry/OpenAI/Anthropic-on-Azure | No fake models; empty catalog contract | Deployment access/version/format/auth/public connectivity/eligibility unverified; no deterministic Basic v2 outbound IP assumed |
| PII input redaction | Public keyless Microsoft Foundry `AIServices` S0 account and gateway-scoped `Cognitive Services User` role; synthetic email detected/redacted through Language PII REST using operator AAD | Gateway managed-identity call/policy is not proven; no whole-request handling, structure/Unicode coverage, or fail-closed behavior acceptance |
| Input/output harm + Prompt Shields | Public keyless Content Safety account/MI/RBAC; documented native policy | Original/redacted checks/fail-closed behavior unverified |
| Live SSE safety | Native sliding-window stop documented; AppGW buffering disabled; no edge cache | Incremental timing/window/overlap/errors/cancellation unverified; delivered content cannot be withdrawn |
| Tools/tool arguments/history | Advertised only by future reviewed per-model catalog | Translation/PII/safety coverage **unverified**; must block unless proved |
| Strict JSON/structured output | No schema-breaking redaction or silent field drop allowed | Translation/string/typed value/stream moderation unverified |
| Per-model region pools | Catalog endpoint/priority/weight contract; documented native pool/circuit capabilities | Native alias integration/auth/actual selected endpoint/Retry-After/retries unverified |
| RPM/TPM/token quotas | IDS configuration contract, native llm-token-limit documented | No production policies activated; v2 best-effort gateway-local token buckets and concurrent overshoot |
| Metadata usage logging | Documented preview metadata-only APIM diagnostics; request/backend headers empty, HTTP bytes 0, LLM message settings omitted | No-payload/correlation/completeness/sink audit unverified |
| Selected provider/region | Response header allowlist reserved; no synthetic values emitted | Must come from actual endpoint selection; pool/gateway region insufficient |
| Prompt/completion/total tokens | Native LlmLog documented fields | Live coverage unverified; terminated/cancelled streams may be incomplete |
| Cached-read/cache-write tokens | Native per-request LlmLog contract lacks fields | **Unsupported in current native log source**; must remain unavailable, not zero |
| True TTFT | Native per-request log contract lacks first-content timestamp | **Unsupported in current native log source**; E2E/header/playground timing is not a substitute |
| Retry accounting | Native logs may not account every provider attempt | Incomplete estimates; retries are not assumed free |
| SQL/Monitor/runtime identity | Public Entra-only SQL with exact operator/app outbound firewall rules, per-host MI/RBAC/config and SQL bootstrap script | Two-pass outbound rule setup, migrations/grants/runtime token acquisition require live validation |
| Function projections | Disabled public keyless Function/storage; no anonymous blob access | Code deployment/schema/bounds/watermarks/token semantics not live verified |

## Precise externally supplied artifact gate

The public native API must remain disabled until IDS supplies and reviews:

1. The actual reproducible native unified-model resource/policy artifact and official
   ARM contract/API version, verified for the selected Basic v2 tier/rollout.
2. Native bearer-key/product-scope proof (not secret comparisons or subscription bypass).
3. Per-provider/model/region capability/access matrix and endpoint equivalence.
4. Structured PII/input safety/Prompt Shields/output safety coverage and fail-closed
   dependency-error evidence, including accepted tools/strict-JSON and live SSE.
5. Regional pool/circuit/retry-after/never-retry-partial-stream evidence.
6. Per-subscription/per-alias IDS quota/config values and isolated counter checks.
7. Native actual-endpoint metadata, correlations, usage/completeness and no-sensitive-log audit.
8. Dated reviewer identity/environment/artifact hashes and expiry; rerun on relevant changes.
9. `public_edge_origin` acceptance: TLS/WAF, App Service/SCM restrictions, SQL exact IP
   rules and **native direct-APIM bypass denial before inference release**. Public
   endpoint reachability alone is not WAF/origin-control evidence.

`attestation.example.json` is a blank handoff form, **not a signed certificate or evidence**.
Supplying it cannot turn on anything. No valid native implementation can be derived safely
from current published API schemas, so further reviewed code is required as well as evidence.
Do not enable a model merely because a portal creation or one ordinary text request worked.

## Verified local results versus missing live evidence

The provided local validation script runs provider-schema checks and **mocked-provider**
plan tests for public deployment plus deferred operator/state roots, and standard-library
gateway contracts. These tests do not spend Azure credits or prove
regional/preview behavior. The bundle release check intentionally fails with exit 2.
The bounded live probe only checks disabled posture and must not be used as release acceptance.

No custom inference proxy/observer, tool executor, payload logger or metric fabrication is
added to hide native gaps. The original cache/TTFT telemetry requirement is an explicit
unmet requirement under the approved APIM-only constraint. An alternative native source
may be considered only after per-request semantics/provider coverage are demonstrated.

## Accepted design limitations, independent of missing evidence

- Shared global region pools can process data across borders; disclose this to tenants.
- Native v2 deployment is single gateway region; backend failover is not gateway-region DR.
- Streaming safety has residual risk: already-delivered chunks cannot be withdrawn.
- Distributed pools/circuit state/distribution and rate/token counters are approximate.
- Showback is an estimate; missing usage/prices/cache categories reduce coverage rather than
  becoming zero-cost usage. Preserve provider cache/reasoning semantics and effective prices.
- No Responses/Assistants/audio/images/agent endpoints, conversation memory, tool execution,
  semantic cache, or customer-editable limits in this release.

## Source-of-truth references

- [Native unified API preview](https://learn.microsoft.com/azure/api-management/unified-model-api)
- [Native safety/stream window semantics](https://learn.microsoft.com/azure/api-management/llm-content-safety-policy)
- [Native token limit behavior](https://learn.microsoft.com/azure/api-management/llm-token-limit-policy)
- [Native LLM logging](https://learn.microsoft.com/azure/api-management/api-management-howto-llm-logs)
- [Documented LlmLog columns](https://learn.microsoft.com/azure/azure-monitor/reference/tables/apimanagementgatewayllmlog)
- [Backend pools/circuit breakers](https://learn.microsoft.com/azure/api-management/backends)
- [Basic v2 and other v2 constraints](https://learn.microsoft.com/azure/api-management/v2-service-tiers-overview)
- [Canonical AI Gateway labs](https://github.com/Azure-Samples/AI-Gateway)
- [Hub accelerator](https://github.com/Azure-Samples/ai-hub-gateway-solution-accelerator)
- [Terraform counterpart](https://github.com/Azure/terraform-ai-gateway-landing-zone)
