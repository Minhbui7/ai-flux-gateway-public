# AIFLUX technical specification

## Scope and source hierarchy

This describes repository contracts, not a live deployment attestation.
[Capabilities](capabilities.md) owns release status and reconciliation history;
[PRD](prd.md) owns business stories; runbooks own executable operational steps.
Source/configuration takes precedence over old prose for behavior/defaults.
Historical tests establish only their recorded scope, not current availability.

## Components and interfaces

| Component | Implementation | Responsibility / dependencies |
| --- | --- | --- |
| Customer SPA | `apps/customer-portal`, shared `packages/ui` | Catalog, keys, text playground and owned showback; Entra, control API and direct APIM |
| IDS SPA | `apps/admin-portal`, shared `packages/ui` | `/admin/` entry, organizations/members/prices, showback/safety metadata |
| Control plane | `services/control-plane/src/aiflux` | FastAPI authorization, SQL ownership, APIM ARM subscription operations; never inference proxy |
| Gateway | `gateway/policies`, OpenAPI files, `infra/terraform/apim.tf`, `dev-unified.tf` | Subscription enforcement, limits, inspection, model routing/translation and metadata |
| AI dependencies | `infra/models/model-spec.json`, `infra/terraform/main.tf` | OpenAI/Foundry Direct/Anthropic model endpoints; Language and Content Safety |
| Data | `models.py`, migrations, `infra/terraform/data.tf` | Organizations/members, subscriptions, effective prices, usage, watermark, audit and safety metadata |
| Ingestion | `services/usage-ingestion`, `ingestion.py`, `queries/usage.kql` | Monitor metadata to owned SQL projections, bounded replay and pricing |
| Edge and network | `edge.tf`, `network.tf`, `private-data.tf` | Conditional WAF/TLS edge, private data DNS/endpoints, API/Function integration |
| Provisioning | `infra/terraform`, separate `infra/models` | Reviewed Terraform roots, model verification/catalog publication; no general customer one-click installer |

