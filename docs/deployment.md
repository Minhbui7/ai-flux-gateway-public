# Customer guarded-pilot deployment

Versioned-control activation requires both the infrastructure foundations and
this application release. Keep `gateway_controls_v2_enabled` off until migration
`0003` and compatible runtime images have been installed and reviewed.

This is a **guided Terraform deployment**, not an unattended production release.
One entry point creates customer-specific infrastructure, registrations and images,
with complete-plan approvals and resumable manual checkpoints. It never deploys
the unimplemented Auto relay, enables native `/v1`, or opens private data services
to get past a failure. Code/offline checks are not evidence of a successful customer
deployment; a customer rehearsal and the acceptance below are still required.

## Supported first-pilot profile

| Setting | Supported choice |
| --- | --- |
| Operator | Windows, PowerShell 5.1+, Python 3.11+, Azure CLI, Git, Terraform 1.16.x (tested locally with 1.16.5); locked AzureRM/AzAPI providers |
| Identity | One customer Entra tenant, three new dedicated API/customer/admin registrations, signed-in bootstrap user |
| Gateway/app region | `legacy` profile: East US with East US/Sweden model backends. `australiaeast-luna`: Australia East only |
| SQL region | `eastus` or `australiaeast`, subject to customer entitlement and capacity |
| Network presets | `10.240.0.0/16` or `10.241.0.0/16`; `.1.0/24` App Gateway, `.3.0/24` private endpoints, `.4.0/24` integrated API/Function |
| Compute | Basic v2 APIM capacity 1, B1 Linux apps, S0 SQL; customer reviews cost and regional support before applying |
| Telemetry retention | 30 days; customer approval and metadata-only logging remain required |
| Models | `legacy`: pinned Luna, Sol and Haiku. `australiaeast-luna`: pinned GPT-5.6 Luna only at 120 GlobalStandard units; no silent substitution |
| DNS/TLS | New Azure-assigned `<dns_label>.<profile-region>.cloudapp.azure.com` and new customer-issued certificate in the new private vault |
| State | Existing keyless Azure Blob backend with distinct main/model keys; no mandatory operator VM, NAT or GitHub runner |
| Customer access | New direct HTTPS App Service portals/API and guarded APIM `/dev/llm/v1`; edge remains operator-restricted candidate |

SQL/network options are deliberately limited. These are deployment constraints,
not promises of capacity or approval for a customer's network. Reject overlapping
CIDRs, unsupported regions/models or governance restrictions during preflight and
review; do not widen access or substitute resources automatically.

### Australia East Luna-only profile

Set `"deployment_profile": "australiaeast-luna"` and
`"sql_location": "australiaeast"` in the customer JSON. The profile field is
optional: omission or `"legacy"` preserves the existing East US behavior.
Australia East requires a new deployment prefix, resource group, state and
dedicated registrations; switching the profile of an existing state is not a
migration. Do not reuse a failed deployment's saved plan or retired state.

This bounded profile places platform resources, SQL and one pinned Luna deployment
in Australia East. It creates no Sweden account and does not deploy, list or route
Sol or Haiku. Both guarded API surfaces reject omitted aliases. The customer API,
portals and disabled ingestion image receive the same one-model catalog.
Luna remains version `2026-07-09`, GlobalStandard capacity 120 (120,000 TPM).
Adding models, changing capacity or adding secondary regions needs a separate
review. Automatic routing is not implemented.

**GlobalStandard is not an Australia-only processing guarantee.** Review Azure's
model terms and processing geography even when the account is in Australia.
Check current subscription quota and entitlement before applying.

The launcher uses the isolated `infra\models-australiaeast` model root for this
profile, sharing the pinned model specification but leaving legacy resource
addresses and state unchanged. Inspect its models-phase saved plan with:

```powershell
terraform -chdir=infra\models-australiaeast show <absolute-path-to-models.tfplan>
```

The verifier must accept exactly one ready Luna backend in Australia East, with
the correct account/subscription, version, SKU, capacity, gateway inference role
and successful direct smoke. There is no Haiku prerequisite for this profile.
The single backend has no regional failover.

Before a full apply, check SQL S0 capabilities, Linux B1/one-instance validation,
APIM Basic v2, safety/Language dependencies, WAF/zones, quotas, inherited policy
and the revised regional cost estimate. A successful Microsoft.Web validation
does not reserve capacity. Any billable allocation probe needs separate approval;
do not use `-target` or automatically adopt probe resources. Review a new full
saved plan for each phase. Private SQL initialization, TLS, safety and signed-in
acceptance remain mandatory. Keep production `/v1`, public edge and ingestion
disabled. Budget alerts are notifications, not a spending cap.

