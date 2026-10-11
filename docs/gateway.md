# APIM gateway: production disabled, guarded development route deployed

## Implemented surface

Terraform creates the public Basic v2 development candidate, an **unpublished** subscription-required
Product `aiflux`, and a **disabled ordinary HTTP placeholder**, not a native unified model API.
The only operations are `GET /v1/models` and `POST /v1/chat/completions`.
Both global and API policy unconditionally return an OpenAI-shaped `503` with `no-store`.
Native subscription validation may reject earlier with `401`. The placeholder has **no backend,
translation, successful model list, inference forwarding, retry, or adapter**.
Do not present its existence as native capability proof.

`gateway\openapi.json` describes this disabled `/v1` surface, not a successful OpenAI API.
`gateway\capabilities.json` records production release gates. A separate, subscription-required
text-only development API is deployed at `/dev/v1` for the verified `gpt-5.6-luna` and
`gpt-5.6-sol` deployments in East US and Sweden Central. Its product is published for
subscription management, requires approval, and permits one subscription.
This pass-through route is not the native unified-model API and does not claim that the
production `/v1` contract is implemented.
When enabled, the route accepts APIM's native `Ocp-Apim-Subscription-Key` header; it does
not claim `Authorization: Bearer <subscription-key>` compatibility.

The development route accepts only bounded, non-streaming text chat requests. It rejects
tools, images, structured output, streaming, unknown fields, and query parameters other than
APIM's subscription key. Input is checked by Prompt Shields and Azure AI Content Safety at
severity threshold 4, then every message is PII-redacted by Azure Language, checked again,
and sent using APIM managed identity. Returned completions are checked by Content Safety
before delivery. A required inspection failure blocks the request. Subscription/model limits
are 2 requests/minute, 2,048 estimated tokens/minute, 64 output tokens/request, and 16 KiB
request size. These are dev-only settings, not production defaults.
The deployed path has returned one synthetic Luna completion through all three safety checks
and PII inspection (HTTP 200, 12 prompt tokens, 4 completion tokens); no prompt or completion
text was logged. This proves only that bounded smoke case, not the full acceptance checklist.

The `/v1` placeholder remains unconditionally denied. Editing the production Product,
catalog or manifest cannot activate it. Any future production activation needs a separately reviewed
implementation using the verified native contract, not an escape hatch around policy.

## Why native provisioning is blocked

