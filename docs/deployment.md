# Customer guarded-pilot deployment

This is a **guided Terraform deployment**, not an unattended production release.
One entry point creates customer-specific infrastructure, registrations and images,
with complete-plan approvals and resumable manual checkpoints. It never deploys
the unimplemented Auto relay, enables native `/v1`, or opens private data services
to get past a failure. Code/offline checks are not evidence of a successful customer
deployment; a customer rehearsal and the acceptance below are still required.

## Supported first-pilot profile

| Setting | Supported choice |
| --- | --- |
| Operator | Windows, PowerShell 5.1+, Python 3.11+, Azure CLI, Git, Terraform 1.12.1; locked AzureRM/AzAPI providers |
| Identity | One customer Entra tenant, three new dedicated API/customer/admin registrations, signed-in bootstrap user |
| Gateway/app region | `eastus` or `southeastasia`; primary models remain pinned to East US, with Sweden Central backends |
| SQL region | `eastus`, `australiaeast` or `southeastasia`, subject to customer entitlement and capacity |
| Network presets | `10.240.0.0/16` or `10.241.0.0/16`; `.1.0/24` App Gateway, `.3.0/24` private endpoints, `.4.0/24` integrated API/Function |
| Compute | Basic v2 APIM capacity 1, B1 Linux apps, S0 SQL; customer reviews cost and regional support before applying |
| Telemetry retention | 30 days; customer approval and metadata-only logging remain required |
| Models | Pinned `gpt-5.6-luna`, `gpt-5.6-sol`, `claude-haiku-5-5`; no silent model/version/region substitution |
| DNS/TLS | New Azure-assigned `<dns_label>.<location>.cloudapp.azure.com` and new customer-issued certificate in the new private vault |
| State | Separate main/model Azure Blob state keys in an existing approved private container; Azure CLI/Entra data-plane access required |
| Customer access | New direct HTTPS App Service portals/API and guarded APIM `/dev/llm/v1`; edge remains operator-restricted candidate |

SQL/network options are deliberately limited. These are deployment constraints,
not promises of capacity or approval for a customer's network. Reject overlapping
CIDRs, unsupported regions/models or governance restrictions during preflight and
review; do not widen access or substitute resources automatically.

The App Gateway candidate provisions fresh DNS/TLS for operator acceptance. It is
**not** the public customer ingress in this pilot. Customers use the dedicated
App Service origins and guarded APIM endpoint. Production edge publication and
custom-domain support are separate work; do not set `public_edge_live_gates_approved`.

## Customer prerequisites and permissions

Use an existing customer-owned resource group. The subscription owner supplies
Owner or Contributor for deployment. **Contributor alone cannot assign Azure roles
or create custom roles**: an authorized Owner/RBAC administrator must separately
delegate the required role-assignment/custom-role actions at the reviewed scopes.
Resource deployment cannot grant itself that authority.

### Manual Azure RBAC handoff

**Elevated privileges required for role assignment.** The main Terraform root
creates user-assigned identities, but does **not** create role assignments or
custom role definitions. An authorized Azure RBAC administrator must provision
and verify the following grants after the prerequisites apply; this must happen
before platform, inference or edge rollout. `identity_principal_ids`,
`apim_resource_id`, and `container_registry` Terraform outputs identify some
of the exact principals and scopes; resolve the other resources in the same
resource group. Never substitute a subscription-wide scope for a resource scope.

| Identity | Role | Resource scope |
| --- | --- | --- |
| API, customer, admin (and ingestion if using a container image) | `AcrPull` | This deployment's container registry |
| Gateway | `Cognitive Services User` | Each of the Content Safety and Language/Foundry accounts |
| Ingestion | `Storage Blob Data Owner`, `Storage Queue Data Contributor`, `Storage Table Data Contributor` | This deployment's Function storage account |
| Gateway | `Key Vault Secrets User` | This deployment's Key Vault |
| API, customer, admin, gateway, ingestion | `Monitoring Metrics Publisher` | This deployment's Application Insights |
| API, ingestion | `Log Analytics Reader` | This deployment's Log Analytics workspace |
| API | Custom `<prefix>-subscription-manager` role | This deployment's APIM service |
| Edge (only when TLS edge is enabled) | `Key Vault Secrets User` | The reviewed certificate Key Vault |
| API (only when admin settings enabled) | Custom `<prefix>-gateway-settings` role | The approved APIM settings fragment(s) |