The App Gateway candidate provisions fresh DNS/TLS for operator acceptance. It is
**not** the public customer ingress in this pilot. Customers use the dedicated
App Service origins and guarded APIM endpoint. Production edge publication and
custom-domain support are separate work; do not set `public_edge_live_gates_approved`.

Generated catalog backend IDs must match Terraform's physical APIM backend names
(`dev-` prefix, lowercase, with dots replaced by hyphens). FinOps matches the
telemetry backend ID exactly to attribute provider and backend region; it does
not substitute the gateway region. After deploying a corrected catalog, the
scheduled ingestion overlap can reconcile recent records. Older records outside
that overlap require a separately reviewed replay; missing attribution remains
Unknown rather than being priced against a guessed region.

### Reconciling an existing pilot with Terraform

The launcher supports `app_always_on` in customer configuration. It is a map of
`api`, `customer` and `admin` Boolean overrides; omitted apps default to `true`,
preserving existing deployment behavior. It populates each Terraform
`apps.<name>.always_on` field (also optional, default `true`). For the reviewed
Australia East pilot, API remains `true` and both portals are explicitly `false`.
This preserves the live choice instead of silently restoring Always On on the
next apply. Portal cold starts remain possible; the ingestion Function retains
Always On independently. This setting does not resize the shared B1 plan.

An optional `monthly_budget` object manages a resource-group budget and actual-cost
email alerts at 50%, 80% and 100%. Omission or `null` creates no budget, preserving
the default for existing customers. Example customer configuration:

```json
{
  "app_always_on": { "api": true, "customer": false, "admin": false },
  "monthly_budget": {
    "name": "pilot-monthly",
    "amount": 1000,
    "start_date": "2026-10-01T00:00:00Z",
    "end_date": "2027-10-01T00:00:00Z",
    "contact_emails": ["operator@example.com"],
    "import_existing": true
  }
}
```

Dates must be increasing, first-of-month UTC dates; choose a valid period for the
customer, not the illustrative dates above. Amount is in the subscription's
**billing currency**, not a currency selected by this configuration. This is an
alerting budget, **not a spending cap**; it covers only the resource group and
does not impose model token quotas. Review expiry and contacts operationally.
The deploying identity needs the budget read/write permissions in addition to
the existing workload deployment permissions; no runtime identity gains them.

For a budget that already exists, read its exact name, scope, amount, dates,
contacts and notification settings first. Set `import_existing=true` only after
verifying ownership. The configuration-driven import in
[budget.tf](../infra/terraform/budget.tf) targets
`azurerm_consumption_budget_resource_group.main["main"]` at that exact group/name.
A plan previews the import and any resulting changes; **only a separately approved
apply imports it into state**. Do not create a duplicate or imperatively import
unreviewed resources. For a new budget, set `import_existing=false` and review the
creation. Keep the import flag after adoption; Terraform skips importing an
address already managed in state. `prevent_destroy` blocks accidental removal or
replacement while this resource configuration remains in place; removing the
resource block itself is not protected. Changing/removing budget ownership needs
explicit state/lifecycle review, not an automatic destructive workaround.

Keep actual deployed image digests in the current phase's protected inputs.
A build manifest records **built** images, not proof that all four were deployed;
an API/ingestion-only rollout must not relabel unchanged portal images as new.
Changes to Terraform/launcher source invalidate saved-plan/source bindings.
Do not rewrite fingerprints to make old evidence pass. The next standard launcher
rollout requires a genuine build and a fresh complete-plan review. A read-only
reconciliation plan may instead inspect the existing phase inputs with the actual
deployed digests; that does not certify a new application build or authorize apply.

Terraform is not the entire release workflow. Keep Entra bootstrap/consent, SQL
migrations and scoped database-user creation, reviewed price import followed by
bootstrap disablement, certificate issuance/manual renewal, normal ingestion
reconciliation and signed-in acceptance as explicit reviewed steps. Existing
nano/Flash deployments remain external dependencies, not Terraform-owned
deployments. Adopting their lifecycle is a separate import decision. No public
SQL/Key Vault access, native `/v1` release, automatic routing, historical replay or
capacity increase is implied by reconciliation.

Do not suppress remaining differences with broad `ignore_changes` or copy live
policies wholesale. APIM may reserialize policy XML; still review policy
differences rather than assuming equivalence. App Service logging normalization
and Function content-share settings also remain visible in complete plans.
Local validation is not a zero-drift claim or permission to apply those changes.

