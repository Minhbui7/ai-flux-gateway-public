# Capability matrix and launch blockers

Documentation and local checks reviewed on 2026-10-09. **No live Azure gateway or model
tests have been run.** Region/RG metadata is not feature evidence. The machine-readable
manifest is `gateway\capabilities.json`; acceptance cases are
`gateway\validation\scenarios.json`.

| Requirement | Current implementation/evidence | Release status |
| --- | --- | --- |
| Private public-edge chain | Schema-valid Premium Front Door -> private-only AppGW -> internal PremiumV2 Terraform; route disabled | Private Link approval/TLS/DNS/SKU/network isolation/bypass checks unverified |
| APIM-only inference | Unpublished Product, two subscription-required placeholder operations, unconditional 503/no backend | **Blocked**, not an inference API |
| Native unified OpenAI interface | Documentation promises Chat Completions/Anthropic translation; portal-only instructions | Reproducible native ARM/IaC artifact absent |
| OpenAI SDK bearer key | Native unified docs contain SDK example; placeholder accepts only native header validation | Native validation order/extraction/conflicts/product scope unverified |
| Foundry/OpenAI/Anthropic-on-Azure | No fake models; empty catalog contract | Deployment access/version/format/auth/private connectivity/eligibility unverified |
| PII input redaction | Private Language account/MI/RBAC; structure/Unicode acceptance requirements | Policy not activated or proven; no whole-JSON replacement/deanonymization |
| Input/output harm + Prompt Shields | Private Content Safety account/MI/RBAC; documented native policy | Original/redacted checks/fail-closed behavior unverified |
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
| SQL/Monitor/runtime identity | Private Entra-only SQL, per-host MI/RBAC/config and SQL bootstrap script | Migrations/grants/runtime token acquisition still require live validation |
| Function projections | Disabled private keyless Function host/configuration | Code deployment/schema/bounds/watermarks/token semantics not live verified |

## Precise externally supplied artifact gate

The public native API must remain disabled until IDS supplies and reviews:

1. The actual reproducible native unified-model resource/policy artifact and official
   ARM contract/API version, tied to the target Premium v2 rollout.
2. Native bearer-key/product-scope proof (not secret comparisons or subscription bypass).
3. Per-provider/model/region capability/access matrix and endpoint equivalence.
4. Structured PII/input safety/Prompt Shields/output safety coverage and fail-closed
   dependency-error evidence, including accepted tools/strict-JSON and live SSE.
5. Regional pool/circuit/retry-after/never-retry-partial-stream evidence.
6. Per-subscription/per-alias IDS quota/config values and isolated counter checks.
7. Native actual-endpoint metadata, correlations, usage/completeness and no-sensitive-log audit.
8. Dated reviewer identity/environment/artifact hashes and expiry; rerun on relevant changes.

`attestation.example.json` is a blank handoff form, **not a signed certificate or evidence**.
Supplying it cannot turn on anything. No valid native implementation can be derived safely
from current published API schemas, so further reviewed code is required as well as evidence.
Do not enable a model merely because a portal creation or one ordinary text request worked.

## Verified local results versus missing live evidence

The provided local validation script runs provider-schema checks for deployment/state,
four **mocked-provider** infrastructure plan tests (deployment/state private posture and cost approval),
and twelve standard-library gateway contracts. All passed locally. These tests do not spend Azure credits or prove
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
- [Premium v2 constraints](https://learn.microsoft.com/azure/api-management/v2-service-tiers-overview)
- [Canonical AI Gateway labs](https://github.com/Azure-Samples/AI-Gateway)
- [Hub accelerator](https://github.com/Azure-Samples/ai-hub-gateway-solution-accelerator)
- [Terraform counterpart](https://github.com/Azure/terraform-ai-gateway-landing-zone)
