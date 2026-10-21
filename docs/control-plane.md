# Control plane and usage ingestion

The FastAPI service provisions team subscriptions through APIM's ARM API. It does
not forward model requests, store conversations, or execute tools.

See the [technical specification](technical-specification.md) for configuration
and data-flow context, [PRD](prd.md) for stories, and
[security/approval guide](security-and-approvals.md) for operator/runtime rights.
[Capabilities](capabilities.md) owns deployment-status interpretation. #10 /
PR #14 usage-model discovery/filtering is pending, not a current-main API here.

## Local setup

From the repository root in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item services\control-plane\.env.example .env
# Edit .env with approved Entra identifiers. Never put secrets in this file.
.\.venv\Scripts\alembic.exe -c services\control-plane\alembic.ini upgrade head
.\.venv\Scripts\aiflux-bootstrap.exe
.\.venv\Scripts\uvicorn.exe aiflux.app:app --port 8000 --no-access-log
```

SQLite is for development and deterministic tests only. It does not bypass
authentication. No tenant or user is approved automatically. Bootstrap requires
the operator's home tenant and Entra object ID, creates an IDS membership, and
refuses to override a disabled organization or conflicting membership.

Production requires an `mssql+pyodbc` database URL, ODBC Driver 18, encryption and
an identity authorized as a contained Azure SQL user. The application obtains an
Azure SQL access token on each connection. Do not put database passwords in the
URL. In the deployed hybrid development environment, SQL public access is disabled:
migrations and contained-user grants require an approved private execution path
using the Entra-authenticated operator, not the runtime managed identity.
The App Service/SCM operator `/32` is not a SQL access rule. SCM DNS/TCP success
does not establish operator SQL authentication, and operator SQL tokens must not
be embedded in SCM command payloads. After operator migrations/grants, run
`aiflux-bootstrap` with the reviewed identity settings and verify the home-tenant
administrator membership and runtime `/ready` 200. Only separately approved legacy
public-data deployments use reviewed operator/App Service SQL firewall rules.
Never run schema creation on web-server startup.

The container build context is the repository root:

```powershell
docker build -f services\control-plane\Dockerfile -t aiflux-control-plane .
```

`/health` is liveness only. `/ready` verifies required identity/database settings,
SQL connectivity and read access to all application tables using constant-only
projections (no tenant data returned). Neither proves gateway/model readiness.
SQL Server approval predicates use Boolean equality, not `IS TRUE`: SQLAlchemy
renders the latter as invalid SQL Server `IS 1`, even though SQLite accepts it.
Regression coverage compiles the actual signed-in organization/member queries
with the SQL Server dialect, not only SQLite execution.

## Identity and authorization

React obtains a delegated access token for the control-plane audience and
`access_as_user` scope. The DEV API/customer/admin registrations use
`AzureADMyOrg` and a tenant-GUID authority; multi-tenant registration requirements
are deferred to the customer production environment. Personal Microsoft accounts
are not supported.

The API checks the JWT signature, tenant-specific issuer, audience, expiry,
not-before, scope, approved tenant, and approved `(tid, oid)` membership on every
request. An IDS role is only accepted in the configured home tenant. Customer
requests cannot select another organization's context via headers or query
parameters.

### MISE token validation and Microsoft SFI compliance

This section describes integration intent and configured code paths, not a
compliance attestation. Confirm the deployed validation mode and the customer's
required evidence; telemetry headers alone do not establish SFI/MISE compliance.

Under Microsoft Secure Future Initiative (SFI) guidelines and MISE Compliance KPI requirements,
the control-plane API (`aiflux-example-dev-api`, App ID `00000000-0000-4000-8000-000000000003`)
supports compliant token authentication:
- **MISE Sidecar validation**: When deployed on Azure App Service with sidecar support (`AIFLUX_MISE_VALIDATION_ENDPOINT=http://127.0.0.1:8081/Validate`), token verification delegates via loopback HTTP to the Microsoft Entra ID authentication sidecar (`mcr.microsoft.com/entra-sdk/auth-sidecar:latest`). The sidecar performs token validation and emits OneCollector client telemetry (`s2svalidation_counter`).
- **Telemetry-compliant key discovery fallback**: In environments without the sidecar (such as local development and automated testing), direct eSTS key discovery through `PyJWKClient` includes compliant MISE client telemetry headers: `User-Agent: MISE_Python/2.4.1`, `x-client-SKU: MISE_Python`, `x-client-VER: 2.4.1`, `x-app-id: <client_id>`, and `x-client-current-telemetry: 2|1001,0|<client_id>,0|`.
- **Loopback isolation**: `AIFLUX_MISE_VALIDATION_ENDPOINT` is strictly validated to ensure only local loopback endpoints (`127.0.0.1`, `localhost`, `::1`) and the `/Validate` path are accepted, preventing arbitrary remote token egress.

