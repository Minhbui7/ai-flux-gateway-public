# APIM gateway: production disabled, guarded development route deployed

This runbook mixes implementation instructions and dated development records;
neither is current cloud verification. [Capabilities](capabilities.md) owns the
canonical status and separates guarded development from native release gates.
See [technical specification](technical-specification.md) and
[security/approval readiness](security-and-approvals.md) for system boundaries.

## Latest guarded adapter (2026-10-12)

The user explicitly approved a non-native fallback. Terraform now owns a
separate ordinary HTTP API, `aiflux-dev-unified`, at `/dev/llm/v1`, and its
subscription-required `aiflux-dev-unified` product. The native preview API is
preserved for investigation but globally denied, alongside the production `/v1`.
No keys are compared manually and native subscription validation stays enabled.
The original two-model `/dev/v1` API and product keep their existing behavior.

The adapter reuses `dev-openai.xml.tftpl` with an explicit mode. The checked-in
development catalog now contains eleven enabled aliases: the original three
(`gpt-5.6-luna`, `gpt-5.6-sol`, `claude-haiku-5-5`) and eight expansion aliases.
The 2026-10-14 infrastructure record describes direct and guarded acceptance
before publication. Earlier three-model checks below predate this expansion.
New aliases are never added to the original `/dev/v1` two-model API.
See [model deployment and acceptance](../infra/models/README.md) for exact
regions, quota budgets, and release commands.

OpenAI v1, Foundry Direct OpenAI-compatible (`MoonshotAI`/`DeepSeek`), and
Anthropic Messages backends have explicit data-driven routing. Foundry Direct
uses the endpoint advertised by the live account metadata, adds the documented
`/models` base to its service root, appends
`/chat/completions?api-version=2024-05-01-preview`,
and translates the guarded `max_completion_tokens` field to provider
`max_tokens`. Anthropic uses the primary Foundry account's `/anthropic/v1/messages`
endpoint for the existing Haiku route; new Sonnet/Opus routes preserve the exact
selected hyphenated model alias on the translated request.
Haiku request translation:
redacted system/developer messages become `system`, user/assistant messages
retain their roles, and `max_completion_tokens` becomes `max_tokens`.
Valid text blocks are joined in provider order and converted to OpenAI
`choices`, `finish_reason` and `usage` before output safety. Metadata-only live
diagnosis confirmed that Haiku also returns a `thinking` block with string
`thinking` and a nonempty string `signature`. Those validated internal blocks
are omitted from the answer; their contents/signatures are not logged, and full
provider input/output usage is retained, including internal generation.
A nonempty text answer is mandatory. Internal-only responses, malformed blocks,
tools, unknown or unconfirmed blocks (including `redacted_thinking`), unsupported
stop reasons and invalid/overflowing counters fail closed with HTTP 503
`provider_response_invalid`. Only fixed error metadata is emitted; no raw
provider error or internal content is released. Temporary shape diagnostics
have been removed.
No streaming, tools, structured output, provider-key authentication or
cross-provider failover is introduced.

Managed-identity auth uses the gateway UAMI client ID and Cognitive Services
audience. Original-input safety/Prompt Shields, guarded PII batching, redacted
input safety and completion safety remain mandatory for both providers.
The user-approved adapter limits are 2 RPM/model/subscription, 20,000 TPM and
per-model completion bounds, with a 240-second backend timeout and at most one
buffered transient-5xx retry. New aliases start at a 4,096-token output bound,
verified by bounded direct and guarded requests before publication; this is not
a claim about their advertised native maximum. The existing per-model TPM
throttle remains in place. Existing accepted-model limits are unchanged.
Separate adapter variables preserve the legacy
`/dev/v1` limits of 2,048 TPM, 64 output tokens and a 45-second backend timeout.
The new variables retain conservative defaults; the active approved inputs
explicitly select the higher limits. Prompt tokens are estimated at admission;
actual reported prompt/completion usage is accounted after the response.
A large response can temporarily exceed the TPM budget and throttle subsequent
calls: TPM is not a hard per-request output ceiling.
Both providers accepted a 100,000-token request budget, and 100,001 is rejected.
Sol completed a 6,364-word essay with 8,571 completion tokens and normal `stop`.
The earlier Haiku 503 was a response-conversion failure: the provider returned
HTTP 200 with mixed thinking/text blocks, but the adapter rejected non-text
blocks before output safety. After the strict normalization repair, a live
Haiku essay completed with 5,241 words, 11,673 reported completion tokens,
11,767 total tokens, normal `stop` and successful output safety in 68.97 seconds.
This verifies one long buffered response, not an unlimited-generation guarantee.
Streaming remains disabled.
Input size/message/history bounds and all safety/PII checks are unchanged.
Retry accounting is still incomplete. Ingestion was disabled at this earlier
adapter snapshot; later activation/reconciliation and the subsequent unowned-row
pause are recorded in [Infrastructure](infrastructure.md).

