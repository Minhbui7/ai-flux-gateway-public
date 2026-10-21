# Capability matrix and evidence boundaries

This is the canonical documentation status matrix. The baseline is the merged
model/analytics expansion in PR #13; #10's usage PR #14 is pending at authoring.
These are repository and recorded-history statements, **not fresh cloud
verification**. Detailed chronological records remain in the linked runbooks.

## Reading evidence

| Label | Meaning |
| --- | --- |
| Repository | Source implements a contract, or IaC conditionally declares a resource. Defaults are not deployed inputs. |
| Historical acceptance | A dated runbook or user confirmation records a bounded outcome. It does not prove current state or broader journeys. |
| Live unverified | No current acceptance is established here; a past success or failure is not a new observation. |
| Proposed | An issue/design option, not supported behavior. |

Use code/contracts for behavior, Terraform inputs for defaults/conditions,
catalogs for declared eligibility and scoped records for historical outcomes.
Vendor documentation establishes platform semantics, not local deployment.
Do not change a release flag or attestation to reconcile prose.

## Implemented and recorded scope

| Surface | Repository behavior / source | Acceptance boundary |
| --- | --- | --- |
| Customer and IDS portals | React entry points share `packages/ui`; missing required configuration denies rendering | Historical basic customer sign-in/reconcile/reveal/playground confirmed; not complete IDS or multi-tenant acceptance |
| Tenant isolation | `auth.py` verifies delegated identity/scope and enabled SQL organization/member; IDS role restricted to home tenant | UI role display, Entra app role and callback HTTP 200 are not backend authorization evidence |
| Team subscriptions | SQL ownership before APIM activation; idempotent creation, reconcile, reveal, rotate and state operations | ARM failures surface explicitly; organization disable can leave suspension incomplete and requires retry |
| Guarded adapter | `dev-unified.tf`, `dev-openai.xml.tftpl`, `openapi-dev-adapter.json`: conditional `/dev/llm/v1` ordinary HTTP API, subscription required | Historical completions; not native unified preview |
| Legacy dev route | Separate `/dev/v1`, original OpenAI route/product | Does not inherit adapter aliases or limits |
| Model catalog | `gateway/catalog/dev-models.json` contains eleven enabled aliases; production catalog/gates separate | Later expansion records direct and guarded checks before publication; per-model backend count varies |
| PII and safety | Original input safety/Prompt Shields, five-document PII batches, redacted input safety and buffered output moderation | Bounded historical checks, not comprehensive adversarial coverage; failed dependencies must not release an unchecked answer |
| Provider translation | OpenAI, Foundry Direct and Anthropic branches; validated thinking blocks omitted from returned answer, usage preserved | Unknown/malformed/internal-only responses fail closed; no tool execution |
| Guarded streaming/tools/strict JSON | Rejected by guarded adapter | Future catalog capability controls do not enable these on this route |
| Limits | Configured RPM/TPM per subscription/model, per-model output bounds; adapter product cap 10 | Counters approximate; historical 2 RPM overshoot observed; TPM is not a per-request output ceiling or spend cap |
| Showback and charts | SQL projections, effective-dated prices, scoped rows/export and UTC minute charts | List-rate estimates; missing metrics/prices Unknown, partial totals lower bounds; millisecond API/CSV contracts preserved |
| Ingestion | Function v1 bindings, bounded overlap replay, durable watermark after transaction | Historical 68-request three-model reconciliation; later recorded pause on 45 unowned smoke-test rows; fresh usage acceptance not established |
| Cache/TTFT metrics | Native source lacks documented per-request cache/first-token fields; guarded `finops-v1` supplements validated cache counters | Native cache categories and true TTFT remain unsupported unless source semantics demonstrated; E2E is not TTFT |
| Retry accounting | Bounded buffered transient retry; completeness flags in ingestion | Not every paid provider attempt is proven observable; never assume retries free |
| Hybrid private data | Conditional SQL/vault/blob/queue/table endpoints; API/Function integration and SQL Proxy | Historical private readiness; current connectivity not rechecked; portal/APIM/Foundry endpoints are not made private by this |
| Edge / certificate | Conditional App Gateway; vault declares `AzureServices` bypass and vault-scoped edge reader | Older certificate failure predates bypass change; no subsequent TLS/origin acceptance established by this documentation |
| MISE | Optional loopback sidecar branch or direct JWT/key-discovery branch with telemetry headers | Configuration and headers are not compliance certification or proof of deployed sidecar validation |