The [README topology](../README.md#architecture) and
[editable diagram](architecture.drawio) distinguish direct development paths
from conditional edge paths. Neither diagram verifies serving state.

## Trust boundaries and request flows

**Portal/control plane:** MSAL SPA authorization-code/PKCE obtains a delegated
token for the configured API scope. `/api/me` establishes application identity.
The API verifies tenant-specific identity and scope, then enabled SQL
organization/member approval. Customer scope derives from the token/member,
not a caller-selected organization. IDS requires the home-tenant SQL role.
Entra app roles/preauthorization do not replace these checks.

**Inference:** API clients and playground send `Ocp-Apim-Subscription-Key`
directly to APIM. The conditional guarded adapter checks allowed shapes and
limits, original-input safety/Prompt Shields, batched PII, redacted-input safety,
provider translation and buffered output safety before returning answer text.
Anthropic validated thinking blocks are omitted, not exposed as final content.
Gateway UAMI authenticates backend calls. Provider processing may cross borders;
the control-plane SQL region does not establish model data residency.

**Subscription management:** SQL commits ownership before APIM activation.
UUID idempotency keys bind create requests; conflicting reuse returns 409.
APIM failure records failure and returns an error; reconciliation retries the
owned subscription rather than creating a duplicate. Secret reveal uses APIM
`listSecrets`, no-store responses and no SQL credential persistence.

**Ingestion:** metadata logs correlate gateway and model usage with exact APIM
subscription ownership, configured product/operation and actual attribution.
Bounded overlap reads produce idempotent projections. Unknown ownership,
invalid counters or partial results fail without advancing the watermark.
Late data outside overlap requires reviewed replay; no arbitrary ID truncation,
test-prefix matching or silent dropping.

## API and authentication surface

| Surface | Authentication / contract |
| --- | --- |
| `/health`, `/ready` | Liveness and identity/database/table readiness respectively; neither proves inference or release acceptance |
| `/api/me`, `/api/models` | Delegated API token plus enabled organization/member |
| `/api/subscriptions` and `/{id}/reveal`, `/rotate`, `/state`, `/reconcile` | Same membership plus subscription ownership; create requires UUID `Idempotency-Key` |
| `/api/usage`, `/export`, `/timeseries` | Customer authorized scope; days/subscription and applicable viewport/page inputs |
| `/api/admin/organizations`, `/members`, `/prices`, `/usage`, `/safety` | Home-tenant IDS approval; admin usage/export/charts respect organization/subscription scope |
| `/dev/llm/v1/models`, `/chat/completions` | Guarded subscription-required adapter, explicit text-only provider translation |
| `/dev/v1` | Separate legacy OpenAI development API/product and limits |
| Native `/v1`, experimental `/llm/v1` | Denied/unaccepted; do not infer bearer subscription support from OpenAI SDK conventions |
| Function readiness | Function-key protected operational check; not a customer showback API |
| ACME challenge | Conditional exact challenge token route only; does not authorize general HTTP application traffic |

See generated FastAPI `/openapi.json`, `app.py` and the gateway OpenAPI files for
exact methods/schema. #10 / PR #14 proposes model filters and authorized
`/api/usage/models` and `/api/admin/usage/models` (`Page[str]`) discovery.
These are pending, not current-main endpoints; see [roadmap](roadmap.md).

## Data and metric contracts

`Organization` and `Member` define tenant ownership and explicit enabled access;
team subscriptions connect SQL identity to APIM identity/state/idempotency.
Prices have effective periods and model/provider/region/token-category semantics.
Usage records retain correlation, observed metrics and completeness; safety
events and audit records contain metadata, not chat transcripts.

Minute charts are UTC, sparse, 60-second buckets in half-open ranges. Average
latency uses measured samples and seconds; summary/row/CSV millisecond fields
remain unchanged. Missing tokens/latency remain null; partially observed totals
are lower bounds. Idle request minutes are not zero-latency measurements.
Known cost is list-rate showback, not the invoice. Native cache/TTFT and retry
coverage limitations remain explicit in [capabilities](capabilities.md).

## Configuration reference

Values below are **source defaults**, not instructions to deploy them.
All `AIFLUX_` names map to `Settings` in `config.py`; `.env.example` is an example,
which can differ from class defaults (notably MISE and completion ceiling).
Public IDs/URLs are not secrets, but runtime/state/evidence still require
access control. Never supply keys/passwords to portal build arguments.

| Input(s) | Default / requirement | Consumer, validation and consequence |
| --- | --- | --- |
| `AIFLUX_ENVIRONMENT` | `development` | API; production requires passwordless encrypted `mssql+pyodbc` |
| `AIFLUX_DATABASE_URL` | Empty; required for readiness | SQL URL, ODBC 18 for Azure SQL; no credentials/opaque production ODBC string, validate certificate |
| `AIFLUX_ENTRA_AUDIENCE`, `HOME_TENANT_ID` | Empty; required identity settings | API audience and home tenant UUID; wrong/missing values deny readiness/access |
| `AIFLUX_ENTRA_CLIENT_ID`, `BOOTSTRAP_OBJECT_ID` | Empty | Telemetry client identity and explicit bootstrap operator; bootstrap refuses conflicting/disabled ownership |
| `AIFLUX_REQUIRED_SCOPE` | `access_as_user` | Required delegated `scp`; no automatic tenant/member approval |
| `AIFLUX_MISE_VALIDATION_ENDPOINT` | Class default unset; example loopback `/Validate` | Optional loopback-only validation branch; empty selects direct JWT key discovery |
| `AIFLUX_GATEWAY_URL`, `GATEWAY_MAX_COMPLETION_TOKENS` | Empty URL; ceiling unset in class (example 64) | Catalog/playground endpoint and optional 1-100000 clamp; must match gateway accepted limit |
| `AIFLUX_APIM_RESOURCE_ID`, `APIM_PRODUCT_ID` | Empty resource, product `aiflux` | ARM and ingestion scope; direct-dev Terraform selects separate adapter product |
| `AIFLUX_LOG_WORKSPACE_ID` | Empty | Monitor query source; workspace identity is not customer tenant identity |
| `AIFLUX_CATALOG_PATH`, `CATALOG_CONFIGURED` | `gateway/catalog/models.json`, false | Catalog eligibility; direct-dev uses dev catalog only under accepted gates |
| `AIFLUX_CORS_ORIGINS` | Empty list | Exact allowed portal origins; Terraform serializes JSON, never wildcard/credential allowance |
| `AIFLUX_ACME_CHALLENGE_ENABLED`, `ACME_CHALLENGE_DIRECTORY` | false, `/home/aiflux-acme-challenges` | Explicit issuance/approved renewal route, not general auth bypass |
| `AIFLUX_INGESTION_OVERLAP_MINUTES`, `INITIAL_DAYS` | 60, 1 | Replay window and initial lookback |
| `AIFLUX_INGESTION_BATCH_MINUTES`, `DELAY_MINUTES`, `MAX_ROWS` | 60, 5, 10000 | Bounded Monitor ingestion; excessive/partial data must not advance watermark |
| `AIFLUX_INGESTION_START_AT` | Unset | Timezone-aware activation cutoff; conflicting later cutoff cannot silently skip existing state |
| `VITE_ENTRA_CLIENT_ID`, `VITE_API_SCOPE` | Required | Compiled public SPA configuration; invalid settings show configuration error |
| `VITE_ENTRA_AUTHORITY` | `https://login.microsoftonline.com/organizations` | Compiled; dedicated dev uses tenant GUID. Default does not establish customer multi-tenant acceptance |
| `VITE_CONTROL_API_URL`, `VITE_GATEWAY_URL` | `/api`; gateway required | Compiled secure/local URLs; gateway base includes `/v1`; exact origins must match deployed paths |
| `CONTROL_ORIGIN`, `GATEWAY_ORIGIN` | Optional for same-origin | nginx runtime CSP extensions, origins only; cannot change compiled API destination |

Names in combined rows share the stated prefix, e.g. `HOME_TENANT_ID` means
`AIFLUX_HOME_TENANT_ID`. Configuration sources:
[API settings](../services/control-plane/src/aiflux/config.py),
[portal validation](../packages/ui/src/config.ts),
[Terraform app mapping](../infra/terraform/apps.tf).

### Infrastructure and model inputs

| Input family | Default / constraints | Review consequence |
| --- | --- | --- |
| `subscription_id`, `resource_group_name`, `location`, `name_prefix`, publisher, `network` | Required; RG is existing; CIDRs validated | Select exact customer scope; RG metadata is not model/SKU availability |
| `deployment_approved`, `deployment_stage` | false, `apim` | Cost/config gate separate from inference; stages include prerequisites/platform/edge-bootstrap/edge-candidate/public-edge |
| `public_edge_live_gates_approved`, `private_sql_connectivity_accepted` | false | Require actual evidence; public-edge does not follow automatically from apply |
| `hybrid_private_data_enabled` | false | When enabled requires all SQL/vault/storage public flags false, SQL enabled and both private/integration subnet inputs |
| SQL/vault/Function storage public flags | true in generic inputs | Not approved customer posture; recorded hybrid dev overrides false; review governance before any apply |
| `entra`, `sql_admin`, `apps`, operator/edge inputs | Conditional stage requirements | Existing identities, immutable images, approved exact operator egress, DNS/certificate and timeouts |
| `dev_openai_inference_enabled`, `dev_unified_inference_enabled`, `dev_direct_portals_enabled`, `dev_catalog_accepted` | false | Separate reviewed development gates; direct origins cannot be combined with final public-edge |
| `dev_openai_rpm_limit`, `dev_unified_tpm_limit`, `dev_unified_max_completion_tokens` | 2, 2048, 64 | Higher historical overrides are not defaults; safety threshold and per-model caps come from validated inputs/policy |
| Candidate / accepted alias sets | Empty | Temporary hidden candidates differ from published accepted models |
| `ingestion_enabled`, `dev_price_bootstrap_enabled` | false | Valid ownership/catalog/prices before activation; disable temporary price importer after seeding |
| `mise_sidecar_enabled` | false | Optional App Service sidecar; deployment/configuration is not compliance proof |
| Model spec/catalog/prices | Pinned files under `infra/models` and `gateway/catalog` | Exact model versions/regions/quotas; unknown new-model prices not inherited; serialize model deployment writes per runbook |

The complete authoritative inventory and validation is
[`variables.tf`](../infra/terraform/variables.tf), not this summary.
Model quota is not provisioned throughput or a sustained performance guarantee.

## Operations and verification

Use [Infrastructure](infrastructure.md) for the reviewed local operator route,
separate migration/grant steps, private execution prerequisites and image
readiness. `infra/operator` and `infra/state` retain deferred designs; do not apply
them to take over the active root's VNet. #11 must define any customer automation.

CI validates Python types/lint/unit/contracts/migrations, portal types/tests/build,
and Terraform schemas/mocked tests without provisioning. API readiness is not
model, customer journey, network-origin or security approval acceptance.
See [Gateway](gateway.md) for bounded live tests, which require separate scope
and cost authorization. No deployment or live inference is required to publish
this technical specification.