APIM CORS is the first adapter inbound policy, before inherited gates; this
allows unauthenticated preflight processing. Only the exact configured customer
and admin App Service origins are permitted, with `Content-Type` and
`Ocp-Apim-Subscription-Key`, and `Retry-After` exposed. No wildcard or credentialed
CORS is used. The browser sends the subscription header, not unverified bearer
subscription auth. Previews are not listed by APIM and cannot be called.

Metadata-only acceptance passed 15 checks: missing/invalid-key denial, exact
three-model discovery, both portal preflight/actual CORS responses, untrusted-origin
exclusion, unsupported-shape rejection and real completions for all three models.
These CLI checks alone do not prove signed-in customer, regional failover or
complete adversarial acceptance. The user subsequently confirmed the basic
signed-in customer flow through the adapter: team subscription reconciliation,
key reveal and both provider playground responses. Regional failover and complete
adversarial acceptance remain pending.
Use `gateway\tools\verify_adapter.py` with an explicitly approved adapter-product
test subscription and both `--portal-origin` values; `--smoke` tests the currently
accepted catalog, while `--candidate-alias` additionally smoke-tests an explicitly
temporary hidden route. Candidate aliases are not returned by `GET /models`.
Keys and response text are never written; empty HTTP 200 responses cannot pass
completion acceptance. Dispose of any unowned synthetic subscription after
checking; it is not a tenant's billable subscription.

Normalization regressions execute the exact policy C# expression against
synthetic provider responses, rather than a Python translation. Install .NET
8 SDK, then run `pytest -q tests\contract\test_anthropic_normalization.py`.
`AIFLUX_DOTNET` can select an isolated SDK executable; CI installs the SDK
explicitly. Cases cover ordered text, thinking/text, internal-only output,
malformed/unknown/tool blocks, stop/length mapping and token counter bounds.
Post-repair live checks also verified all three aliases with 100,000-token
budgets, 100,001 rejection, key/CORS/input-shape controls and the specific
fail-closed error for an internal-only Haiku response. Test subscriptions were
deleted. Signed-in long-Haiku browser acceptance remains separate from these
gateway checks.

The native investigation found an empty inherited backend section caused
empty HTTP 200 responses. The manually created backends also lacked the gateway
UAMI client ID, with an incorrect OpenAI audience. Correcting authentication
and forwarding enabled OpenAI, but Haiku was sent to
`/anthropic/v1/messages/chat/completions` without translation. ARM model aliases
exist, yet a working native routing/translation pipeline was not established.
That is why the explicit adapter was approved; do not represent it as native support.

## Implemented surface