## Customer prerequisites and permissions

Use an existing customer-owned resource group. The subscription owner supplies
Owner or Contributor for deployment. **Contributor alone cannot assign Azure roles
or create custom roles**: an authorized Owner/RBAC administrator must separately
delegate the required role-assignment/custom-role actions at the reviewed scopes.
Resource deployment cannot grant itself that authority.

### Manual Azure RBAC handoff

The public main Terraform root creates identities but does **not** create role
assignments or custom role definitions. An authorized RBAC administrator must
provision and verify these grants after prerequisites and before runtime rollout:

| Identity | Role | Resource scope |
| --- | --- | --- |
| API, customer, admin (and containerized ingestion) | `AcrPull` | Deployment container registry |
| Gateway | `Cognitive Services User` | Content Safety and Language/Foundry accounts |
| Ingestion | Blob Data Owner, Queue Data Contributor, Table Data Contributor | Function storage account |
| Gateway | `Key Vault Secrets User` | Deployment Key Vault |
| API, customer, admin, gateway, ingestion | `Monitoring Metrics Publisher` | Deployment Application Insights |
| API, ingestion | `Log Analytics Reader` | Deployment Log Analytics workspace |
| API | Custom `<prefix>-subscription-manager` | Deployment APIM service |
| Edge when TLS enabled | `Key Vault Secrets User` | Certificate Key Vault |
| API when settings provisioned or enabled | Custom `<prefix>-gateway-settings` | Exact approved settings fragment(s) |

The reviewed least-privilege role definitions remain commented in
`infra/terraform/rbac.tf` and `gateway-settings.tf`. Record principal, scope,
role and effective assignment; only then set configuration
`manual_rbac_verified` to `true`. The Terraform precondition blocks runtime or
inference without this attestation. Role lifecycle stays outside main state.
Separate model/operator/SQL-runner roots retain their documented elevated
permission requirements; this handoff does not authorize their execution.

Azure Owner/Contributor also does not confer Entra app-registration/consent rights,
SQL data-plane administration, model entitlements or DNS/certificate authority.
Use the [security and approval matrix](security-and-approvals.md) for customer
directory/admin/CISO review. Runtime identities retain their existing narrow
Terraform roles, not the operator's deployment rights.

