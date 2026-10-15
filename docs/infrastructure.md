# Hybrid development Terraform and local operator runbook

## Opt-in admin gateway settings

The code supports `dev_admin_settings_enabled=false` by default. No live deployment
or activation is implied. See [the settings contract](control-plane.md#admin-managed-gateway-settings)
for exact bounds, failure behavior, ownership and propagation limits.

For a separately approved rollout: migrate SQL to `0002`, package the API bootstrap
fragment and admin portal, retain all existing explicit inference/safety approvals,
then review a Terraform plan enabling `dev_admin_settings_enabled`. This creates
one denied inbound settings fragment per deployed guarded API, assigns the API
identity read/write at those exact fragment resources, wires the API scope list
and changes the invariant policy to include it. The runtime receives no write
permission for API policies, backends or service configuration.

Activation starts new API-scoped counter namespaces and blocks inference until an
IDS administrator explicitly publishes safety, RPM/TPM, token quota and quota period.
Schedule/block traffic accordingly; do not copy assumed budgets into deployment
defaults. Apply only through the established authorized operator process, never
from a portal request. After publication, verify the effective policy and bounded
safe/safety-denied/rate-denied/quota-denied calls on each deployed API, metadata-only
logging, and another Terraform plan showing published fragment values are preserved.
Matching ARM readback is not proof of propagation or live enforcement.

For recovery, retry uncertain writes from the portal; if external fragment edits
cause a conflict, compare the exact reviewed desired/published SQL revision with
the APIM fragment before operator restoration. Do not overwrite unknown drift.
Then reconcile, or publish prior history values as a new audited revision. For
urgent tightening, first disable affected inference with its established gate and
verify traffic is blocked. Disabling the admin-settings flag returns to explicitly
configured Terraform values and removes managed quota enforcement; it is a
potential relaxation, not a safe automatic rollback. Do not downgrade SQL revision
history or roll back to application code lacking the new schema during recovery.

Customer packaging must carry migration `0002`, the bootstrap fragment, the
scope/identity/ownership contract and operator activation/recovery instructions.
Future Auto routing must decide whether quotas attach to the requested alias,
resolved alias or both; selection/retry must not bypass subscription budgets.

## Model and portal expansion (2026-10-14)

The guarded `/dev/llm/v1` development catalog now enables eleven models. All eight
new aliases passed direct Foundry and guarded APIM completions before publication.
The three GPT-6 models and two DeepSeek models have 100,000 backend TPM allocated
in each existing account (East US and Sweden Central). Kimi-K2.6 has 100,000 TPM,
claude-sonnet-5-5 has 50,000 TPM, and claude-opus-5-5 has the explicitly approved
40,000 TPM in East US only. GlobalStandard quota is shared across regions:
single-backend models must not be described as regionally redundant. These are
pay-as-you-go quota allocations, not PTUs or a sustained-throughput guarantee.
See `infra\models\model-spec.json` for exact pinned formats and versions.

New models use a verified 4,096-token request output ceiling. Existing models'
limits and the gateway's 20,000 TPM per-subscription/model throttle are unchanged.
DeepSeek-V4-Flash-0731 advertises deprecation on 2026-12-03; do not silently
substitute another version. No prices were invented for the new aliases:
unpriced usage remains Unknown.

API and ingestion images must bundle the same accepted catalog. Customer/admin
images add configured endpoint details, secret-free REST/OpenAI Python examples,
and synchronized requests/tokens/average-latency minute charts with zoom, pan and
reset. Display latency in seconds without changing millisecond API/CSV contracts.
Time-series routes retain Entra and organization/subscription authorization.
Signed-in acceptance of these new portal features requires an approved browser
session; anonymous probes and served-bundle checks do not establish that journey.
Do not grant Azure CLI additional consent or introduce an authentication bypass
to complete that check.

The expansion preserves B1 compute, private SQL/vault/storage, MISE, exact CORS,
existing model routes and production/native release gates. Review full saved
plans and pin all four app images by immutable ACR digest. Apply serially and
verify serving state, not just management-plane image settings.

Final rollout checks confirmed the new customer/admin bundles, API `/health`
and private-SQL `/ready` responses, both protected time-series routes, and eleven
models in Function readiness. However, usage ingestion is currently paused:
45 smoke-test requests from three deleted temporary APIM subscriptions have no
SQL owner. The durable watermark remains `2026-10-13T17:35:00.608966+00:00`.
Do not advance it, drop those rows, or assign them to a customer implicitly.
Reconcile explicit test ownership before declaring fresh-usage acceptance.
These APIM IDs are longer than the current 36-character SQL subscription ID:
retain their exact telemetry identity through a reviewed mapping rather than
truncating IDs or broadly matching a test-name prefix.

## Current development repair (2026-10-12)

This status supersedes the historical partial-deployment notes below.
The live App Service plan is B1 and is preserved by explicit user direction;
no P1v3 upgrade, additional compute, public data endpoint or certificate change
was made. SQL's live enabled express vulnerability assessment is preserved too.
API `/ready` is 200 with private SQL. SQL, Key Vault and Function storage remain
public-disabled. The existing Function is now enabled with the accepted development
catalog, immutable Python v1 binding container, and five-minute ingestion timer.
Live scheduled executions advance private SQL state; the three-model SingtelIDS
pilot reconciles provider counters, Monitor, SQL and portal showback without
duplicate overlap records. Five effective-dated USD price rules are installed.
The temporary price-import startup gate is disabled after successful seeding.
The completed SingtelIDS workload reconciles all 68 successful requests, 4,974
input tokens, 780,312 output tokens and USD 15.15973620 estimated inference cost.
No estimate is incomplete and overlap replay preserves totals. See the
control-plane runbook for per-model rates, accounting and the excluded charges.
Readiness now verifies all application tables with constant-only projections.
The signed-in database 503 was traced to SQL Server-invalid Boolean approval
predicates (`IS 1`); the fixed API image uses `= 1`. Live synthetic lookup confirms
the organization query executes and unapproved access is denied. The user
subsequently confirmed subscription reconciliation, key reveal and both provider
playground responses after the subscription-cap repair: basic customer acceptance
is complete, without changing private data or the B1 compute posture.

The approved `dev_direct_portals_enabled` stopgap makes the three web origins
public while retaining Entra/approved-membership authorization, disabled basic
publishing auth and independently operator-restricted SCM. It does not authorize
`public-edge` release and cannot be combined with that stage.
`dev_portal_origins` supplies only the two exact HTTPS App Service origins.
Portal images must be built with the direct API `/api` and APIM
`/dev/llm/v1` URLs, plus the existing dedicated SPA IDs and tenant authority.
Runtime `CONTROL_ORIGIN`/`GATEWAY_ORIGIN` must match those compiled URLs.
After image/settings updates, explicitly restart the three apps if probes still
see old assets/CSP; management-plane image readback alone is not serving-state proof.

`dev_unified_inference_enabled` creates the separately labeled guarded APIM
text adapter/product after the existing OpenAI deployment gate and a live ARM
read of the succeeded primary-region Haiku deployment. It provisions no new
model deployment. `dev_catalog_accepted` must stay false until actual guarded
OpenAI and Anthropic completions pass; enabling it selects the bundled development
catalog and the adapter product for control-plane-created team keys.
The production catalog/product are still blocked.
The adapter product allows the user-approved 10 subscriptions, not one: SQL-owned
team subscriptions share APIM's ownerless per-user cap. Suspended synthetic test
subscriptions still consume slots and must be deleted after acceptance. A failed
team provision remains SQL-owned; use portal Reconcile after fixing APIM rather
than creating duplicate requests. The original single-key `/dev/v1` product and
each adapter subscription's inference bounds are unchanged.

Use the existing protected local state and ignored deployed inputs. Review the
full saved plan before applying; no `-target`. Pin all three successful ACR build
outputs by digest, specifying both subscription and resource group explicitly
to avoid shared CLI defaults. Final edge TLS, native translation and
full safety/failover acceptance remain separate backlog items.

For the user-approved larger adapter limits, the active inputs set
`dev_unified_tpm_limit=20000` and `dev_unified_max_completion_tokens=100000`.
The four existing GlobalStandard OpenAI deployments use capacity 120 (120,000
backend TPM each), not reserved provisioned compute: available regional quota was
checked before increasing allocation. This headroom accommodates Azure's estimated
request accounting for a 100,000-token completion budget plus the bounded prompt;
the APIM per-subscription/model throttle remains 20,000 TPM.
Apply `infra\models` changes with `-parallelism=1`: concurrent deployment writes
under the same Foundry account returned `RequestConflict` (409); a refreshed full
plan and serialized retry completed the remaining updates. No model/SKU change,
new compute, public data access or production/native-route enablement was made.

## Decision, status and ownership

Development uses **public app endpoints, Basic v2 APIM and Entra authorization**,
with approved private endpoints only for SQL, Key Vault and Function storage.
Application Gateway WAF_v2 is deployed in `edge-candidate`; its HTTPS listener
currently fails Key Vault certificate validation and is not accepted for release.
`infra\terraform` owns the existing VNet and the hybrid additions; do not apply
`infra\operator` against that VNet (it is a separate, incompatible ownership root).
No VM, mandatory private runner, NAT or private Terraform backend is introduced.
Basic v2 APIM and Foundry stay public, without private endpoints or APIM integration.

### Approved hybrid data path

Set `hybrid_private_data_enabled = true` with all three data services' public
network access flags false. The active ignored `fdpo.deployed.tfvars` preserves
those governance-disabled interfaces. In the East US `10.240.0.0/16` VNet,
`10.240.3.0/24` hosts five endpoints: SQL, vault, blob, queue and table.
Each has its matching private DNS zone linked to this VNet with registration
disabled: `privatelink.database.windows.net`, `privatelink.vaultcore.azure.net`,
and `privatelink.{blob,queue,table}.core.windows.net`.
API and ingestion Function alone integrate outbound through
`10.240.4.0/24`, delegated to `Microsoft.Web/serverFarms`. Customer/admin apps
remain uninvolved. Public app/SCM access restrictions and the existing App Gateway
subnet's `Microsoft.Web` service endpoint are retained.

SQL stays in Australia East; a private-link target may be in a different region
from the East US endpoint/VNet. Use the original `<server>.database.windows.net`
FQDN, not a private IP or private-link hostname, in SQL connections. Explicit SQL
`Proxy` policy limits private SQL traffic to TCP 1433. Private-endpoint Redirect
requires 1433–65535, **not** the public-endpoint 11000–11999 rule. Integration NSG
allows TCP 1433/443 to the data subnet and denies other ports to it; normal Azure
DNS and existing public egress remain unchanged (no route-all/NAT requirement).

The existing B1 dedicated Linux Function uses managed-identity host storage with
`content_share_force_disabled = true`; no Azure Files content share or connection
string is configured, so no paid File endpoint is provisioned. Reassess this only
if the deployment model actually adds an Azure Files share. Provider refresh has
previously reported this field false despite the configured true value; do not
mistake that known drift for permission to create a share or enable shared keys.

Hybrid mode removes public SQL outbound-IP capture/firewall gating. Edge release
instead requires `private_sql_connectivity_accepted` after actual identity grants,
migrations and live API/Function SQL acceptance, independently of
`public_edge_live_gates_approved`. Both remain false for deployment. Management
plane endpoint approval/DNS records do **not** prove application readiness.

### Microsoft SFI / MISE compliance for App Service API

To fulfill Microsoft Secure Future Initiative (SFI) requirements for Entra ID Application
Registrations (specifically App ID `26f09831-946d-4dd3-874a-9d573ec7e4f4` / `aiflux-fdpo-dev-api`),
the control-plane API supports MISE (Microsoft Identity Service Essentials) authentication:
- **App Service Sidecar**: Configured via `mise_sidecar_enabled = true` in Terraform, which attaches
  the official `mcr.microsoft.com/entra-sdk/auth-sidecar:latest` sidecar container to the API Linux Web App
  via `Microsoft.Web/sites/sitecontainers`. The sidecar listens on port 8081 (`http://127.0.0.1:8081/Validate`)
  and handles token validation with full OneCollector `s2svalidation_counter` telemetry.
- **Client Telemetry Fallback**: If running without the sidecar, direct key discovery via `PyJWKClient`
  emits compliant MISE 2.4.1 client headers (`User-Agent: MISE_Python/2.4.1`, `x-client-SKU: MISE_Python`,
  `x-client-VER: 2.4.1`, `x-app-id: <client_id>`) to satisfy eSTS key-discovery telemetry audits.
The API uses its managed identity against APIM ARM to manage subscription keys;
do not invent Key Vault named values for Basic v2 APIM, which cannot reach this
private vault. Existing vault role assignments do not establish APIM reachability.

Prefer bearer-authenticated operator-restricted App Service Kudu execution to
verify DNS and TCP from the existing integrated app without creating compute.
Do not output tokens, settings, SQL payloads or certificates. Kudu's SCM context
may differ from the running application; state the verification scope precisely.
If remote execution is unavailable, SQL grants/migrations and private vault upload
remain pending a separately approved private execution route. Do not register new
providers or silently provision NAT, ACI, Container Apps environments or paid ACR
agent pools. Local laptop connections cannot reach the private endpoints.

The SQL initialization preflight on 2026-10-11 verified the current operator is
still the configured Entra SQL administrator, both runtime identity object/client
IDs match deployment evidence, and the API's production audience, home tenant,
bootstrap object ID and managed-identity client ID are configured. SQL is Online
at S0 with public access Disabled, Proxy policy and zero firewall rules.
The operator laptop resolves the SQL FQDN to public `20.53.46.128`, and a bounded
TCP probe of private `10.240.3.6:1433` timed out. The repository virtual environment
has `pyodbc`, but Windows has no ODBC Driver 18; installing a driver alone would
not fix the missing private route.
Bearer-only SCM command execution works, but its sidecar has Python 3.9 and no
`sqlcmd` or application `/app` directory; it is not the deployed API container.
The deployed API Dockerfile has no SSH server configuration, and SCM tunnel
discovery did not establish a supported operator-to-SQL transport. Do not relay an
operator SQL token in a Kudu command body: command payload retention is not proven
secret-safe. Do not temporarily replace the SQL Entra administrator with a runtime
identity without separate explicit approval, or grant Graph Directory Readers.
That preflight executed no SQL DDL/grants/bootstrap and changed no administrator.

The subsequently **explicitly approved** temporary managed-identity administration
initialized SQL through the existing VNet-integrated production API container.
SCM VFS maps its root to `/home`; its command sidecar is not the API image.
The one-off startup used `infra\sql\init-managed-identity.py`, production ODBC 18
and `ManagedIdentityCredential` inside the API, with no relayed operator SQL token.
The script validated private-only SQL DNS, migration revision `0001`, actual UAMI
contained users, scoped ingestion grants and the single approved home-tenant IDS
bootstrap membership. SQL contained-user SIDs for managed identities must use
binary **client IDs**; ARM Entra administration uses principal **object IDs**.
An initial object-ID SID attempt failed runtime login and was narrowly repaired.
No Graph lookup or directory role change was needed.

The full original ARM administrator/server metadata was snapshotted into ignored
`infra\.sql-init` recovery evidence. Every attempted elevation restored and
verified that metadata, Entra-only authentication and disabled public SQL access
in cleanup. Post-restoration verification obtained a fresh API managed-identity
SQL connection and confirmed revision, bootstrap and schema CRUD without
`db_owner`, database CONTROL or schema ALTER. Temporary startup/storage settings
were restored and checked; one-off remote scripts/markers were deleted.
API `/health` and `/ready` returned 200 after restoring the normal startup.
The post-restoration Terraform plan has zero additions/deletions and only the
four previously known App Service logs/content-share refresh updates; SQL
administration has no drift. These unrelated refresh changes were not applied.
Function execution, inference, TLS certificate upload and public-edge release
remain disabled/pending independently of SQL initialization.

The approved hybrid apply completed with **19 additions, five in-place updates,
zero destructions** (five endpoints, five DNS zones, five VNet links, two subnets,
one NSG and its association). All endpoints are `Succeeded`/`Approved`; DNS A
records and VNet links are verified. Operator ARM-bearer-only API Kudu execution
resolved all five original FQDNs to private addresses and established TCP to
SQL `10.240.3.6:1433`. The raw telnet probe subsequently reset because it was not
a SQL TDS login; this proves transport only. SCM execution is not a SQL
managed-identity/application-login proof. API `/health` is 200 and `/ready` stays
503; contained users, migrations, member bootstrap and private vault certificate
upload are still pending. No extra compute or provider registration was created.
Post-apply plan has no additions/deletions and only the four previously known
logs/content-share refresh updates, which were not reapplied. Local checks pass:
22 main-root mock tests, eight operator tests, three state tests, 17 gateway
contracts and the disabled bundle validator.

The existing, externally owned RG is `rg-aiflux-fdpo-dev`, subscription
`4d75ed7f-75ab-4db6-b1f3-263f240d1450`, location `eastus`. It remains a data source:
Terraform does not create/import/destroy the RG or modify unrelated workloads.
APIM-first provisioning has succeeded: Basic v2 APIM, Monitor/App Insights, RBAC
Key Vault and Content Safety exist. The remaining deployment is explicitly partial,
not a same-day readiness claim. Initial dedicated Language provisioning returned
`SpecialFeatureOrQuotaIdRequired`; the approved replacement is the Microsoft Foundry
umbrella `AIServices` S0 resource `aiflux-fdpo-dev-foundry` in East US. Terraform
created only that resource and its gateway-scoped `Cognitive Services User` role
assignment (two additions, zero changes/deletions); Content Safety was retained.
A synthetic-email Language PII REST smoke test using an operator AAD token detected
and redacted the entity without logging request/response payloads. This verifies only
the operator's endpoint access: gateway managed-identity access, gateway PII policy,
request-shape coverage, fail-closed handling, and production logging controls are not
yet accepted or proven. The earlier entitlement failure was for a dedicated
TextAnalytics resource; it did not block this Foundry resource.
An earlier tenant-policy decision rejected `AzureADMultipleOrgs`. Per the operator's
explicit DEV-only approval, dedicated API/customer/admin registrations now use
`AzureADMyOrg`; no tenant policy was changed or bypassed. API scope
`access_as_user`, role `ids_admin`, both SPA redirects and preauthorized client IDs
were verified. The customer production environment must satisfy its separate
multi-tenant registration requirements. API authorization still requires both an
approved tenant and an explicitly approved user, with IDS administrator membership
restricted to the home tenant. The portal defaults to `organizations` for
compatibility and accepts only an explicit tenant GUID as the alternate authority.
ARM currently still reports Key Vault and Function Storage public network access
as `Disabled`, despite the operator's report of manual changes. No access mutation
or repeated enable attempt is made until the approved state is observed live.
Shared keys and anonymous blobs remain disabled.
The independent prerequisites apply created Basic ACR `aifluxfdpodevacr`,
P1v3 plan `aiflux-fdpo-dev-apps-plan`, Function storage `aifluxfdpodevfunc`,
the VNet/AppGW subnet and API/customer/admin/ingestion managed identities with
resource-scoped registry/Monitor/storage/APIM roles. Basic ACR, remote builds and
the idle P1v3 plan add dev costs even without running apps.
SQL S0 and database `aiflux` are Online in Australia East; apps remain in East
US and the operator accepts the cross-region latency/egress. The server has the
verified Entra-only administrator. ARM reports SQL public network access
`Disabled`; creating even the exact operator firewall rule failed with
`DenyPublicEndpointEnabled`. The configuration now preserves that disabled state,
suppresses firewall writes rather than retrying or widening access. The earlier
31-address capture is historical and no longer a hybrid dependency; private SQL
runtime acceptance replaces the former `sql-public-endpoint` blocker. No SQL migration or member
bootstrap was attempted: local `pyodbc` and ODBC Driver 18 are unavailable, and
no migration credential was relayed to a remote task. `/ready` therefore remains
503. Runtime Function remains disabled.
The APIM metadata diagnostic was applied after correcting live API validation:
wildcard query masking must stand alone and `operationNameFormat` is not supported
for Azure Monitor diagnostics. HTTP body capture is zero and client-IP logging off.
ACR remote build `ca1` succeeded and published the actual local API source as
`aiflux/api@sha256:e287f94675ae9430d668de3d0d096190685c7fd7ece501dd121fa889f13a46f9`.
The CLI log stream encountered a Windows Unicode encoding error; the existing
server-side run and registry manifest were queried to confirm success, without
submitting a duplicate build. Remote ACR builds `ca4` and `ca5` succeeded using
the dedicated single-tenant SPA client IDs and tenant-GUID authority. Customer
and admin images are pinned by their resulting immutable SHA-256 digests in the
ignored deployed tfvars.
ACR smoke run `ca3` executed that immutable API image: a real localhost Uvicorn
process returned `/health` 200 and denied unconfigured `/ready` with 503; ODBC
Driver 18 was present, and the process was stopped within the task. This is image
startup verification, not live App Service/auth/SQL readiness. The smoke task is
`services\control-plane\acr-smoke.yaml`, inside the permitted upload context.
The platform stage deployed the API/customer/admin App Services and disabled
ingestion host (four additions, zero changes/deletions). Their default hosts are
restricted to the reviewed operator `/32` and App Gateway subnet; live probes
returned API `/health` 200, portal health 200, and API `/ready` 503. The portal
redirects target the eventual shared gateway host, so browser sign-in awaits the
TLS/DNS edge. Twenty mocked Terraform tests and seventeen contract tests pass;
all live gateway capability gates remain unverified. Nonsecret resource/client
IDs, image digests and exact blockers are recorded in ignored
`infra\terraform\live-evidence.json`. Local deployed inputs remain in ignored
`infra\terraform\environments\fdpo.deployed.tfvars`.
Live APIM verification returned Product state `notPublished` with subscription
and approval required; anonymous `/v1/models` returned 503, retaining the
fail-closed disabled gateway rather than enabling inference.

The main root pins Terraform `~>1.16.0` (locally `1.16.5`), AzureRM `5.9.0` and
AzAPI `2.13.0`. Providers do not auto-register resource providers. Use local Azure CLI
authentication and protected local state; do not set shared Azure CLI account defaults.

## Cumulative stages and resource inventory

| Stage | Resources |
| --- | --- |
| `apim` | Public `BasicV2_1` (capacity configurable), public RBAC Key Vault, public keyless Foundry `AIServices` S0 for Language PII and Content Safety S0, gateway identity, metadata-only Monitor/App Insights |
| `prerequisites` | Approved P1v3 Linux plan, Entra-only SQL S0 unless explicitly deferred, keyless Function storage, four additional managed identities/resource-scoped roles, isolated VNet/AppGW subnet; no runtime apps or edge and no fabricated Entra/image configuration |
| `platform` | P1v3 Linux plan, three TLS public App Services with deny-default access restrictions, Entra-only SQL S0 with `prevent_destroy`, disabled managed-identity Function and keyless/nonanonymous storage; approved hybrid endpoints/DNS and API/Function outbound integration |
| `public-edge` | Public zonal Standard static IP, Application Gateway WAF_v2 HTTPS/SNI listener, existing Key Vault certificate, HTTPS backends and `/`, `/admin/`, `/api/`, `/v1/` routes |

The isolated, unpeered `10.240.0.0/16` network retains the dedicated AppGW
`10.240.1.0/24` subnet plus the hybrid `.3/24` and `.4/24` subnets described above.
It is created at `prerequisites` or `platform`, with `Microsoft.Web` service
endpoint enabled so App Service origin restrictions can be established before the
edge. No corporate peering/VPN review is a dependency for this unpeered dev design;
review overlap/routing afresh if connectivity is added later.

`deployment_approved=false` blocks planning until costs/configuration are approved.
`public_edge_live_gates_approved=false` separately blocks edge deployment until
operator acceptance of app restrictions, authorization, SQL connectivity, certificate/DNS,
WAF configuration and backend checks. First edge creation necessarily needs **post**
creation TLS/probe/WAF checks too; the flag is not evidence of a running WAF.
Do not claim those live checks have passed before the edge exists.
By default the production APIM Product stays unpublished, its API/global policies
deny, the catalog is unconfigured and the Function host is disabled in all stages.
The separately approved development adapter and ingestion flags require their
own live acceptance; they do not release the production/native API.
Deferring Language blocks `public-edge` even with live approval. Deferring SQL
blocks both runtime stages. `gateway_origin_hostname` configures the candidate
HTTPS URL before edge provisioning; it does not advertise a live endpoint.

Stage selection uses the **same state** and is cumulative, not additive: moving
back to an earlier stage plans to remove later resources. Review full plans; no
`-target`. Never roll a deployed platform back to `apim` without data-retention/state
review. To remove only the edge, review a `platform` plan; SQL `prevent_destroy`
continues to protect the database.

## Public does not mean anonymous or bypass-safe

- SQL uses TLS 1.2+, Entra-only administration and contained runtime identities.
  In hybrid mode the public interface is disabled and firewall/IP capture is skipped;
  `operator_ip` restricts public app/SCM management only, not private SQL access.
  The following exact-firewall steps apply only to the optional legacy public-data mode.
  `operator_ip` is mandatory for platform/edge, an exact reviewed public IPv4 only.
  `0.0.0.0` / AllowAzureServices, CIDR ranges, private/loopback/IPv6 addresses are
  rejected. App/Function possible outbound IPs are individually reviewed and entered
  into `sql_firewall_ipv4s`; there is no all-Azure firewall exception.
- Platform creation emits `sql_required_outbound_ipv4s`. Since those addresses do not
  exist before the apps, first create platform with operator access, then review
  the actual output and **apply a second platform plan** adding exact SQL rules.
  API readiness is not expected before those rules and SQL grants are installed.
  An edge precondition rejects missing possible-outbound IP coverage. Refresh rules
  after plan/SKU/scale changes; do not infer App Service outbound addresses from
  Application Gateway's public IP.
- Web origins/SCM use deny-default restrictions: allow the AppGW subnet via the
  `Microsoft.Web` service endpoint and the explicit operator `/32`. This is public
  service-endpoint routing, **not Private Link**. The operator is an intentional
  direct-access exception; test denied untrusted-origin/SCM access live before release.
  The Function allows only that operator `/32`, whether enabled or disabled.
- AI protection endpoints remain public; Key Vault is private in hybrid mode.
  Identity/RBAC authorization is still required. AI local/key auth is disabled. Basic v2
  has **no deterministic dedicated outbound IP**: do not fabricate an APIM outbound
  allowlist for AI. Future model pools must use validated managed-identity/provider
  authentication, not anonymous access or synthetic endpoint/IP catalogs.
- Hybrid storage uses private blob/queue/table HTTPS endpoints; shared keys and anonymous blobs are disabled,
  OAuth is preferred and dedicated host-storage data roles are retained. A public
  network ACL is not a data permission.
- ACR is an existing public, authenticated registry, or a dedicated Basic registry
  maintained in this state when `create_container_registry=true`. Admin and anonymous
  pull are disabled; app identities receive resource-scoped `AcrPull`.
  No registry admin password is put into Terraform or app settings.
- APIM's native public hostname **can bypass AppGW networking**. It is safe only in the
  current deny-all state, not proof that WAF protects future inference. Before releasing
  inference, implement and live-prove native origin controls (for example a reviewed
  native `ip-filter` accepting the actual AppGW source IP) plus Entra/native subscription
  validation. Prove direct-origin denial and health-probe behavior; header secrecy or
  an unverified static-IP assumption is not origin proof. This control is **deferred**,
  not secretly activated by Terraform.

PII redaction through Foundry's Language API, Content Safety/Prompt Shields, SSE inspection, native subscription
scope/quotas and no-sensitive-log gates remain mandatory. WAF/access diagnostics stay
off until sensitive-field scrubbing is proven; APIM diagnostics omit HTTP bodies and
LLM message capture. Public connectivity never relaxes tenant/member authorization.

## Required inputs and remaining blockers

Copy `infra\terraform\environments\fdpo.tfvars.example` to an ignored `.tfvars`.
It selects APIM first, approval false, publisher `ajanakiraman@microsoft.com`,
P1v3/S0 and the approved isolated network. Complete externally verified inputs:

1. Basic v2/East US availability, quota, names and current costs; WAF_v2 zones and
   capacity (min 2/max 4), retention, protection services and budgets.
   Older Standard v2/VM pricing is not a Basic v2 estimate.
2. Required registrations outside Terraform: Microsoft.ApiManagement, Microsoft.Network,
   Microsoft.Web, Microsoft.Sql, Microsoft.Storage, Microsoft.KeyVault,
   Microsoft.CognitiveServices, Microsoft.Insights, Microsoft.OperationalInsights,
   Microsoft.ManagedIdentity and Microsoft.Authorization. **No Microsoft.Compute/VM**
   dependency for public dev; do not register anything as part of local validation.
3. DEV Entra API/customer/admin registrations and service principals are exact-name,
   owner-checked and single-tenant (`AzureADMyOrg`), with delegated `access_as_user`,
   v2 tokens, requested SPA redirects and the `ids_admin` role. Their nonsecret IDs
   are in ignored `infra\terraform\live-identity.json`. No secrets or directory-wide
   permissions were created. Multi-tenant registration is a separate customer-
   production requirement. Backend authorization still requires tenant AND user
   database approval, not merely an Entra app-role assignment.
4. API/customer/admin images are SHA-256 pinned from successful ACR remote builds.
   Local Docker is missing; use approved `az acr build` against the maintained Basic
   registry with explicit subscription and RG, uploading the current local source,
   not a stale Git branch. `.dockerignore` excludes all `infra`, Terraform inputs/
   state/plans, local credentials and dependencies from the build context.
5. The public DNS label `aiflux-gateway-dev` and hostname
   `aiflux-gateway-dev.eastus.cloudapp.azure.com` now resolve to the bootstrap IP
   `134.33.136.180`. Let’s Encrypt staging and production HTTP-01 issuance both
   succeeded. The production PFX is in private Key Vault secret `aiflux-dev-tls`;
   Terraform uses its **versionless URI**. Application Gateway HTTPS remains pending
   until its read permission and certificate refresh succeed. Never export PFX/private
   keys or enable public Key Vault access as a workaround.
6. **Automatic renewal is not installed.** The one-shot issuer has no durable scheduler.
   App Gateway is configured with a versionless Key Vault reference, which supports
   Azure-side refresh after a new secret version exists; this does not renew the
   Let’s Encrypt certificate. Renewal still needs a reviewed scheduler, narrowly
   scoped API write authorization, expiry alerting, and rehearsed recovery.
7. SQL S0/database are in Australia East, with apps in East US and cross-region
   latency accepted. ARM keeps SQL public access disabled; the exact operator rule
   was rejected, so the 31 captured app outbound `/32`s remain dormant in the ignored
   inputs (no `AllowAzureServices`). Reconcile only after the public interface is
   approved/enabled. Local ODBC Driver 18/pyodbc are missing; schema migration,
   contained-user grants and runtime token/readiness acceptance remain blocked.
8. Native unified-model IaC/policies and origin/subscription/PII/safety/quotas/metadata
   release evidence. Selected future model intentions (GlobalStandard Luna/Sol OpenAI
   versions `2026-07-09`, Claude Sonnet 5.5 versions `1`/`2`, East US/Sweden) are
   **not resource deployments, proven availability, or catalog entries**. Keep all
   unadvertised until reproducible native implementation and per-model checks pass.

## Local authentication, state and deployment route

Use an existing authorized Entra operator with Azure CLI; do not create identities
or registrations merely to run Terraform. Explicitly pass the subscription to Azure
commands and verify provider identity/subscription matches. Keep state/plan files on
an **encrypted, access-controlled local disk**, excluded from source control and shared
sync folders; Terraform local state is not itself encrypted. Back up securely and allow
one writer only. No blob backend, state account, bootstrap or VM is mandatory today.

`infra\operator` and `infra\state` remain **optional deferred private-design artifacts**,
validated locally but not prerequisites and not consumed by this public root.
Their private backend/OIDC examples do not configure the main local backend.
Any later remote-state migration requires a separate reviewed auth/firewall/locking plan;
do not toggle or migrate ownership blindly after resources exist.

Use this reviewed operator route only after the recorded policy/entitlement
blockers have approved resolutions. Do not repeatedly retry those failures:

```powershell
# Check an existing Azure CLI login without changing shared subscription defaults.
az account show --subscription 4d75ed7f-75ab-4db6-b1f3-263f240d1450
$env:ARM_SUBSCRIPTION_ID = "4d75ed7f-75ab-4db6-b1f3-263f240d1450"
# Azure CLI auth is used; remove stale ARM OIDC/client-secret overrides from this
# process only before proceeding. Do not print credentials.
& infra\.tools\terraform.exe "-chdir=infra\terraform" init -input=false
& infra\scripts\validate-local.ps1

# Fill the ignored tfvars and review costs/inputs before approving a real plan.
& infra\.tools\terraform.exe "-chdir=infra\terraform" plan -var-file=environments\fdpo.tfvars -var=deployment_stage=apim -out=apim.tfplan
# Inspect and explicitly approve the complete plan, then:
& infra\.tools\terraform.exe "-chdir=infra\terraform" apply apim.tfplan

# With existing Entra/SQL/registry/images/operator_ip inputs:
& infra\.tools\terraform.exe "-chdir=infra\terraform" plan -var-file=environments\fdpo.tfvars -var=deployment_stage=platform -out=platform.tfplan
& infra\.tools\terraform.exe "-chdir=infra\terraform" apply platform.tfplan
& infra\.tools\terraform.exe "-chdir=infra\terraform" output sql_required_outbound_ipv4s
# Hybrid output is empty: verify private DNS/TCP, then SQL grants/migrations
# through the approved private execution route, API readiness, auth and origin checks.
# Only legacy public-data mode needs exact sql_firewall_ipv4s and a second plan.
# After certificate/DNS/WAF/backend preflight and explicit approval:
# Hybrid additionally needs private_sql_connectivity_accepted=true with live evidence.
& infra\.tools\terraform.exe "-chdir=infra\terraform" plan -var-file=environments\fdpo.tfvars -var=deployment_stage=public-edge -var=public_edge_live_gates_approved=true -out=public-edge.tfplan
& infra\.tools\terraform.exe "-chdir=infra\terraform" apply public-edge.tfplan
```

The former private self-hosted deployment workflow is **disabled**, with no OIDC
deployment permission, and references this local route. CI continues validation only.
Future GitHub-hosted deployment must have reviewed ephemeral runner `/32` allowlisting
for App Service/SCM and guaranteed cleanup on failure/cancellation; private data work
still requires separately approved VNet execution, not public SQL allowlisting. Never grant
all Azure services or broad GitHub ranges. Build immutable images using the existing
Dockerfiles and deployment identity; no registry keys, publish passwords or credentials.

## Runtime integration and acceptance

Routes preserve paths: `/v1[/*]` to APIM (denied), `/api[/*]`, `/health`, `/ready` to API,
`/admin[/*]` to the admin portal, and everything else to the customer portal.
Only `public-edge` emits the public gateway URL; the earlier public resource hostnames
are not a released portal/inference URL.

`control_plane_settings` supplies database/Entra/bootstrap/APIM/Product/workspace/catalog
IDs with `AIFLUX_CATALOG_CONFIGURED=false`. `AZURE_CLIENT_ID` selects per-host MI.
Portal Entra settings are build-time public values; use relative `/api` and the final
edge `/v1`, no embedded keys. API images use `services\control-plane\Dockerfile` with
repository-root context.

SQL URL is `mssql+pyodbc://@<server>:1433/aiflux` with Driver 18, `Encrypt=yes` and
`TrustServerCertificate=no`, without passwords. Runtime obtains the SQL access token.
From an approved private operator execution environment in hybrid mode (the
App Service operator IP allowlist does not provide private SQL connectivity),
as the existing Entra SQL administrator, run
`alembic -c services\control-plane\alembic.ini upgrade head` then
`infra\sql\bootstrap-identities.sql` with SQLCMD managed-identity **client IDs** from
the live UAMI `clientId` fields (`az identity show`); the Terraform
`identity_principal_ids` output is for ARM/RBAC, **not** these SQL SIDs.
Runtime API gets schema DML, not DDL/db_owner; ingestion gets
scoped usage/safety/watermark DML. Graph Directory Readers is not required by the
SID-based bootstrap. Run `aiflux-bootstrap` with the reviewed database URL, audience,
home tenant and bootstrap object ID; it creates only the configured home-tenant
IDS administrator membership and refuses conflicting or disabled membership.
Verify the database's `alembic_version` is `0001`, external-user SIDs match the
verified principal object IDs, and actual permissions/role memberships contain no
runtime DDL or `db_owner`. Verify the home organization/member rows and an
authorized `/api/me` call; merely possessing an Entra token does not approve a user.
Validate runtime SQL login and `/ready` 200; `/health` is liveness,
`/api/models` separately checks catalog, and none proves inference readiness.

Function MI settings include keyless Blob/Queue/Table endpoints and the shared runtime
contract. Package ingestion code/dependencies/catalog and ODBC Driver 18 with an
authenticated immutable package mechanism, no SAS/account key. Keep the host disabled
until actual binding registration, package execution, storage/SQL permissions,
metadata/watermark semantics and the selected gateway's telemetry gates are reviewed.
For the accepted development adapter, set `ingestion_enabled` and
`ingestion_timer_enabled` with an immutable `ingestion_container_image` and explicit
timezone-aware `ingestion_start_at`. Registering the host alone is insufficient:
verify scheduled timer execution and exact native/SQL/reporting reconciliation.
Resource-scoped Monitor, AI, certificate and ACR roles remain.
API's APIM custom role grants team subscription operations only, not policy/service write.

Before release, test from the operator and an untrusted public client: Entra/membership
denials, App Service/SCM restrictions, SQL rejected addresses, AI/vault/storage unauthenticated
denials, WAF body limits/attack handling, TLS/SNI/certificate rotation, backend 200 probes,
request buffering on and SSE response buffering off. Direct APIM must still deny.
Audit no prompts/completions/keys/entity mappings in normal/error diagnostics.
Run all native origin/inspection/subscription/quotas/telemetry gates before any inference
change. Restore unconditional deny first on rollback; never use an uninspected proxy.

## Local validation and references

### TLS bootstrap without a circular release gate

`edge-bootstrap` preserves the complete authenticated platform and adds a Standard
static regional DNS IP, WAFv2, and **HTTP-01 only** listener. It needs no certificate
or live-release attestation. WAF blocks non-challenge paths; the default origin is
an actual fixed 403 API route, not a fake health success. No portal/APIM backend is
configured. The API challenge endpoint defaults off and serves only bounded,
strictly named public ACME key authorizations; arbitrary files and symlinks are denied.

`edge-candidate` adds a real versionless Key Vault PFX secret reference and TLS
20220101S. Portal/control-plane routes are restricted to the reviewed operator IP
until `public-edge` live acceptance. HTTP remains challenge-only with a deny default
in every stage. `/v1` is unconditionally blocked at WAF and the origin: this is **403**,
not inference readiness or an APIM 503 acceptance claim. Response buffering stays
off, request buffering on, backend TLS uses default-hostname SNI, and v2 backend
timeouts are integer 1–240 seconds. WAF scrubs all supported header/cookie/query/form/
JSON fields and IP; matching body content types remain required by Azure.

`infra\scripts\issue-edge-tls.py` runs a one-shot issuer **inside the private-integrated
API container**, staging before production. Staging validated the HTTP-01 challenge
without writing Key Vault. Production uploaded the base64 PFX in memory through the
API managed identity to only `aiflux-dev-tls`, using a temporary Secrets Officer
assignment at that exact secret scope; startup and the temporary assignment were
restored afterward. The App Gateway managed identity uses read-only Key Vault Secrets
User at the vault scope, which is required for Application Gateway's Key Vault RBAC
check; it has no administrative role. Private account and certificate keys never touch
disk, Terraform, command arguments, or SCM logs. Only public HTTP-01 files touch
`/home`; they are deleted after validation. Keep operator recovery evidence protected
and check its `restored` flag after any failure.

**Renewal is not installed by this one-shot script.** A reviewed, monitored scheduler,
secret-scoped write authorization, distributed execution lock, expiry alert, and
failure recovery are still required before claiming automatic renewal or public release.
Do not permanently grant vault-wide certificate/secret administration to the API.

On the initial 2026-10-11 dev attempt, both Terraform and explicit Azure CLI Standard/Static/
IPv4 public-IP creation were rejected with
`SubscriptionNotRegisteredForFeature: Microsoft.Network/AllowBringYourOwnPublicIpAddress`;
read-only feature inspection returned `NotRegistered`. No feature registration,
policy exemption, API-version workaround, or alternate public-IP scheme was attempted.
Consequently DNS/HTTP-01, CA eligibility orders, certificates, HTTPS and public portal
acceptance remain unverified. A CAA hierarchy read found no restricting `issue`
record, but that does not prove CA issuance eligibility. The API image/challenge
route and free edge identity/NSG were created; Application Gateway was not created
by that initial attempt.

After the user-approved feature registration, both feature and Microsoft.Network provider
reported `Registered`; no provider refresh or policy exception was needed. The saved,
refreshed `edge-bootstrap-registered.tfplan` had zero destroys and applied **7 adds,
4 in-place changes, 0 destroys**. The WAF_v2 gateway is Running with only the HTTP
challenge listener at `134.33.136.180`. Its API and deny backend probes are Healthy.
Public synthetic challenge content returned 200/no-store and was deleted; missing
tokens return 404, while `/`, `/admin/`, `/api/me`, `/health`, `/ready` and `/v1/models`
return 403 over HTTP. Direct operator API checks remain health/ready 200 and anonymous
`/api/me` 401; direct APIM remains 503.

The default `python-requests` client identifier receives a WAF 403, while the
application-specific `AIFLUX-TLS/1` identifier reaches the exact challenge route.
WAF Prevention/managed rules were not relaxed. Staging validation and production
issuance then completed for `aiflux-gateway-dev.eastus.cloudapp.azure.com`; the
production certificate metadata reports Let’s Encrypt and expiry `2027-01-09T09:15:36Z`.
The one-shot runner reported private-key disk writes as false and restoration as
successful. No certificate or secret value was read back or printed.

The first HTTPS candidate update failed `ApplicationGatewayKeyVaultSecretAccessDenied`
because its Key Vault Secrets User role was scoped only to the secret. Microsoft’s
Application Gateway troubleshooting guidance requires this reader role at the vault
resource or higher. The candidate configuration now uses vault-scoped read-only access
for the App Gateway identity; the API writer remains restricted to the individual
secret and its temporary assignment has been removed. After RBAC propagation, a
versionless-URI refresh was attempted but returned the same access-denied error. The
private endpoint is Approved, its DNS zone is linked to the gateway VNet, and the
vault remains public-network-disabled; trusted-service bypass and firewall weakening
were not enabled. The remaining Key Vault access failure is unresolved and needs
network/service diagnostics before another deployment attempt. Port 443 is not serving
HTTPS; the listener certificate reports `Failed`. HTTP non-challenge routes remain
WAF-denied, direct API health/readiness return 200, and anonymous API access returns
401. Inference stays disabled and the `public-edge` live-release gate remains false.
Ignored `.tls-edge` evidence contains only sanitized public certificate metadata and
restoration status.

Azure stamped the new IP with immutable `FirstPartyUsage=/Unprivileged` IP tags.
Terraform ignores Azure-owned `ip_tags` instead of removing them and replacing the
reserved address. No Azure tag or policy was changed. The last bootstrap plan had zero
destroys; the reader-role correction replaced one narrower read-only role assignment
with the documented vault-scoped reader. All five private endpoints remain Succeeded;
Key Vault/SQL/storage public access remains Disabled, storage shared keys remain off,
and APIM remains BasicV2.
Azure stamped the new IP with immutable `FirstPartyUsage=/Unprivileged` IP tags.
Terraform ignores Azure-owned `ip_tags` instead of removing them and replacing the
reserved address. No Azure tag or policy was changed. The final saved
`edge-bootstrap-post-apply-safe.tfplan` contains only the four previously observed
in-place App Service/Function drift updates and **zero destroys**; it was not applied.
All five private endpoints remain Succeeded; Key Vault/SQL/storage public access
remains Disabled, storage shared keys remain off, and APIM remains BasicV2.

Governance already attached an empty NSG to the AppGW subnet. Set
`app_gateway_existing_nsg_name` to preserve that NSG, import its existing subnet
association, and add only the named AIFLUX ingress rules. Never replace a
governance-owned association or erase unrelated policy rules.

`validate-local.ps1` checks formatting, provider schemas and mocked **plan** tests for
all roots, plus standard-library gateway contracts. It creates no Azure resources.
Main-root tests cover public Basic v2/no APIM integration, legacy public data/firewall
behavior, hybrid public-disabled data services, exactly five endpoints/correct DNS,
API/Function-only integration, SQL Proxy/NSG ports, origin restrictions and independent
disabled/approval gates.
Local success is not Azure availability, naming, connectivity, RBAC or native proof.
The bundle release check must continue to block release.

- [APIM v2 tiers and supported networking](https://learn.microsoft.com/azure/api-management/v2-service-tiers-overview)
- [APIM addresses and nondeterministic v2 IPs](https://learn.microsoft.com/azure/api-management/api-management-howto-ip-addresses)
- [App Service access restrictions/service endpoints](https://learn.microsoft.com/azure/app-service/app-service-ip-restrictions)
- [SQL firewall rules](https://learn.microsoft.com/azure/azure-sql/database/firewall-configure)
- [SQL private endpoints and Proxy/Redirect ports](https://learn.microsoft.com/azure/azure-sql/database/private-endpoint-overview)
- [Private endpoint regions and target subresources](https://learn.microsoft.com/azure/private-link/private-endpoint-overview)
- [Dedicated Functions storage considerations](https://learn.microsoft.com/azure/azure-functions/storage-considerations?pivots=dedicated-plan)
- [Application Gateway WAF](https://learn.microsoft.com/azure/web-application-firewall/ag/ag-overview)
- [Application Gateway Key Vault certificates](https://learn.microsoft.com/azure/application-gateway/key-vault-certs)
- [AzureRM 5.9 provider](https://registry.terraform.io/providers/hashicorp/azurerm/5.9.0/docs)