Configure `AIFLUX_CORS_ORIGINS` as a JSON array of exact portal origins when they
are hosted separately. Same-origin deployment needs no CORS allowance.

## Subscription operations

See `/openapi.json` for the generated control-plane contract. The main routes are:

| Operation | Route |
| --- | --- |
| Identity / active catalog | `GET /api/me`, `GET /api/models` |
| Customer subscription metadata / Playground key | `GET /api/subscriptions`, `POST /api/subscriptions/{id}/reveal` |
| IDS subscription list / create | `GET/POST /api/admin/subscriptions` |
| IDS explicit key reveal / rotate | `POST /api/admin/subscriptions/{id}/reveal`, `/rotate` |
| IDS suspend / reactivate / reconcile | `PUT /api/admin/subscriptions/{id}/state`, `POST .../reconcile` |
| Scoped showback / export | `GET /api/usage`, `GET /api/usage/export` |
| Scoped minute charts | `GET /api/usage/timeseries`, `GET /api/admin/usage/timeseries` |
| Customer tokens stacked by model | `GET /api/usage/model-tokens` |
| Historical usage models | `GET /api/usage/models`, `GET /api/admin/usage/models` |
| IDS onboarding | `/api/admin/organizations`, `/api/admin/members` |
| IDS showback / safety / prices | `/api/admin/usage`, `/api/admin/safety`, `/api/admin/prices` |
| IDS gateway settings / history / reconcile | `/api/admin/gateway-settings`, `/{scope}/history`, `/{scope}/reconcile` |

### Admin-managed gateway settings

#### Legacy configuration

The following contract remains available when versioned controls are disabled.
For team/subscription controls and the separate safety page, use the versioned
contract below. Both are opt-in; implementation does not imply live activation.

This feature is opt-in for the guarded development APIs, not production `/v1`.
Terraform `dev_admin_settings_enabled` controls the fragment resources, narrowly
scoped identity permissions and `AIFLUX_GATEWAY_SETTINGS_SCOPES`. With no scopes,
the settings list is empty and mutations fail explicitly; existing code-managed
settings are unchanged. Never set the application environment variable alone.

Only approved home-tenant `ids_admin` principals can list, publish, reconcile or
read history. The customer portal has no settings controls. Scope is API-wide:
`dev-openai` (`/dev/v1`) or, when deployed, `dev-unified` (`/dev/llm/v1`).
There are no tenant overrides, inspection-disable switches or caller-supplied
ARM targets/XML. Completion ceilings, provider/alias allowlists, PII, Prompt Shields,
all three Content Safety checks and production activation remain operator-owned.

| Setting | Accepted values |
| --- | --- |
| `safety_threshold` | Integer 0-7, shared by Hate, SelfHarm, Sexual and Violence on original input, redacted input and output. Higher is more permissive; zero is not off. |
| `rpm` | Integer 1-2 requests/minute |
| `tpm` | Integer 1-2048 for `dev-openai`; 1-20000 for `dev-unified` |
| `token_quota` | Explicit positive integer, at most 2147483647 prompt + completion tokens; this is a representation bound, not a recommended budget |
| `quota_period` | `Hourly`, `Daily`, `Weekly`, `Monthly` or `Yearly`, native UTC fixed window |