Install the listed tools through approved customer channels. From the repository:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
New-Item -ItemType Directory -Force .deployment
Copy-Item infra\deployment\customer.example.json .deployment\customer.json
az login --tenant <customer-tenant-id>
```

Edit the nonsecret JSON file, replacing placeholder UUIDs, contact/name, operator
egress IPv4, DNS label and choices. `bootstrap_object_id` is the signed-in user's
object ID in this tenant. `sql_admin_object_id` may identify a separately approved
SQL administrator group containing that operator. No credential belongs in JSON.

Before any deployment, protect `.deployment` using customer-reviewed NTFS ACLs and
encrypted disk storage. Restrict access to the deployment operator and approved
backup administrators. The launcher ignores this directory in Git and build
uploads; ignore rules are **not encryption or access control**. Do not place the
configuration or state elsewhere under the Docker build source tree.

Configure the optional `backend` object before any Terraform action; execution
without it is refused. Use an existing Azure Blob account/container and keyless
Azure CLI authentication:

```json
"backend": {
  "resource_group_name": "approved-state-rg",
  "storage_account_name": "approvedstateaccount",
  "container_name": "tfstate",
  "main_key": "aiflux-pilot/main.tfstate",
  "models_key": "aiflux-pilot/models.tfstate"
}
```

Keys must be different and namespaced by the configured `name_prefix`. The
Australia East model root uses the isolated `models_key` instead of the legacy
models root; never share it with another profile/environment. Changing profile,
region or backend requires separate migration review. Existing remote/local state
is not silently adopted. Legacy configurations may still explicitly set
`location` to `eastus` or `southeastasia`, with `model_location` pinned to
`eastus`; Australia East requires both to be `australiaeast` when specified.

Resource providers must be registered by an authorized subscription administrator.
The launcher checks the required namespaces and reports missing ones; it does not
register them implicitly. For each reported provider, the administrator can use:

```powershell
az provider register --subscription <subscription-id> --namespace <reported-namespace>
az provider show --subscription <subscription-id> --namespace <reported-namespace> --query registrationState
```

Review cost, address overlap/peering/DNS and permission delegation, then set
`cost_network_and_permissions_reviewed` true. This is an explicit customer
attestation, not a capability inferred from a role name.

## One entry point and resumable phases

### Existing Australia East budget deployments

The `australiaeast-luna` profile remains Luna-only by default. After verifying
operator-created GlobalStandard deployments and passing the guarded gateway
checks, explicitly opt in through `additional_model_aliases`:

```json
"additional_model_aliases": ["DeepSeek-V4-Flash", "gpt-5.4-nano"]
```

These exact GA versions are pinned in the shared model specification:
DeepSeek-V4-Flash `2026-04-23` and gpt-5.4-nano `2026-03-17`, capacity250 each.
They are externally managed: neither model Terraform root creates, imports or
deletes them. The verifier checks exact ARM identity, version, region, capacity,
endpoint, gateway role and bounded direct completion. DeepSeek uses the Foundry
model-inference endpoint and `max_tokens`; nano uses OpenAI v1 and
`max_completion_tokens`. Both retain subscription, safety and PII policies.

Stage them using `dev_unified_candidate_model_aliases` in the reviewed main-root
plan while leaving `dev_unified_accepted_model_aliases` empty and the deployed
catalog unchanged. Candidates are hidden from the gateway model listing. Only
after per-model guarded acceptance should they be added to the customer
configuration and accepted inputs, and customer catalog images rebuilt. Adding
aliases invalidates the build fingerprint. Continue at the current deployment
phase (including enabled ingestion and its original cutoff); do not rerun an
earlier phase to add models. API and ingestion use the same generated catalog
for model/provider/region attribution. No prices or automatic routing are implied
by model activation; enter reviewed Azure rates separately.

The customer build filters bundled price rules to exact enabled
model/provider/region endpoints; it never imports legacy-region rules into
Australia East. Reviewed on 19 October 2026 with the Australia East and USD
selectors on Microsoft's [Azure OpenAI pricing](https://azure.microsoft.com/en-us/pricing/details/azure-openai/)
and [DeepSeek pricing](https://azure.microsoft.com/en-us/pricing/details/ai-foundry-models/deepseek/)
pages, the Global Standard rates per million tokens are:

| Model | Input USD | Cached input USD | Output USD |
|---|---:|---:|---:|
| gpt-5.4-nano | 0.20 | 0.02 | 1.25 |
| DeepSeek-V4-Flash (GA, not 0731) | 0.19 | 0.028 | 0.51 |

Rules are effective from the review, not retroactively inferred. These are
public estimates, not contract/invoice rates, and nano is not cheaper than
Luna's displayed short-context rates. Use the existing explicit one-off
`dev_price_bootstrap_enabled` Terraform input only after guarded model acceptance,
verify the audited SQL rules, then disable it in a separately validated plan.
Do not leave deployment price import enabled permanently. Missing token/cache
telemetry or prices for other models still produce incomplete/Unknown costs.

```powershell
.\scripts\deploy.ps1 -Config .deployment\customer.json
```

The launcher performs read-only Azure preflight, requests approval to create the
dedicated registrations, and advances through these phases:

| Phase | Result / checkpoint |
| --- | --- |
| `prerequisites` | Main root creates private-data network, identities, registry, SQL and protection/APIM prerequisites; no app or inference acceptance |
| `models` | Legacy root creates Sweden account and pinned GPT deployments in both regions; Australian root creates Luna only in the primary account, with serial writes |
| Build | ACR builds API, customer, admin and ingestion images with customer identity/origins and the profile-specific catalog; all references are resolved to SHA-256 digests |
| `platform` | Deploy all four images; inference and ingestion remain gated; API can now be initialized via private SQL |
| `edge-bootstrap` | New public IP/DNS and HTTP challenge-only edge preparation; no accepted HTTPS/public release |
| `candidate` | Requires direct model evidence, private SQL and certificate checkpoints; guarded routes/direct portals enabled, catalog not yet accepted |
| `pilot` | Requires customer guarded/signed-in acceptance attestation; selects the customer catalog/product; ingestion remains disabled |
| `ingestion` (separate opt-in) | Requires explicit telemetry/ownership acceptance and activation cutoff; enables Function/timer |

At each Terraform phase a **full saved plan** is created. The launcher prints a
metadata-only change summary and approval hash. Inspect the complete plan in a
private terminal using the correct root before pasting that hash:

```powershell
terraform -chdir=infra\terraform show <absolute-path-to-phase.tfplan>
# For the models phase:
terraform -chdir=infra\models show <absolute-path-to-models.tfplan>
```

Terraform display may contain sensitive state; do not save terminal output in an
issue or general CI artifact. The launcher never auto-approves plans or uses
`-target`. It refuses deletions/replacements and settings-fragment content updates.
Changing source/configuration, identity/model evidence, saved variables or the plan
invalidates its approval. A failed apply consumes approval: refresh/replan before
retrying. Main and model roots have separate state, provider metadata and locks.

The sequence intentionally stops when a manual checkpoint is absent. Complete it,
update the configuration attestations, and rerun. Earlier applied phases are not
replayed; the current phase is freshly planned. Do not change an attestation while
a launcher process is running. To build again, use `-Action build`; a changed source
or compiled configuration requires a new image manifest, not reuse of old digests.

Individual actions use the same launcher:

```powershell
.\scripts\deploy.ps1 -Config .deployment\customer.json -Action preflight
.\scripts\deploy.ps1 -Config .deployment\customer.json -Action plan -Phase platform
.\scripts\deploy.ps1 -Config .deployment\customer.json -Action apply -Phase platform -Approval <reviewed-hash>
.\scripts\deploy.ps1 -Config .deployment\customer.json -Action build
.\scripts\deploy.ps1 -Config .deployment\customer.json -Action models-verify
.\scripts\deploy.ps1 -Config .deployment\customer.json -Action verify
```

`preflight` performs no Azure writes but creates local environment binding/lock
metadata. It verifies tools, active operator/tenant, explicit subscription, existing
RG and provider registration. It does not claim effective directory/RBAC permissions,
quota or private SQL access. Every Azure operation specifies subscription context;
the launcher does not change shared CLI subscription defaults.

## Required manual/customer actions

These are deliberate external authority/connectivity boundaries, not hidden
automated steps. Do not mark an attestation true solely to continue.

| Action / owner | Why separate | Completion / retry |
| --- | --- | --- |
| Tenant sign-in / customer operator | MFA and conditional access require customer interaction | `az login --tenant ...`; confirm target operator and subscription; retry preflight |
| RG/providers/RBAC / subscription owner | Contributor lacks role-assignment authority; provider/governance decisions need approval | Existing RG, registered providers, reviewed create/assign-role rights; no blanket Graph or runtime Owner grants |
| App registrations/consent / directory administrator | Resource deployment roles do not confer directory rights | Run `-Action identities` as the configured authorized bootstrap user, or have directory admin grant reviewed app creation/role-assignment authority; verify dedicated apps, exact redirects, `access_as_user`, `ids_admin` and tenant policy consent |
| Model terms/quota/access / model administrator | Provider entitlement, terms and capacity are customer-specific | Approve pinned spec and paid direct smoke, set `model_terms_and_quota_reviewed`; unsupported versions block, never substitute |
| Haiku deployments / Foundry model administrator | Legacy profile only; the Australia East Luna-only profile excludes Haiku | For legacy, deploy `claude-haiku-5-5`, version `2`, GlobalStandard, capacity 50 in East US and 30 in Sweden Central; verify exact metadata against `infra\models\model-spec.json` |
| Direct inference operator role / authorized RBAC administrator | Gateway identity roles do not authorize the human verifier | Assign operator reviewed inference roles only at the profile's account(s); verify direct smoke without exporting tokens |
| Private SQL route/DDL / network and SQL administrators | Laptop/public SCM cannot administer private SQL; runtime identities must not get DDL | Follow private initialization below; verify migration head, scoped users and runtime `/ready`; then attest |
| Fresh TLS certificate / certificate and vault administrators | CA approval, private-key custody and renewal are external | Issue a new certificate for the new hostname, import through an approved private vault route, verify HTTPS/backend/certificate retrieval and renewal ownership; then attest |
| Guarded/signed-in acceptance / customer pilot owner | Anonymous probes cannot prove authorization or protection | Owned test subscription, guarded verifier and real Entra customer/admin journeys; then attest, apply pilot and complete playground acceptance |
| Prices/ingestion / finance and data owner | List prices and telemetry ownership cannot be inferred | Configure reviewed effective-dated list prices or preserve Unknown; validate Monitor/SQL ownership and cutoff before optional timer activation |

### If app registration needs manual directory work

The `identities` action uses the existing Entra helper with customer parameters and
does not accept client secrets. It creates exactly `<prefix>-api`, `-customer` and
`-admin`; API audience and delegated scope, single-tenant SPA redirects, and initial
home-tenant IDS role assignment are configured in that tenant. The database
membership remains a separate SQL bootstrap.

If creation/assignment is denied, stop and give the directory administrator
`tenant_id`, prefix, bootstrap object ID and proposed hostname, plus
`infra\scripts\bootstrap-entra.py` for review. An approved administrator can authorize
the configured operator to run the same action. Alternatively, under the customer's
approved identity process, configure the three new apps in **Entra admin center ->
App registrations**, using the scope/roles/redirect contract in that helper, and
provide the nonsecret `identity.json` schema emitted by the helper. Do not borrow
development application IDs, add CLI consent to bypass sign-in, or weaken approval.

Customer registrations carry an ownership marker in `notes`; an existing unmarked
or differently owned exact-name application is refused, not overwritten. If
creation was interrupted before ownership/marker assignment, a directory operator
must first verify the exact application object/audit history and repair ownership
and marker (`AIFLUX customer deployment: <prefix>`) before retrying. Never repair an
ambiguous application by deleting it or assigning ownership automatically.

### Private SQL initialization

Default execution is an **already approved private-connected Windows operator
host**, not temporary runtime-identity elevation or public SQL firewall access.
It needs private DNS/1433, the configured Entra SQL administrator authority, ODBC
Driver 18, the repository/package and protected local state for this environment.
If no such route exists, network administrators must supply one; deployment stops.
Securely transfer the isolated customer state/configuration if moving hosts, ensure
one writer, and preserve custody/backup. The default action never provisions a host.

After `platform`, run on that host:

```powershell
.\scripts\deploy.ps1 -Config .deployment\customer.json -Action sql-init -Approval INITIALIZE
```

The action explicitly uses the interactive CLI operator, requires exclusively
private SQL DNS and database CONTROL, migrates to the actual Alembic head
(including `0002`), creates contained users using **managed-identity client IDs**,
grants scoped API/ingestion permissions and bootstraps the home-tenant IDS member.
It never changes the ARM SQL administrator, web startup or network settings.
Existing SID conflicts or database-role memberships require operator review rather
than silent repair. Runtime users receive DML but explicit DDL denies.

Verify `/ready` through the running API using its runtime identity after the
operation, plus actual Function access before enabling ingestion. SQL admin
success and SCM TCP tests are not runtime proof. Set `private_sql_initialized`
only after this verification.

An explicitly approved alternative is the disposable Australia East runner in
`infra/sql-runner`, using separate protected local Terraform state, a dedicated
managed identity, private-only NIC, denied inbound access and temporary NAT
outbound. It does not share the API/ingestion identities. Build
`scripts/deployment/Dockerfile.sql-init` with `API_IMAGE` set to the deployment's
immutable API image digest. The image reuses the existing migrations and scoped
bootstrap script; no operator tokens or SQL passwords are supplied.

Validate and inspect the complete runner plan before provisioning. After applying,
save `terraform output -json` as `sql-runner-output.json` in the protected
environment, and invoke:

```powershell
.\.venv\Scripts\python.exe -m scripts.deployment.sql_runner `
  --config .deployment\customer.json --environment .deployment\<prefix> `
  --runner-output .deployment\<prefix>\sql-runner-output.json `
  --image <registry>/aiflux-sql-init@sha256:<digest>
```

