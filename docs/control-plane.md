# Control plane and usage ingestion

The FastAPI service provisions team subscriptions through APIM's ARM API. It does
not forward model requests, store conversations, or execute tools.

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

Under Microsoft Secure Future Initiative (SFI) guidelines and MISE Compliance KPI requirements,
the control-plane API (`aiflux-fdpo-dev-api`, App ID `26f09831-946d-4dd3-874a-9d573ec7e4f4`)
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
| Team keys | `GET/POST /api/subscriptions` |
| Explicit key reveal / rotate | `POST /api/subscriptions/{id}/reveal`, `/rotate` |
| Suspend / reactivate / reconcile | `PUT /api/subscriptions/{id}/state`, `POST .../reconcile` |
| Scoped showback / export | `GET /api/usage`, `GET /api/usage/export` |
| IDS onboarding | `/api/admin/organizations`, `/api/admin/members` |
| IDS showback / safety / prices | `/api/admin/usage`, `/api/admin/safety`, `/api/admin/prices` |

Subscription creation requires a UUID `Idempotency-Key`. SQL ownership is
committed before activating an APIM key. A failed ARM operation records `failed`
and returns HTTP 502. Retry the same idempotency key or explicitly reconcile.
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
the time/subscription filter for larger data and use an IDS data-export process
for bulk retrieval. CSV fields are protected against spreadsheet formula injection.

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