No threshold or quota is seeded. Enabling the feature initially denies inference
with 503 until an admin publishes a complete, explicitly approved configuration.
The original explicit Terraform safety prerequisite remains required.

`GET /api/admin/gateway-settings` returns desired configuration, version, latest
published version, publication state and sanitized failure per enabled scope.
`PUT /api/admin/gateway-settings/{scope}` takes `expected_version` (0 for initial
configuration), `configuration` containing every field above, and a nonempty
`reason` (maximum 500 characters). Values must be JSON integers, not strings,
booleans or fractional numbers. Unknown fields and scopes are rejected.

SQL stores revisions before publication. The settings fragment is rendered only
from validated values and published with its exact APIM ETag. Readback must match
before a revision becomes `published`; an APIM response alone is not enough.
Fragment writes also wait for APIM's asynchronous validation result (up to
60 seconds per fragment). A rejected or timed-out operation leaves a failed
revision for explicit reconciliation rather than reporting success.
Stale version, unrecognized fragment drift or another pending revision produces
409, not a blind overwrite. APIM publication/readback failure produces 502 and a
durable failed revision. Retry using
`POST /api/admin/gateway-settings/{scope}/reconcile` with `expected_version`.
This also detects a previous write that succeeded remotely before a timeout/crash,
without reapplying it. Reconciliation is explicit and durable, not fire-and-forget;
there is no automatic worker or claim of automatic convergence.

`published` means matching management-plane readback, **not** live, atomic
gateway-wide enforcement. APIM propagation is eventual: old settings may continue
to be enforced while a revision propagates. The request-scoped threshold is
captured with its RPM/TPM/quota snapshot by a single inbound fragment and reused
for all inspection passes. A missing fragment/threshold or inspection failure
does not bypass safety. For urgent tightening, the operator must block affected
traffic using the existing inference gate before publishing and verifying the
new revision; this feature does not promise an immediate distributed cutover.

`GET /api/admin/gateway-settings/{scope}/history?offset=0&limit=50` is paginated
(maximum 100). Immutable configuration, reason, actor and time are retained;
publication status/error can change during retry. Existing `AuditEvent` rows link
requested, published and failed operations to `scope:version`. Reasons must not
contain prompts, responses, keys, entity mappings or other sensitive content.
Reverting means selecting a prior history configuration and publishing it as a
new version with a new reason and approval, never rewriting history.
Reconcile failed/pending publication first; an out-of-band fragment conflict needs
operator recovery to a known reviewed snapshot before retrying.

Managed counter keys are stable `rpm:{scope}:{subscription}:{alias}` and
`tpm:{scope}:{subscription}:{alias}`. This deliberately isolates the two dev APIs
because they have different TPM ceilings; legacy keys omitted API scope. Initial
opt-in changes the namespace and effectively starts new counters. Later settings
revisions do not change keys; changing quota periods can change reset behavior.
Native rate denial is 429, native quota denial is 403 (`token_quota_exceeded`),
and safety denial is a separate 403 (`content_safety_rejected`). Dependency errors
remain fail-closed 503. Native counts are gateway-local, estimated and may overshoot
under concurrency; they are not strict global billing/spend enforcement.

Use migration `0003` before deploying this API version. Package the bootstrap
fragment (`gateway/policies/settings-unconfigured.xml`) as in the API Dockerfile.
Terraform owns the invariant API policy and all backends, and only ignores the
runtime fragment's `body.properties.value`. The API identity has read/write rights
only at the exact settings-fragment resources, not service-wide policy or backend
write. A subsequent Terraform apply must preserve published fragment values.
An intentional fragment replacement resets it to denied and needs explicit
republication. Do not treat reverting application code, changing activation flags,
or running Terraform as a substitute for audited configuration rollback.

#### Versioned team limits and Content Safety