This action **temporarily replaces the logical server Entra administrator** with
the dedicated migration identity, after private DNS/TCP and image checks. Obtain
explicit authorization for this server-wide elevation. It journals the original
administrator before changing it and restores it in `finally`. The privilege has
no automatic expiry: keep the operator host connected until restoration is
verified. After interruption, rerun the same command with `--recover`; it refuses
unexpected third-party administrator changes. Never remove an unresolved journal
to force another migration. Failed DDL requires review before retrying.

Require the bound migration result, administrator restoration, fresh runner login
denial, then API `/ready`. Inspect a destroy plan **only for the isolated runner
state**, and remove the temporary VM/disk/NIC, identity/role, subnet and NAT/IP.
Retain recovery/evidence files; deallocating a VM does not stop NAT/IP/disk charges.
This alternative does not open public SQL, relax runtime DDL denies, enable
ingestion or certify signed-in chat/TLS acceptance.

### DNS and fresh TLS

If governance already attaches a network security group to the Application Gateway
subnet, set optional `app_gateway_existing_nsg_name` to its name in the same resource
group. Review and import only the existing subnet/NSG association into the correct
customer state before applying; do not replace or adopt the governance NSG.
Terraform adds separately managed `AIFLUX*` gateway ingress rules and preserves
the existing association. Retain this setting through every later phase.

