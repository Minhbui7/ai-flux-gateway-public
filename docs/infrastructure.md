# Terraform infrastructure and operator runbook

## Status and ownership

The infrastructure is schema-validated Terraform, **not an Azure deployment or a released gateway**.
No paid resources, model deployments, tenant/app registrations, keys, or runtime subscriptions
were created by this worker. The parent separately created the resource-group metadata:

- Subscription: `4d75ed7f-75ab-4db6-b1f3-263f240d1450`
  (`MCAPS-Hybrid-REQ-67039-2023-ajanakiraman`).
- Existing RG: `rg-aiflux-fdpo-dev`, metadata location `eastus`, provisioning succeeded.
- Terraform consumes that RG using a **data source**. It does not own, replace, import or
  destroy the RG. Resource-group location does not constrain resources or prove regional
  model/SKU support. The gateway region is a separate reviewed input.

`deployment_approved=false` fails a real plan before deployment. Approval refers to
infrastructure costs/configuration only, **never** inference capability.
The Front Door route, APIM Product and Function host are hard-disabled; inference remains
blocked independently by global/API policy. See `docs\gateway.md`.

## Resource inventory

`infra\terraform\` pins Terraform `~>1.16.0`, AzureRM `5.9.0`, AzAPI `2.13.0`.
Both deployment and state lockfiles contain signed Windows/Linux AMD64 package checksums.
No Terraform executable/provider binary is tracked. This implementation was checked with
a checksum-verified workspace-local Terraform `1.16.5` in ignored `infra\.tools`.

| Surface | Implemented resources/configuration |
| --- | --- |
| Edge | Front Door **Premium**, default HTTPS endpoint, prevention WAF, no cache block; disabled route to private AppGW origin |
| App Gateway | WAF_v2, private-only listener/frontend, Private Link configuration, TLS from **existing** Key Vault secret reference, HTTPS private backends, request/response buffering disabled |
| APIM | PremiumV2 candidate, **Internal injection at creation**, delegated dedicated subnet, NSG, hostname-specific private DNS A record from returned private VIPs |
| Applications | Separate Linux container App Services for customer, admin, API; public origins/publishing basic auth disabled, outbound VNet integration, managed ACR pull |
| Data | Azure SQL server/database, Entra-only authentication and TLS 1.2, public access disabled, private endpoint, database prevent_destroy |
| AI protection | Language TextAnalytics S0 and ContentSafety S0 accounts via documented AzAPI, local-key auth disabled, private endpoints and Cognitive Services User for gateway identity |
| Secrets | RBAC Key Vault, soft-delete/purge protection, no public access, private endpoint; **no secret values read/written** |
| Telemetry | Log Analytics, workspace App Insights with local auth disabled, metadata-only APIM HTTP/LLM diagnostic configuration and dedicated gateway/LLM log categories |
| Ingestion | Disabled Python 3.11 timer Function host on dedicated App Service plan, private SCM/origin, AzureWebJobsStorage managed identity, keyless private blob/queue/table endpoints |
| Identity | Separate user-assigned gateway/edge/API/customer/admin/ingestion identities, resource-scoped roles, no Entra registration or Graph permission creation |
| State bootstrap | Separate `infra\state\` root for private ZRS storage, Azure AD-only access, versioning/soft deletion, private endpoint, container-scoped runner Blob Data Contributor |

Language, Content Safety, storage and Front Door origin AzAPI bodies use published API
versions with schema validation enabled. Front Door origin uses AzAPI because AzureRM's
`private_link.target_type` enum doesn't accept AppGW's private frontend groupId. The
documented `sharedPrivateLinkResource.groupId="private"` and AppGW resource ID are used;
no private-link connection is automatically approved.

The sample's outbound Standard v2 networking was **not** substituted for private
Premium v2 injection. Injection uses `Microsoft.Web/hostingEnvironments`; application
integration uses `Microsoft.Web/serverFarms`. APIM `public_network_access_enabled`
retains the provider's creation default because ARM management access is needed;
`virtual_network_type="Internal"` is the gateway isolation mechanism. Do not mistake
the management setting for a public inference listener. Prove this on the actual service.

AppGW NSG permits Private Link NAT-subnet listener traffic, platform health and
management, and denies other direct TLS listeners. APIM NSG permits AppGW TLS/platform
health and rejects other TLS clients. Network security group default egress is not a
domain-filtering firewall; public outbound service dependencies remain allowed.
Strict egress allowlisting/private model connectivity requires a reviewed network design.
Private application endpoints are not authorization boundaries against trusted VNet
operators: the control API still must enforce Entra/membership authorization.

## Required operator decisions before a plan

Fill `environments\fdpo.tfvars.example` into an **ignored** `.tfvars` after review.
Empty strings deliberately make it unusable as-is. Numerical sizing/window values in
the example are illustrative development inputs, not approved production settings.

1. Cost approval: Premium Front Door/APIM, zone-capable AppGW, plan/database/AI capacities,
   retention, budgets and named owners. No cheap classic SKU that changes tested features.
2. Gateway/Private Link/AI-service regions and Azure provider/SKU quota availability.
   Premium v2 injection is chosen **at creation** and cannot be switched later.
   Verify zone redundancy/availability; no APIM multi-region DR is configured.
3. Reviewed nonoverlapping address ranges; dedicated /24 recommended APIM/AppGW subnets,
   private-link NAT subnet, /26-or-larger shared integration subnet sized for hosts/scaling,
   private-endpoint subnet, private DNS/peering and deployment-runner connectivity.
4. Verify private-only Application Gateway network isolation availability/feature
   registration in this subscription. Register required providers outside Terraform
   (providers intentionally use `resource_provider_registrations="none"`):
   Microsoft.ApiManagement, Microsoft.Network, Microsoft.Web, Microsoft.Cdn,
   Microsoft.Sql, Microsoft.Storage, Microsoft.KeyVault, Microsoft.CognitiveServices,
   Microsoft.Insights, Microsoft.OperationalInsights, Microsoft.ManagedIdentity,
   Microsoft.Authorization. Do not change global Azure account defaults.
5. Operator-owned origin DNS hostname and matching unexpired public-trust TLS certificate
   in an **existing reachable** Key Vault. Supply vault resource ID and **versionless**
   certificate secret URI, never PFX/private-key contents. The edge identity gets
   Secrets User on that vault; its firewall/private endpoint/DNS must already permit
   AppGW to retrieve the certificate. Do not broaden vault access to make TLS work.
6. Existing ACR resource ID and reviewed immutable image references/registry URLs,
   ports and health probes. If ACR is private, provide runner/app routing and DNS
   separately; no registry or model endpoints are fabricated or deployed by default.
7. Real Entra audience, client ID, home tenant/bootstrap object IDs and Entra SQL
   administrator identity. Applications/scopes/consent/approved tenants/users are
   configured externally; no fake tenant or authentication bypass is created.
8. Reviewed model catalog, endpoint access/RBAC or Key Vault credentials, actual
   inspection settings, IDS limits, safety thresholds, native rollout and full acceptance
   attestation. These remain absent and inference stays disabled.

The Azure Developer CLI skill dependency check reported missing `azd`. No global
installation was attempted. The selected Terraform/ARM workflow does not need azd.

## State bootstrap and validation commands

Use an operator/federated identity on a private-network runner. `infra\state\` starts
with local state only to solve the bootstrap dependency; protect that file with filesystem
ACLs, never commit it, and migrate its state to a **separate bootstrap key** after creation.
Provide an existing operator-network subnet and linked private blob DNS zone. Do not
open public state access to accommodate a laptop. Azure Blob backend provides leases/
locking; never use force-unlock while another writer may be active.

There are no automatic deployment scripts. The following are **operator commands**,
not work executed during this implementation:

```powershell
# Local-only dependency/schema checks; init does not provision Azure.
& infra\.tools\terraform.exe "-chdir=infra\terraform" init -backend=false -input=false
& infra\.tools\terraform.exe "-chdir=infra\state" init -input=false
& infra\scripts\validate-local.ps1