Operator configuration `dev_gateway_controls_v2_enabled` opts into contract
`schema_version: 2`. Migration `0003` creates tenant-scoped stable team IDs and
backfills existing subscriptions using their exact labels (case differences
remain distinct). Admin subscription creation still accepts `team`
and associates it with a stable ID; no API key value is stored in settings.

`GET /api/admin/gateway-targets?offset=0&limit=100&organization_id=<uuid>` returns
paginated organization/team/subscription IDs and names. IDS administrators only;
organization/target associations are checked again before publication. Unknown,
unmigrated, disabled-organization and oversized targets cannot bypass validation.

Versioned gateway configuration:

```json
{
  "schema_version": 2,
  "defaults": {
    "rpm": 2, "tpm": 1024, "token_quota": 10000, "quota_period": "Daily",
    "concurrency": 2, "request_quota": 100, "request_quota_period": "Daily"
  },
  "teams": [],
  "subscriptions": [],
  "safety": {
    "profile": "Custom", "hate": 1, "violence": 1, "sexual": 1, "self_harm": 1,
    "prompt_attack": true, "protected_material": false,
    "input_filtering": true, "output_filtering": true
  }
}
```

These are illustrative values, not automatically seeded budgets. Team entries
contain `organization_id`, `team_id`, `limits`; subscription entries contain
`organization_id`, `subscription_id`, `limits`. Each override is a complete set of
limits. Inheritance is defaults -> team -> subscription; an additional aggregate
team ceiling applies even where subscriptions override inherited limits.
`request_quota: null` explicitly disables that request-count quota; it does not
disable TPM, token quotas, concurrency or any aggregate team constraint.
Concurrency is one of 1/2/4/8/16. RPM stays within the operator-approved ceiling
(default 2); TPM uses the lowest supported ceiling across configured routes.

Both guarded routes share **one configuration, revision and counter namespace**.
Saving either alias publishes the same typed snapshot to all provisioned scopes.
This avoids incompatible token-counter values or fresh budgets by switching API,
model, primary/secondary key or settings revision. Key rotation keeps counters.
Initial legacy-to-versioned cutover changes namespaces: explicitly approve its
counter-reset effect. Period/team identity changes can change applicable counters.

Membership bindings are frozen into each publication for deterministic retries.
Admin creation automatically publishes a fresh membership snapshot using unchanged
published limits/safety values. Uninitialized settings, pending administrator
edits, drift or publication failures leave `gateway_access: pending` separately
from APIM lifecycle `state`. Reconcile retries only a membership revision owned
by that subscription, never another administrator's pending configuration edit.
Duplicate create/reconcile calls do not add revisions once membership is published.
No initial defaults or capability approvals are invented. Customers still fail
closed with `subscription_controls_unpublished` until publication succeeds.
Limits do not cover anonymous/preflight/
model-list/invalid-shape requests. Validated generation attempts reaching admission
count even if later inspection/backend work fails; retries are not new client calls.
Layered native counters are not transactional and can increment before a later
gate rejects. Native limits are distributed estimates, not monetary hard caps.

Daily request counters partition at UTC midnight; Monthly means a UTC calendar
month. These use stable, calendar-partitioned native lifetime counters, not a
30-day approximation. Monthly selection is capability-gated until operator
validation; counter lifecycle/growth must be reviewed before high-scale use.
Native token quotas retain supported UTC periods and estimation caveats.

The separate `/api/admin/content-safety-settings` list, `/{scope}` PUT,
`/{scope}/history` GET and `/{scope}/reconcile` POST share the gateway revision.
Safety PUT accepts `expected_version`, `configuration` (only the safety object),
`reason` and `acknowledge_relaxation`. Raising thresholds or disabling existing
protection requires explicit relaxation acknowledgement. Gateway PUT must preserve
the current safety object; stale/legacy writes cannot silently discard new fields.
Safety settings require an initialized versioned gateway snapshot.