The customer launcher sets `dev_portals_operator_only=true` for candidate/pilot:
direct App Service origins keep default Deny with only the operator and gateway
subnet permitted. The raw Terraform flag defaults to false to preserve historical
explicit direct-public development deployments; enabling the guarded adapter
through the launcher does not authorize public origin access.

`edge-bootstrap` creates a new Azure public IP and DNS label in this customer
state. Confirm the resulting FQDN resolves to that IP. The customer CA/certificate
administrator must issue a **new** certificate for this exact hostname; no
development PFX or secret is copied.

Through an approved route to the private vault, use **Key Vault -> Certificates ->
Generate/Import -> Import** or the customer's approved secure certificate tooling.
The certificate must include a valid private key/chain appropriate for Application
Gateway. Do not place PFX passwords or private material in command arguments,
Terraform inputs/state or this launcher. Use a versionless secret URI such as
`https://<compact-prefix>kv.vault.azure.net/secrets/pilot-tls` in
`certificate_secret_id`. The vault ARM ID is derived from this environment.

Assign a customer renewal owner/process; rotate the secret version, verify
Application Gateway can retrieve it, and verify certificate chain, hostname,
expiry, backend health and HTTPS from the approved operator address. Mark
`tls_and_renewal_reviewed` only after issuance/private-vault path and renewal review;
complete edge runtime verification after candidate apply. The historical ACME helper
is not invoked automatically: its development secret/temporary-startup mechanism
is not a general customer renewal design. Public edge remains gated.