Original adapter development overrides were recorded as 2 RPM, 20,000 TPM and
100,000 output tokens for original aliases; new aliases use a 4,096 output bound.
The Terraform defaults remain more conservative. See [Gateway](gateway.md) and
[model specifications](../infra/models/model-spec.json), not prose, for exact
per-model/configuration constraints.

## Native production gates remain closed

`gateway/capabilities.json` has `inference_enabled=false`,
`product_published=false`, no native artifact/attestation and unverified gates.
It describes the native release bundle, not the separate development product.
Production/native `/v1` and experimental `/llm/v1` must not be advertised as
accepted inference paths.

Before native release, require reproducible tier/rollout-specific IaC,
subscription bearer/product-scope proof, provider/model/region eligibility,
structured PII and original/redacted safety, Prompt Shields, output/SSE coverage,
tools/strict-JSON inspection, actual endpoint attribution, Retry-After/failover
and no-partial-stream retry proof, isolated quota checks, and metadata-only
correlation/completeness evidence. Final edge acceptance additionally needs
TLS/WAF/origin restrictions and direct-APIM bypass denial.

`gateway/validation/scenarios.json` and `attestation.example.json` define the
review handoff. A blank example is not an approval or executable native
implementation. Record reviewer, environment, artifact hash, scope and expiry;
revalidate when relevant behavior changes.

## Reconciliation ledger

| Conflicting historical claims | Canonical interpretation |
| --- | --- |
| Three aliases / preview tiles versus eleven callable aliases | Three-model acceptance predates expansion; current dev catalog declares eleven. Neither implies native release. |
| Ingestion disabled, enabled/reconciled, then paused | Distinct snapshots. Latest recorded blocker is unowned test telemetry; no automatic ownership assignment or watermark advance. |
| Key Vault bypass disabled versus `AzureServices` | Earlier runbook record predates current `main.tf`; storage `None` is unrelated. Certificate success remains live unverified. |
| Integration `.2.0/24` versus `.4.0/24` | Subnet is a required hybrid input. Historical runbook uses `.4`; diagrams now use input names instead of asserting live CIDRs. |
| Public apps versus operator-restricted origins | Approved direct-dev mode and staged edge restrictions are distinct configurations; direct-dev is not final origin-protection acceptance. |
| P1v3 staging examples versus B1 development records | Input/stage examples are not current SKU readback; B1 preservation is recorded development direction. |

## Proposed and excluded

#10 / PR #14 (private historical reference)
adds model filtering/discovery, collapsed transactions and pricing disclosure;
it is not merged baseline behavior here. #9 admin safety/limit editing, #11
customer one-click deployment and #8 stateless Auto classification are proposed.
No Responses/Assistants/audio/images/agent endpoints, tool executor, semantic
cache or subscription conversation memory is provided by the guarded release.

Accepted design limitations include cross-border model pools, one gateway
region, approximate distributed counters and estimate-only showback. Future SSE
moderation cannot withdraw already delivered content. See [PRD](prd.md),
[security readiness](security-and-approvals.md) and [roadmap](roadmap.md).

## Validation sources

Local contract tests and mocked Terraform tests do not spend Azure credits or
prove service availability. `validate_bundle.py` validates the disabled bundle
posture by default; release mode must reject an unaccepted bundle. Live probes
need separate approved scope/cost and cannot turn a local pass into release proof.

- [Native unified API](https://learn.microsoft.com/azure/api-management/unified-model-api)
- [Safety policy](https://learn.microsoft.com/azure/api-management/llm-content-safety-policy)
- [Token limits](https://learn.microsoft.com/azure/api-management/llm-token-limit-policy)
- [Native LLM logging](https://learn.microsoft.com/azure/api-management/api-management-howto-llm-logs)
- [Native log schema](https://learn.microsoft.com/azure/azure-monitor/reference/tables/apimanagementgatewayllmlog)
- [Backend pools/circuits](https://learn.microsoft.com/azure/api-management/backends)
- [v2 tier constraints](https://learn.microsoft.com/azure/api-management/v2-service-tiers-overview)