Application presets Standard/Strict require all four thresholds 4/1 respectively,
prompt protection, protected-text detection and input/output scanning enabled.
They are **not official Azure preset names**. Custom permits thresholds 0-7; lower
is stricter and zero blocks all severities, not "off". Hate covers discrimination/
hate detection, not generalized fairness. Operator floors lock input/output scans
and prompt protection unless separately approved to allow relaxation. Mandatory
input PII redaction is independent and cannot be switched off here.
The Terraform-owned policy also enforces this scan/shield floor against stale
runtime opt-outs when the operator disables relaxation; the API floor is not
the sole enforcement layer.

Protected material is an additional outbound REST scan, not a cosmetic
`llm-content-safety` toggle. It is capability-gated, uses managed identity, scans
bounded normalized output, and fails closed on service/shape/size failures.
Supported text detection is not a legal guarantee or a protected-code classifier.
Generated-but-blocked usage remains billable and must remain in FinOps telemetry.
Semantic custom categories and blocklist authoring are not implemented.

Settings responses expose capabilities, operator bounds and enforcement state.
Provisioned-only mode records/publishes settings without claiming runtime
enforcement. Both pages preserve unsaved edits on conflicts. Readback/publication
is not atomic gateway propagation: partial multi-scope failures remain durable,
block subsequent changes and require explicit reconciliation. Previous complete
snapshots can be republished as new audited revisions. No raw XML or caller-
supplied ARM targets are accepted; fragment size is bounded to 64KiB.

### Minute usage charts

Showback, minute charts, and CSV accept an optional `model` string, matched against
the recorded usage model (including historical models absent from the active
catalog). Omitting it preserves all-model behavior. It applies before summary,
p95, capability checks, transaction pagination, chart aggregation, and export
limit evaluation; an unmatched model returns empty usage, not a zero cost.

Historical model routes return `{ "items": ["model-name"], "total": 1 }` with
sorted distinct names from all authorized usage in the selected `days` and
`subscription_id` scope, plus `organization_id` for admins. Options are independent
of selected model, transaction pagination, and chart viewport; they are not
limited to the current page or callable catalog. Customer organization comes
from the authenticated principal. Admin access and subscription ownership checks
are the same as showback. A scope change that removes a selected model visibly
resets the portal to All models only after successful option discovery; errors
are surfaced without silently clearing the filter.

Minute chart queries accept `days` (1-366, default 30), `subscription_id`, `model`, and
optional paired timezone-qualified `start`/`end` timestamps for a viewport inside
that period. IDS queries additionally accept `organization_id`. The same
membership and subscription ownership checks as showback apply. The interval is
60 seconds, timestamps are UTC, and ranges are half-open (`start <= time < end`).
Queries aggregate all matching ingested requests in the database, independently
of request-table pagination; failed and throttled requests count too.

The response contains `items`, `start`, `end`, and `interval_seconds`. Each sparse
minute item reports requests, reported input/output token sums, paired-known
`total_tokens`, `missing_token_requests`, `latency_samples`, and
`avg_e2e_seconds`. Missing minute rows mean no ingested requests, not missing
latency measurements. All-missing token/latency values remain null; partially
observed token sums are lower bounds, not complete totals. Average latency uses
only measured requests and is converted from stored milliseconds to seconds.
The existing summary/row API and CSV millisecond fields remain unchanged.
SQL Server uses `DATEADD`/`DATEDIFF` minute grouping, floating-point latency
averages, and BIGINT token sums; SQLite tests also compile the query with the
MSSQL dialect to catch dialect-specific mistakes.

### Customer model-token aggregation

`GET /api/usage/model-tokens` accepts the same customer `days`, `subscription_id`,
`model` and paired timezone-qualified `start`/`end` filters as the minute-series
endpoint. Organization scoping comes only from the authenticated principal;
foreign or missing subscription IDs return 404. No admin cross-organization
endpoint is added. Viewport checks are shared with the existing series endpoint.