The custom subscription-manager role is assignable only within this resource
group and permits APIM service/products/subscriptions read, APIM subscription
write, listSecrets and primary/secondary key regeneration. It does **not**
manage Azure subscriptions. The optional gateway-settings role permits only
APIM policy fragment read/write. The exact least-privilege definitions remain
commented in `infra/terraform/rbac.tf` and `gateway-settings.tf` for administrator
review; Terraform must not be used to create them from this root.

The administrator should record the principal ID, resource scope, role ID and
verified effective assignment for every grant through the approved internal
process. Set `manual_rbac_verified = true` **only** after checking the grants;
the Terraform precondition blocks runtime/inference rollout until then. Manual
changes to roles are outside this root's state and must be managed separately.
Existing saved plans with Terraform-managed RBAC are invalid after this code
change: discard and regenerate them before review or apply.

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

### Azure Blob Terraform state

Both deployment roots declare `backend "azurerm" {}`. Configure an existing private
Blob container in the optional `backend` object of the customer configuration,
with distinct `<prefix>/main.tfstate` and `<prefix>/models.tfstate` keys. The
launcher writes separate ignored `.backend.hcl` files, uses Azure CLI/Entra
authentication (`use_azuread_auth = true`, `use_cli = true`) and does not use
storage account keys. The signed-in operator needs Storage Blob Data Contributor
at the state-account scope and network access to the Blob data endpoint. This
permission does not grant the separate Azure RBAC role-assignment permissions.

To migrate an existing environment, use Terraform `init -migrate-state`
after binding the old local backend to the actual protected state file. Initialize
the separate models key empty only if no model resources are already managed.
Preserve the protected pre-migration local backup until the remote state and
recovery procedure have been reviewed. Do not reapply saved local-state plans or
pass `-state` when using the remote backend. Before migration for any other
environment, confirm the destination key is empty and that no other Terraform
writer is active; do not automatically adopt or overwrite existing remote state.

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

```powershell
.\scripts\deploy.ps1 -Config .deployment\customer.json
```

The launcher performs read-only Azure preflight, requests approval to create the
dedicated registrations, and advances through these phases:

| Phase | Result / checkpoint |
| --- | --- |
| `prerequisites` | Main root creates private-data network, identities, registry, SQL and protection/APIM prerequisites; no app or inference acceptance |
| `models` | Separate model root creates Sweden account and the two pinned GPT deployments in both regions, with serial writes |
| Build | ACR builds API, customer, admin and ingestion images with customer identity/origins and a three-model catalog; all references are resolved to SHA-256 digests |
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
| Haiku deployments / Foundry model administrator | Existing model root intentionally does not own Haiku | In Foundry portal deploy new `claude-haiku-5-5`, version `2`, GlobalStandard, capacity 50 in East US and 30 in Sweden Central; verify exact metadata against `infra\models\model-spec.json` |
| Direct inference operator role / authorized RBAC administrator | Gateway identity roles do not authorize the human verifier | Assign operator the reviewed inference roles at the two accounts only; verify direct smoke without exporting tokens |
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
Driver 18, the repository/package and authorized access to the remote Terraform
state for this environment (plus protected local configuration and backups).
If no such route exists, network administrators must supply one; deployment stops.
Securely transfer the isolated customer state/configuration if moving hosts, ensure
one writer, and preserve custody/backup. No VM/NAT is provisioned as a shortcut.

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

### DNS and fresh TLS

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

### Guarded acceptance, admin settings and ingestion

At candidate, direct routes exist but `/api/models` remains gated. Use the normal
signed-in key-management flow or, if the portal's catalog-dependent UI is not yet
available, an approved interactive delegated REST client calling the existing
`POST /api/subscriptions` with `{"name":"Pilot acceptance","team":"Pilot"}` and a
fresh UUID `Idempotency-Key`. This endpoint does not require catalog acceptance:
it commits SQL ownership before activating the adapter-product APIM key. Retain the
same idempotency key on retry, or reconcile its existing failed subscription.
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

Ingestion is intentionally separate from `deploy`. After owned telemetry,
private Function SQL/storage access, metadata-only logging and reviewed prices
are accepted, set an explicit timezone-qualified `ingestion_start_at` and
`ingestion_ownership_and_telemetry_accepted`, then plan/apply `-Phase ingestion`.
Verify Function readiness and scheduled watermark progress/replay invariance.
Never advance/reset the watermark to skip unknown owners or claim list-price
estimates are actual customer bills.

## State, retry, upgrade and teardown

Everything local lives in `.deployment\<prefix>`: separate `main.tfstate` and
`models.tfstate` (and backups), provider directories, saved plans, nonsecret
identity/image/evidence manifests and phase progress. State/plans can still contain
secrets; protect and back them up before changes. No raw Terraform/CLI failure
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
