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
URL. Run migrations explicitly from a runner inside the private network; never
run schema creation on web-server startup.

The container build context is the repository root:

```powershell
docker build -f services\control-plane\Dockerfile -t aiflux-control-plane .
```

`/health` is liveness only. `/ready` verifies required identity/database settings
and SQL connectivity. Neither proves gateway/model readiness.

## Identity and authorization

React obtains a delegated access token for the control-plane audience and
`access_as_user` scope. Register an organizational multitenant application with
that scope; customer administrators grant tenant consent. Personal Microsoft
accounts are not supported.

The API checks the JWT signature, tenant-specific issuer, audience, expiry,
not-before, scope, approved tenant, and approved `(tid, oid)` membership on every
request. An IDS role is only accepted in the configured home tenant. Customer
requests cannot select another organization's context via headers or query
parameters.

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

The ingestion Function imports `aiflux.ingestion`, the same package as the API.
CI assembles its wheel into `services\usage-ingestion\wheels` for deployment.
Run `aiflux-ingest` from an authenticated private-network environment to execute
one bounded ingestion batch. Timer executions replay an overlap window and
advance the durable watermark only after the database transaction succeeds.

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
These remain nullable and the dashboard marks them unsupported. Gateway total
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