Response: `{items, start, end, interval_seconds}`. Each sparse item has
`{start, end, model, requests, total_tokens, missing_token_requests}`. Grouping is
by UTC bucket and model across all matching rows, independent of pagination.
The smallest interval in 60/300/900/3600/21600/43200/86400/604800 seconds that
produces at most 120 buckets is chosen. Buckets are anchored at 2000-01-01 UTC;
response item bounds are clipped to the half-open viewport.
An absent bucket/model pair means no ingested requests. A null `total_tokens`
means all requests in that pair lack a complete input/output measurement.
Partial known totals exclude incomplete pairs and carry missing-request counts.
SQL Server uses minute `DATEDIFF` bucket indexes and BIGINT token sums; SQLite
tests execute aggregation and compile the production SQL Server expression.
The allowlisted, server-selected interval is a SQL literal so the repeated
grouping expression remains identical with pyodbc positional parameters. User
filters remain bound parameters. Empty model identifiers are displayed as
**Unknown model** without changing their recorded counts.

Subscription creation requires a UUID `Idempotency-Key`. SQL ownership is
committed before activating an APIM key. A failed ARM operation records `failed`
and returns HTTP 502. Retry the same idempotency key or explicitly reconcile.

Subscription management is IDS-admin-only across organizations. Admin creation
requires an explicit enabled `organization_id`; list supports optional
`organization_id`, `offset` and `limit`. Admin output includes organization
identity/name, stable `team_id`, and `gateway_access` (`ready`, `pending` or
`not_managed`) with an actionable `gateway_message`. `ready` describes membership,
not activation: a suspended APIM subscription still cannot send requests.
No schema migration is added: membership-refresh ownership is recorded in the
existing frozen gateway revision document.