The legacy optional admin settings fragment supplies a request-scoped Content Safety
threshold and native RPM/TPM/token quota enforcement for each guarded dev API.
The API policies still own all three safety passes, PII/Prompt Shields, routing,
output ceilings and fail-closed errors. This does not activate production.
The feature is off by default and denied until explicitly configured when enabled;
see [the canonical settings contract](control-plane.md#admin-managed-gateway-settings)
and [operator rollout/rollback](infrastructure.md#opt-in-admin-gateway-settings).
Initial activation isolates counter keys by API because the two guarded surfaces
have different TPM ceilings. Subsequent revisions retain stable keys.

The new opt-in versioned policy templates prepare for a dependent application
release; do not activate them with the baseline runtime. That release will share one complete configuration and
counter namespace across guarded routes/models, using the lower supported TPM
ceiling. They add aggregate team and subscription RPM, literal-tier backend
concurrency, calendar-partitioned request quotas and a separate safety profile.
Native limits remain approximate. Terraform owns routing/forwarding and minimum
inspection; the runtime writes only bounded settings fragments. Protected-text
output scanning is separately capability-gated. See
[versioned controls](control-plane.md#versioned-team-limits-and-content-safety)
and [staged activation](infrastructure.md#versioned-controls-rollout).
Implementation is not proof of live Basic v2 enforcement or production release.

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
tools, images, structured output, streaming, unknown fields, and all query parameters,
including query subscription keys. Combining Authorization and subscription-header
credentials is rejected. Input is checked by Prompt Shields and Azure AI Content Safety at
severity threshold 4, then every message is PII-redacted by Azure Language, checked again,
and sent using APIM managed identity. Returned completions are checked by Content Safety
before delivery. A required inspection failure blocks the request. Subscription/model limits
are 2 requests/minute, 2,048 estimated tokens/minute, 64 output tokens/request, and 16 KiB
request size. These are dev-only settings, not production defaults.
Live development acceptance passed 24 bounded checks on 2026-10-11, including Luna/Sol
completions (HTTP 200, 9 prompt and 4 completion tokens), native-key denial (401),
schema/credential conflict rejection (400), media rejection (415), RPM throttling (429),
and a synthetic Prompt Shields fixture (403). A configured 2 RPM limit allowed three
requests before 429 in that burst: observed overshoot was one, not an exact rate guarantee.
RPM and TPM use separate subscription/model counter namespaces. Required service/runtime
failures remain 503; confirmed native safety violations return 403 and emit only a generic
`ContentSafety` blocked-event trace, never raw error messages or inferred harm categories.
The live native trace serializes its metadata as a JSON string; ingestion accepts that
documented observation as well as object metadata, and rejects malformed metadata explicitly.
These checks are not provider-side PII capture, full adversarial acceptance, regional
failover proof or production release evidence.

The original synchronous PII call incorrectly sent up to 25 documents to an API whose
[document limit is five](https://learn.microsoft.com/azure/ai-services/language-service/concepts/data-limits).
The dev policy now emits at most five sequential, guarded five-document batches, retaining
global message IDs and validating every response before assembling redacted messages.
Timeouts/errors/warnings/missing or mismatched documents still fail closed. Text remains
bounded to 4,800 UTF-16 code units per message and 8,000 total; no chunking within a message
or serialized-JSON replacement is used. No PII response content is carried in outbound headers.

Fresh acceptance now passes 27 checks, including 5-, 6- and 25-message requests across
system/developer/user/assistant roles with synthetic contact data, supplementary Unicode
and combining marks. These are successful inspection/forwarding checks, **not** independent
provider-side capture or evidence that every PII category/language is handled.

The latest raw UTF-8 acceptance passes 28 checks. Unlike JSON-escaped Unicode, raw
supplementary characters exposed an invalid-header failure in the original-body scratch
header. That header is removed: the original JSON is retained directly in a request-local
string variable, preventing Unicode/header-size restrictions and accidental forwarding.
An independent 6,100-byte high-token fixture exposed native
`TokenLimitExceededAfterPrompt` being incorrectly reported as 503. The observed native
reason now maps to an OpenAI-shaped 429 with Retry-After, separately from RPM throttling.
Other token-policy runtime failures still fail closed rather than being assumed rate limits.
An independent native TPM probe also verified a positive `Retry-After: 60` response.
The approved disposable test subscription was temporarily suspended: its existing header
key returned 401, then the original active state was restored and `/models` returned 200.
Only that subscription's state changed; no key was exposed, revoked permanently or rotated.
This proves suspension enforcement, not bearer authentication or cross-subscription isolation.

A six-message test exposed a genuine Sol East US backend 500. The dev route now retries
only buffered 500/502/503/504 model responses once, reselecting the same-model regional pool,
with a one-second delay and 45-second timeout per attempt. Exhausted 5xx returns an
OpenAI-shaped 503. Validation/auth/safety errors and backend 429 are not retried.
This does not prove deterministic failover, transport recovery or Retry-After handling.
Retry traces contain only a constant marker and previous HTTP status. Ingestion marks
otherwise complete retried usage `retry_usage_unknown` with no complete cost, since prior
attempt usage may be missing. Neither prompts nor completions are traced.

Both manually deployed Haiku 5.5 endpoints passed direct operator-Entra completions.
Account-scoped Cognitive Services User access is configured for the gateway in both regions;
actual Haiku gateway invocation and OpenAI-compatible native translation remain unverified.
The model Terraform root does not own or import those manual deployments.

Reproduce bounded checks with `python gateway\tools\verify_dev.py --subscription <id>
--resource-group <rg> --apim <name> --output infra\terraform\dev-acceptance.json --smoke --limits`.
Add `--pii-batches` for the three bounded synthetic role/Unicode batching checks.
The verifier obtains the approved test key in memory, never writes response text or secrets,
and reports unsupported/unverified functionality separately. `--limits` makes at most
eight burst requests and waits for counter recovery; it is paid synthetic traffic.
`--probe-bearer` currently fails explicitly rather than treating unsupported auth as a pass.

The `/v1` placeholder remains unconditionally denied. Editing the production Product,
catalog or manifest cannot activate it. Any future production activation needs a separately reviewed
implementation using the verified native contract, not an escape hatch around policy.

## Earlier native provisioning investigation

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

A canonical sample's preview `subscriptionKeyParameterNames.bearer = "enabled"` setting
was tried on this instance. ARM accepted the update but omitted it on readback, and
bearer-only access returned 401. The ineffective configuration was removed; native header
authentication remains required.

User-directed verification is CLI-only: Azure CLI authentication, ARM reads and direct
HTTPS probes, not Azure portal sign-in. On 2026-10-12, an ARM API-list read using
`2025-09-01-preview` confirmed only the disabled `/v1` and guarded `/dev/v1` APIs,
both subscription-required, with no model/LLM configuration properties exposed.
Fresh CLI-driven acceptance passed 21 baseline/error/model-completion checks.
Provider registration was `Registered`, but its resource-type listing returned empty;
that result does **not** prove preview unavailability. Likewise, absence of a portal
tile is not definitive rollout evidence.

At that point, the remaining native blocker was a supported, reproducible management-plane contract
and verified target rollout, **not browser authentication**. Do not require the user to
sign in as a verification workaround or invent resource/policy fields to fill that gap.

## Catalog integration

The shared source is `gateway\catalog\models.json`, currently exactly `{"models":[]}`.
That is the **production** source. The separately bundled development source
`gateway\catalog\dev-models.json` is activated only after adapter acceptance.
Its three enabled models advertise `chat` and the 64-token output bound;
the six preview placeholders have no capabilities and cannot be enabled.
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
region as a model-backend region. Successful guarded calls now expose the exact selected
Sweden backend IDs and matching Foundry host in gateway metadata. This proves those
observations, not failover or both-region selection coverage. Ingestion resolves an exact
`backends[].id` against the reviewed catalog, never the pool or caller metadata. Pooled
models with missing/unknown endpoint IDs remain visibly incomplete even if a default model
region exists; duplicate endpoint IDs are rejected.

Native documented logs contain PromptTokens, CompletionTokens, TotalTokens, ModelName,
DeploymentName, IsStreamCompletion and correlation IDs. Cached-read/write counts and true
TTFT are **unsupported by that log contract**. Do not substitute zero, gateway TotalTime,
backend response headers, or playground timing. Retry/terminated/cancelled stream usage
may be partial/missing. Show known estimated cost and coverage independently; never
invoice-grade billing or zero-cost unknowns. See `docs\capabilities.md`.

APIM HTTP body collection is zero bytes, request/backend headers are empty, and LLM
message settings are omitted. LLM metadata logging is explicitly enabled using the
documented preview diagnostic schema and `GatewayLlmLogs` category; prompts/completions
are not enabled. Information verbosity and 100% sampling collect successful gateway
metadata as well as failures. The ingestion operation filter accepts the deployed `chat`
operation and the final contract's `chat-completions` operation. Model attribution considers
both exact deployment and model identifiers, since native model names can include a version.

Before explicit LLM diagnostic activation, successful gateway and LLM correlation IDs did
not join. After activation on 2026-10-11, both fresh Luna/Sol completions joined by exact
correlation ID, each with 9 input and 4 output tokens. The same bounded post-change window
had 21 gateway rows with zero captured bodies and 19 LLM rows with zero captured messages.
Live SQL ownership, reviewed catalog/pricing and scheduled ingestion remain unverified;
the Function stays disabled. Do not time-join unrelated requests or fabricate usage/region.
WAF/access diagnostic
sinks are deliberately not enabled because matched values/URLs can contain prompts or
credentials. Do not enable allLogs, raw trace/debug, or application request/response logging.

Existing app logging/content-share hardening was applied without enabling the ingestion
Function or changing SQL/TLS settings. API health/readiness still return 200 and anonymous
control access returns 401. A subsequent full refresh still proposes app logging,
Function content-share, policy serialization and SQL vulnerability-assessment changes;
this is not a no-drift deployment. Do not blanket-apply those changes or disable an
existing SQL vulnerability assessment.

The current control-plane source was built as immutable ACR image
`sha256:d689dbae4a590ef78060dbda5b6e0fbc595e3750a2fc3d045e074bbfcd87b412`.
ACR build `cag` and runtime smoke `cah` succeeded, including native safety metadata and
endpoint-catalog imports. The API now runs that image; after restart health/readiness
returned 200 and anonymous `/api/me` returned 401. A targeted Terraform image plan tried
to disable the existing SQL express vulnerability assessment as a dependency; it was
not applied. Only the App Service image was updated, retaining registry managed identity,
network restrictions, SQL assessment and closed catalog/ingestion flags.

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