For explicitly authorized one-shot Let's Encrypt issuance, first apply a reviewed
bootstrap plan with `acme_http01_enabled=true`. This also mounts App Service
storage on the API so the temporary SCM script and the challenge directory are
visible in its private-integrated container. Run `infra/scripts/issue-edge-tls.py`
with `--agree-terms` and `--approve-secret-scoped-temporary-writer`, staging
before production, using the exact customer subscription/app/principal/vault/
hostname and a protected evidence directory. Production grants only temporary
Secrets Officer on `secrets/aiflux-dev-tls`, journals its role ID before creation,
and imports the new PFX in memory. Startup and role removal are checked afterward.
Keep the journal; an interrupted local process has no automatic cloud rollback.
Recover its recorded startup/role before retrying an unrestored journal.

The one-shot helper is also the manual renewal procedure: the operator contact
owns checking certificate expiry, arranging renewal before the last 30 days,
temporarily re-enabling HTTP-01/storage in a reviewed plan, running production
issuance under change control and restoring the normal settings. Use the same
versionless secret URI, verify gateway certificate refresh and actual HTTPS chain/
expiry, and retain evidence. This is manual renewal, not a scheduled service.
Disable `acme_http01_enabled` again in the subsequent candidate/pilot plan.

### Guarded acceptance, admin settings and ingestion

If the optional MISE sidecar cannot run, explicit
`mise_direct_jwt_enabled=true` selects the existing direct Entra JWT signature
validation branch. It still verifies signed claims, issuer, audience, expiry,
delegated scope and SQL organization/member approval. The optional sidecar ARM
configuration is retained to avoid an unapproved deletion; this setting is not
a runtime fallback and does not certify MISE compliance. Verify real signed-in
API requests after changing it, and retain the setting through later phases.

The managed `llm-content-safety` policy rejects severity equal to its threshold:
threshold `0` can reject even benign severity-zero text. Live-trace a benign
bounded request before accepting the gateway. Do not bypass inspection or mark
the pilot accepted if it fails. An approved threshold `1` allows severity zero
while blocking every positive severity; changing a safety threshold requires
explicit operator approval and full-plan validation.
Persist that approval in customer configuration as
`dev_openai_content_safety_threshold: 1`; the launcher carries it through
candidate, pilot and ingestion. Omission preserves legacy threshold `0`.

At candidate, direct routes exist but `/api/models` remains gated. Use the normal
signed-in key-management flow or, if the portal's catalog-dependent UI is not yet
available, an approved interactive delegated REST client calling the existing
`POST /api/admin/subscriptions` as an IDS admin with
`{"organization_id":"<target-org-uuid>","name":"Pilot acceptance","team":"Pilot"}` and a
fresh UUID `Idempotency-Key`. This endpoint does not require catalog acceptance:
it commits SQL ownership before activating the adapter-product APIM key. Retain the
same idempotency key on retry, or reconcile its existing failed subscription.
With initialized versioned controls, creation automatically refreshes membership
using unchanged published settings. Check `gateway_access` as well as APIM
`state`; pending publication is not usable-access success. Reconcile the
subscription to retry its membership refresh. Resolve unrelated pending settings
or drift in Gateway settings rather than automatically approving them.
Do not manually insert SQL ownership, create unowned smoke subscriptions or expose
bearer/APIM keys in CLI arguments or logs. Keep paid calls bounded.

The gateway verifier supports the generated customer catalog:

```powershell
python gateway\tools\verify_adapter.py `
  --subscription <subscription-id> --resource-group <rg> --apim <prefix>-apim `
  --test-subscription <sql-owned-test-subscription-id> `
  --portal-origin https://<prefix>-customer.azurewebsites.net `
  --portal-origin https://<prefix>-admin.azurewebsites.net `
  --catalog .deployment\<prefix>\catalog.json --smoke `
  --output .deployment\<prefix>\gateway-acceptance.json
```

Keys are obtained transiently, not supplied in configuration. Acceptance must pass
key denial, exact catalog, CORS, unsupported shapes and bounded model completions,
plus explicit adversarial PII/safety checks and real signed-in admin/customer
authorization. Set `guarded_smoke_and_signed_in_accepted`, apply `pilot`, and then
verify portal team provisioning/reconciliation, reveal/rotation and playground
with the accepted catalog/product. Do not treat HTTP-only `verify` as that journey.

If `admin_settings_enabled=true`, candidate deploys initially denying bootstrap
fragments. Publish explicit safety/RPM/TPM/quota settings from `/admin/settings`
before guarded acceptance. The launcher never seeds a quota, never overwrites
runtime fragment values, and blocks fragment replacement/update for separate
review. See [publication/retry/history](control-plane.md#admin-managed-gateway-settings):
`published` is management readback, not atomic/live enforcement. For urgent
tightening, use the existing reviewed inference gate before publication and
measure live enforcement after propagation. Reruns preserve administrator settings.

For the new team/subscription limits and separate Content Safety settings page,
prefer the [provision-before-enforcement workflow](infrastructure.md#versioned-controls-rollout).
Optional customer keys `admin_settings_provisioned`, `gateway_controls_v2_enabled`,
`protected_material_available`, `monthly_request_quota_available`,
`safety_relaxation_allowed` and `gateway_max_rpm` are validated by the launcher.
They do not authorize activation, raise model capacity or change current protected
deployment inputs. Migrate through `0003`, publish an explicit baseline while
enforcement remains off, and separately approve policy/capability acceptance and
counter-namespace cutover. Never flip capability assertions merely to enable a
disabled UI control.

Ingestion is intentionally separate from `deploy`. After owned telemetry,
private Function SQL/storage access, metadata-only logging and reviewed prices
are accepted, set an explicit timezone-qualified `ingestion_start_at` and
`ingestion_ownership_and_telemetry_accepted`, then plan/apply `-Phase ingestion`.
Verify Function readiness and scheduled watermark progress/replay invariance.
Never advance/reset the watermark to skip unknown owners or claim list-price
estimates are actual customer bills.

## State, retry, upgrade and teardown

Local evidence lives in `.deployment\<prefix>`: backend binding/configuration,
isolated provider directories, saved plans, nonsecret
identity/image/evidence manifests and phase progress. State/plans can still contain
secrets; protect and back them up before changes. Main/model state is held in
separate Azure Blob keys, not launcher-local state files. The deployment-only
SQL runner retains separately protected local state and explicit teardown.
No raw Terraform/CLI failure
output is printed by the launcher because providers may include sensitive payloads.
Failures identify the command category and stop; investigate the equivalent command
in a private terminal. Never attach full output/state to an issue.

The PID lock prevents concurrent launcher writers. After a crash, inspect that PID
and any Terraform child process; only remove the specific stale lock when all
writers have stopped. Do not force-unlock live state. Failed/interrupting applies
invalidate approval; review refreshed complete plans, including partial resources.
Repeated app registration/SQL/bootstrap is idempotent for the same owned identities.
Paid direct-model smoke is not replayed automatically on failure; explicit rerun
may incur additional cost.

Backward phases and skipped prerequisites are refused. The launcher is a fresh
installation/forward-rerun tool, **not** automatic adoption, arbitrary upgrade,
rollback or teardown tooling. Later source upgrades, urgent gate changes, restoring
an older image, importing existing resources and changing topology/identity require
a reviewed complete plan and schema/ownership compatibility assessment. Do not
revert migrations, reset admin fragment history or destroy data to recover an app.

For retirement, disable traffic and ingestion under approved change control, back
up required SQL/state/audit evidence, and review model/main destroy plans separately.
Existing RG, manually owned Haiku, Entra registrations, CA renewal and retained
vault/SQL data require explicit customer cleanup decisions. Prevent-destroy,
soft-delete/purge protection and externally owned objects may block deletion;
never remove those protections or delete the RG automatically.

The disabled GitHub deployment workflow, deferred operator/state roots and
historical development notes are not alternate instructions to bypass these gates.