Legacy create/rotate/state/reconcile paths remain admin-gated compatibility
aliases (legacy create targets the admin's own organization). Customer writes
return 403. Customer list and active-key reveal remain organization-scoped for
Playground and usage filters. Customers therefore still receive their own key in
the browser: removal of management UI is not admin-exclusive secret custody.
Admin subscription audit events retain the actual actor and target organization.
Reusing a key with a different request returns 409. No secret is stored in SQL.
Keys only come from APIM `listSecrets`, and responses use `Cache-Control: no-store`.

SQL Server update/serializable locks coordinate ownership/state changes.
Disabling an organization first removes portal access and requests suspension of
all owned APIM subscriptions. If ARM fails, the response explicitly reports
incomplete key suspension; retry the **disable** operation until it succeeds.
Reenabling an organization does not reactivate its suspended keys.

The managed identity needs only APIM subscription read/write, listSecrets and
key-regeneration actions on this APIM instance, not Contributor across the
subscription. Secret reveal, rotation, membership changes and configuration
changes write metadata-only audit records.

## Showback and native telemetry limits

**Historical acceptance:** the three-model Function/workload results below
precede the eleven-model expansion. The latest recorded runbook status is a
pause on unowned smoke-test subscriptions, not fresh-ingestion acceptance.
Current live state has not been reverified by this documentation.

The existing Function now uses the supported Python v1 `function.json` binding
model with shared `handlers.py` entry points. Decorator discovery returned zero
functions in isolated and live hosts; explicit metadata loaded both functions
without changing runtime worker files. Live key-protected readiness confirms
ODBC Driver 18, private SQL access, three enabled models and SingtelIDS ownership.
Live scheduled five-minute batches and manual overlap replay complete and commit
the durable watermark. Five effective-dated price rules were seeded using the
API identity, then the temporary importer gate was disabled. The SingtelIDS
three-model pilot reconciles exactly across provider metadata, Monitor, SQL and
the portal's reporting helper: three requests, 60 input tokens, 567 output tokens,
USD 0.00550980, no incomplete estimates. Replaying twice did not duplicate usage;
an unowned subscription UUID returned no customer summary.

The approved single-flight SingtelIDS workload then stopped at USD 15.15973620
estimated model-inference usage, below the conservative USD 20 ceiling:

| Model | Requests | Input tokens | Output tokens | Estimated USD |
| --- | ---: | ---: | ---: | ---: |
| Claude Haiku 5.5 | 2 | 140 | 12,082 | 0.00605500 |
| GPT-5.6 Luna | 2 | 92 | 12,229 | 0.01469320 |
| GPT-5.6 Sol | 64 | 4,742 | 756,001 | 15.13898800 |
| Total | 68 | 4,974 | 780,312 | 15.15973620 |

Final native telemetry, the metadata-only workload ledger, SQL and the portal
reporting helper match exactly. All 68 estimates are complete, with no failed or
throttled requests; two further overlap replays leave totals unchanged.
One transient ARM trace-read HTTP 503 paused the runner with its full reservation
retained. Native metadata reconciled that successful inference before continuation;
the paid request was never replayed. Read-only ARM retrieval now has bounded
transient retries. The ledger uses atomic, flushed replacement and never stores
keys, prompts or answer content. These estimates exclude safety, logging and
infrastructure charges. API readiness and both portal health routes return 200.

`gateway\catalog\dev-prices.json` contains reviewed Global Standard short-context
USD showback rates per million tokens, effective at the explicit activation cutoff:

| Model | Input | Output | Cached read | Cache write |
| --- | ---: | ---: | ---: | ---: |
| GPT-5.6 Luna | 0.20 | 1.20 | 0.02 | Not requested by this adapter |
| GPT-5.6 Sol | 4.00 | 20.00 | 0.40 | Not requested by this adapter |
| Claude Haiku 5.5 | 0.10 | 0.50 | 0.01 | 0.125 (5-minute) |

OpenAI rates were verified in the raw `data-amount` attributes of Microsoft's
[Azure OpenAI pricing page](https://azure.microsoft.com/en-us/pricing/details/azure-openai/),
for `us-east` and `sweden-central`, in the Standard column (not Batch or Priority).
Anthropic's [pricing reference](https://platform.claude.com/docs/en/about-claude/pricing)
names Haiku 5.5 explicitly and confirms that Anthropic-hosted Microsoft Foundry
deployments convert standard model rates to marketplace Claude Consumption Units.
These are configured, pre-tax public-rate estimates, not the invoice or a promise
of negotiated discounts. The adapter's 8,000-character total prompt limit keeps
requests below short-context pricing thresholds; it cannot request explicit
cache control or a 1-hour Anthropic cache. Do not substitute a different model version.

When an interactive admin session is unavailable, the explicit, default-off
`dev_price_bootstrap_enabled` deployment gate runs `python -m aiflux.price_bootstrap`
inside the existing API container using its existing private SQL DML identity.
It validates rules against the accepted catalog, reuses the API's locked period
validation, rejects conflicting periods, and audits the API service principal.
It creates no schema, grants no new permissions and adds no public authorization
bypass. Disable the gate after verifying the five rules; an identical rerun is
idempotent and cannot overwrite configured prices. The temporary command uses
`--serve` to replace the Python process with Uvicorn only after a successful
transaction; no shell quoting is involved. App Service's custom-container
startup argument splitting rejected the earlier shell-quoted command.

The ingestion Function imports `aiflux.ingestion`, the same package as the API.
CI assembles its wheel into `services\usage-ingestion\wheels` for deployment.
Run `aiflux-ingest` from an authenticated, explicitly SQL-allowlisted environment to execute
one bounded ingestion batch. Timer executions replay an overlap window and
advance the durable watermark only after the database transaction succeeds.

An optional timezone-aware `AIFLUX_INGESTION_START_AT` sets the initial activation
cutoff and clamps all overlap reads to it. Restart preserves existing state.
A cutoff later than an existing watermark raises an error rather than silently
skipping records. Historical backfill requires separate reviewed reconciliation.
Distinct backend request IDs within a correlation mark the estimate
`retry_usage_unknown`; this does not prove that telemetry captures every attempt.
The Function's key-protected readiness route verifies driver, catalog and
SQL-table access, plus the durable watermark. An optional SQL subscription UUID
also returns its aggregate summary through the same `usage_response` implementation
used by the portals, without keys, customer identities, prompts or answer text.

The KQL query uses resource-specific `ApiManagementGatewayLogs` joined to
`ApiManagementGatewayLlmLog` on `CorrelationId`, restricted to the configured
APIM resource, Product, and Chat Completions operation. Configure diagnostics as
unsampled metadata-only logs. Gateway `ApimSubscriptionId` maps to runtime SQL
ownership; Azure subscription IDs and workspace `TenantId` are not customer IDs.

Before enabling ingestion, validate the selected gateway's Product/operation IDs,
actual backend attribution, usage and safety trace fields against a live fixture.
Unknown ownership, invalid counters, excessive rows and partial Monitor results
raise errors without advancing the watermark. No unowned usage is silently
dropped. Narrow the configured batch size for higher-volume gateways. Late data
outside the overlap requires an operator-controlled watermark rewind/replay.

Native logging does not document cache-token or first-content-token timing fields.
The guarded adapter supplements native logs with a `finops-v1` information trace:
only validated input/output/cache counters, approved model alias and bounded
backend-attempt count. It captures provider usage before normalization and output
inspection, because blocked outputs can still incur inference cost. Missing
optional provider counters remain null, not zero; malformed or duplicate traces
stop ingestion without advancing its watermark. The dashboard exposes cache
support only when captured records contain counters. TTFT remains unsupported.
Gateway total
elapsed time is E2E gateway latency, **not** client-observed latency or TTFT.
If a model alias maps to multiple regional endpoints and selected-backend metadata
is unavailable, backend region must remain unknown; never use the gateway region
as a substitute.

Price rules are effective-dated and nonoverlapping per model/provider/region.
Close an open period using `PUT /api/admin/prices/{id}/end` with a timezone-aware
`effective_to` before creating its replacement. The next period may start at the
previous end timestamp; a historical closed period cannot be reopened.
Amounts are decimals with an ISO currency code. Cached reads/writes are priced
separately, subtracting them from input totals only where the provider includes
them. Missing counters or configured cache prices without native cache usage
produce incomplete estimates, not free usage. Price creation does not retroactively
rewrite old projections: replay the relevant watermark window to reprice.

Showback lists bounded records, known cost and completeness. Mixed currencies are
never summed into one amount. CSV exports are capped at 10,000 records; narrow
the time/subscription/model filter for larger data and use an IDS data-export process
for bulk retrieval. CSV fields are protected against spreadsheet formula injection.
CSV includes the full filtered period, not the visible transaction page or chart
viewport, and is available even when the portal's default-collapsed transaction
details are closed. Its columns and raw millisecond latency values are unchanged.
Portal costs are estimates from configured list prices, not invoices; actual
charges may differ due to Singtel-specific discounts. This disclosure does not
change pricing calculations, apply discounts, or reprice historical usage.

Safety records use an allowlisted metadata schema from an APIM trace with
`source: "aiflux"` and metadata `category`/`action`. Arbitrary trace content and
original prompts are not persisted. Absence of a safety event is not proof that
no attack occurred; deployment must validate trace coverage for streaming stops
and service failures.

## Required environment

`AIFLUX_DATABASE_URL`, `AIFLUX_ENTRA_AUDIENCE`, `AIFLUX_HOME_TENANT_ID`,
`AIFLUX_APIM_RESOURCE_ID`, `AIFLUX_APIM_PRODUCT_ID`, `AIFLUX_LOG_WORKSPACE_ID`,
`AIFLUX_CATALOG_PATH`, and `AIFLUX_CATALOG_CONFIGURED` must match the reviewed
deployment. Bootstrap additionally needs `AIFLUX_BOOTSTRAP_OBJECT_ID`.

The catalog defaults to unconfigured. It cannot be enabled merely to conceal a
missing native API, inspection gap, or unvalidated Anthropic translation.