# After approved private-state bootstrap, configure this copied/edited ignored file.
& infra\.tools\terraform.exe "-chdir=infra\terraform" init -reconfigure -backend-config=backend.hcl
& infra\.tools\terraform.exe "-chdir=infra\terraform" validate
& infra\.tools\terraform.exe "-chdir=infra\terraform" plan -var-file=environments\fdpo.tfvars -out=reviewed.tfplan
# Inspect the entire plan and cost/config approval; apply only that reviewed plan.
& infra\.tools\terraform.exe "-chdir=infra\terraform" apply reviewed.tfplan
```

Backend config template `backend.hcl.example` uses OIDC and Azure AD authorization.
Set `ARM_CLIENT_ID`, `ARM_TENANT_ID`, `ARM_SUBSCRIPTION_ID` and the runner's supported OIDC
token environment outside version control; do not provide account keys, SAS, client secrets
or API keys. On interactive approved operators, use supported Azure CLI/Azure AD auth
instead of enabling a public backend or embedding credentials.

Local `terraform test` uses mock providers for **every Azure provider** and `command=plan`;
it makes no Azure API calls. It checks graph coherence, private/disabled posture and
rejection of missing cost approval: two tests for the deployment root and two for the
state root passed. Twelve gateway contracts and the disabled-bundle check also passed.
The release check returned the expected blocking exit 2. `terraform validate` checks provider schemas, not
remote Azure acceptance, rollout, region, naming availability, RBAC propagation or quotas.
AzAPI preflight/live plans must be reviewed on the real approved target later.

If APIM automatically materializes `azuremonitor`, explicitly import the existing logger
at `.../service/<name>/loggers/azuremonitor` to `azapi_resource.monitor_logger` before the
reviewed apply. Never replace it with a shell PUT or `schema_validation_enabled=false`
to hide ownership problems. RG remains a data source and must not be imported.

## Application/Function integration

Public path map preserves paths:

- `/v1` and `/v1/*`: APIM only, unconditionally disabled.
- `/api`, `/api/*`, `/health`, `/ready`: control plane (Python port `8000`).
- `/admin` and `/admin/*`: admin portal, built with base `/admin/`.
- Everything else: customer portal, built for `/`.

Front Door's planned base URL is output as `gateway_url` with `/v1`; its route is disabled.
Do not supply the private `*.azure-api.net` address to clients. Health probes use liveness
`/health`; `/ready` is a separate identity/database-config and SQL connectivity gate.
Catalog readiness is enforced by `/api/models`, not `/ready`. Liveness and readiness
are not declarations of inference capability or an approved user membership.

The API Docker build uses repository context and `services\control-plane\Dockerfile`;
Terraform only hosts reviewed images and does not build/push them. Portal auth variables
are **build-time** public configuration; Terraform does not mutate static compiled JS.
Use relative `/api` and the public `/v1` URL, real Entra registrations, no embedded keys.

API settings emitted by `control_plane_settings`:
`AIFLUX_DATABASE_URL`, `AIFLUX_ENTRA_AUDIENCE`, `AIFLUX_ENTRA_CLIENT_ID`,
`AIFLUX_HOME_TENANT_ID`, `AIFLUX_BOOTSTRAP_OBJECT_ID`, `AIFLUX_GATEWAY_URL`,
`AIFLUX_APIM_RESOURCE_ID`, `AIFLUX_APIM_PRODUCT_ID`, `AIFLUX_LOG_WORKSPACE_ID`,
`AIFLUX_CATALOG_PATH`, `AIFLUX_CATALOG_CONFIGURED=false`, plus production environment.
`AZURE_CLIENT_ID` selects each host's user-assigned managed identity.

The SQLAlchemy URL is `mssql+pyodbc://@<server>:1433/aiflux` with ODBC Driver 18,
Encrypt=yes and TrustServerCertificate=no, **without SQL credentials**. Application code
acquires `https://database.windows.net/.default` and supplies its driver access token.
ODBC Driver 18 must be packaged in the application/Function Linux artifact.

Function settings use the same IDs/database/workspace/catalog contract but
`AIFLUX_CATALOG_PATH=/home/site/wwwroot/gateway/catalog/models.json`.
Package the catalog and `aiflux` Python package with `services\usage-ingestion\function_app.py`,
`host.json` and dependencies. Its timer imports `aiflux.ingestion.main`.
For immutable package deployment, use a reviewed private blob/package with managed identity,
not a SAS/account key. Do not switch on the disabled host until code packaging, DNS,
SQL grants, ingestion watermarks/bounds and metadata schemas pass. Enabling it requires
a reviewed Terraform change, not an unsupported automatic deployment toggle.

## Runtime RBAC and SQL bootstrap

The API receives a custom role assigned **only on this APIM**:
service read, product read, subscription read/write, listSecrets/action,
regeneratePrimaryKey/action, regenerateSecondaryKey/action. It cannot change service,
policies, APIs, backends, or model deployments. Runtime team subscription secrets live in
APIM/control-plane responses only, not Terraform, SQL or app settings.

API/ingestion get Log Analytics Reader on this workspace. Telemetry writers get Monitoring
Metrics Publisher on this App Insights only. Gateway gets Cognitive Services User on each
protection account and Secrets User on the gateway vault; edge gets Secrets User on the
certificate vault. Apps get AcrPull on the supplied ACR. Ingestion storage data roles apply
only to its dedicated host storage, whose shared-key auth is disabled.

Azure RBAC does not create SQL contained users. As the configured Entra SQL administrator,
run migrations first using a **separate operator identity**, then execute
`infra\sql\bootstrap-identities.sql` on the private database using SQLCMD variables
`API_PRINCIPAL_ID`/`INGESTION_PRINCIPAL_ID` from `identity_principal_ids`.
These are principal **object IDs**, not client IDs. The script uses SID-based external
users to avoid granting SQL server Directory Readers/Graph privileges; it rejects an
existing mismatched SID. API has schema DML but no DDL; ingestion has read access to
ownership/prices and DML only to usage/safety/watermark tables. Validate schema/grants
against actual migrations; do not grant db_owner to runtime identities.

## Post-deployment checks and rollback (not yet run)

1. Approve **only** the Front Door profile's pending private endpoint connection on the
   AppGW `private` frontend; confirm approved state and certificate/name/health/DNS.
2. Confirm APIM private VIP and internal DNS; test public and untrusted private-client
   bypass denial, SQL/AI/vault/storage public disablement and origin access.
3. Apply migrations/grants and verify API `/ready` remains accurately gated.
4. Audit diagnostics: no prompts/completions/body/entity mappings/keys in normal/error paths.
   APIM masks known credential query names, but query-key auth must be rejected by the
   future native contract; do not assume arbitrary URLs are sanitized.
   WAF/access diagnostics remain off until an independent safe projection is reviewed.
5. Run every native release gate; only after reviewed code/evidence enable the edge route,
   Function host and native API/Product in separate reviewed changes.

To stop a launched service, republish the unconditional denial first and disable
publication/routes/ingestion as appropriate. Never rollback to an uninspected pass-through.
Protect SQL/state from destroy and retain ownership/usage history. Terraform does not
manage or delete runtime APIM team subscriptions; reconcile them separately.

## References

- [Premium v2 private injection and subnet requirements](https://learn.microsoft.com/azure/api-management/inject-vnet-v2)
- [Front Door private App Gateway origin and approval](https://learn.microsoft.com/azure/frontdoor/how-to-enable-private-link-application-gateway)
- [App Gateway private-only network isolation](https://learn.microsoft.com/azure/application-gateway/application-gateway-private-deployment)
- [Front Door origin ARM contract](https://learn.microsoft.com/azure/templates/microsoft.cdn/2025-04-15/profiles/origingroups/origins)
- [Native LLM diagnostic ARM contract](https://learn.microsoft.com/azure/templates/microsoft.apimanagement/2025-09-01-preview/service/diagnostics)
- [AzureRM provider documentation](https://registry.terraform.io/providers/hashicorp/azurerm/5.9.0/docs)
- [Terraform AI gateway landing-zone reference](https://github.com/Azure/terraform-ai-gateway-landing-zone)