The [unified-model API documentation](https://learn.microsoft.com/azure/api-management/unified-model-api)
documents **portal creation only** and preview rollout. The published
[2024-05-01 API ARM contract](https://learn.microsoft.com/azure/templates/microsoft.apimanagement/2024-05-01/service/apis)
and [2025-09-01-preview contract](https://learn.microsoft.com/azure/templates/microsoft.apimanagement/2025-09-01-preview/service/apis)
do not define a unified-model alias/translation configuration. No `type = llm`,
made-up model properties, or invented translation policy has been used here.

The [Azure-Samples/AI-Gateway Content Safety sample](https://github.com/Azure-Samples/AI-Gateway/blob/main/labs/content-safety/main.bicep)
uses backend `credentials.managedIdentity` with `Microsoft.ApiManagement/service/backends@2024-06-01-preview`.
The deployed Content Safety backend follows that contract, explicitly selecting the gateway
user-assigned identity and Cognitive Services audience. The AzAPI provider's older embedded
schema doesn't describe the preview property, so validation is disabled only for that backend
resource; the resulting ARM configuration and live guarded completion were verified.
Likewise, backend pools are documented, but their integration with native aliases,
actual selected-endpoint logging, and per-endpoint authentication still needs proof.
No unauthenticated model backend is provisioned as a substitute.

An SDK example using `api_key` is documentation, not proof that an ordinary policy can
extract `Authorization: Bearer <key>` **before native APIM subscription validation**.
Configuring `Authorization` as the key-header name does not remove the `Bearer ` prefix.
Manually comparing secrets, disabling `subscription_required`, or trusting arbitrary
organization/model headers is not acceptable. Bearer/header conflict handling,
revocation, product scope and native validation must be proved on the target rollout.

## Catalog integration

The shared source is `gateway\catalog\models.json`, currently exactly `{"models":[]}`.
Python and portals read `id`, `provider`, `capabilities`, `enabled`, `backend_model`,
and optional `region`. No provider/model/deployment names are supplied as production defaults.
`catalog.schema.json` also describes operator-supplied endpoint pools, priorities/weights,
managed-identity audience or **Key Vault secret references only**, and IDS limits.
These extra fields are a **configuration contract**, not native ARM properties or
currently provisioned pools. Never put provider keys/customer keys in the catalog.

For each alias, backends must be equivalent versions of that model; regions are shared
globally. Do not silently substitute another model. Each endpoint has a stable unique
`backends[].id`, region, optional actual model/provider override and URL. Check all
capabilities on **every** failover member before advertising them. Access, commercial
eligibility and availability are operator inputs, particularly for Anthropic-on-Azure.

`enabled` remains false until reviewed implementation and live evidence exist.
API setting `AIFLUX_CATALOG_CONFIGURED=false` is deliberate: an empty catalog is not a
ready production gateway. Container packaging must include the exact catalog snapshot.
Terraform does not write an independent SQL model catalog or supply fake models.

## Inspection pipeline required before activation

`gateway\validation\scenarios.json` is the complete acceptance checklist, **not results**.
The approved order is native subscription/schema/capability validation; subscription+alias
RPM/token counters; original-input safety and Prompt Shields; structured PII redaction;
safety of the redacted forwarded input; native translation/routing; response safety;
metadata-only accounting. All unsafe/unknown/dependency-failure paths fail closed.

Redact textual fields in every accepted role and history, tool descriptions/results and
free-text argument values. Never regex-replace serialized JSON. Preserve identifiers,
keys, schema types, strict contracts and Unicode boundaries. Sensitive typed values that
cannot be safely changed must reject. Prove Language chunking, overlap/span merging,
document/batch limits, and every accepted input format with a controlled backend capture.
No original/redacted mappings or entity values may be logged. No deanonymization.

[llm-content-safety](https://learn.microsoft.com/azure/api-management/llm-content-safety-policy)
documents input Prompt Shields, `enforce-on-completions`, and streaming sliding windows.
Streaming moderation stops further events; it cannot replace already-started SSE with
an HTTP 403 or withdraw content already delivered. The documentation does **not**
establish complete tool-argument/strict-JSON inspection. Block those format/model
combinations unless actual coverage and fail-closed behavior pass. Do not fully buffer
an SSE response and label it live streaming.

IDS must provide harm thresholds, request/inspection limits and languages, chunk/window/
overlap sizes, dependency timeouts, retry budget, RPM/TPM/quota/max-response-token settings.
No production values are guessed. [Native token limits](https://learn.microsoft.com/azure/api-management/llm-token-limit-policy)
are best effort: counters are gateway-local, concurrency can overshoot, v2 uses token
buckets, and streams are estimated. Keep subscription+alias and model-only counters
distinct. Pool round-robin/circuit breakers are approximate; respect Retry-After and
never retry after an SSE event, or retry auth/schema/safety errors.

## Metadata contract and current gaps

The ingestion join uses `ApiManagementGatewayLogs.CorrelationId` and
`ApiManagementGatewayLlmLog.CorrelationId`, scoped to this APIM `_ResourceId`.
`ApimSubscriptionId` is the team subscription, **not** Azure `_SubscriptionId`.
Map its SQL ownership to organization/team; never take ownership from caller headers.
Log Analytics `TenantId` is the workspace, not an Entra organization.

The diagnostic permits only these frontend **response** headers:
`x-aiflux-model`, `x-aiflux-provider`, `x-aiflux-region`. A future native selection must
overwrite them from trusted alias/actual-endpoint configuration and discard caller values.
The disabled policy emits none. `BackendId` must identify the selected **endpoint**, not
merely the pool. If native selection exposes only a pool, actual region/provider costing
remains incomplete. Do not use `LlmLog.Region` (ambiguous resource geography) or gateway
region as a model-backend region. Selection metadata is **unverified**, not currently
promised or synthesized.

Native documented logs contain PromptTokens, CompletionTokens, TotalTokens, ModelName,
DeploymentName, IsStreamCompletion and correlation IDs. Cached-read/write counts and true
TTFT are **unsupported by that log contract**. Do not substitute zero, gateway TotalTime,
backend response headers, or playground timing. Retry/terminated/cancelled stream usage
may be partial/missing. Show known estimated cost and coverage independently; never
invoice-grade billing or zero-cost unknowns. See `docs\capabilities.md`.

APIM HTTP body collection is zero bytes, request/backend headers are empty, and LLM
message settings are omitted. Native LLM metadata logging uses the documented preview
diagnostic schema; omission needs a live absence-of-payload check. WAF/access diagnostic
sinks are deliberately not enabled because matched values/URLs can contain prompts or
credentials. Do not enable allLogs, raw trace/debug, or application request/response logging.

## Validation and reviewed artifact handoff

Local checks: `python gateway\tools\validate_bundle.py` and
`python -m unittest discover -s tests\contract -p "test_gateway*.py" -v`.
`python gateway\tools\validate_bundle.py --release` deliberately returns **exit 2**.
No local pass proves Azure connectivity, feature rollout, PII/safety, translation or SSE.

After explicit Azure/config/cost approval, a network operator can run
`python gateway\tools\live_probe.py --base-url https://<public-edge>/v1`.
This sends at most four requests, with ten-second timeouts, TLS verification and no redirects.
An optional `AIFLUX_VALIDATION_SUBSCRIPTION_KEY` process environment value adds two
native-header blocked checks; the tool neither prints keys nor collects response bodies.
Use disposable bounded validation subscriptions and remove the environment variable
afterwards. Metadata output may be saved under `gateway` or `infra`.
This smoke probe proves **only blocked posture**, not bearer compatibility or full acceptance.
The default disabled edge route intentionally prevents it from succeeding yet.

For a release, obtain an externally verified/reviewed reproducible native artifact and
complete `gateway\validation\attestation.example.json`: target resource/SKU/region/rollout,
reviewer object IDs, observation/expiry dates, official contract/API version, exact artifact,
policy/catalog/lock hashes, per-model/per-endpoint capability matrix and metadata-only
evidence for every applicable gate. Include failing/unknown cases, request budgets and
inspection configuration. Hashes/claims alone are **not** capability evidence.
Review and implement the native resource/policy contract before removing the placeholder
and publishing the Product. Keep gates closed on missing/stale/mismatched evidence.

## Canonical references adapted, not copied wholesale

- [Azure-Samples/AI-Gateway](https://github.com/Azure-Samples/AI-Gateway): backend pools,
  token policies and native feature labs.
- [Hub accelerator PII guidance](https://github.com/Azure-Samples/ai-hub-gateway-solution-accelerator/blob/main/guides/pii-masking-apim.md):
  MI/chunking inspiration only; global serialized-body replacement, deanonymization and
  raw Event Hub payload logging are explicitly **not** adopted.
- [Terraform landing-zone counterpart](https://github.com/Azure/terraform-ai-gateway-landing-zone):
  AzureRM/AzAPI and private-DNS patterns; classic/standard outbound networking,
  custom universal router, cache/memory, schema-validation bypasses and
  secrets/state patterns are not substitutes for the approved native v2 architecture.
