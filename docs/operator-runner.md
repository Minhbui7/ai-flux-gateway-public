# Deferred private operator design

**Not the active development deployment plan.** Public Basic v2 dev now uses the
local operator route in [Infrastructure](infrastructure.md), protected local state
and conditional hybrid private-data endpoints/API-Function integration in the
active root. No VM/runner/NAT/state bootstrap is required.
The artifacts below retain an unapproved future private design. Do not apply them
to the public root's same VNet/name space: no ownership transfer is implemented.

## Prepared, not deployed or registered

`infra\operator\` is a separate Terraform root, prepared for a deferred **Azure-hosted
Ubuntu 24.04 LTS machine in the dev VNet**. No Azure plan/apply, registration, certificate,
key generation or deployment is performed by this implementation. Every checked-in
environment example keeps `deployment_approved=false`. A machine is **not** an operational
GitHub runner: Azure CLI, Terraform, runner binaries, registration and live acceptance
remain separate operator work.

The root pins Terraform `~>1.16.0` and AzureRM `5.9.0`; the main/state roots additionally
pin AzAPI `2.13.0`. Local checks use Terraform `1.16.5` and mock all Azure providers.
The existing RG `rg-aiflux-example-dev` in subscription
`00000000-0000-0000-0000-000000000000` is a data source, not managed/imported/deleted.
The former design assumed Standard v2/private APIM and private apps; that is not
what the active Basic v2 public root deploys. This bootstrap does not add Front Door.

## Ownership and bootstrap order

The deferred private topology would give **exclusive shared-network ownership to
`infra\operator\` before any deployment**. It creates one VNet, five subnets, the private
blob DNS zone/link, private VM/NIC, runner NSG, NAT/public egress IP and a separate
environment-federated deployment identity. It does not create private state storage.

| Address | Purpose | Owner |
| --- | --- | --- |
| `10.240.0.0/16` | `aiflux-example-dev-vnet` | operator root |
| `10.240.1.0/24` | App Gateway, reserved during APIM stage | operator root |
| `10.240.2.0/24` | APIM Standard v2 integration; `Microsoft.Web/serverFarms` delegation | operator root |
| `10.240.3.0/24` | State and service private endpoints; endpoint policies disabled | operator root |
| `10.240.4.0/24` | App Service integration; `Microsoft.Web/serverFarms` delegation | operator root |
| `10.240.5.0/24` | Private operator/runner VM, no delegation | operator root |

All subnets explicitly disable default outbound access; **only the runner subnet**
has this NAT association. This is not an outbound solution for later apps/APIM:
their own service-specific outbound paths/dependencies still need acceptance.
The subscription VNet ARM list returned no entries/no continuation link. That does
**not** establish corporate/peering/VPN overlap clearance. The selected address candidate
is recorded, but `network_overlap_review_approved=false` until that review is complete.

After separately approved bootstrap:

1. An authorized laptop operator can create the operator root using protected local
   state: these resources use ARM management APIs, not private blob data-plane access.
2. Pass its `state_inputs` outputs explicitly to `infra\state\`:
   `private_endpoint_subnet_id` is the `.3` endpoint subnet, `private_dns_zone_id` is
   the linked `privatelink.blob.core.windows.net` zone and `runner_principal_id` is
   the **deployment** identity principal ID, not the VM identity.
3. The state root can initially create keyless/private ZRS storage, container and
   endpoint via ARM from the laptop, with its own protected local state. It grants
   Blob Data Contributor only at the `tfstate` container to that deployment identity.
   Storage-name uniqueness, cost and state-root approval remain required.
4. Verify private DNS/connectivity and authorize a private-connected operator for
   blob data access. Securely transfer both local states to that host. Only there,
   migrate operator and storage-bootstrap state to **different blob keys**;
   `aiflux-operator.tfstate`, `aiflux-state-bootstrap.tfstate`, and
   `aiflux-example-dev.tfstate` for the gateway are separate suggested keys. Never expose
   state publicly, copy state into Run Command payloads, or force-unlock an active lease.
5. Stop before gateway deployment: the active public root no longer accepts
   `operator_network` or shares private DNS. A future private gateway root and explicit
   state/resource ownership migration must be reviewed first; do not reuse the public
   dev resource names or consume this output in its current main root.

Operator and state roots intentionally start with the local backend. To migrate later,
copy their `backend_override.tf.example` to ignored `backend_override.tf`, supply a
private/keyless `backend.hcl` with that root's distinct key, and run `init -migrate-state`
on the private-connected authorized host. Do **not** use `-reconfigure` for a local-to-remote
migration, blindly accept overwrite prompts, or run a second writer during transfer.
After verifying remote state/version/lease behavior, securely remove residual local state
and backups according to the organization's retention policy.

The old main-root `operator_network` mode and VNet `moved` block are retired for this
empty public-dev configuration. **Do not apply this revision to an already deployed
private main state:** it would plan removal of private network resources.
For such a deployment, first back up states and explicitly migrate those resource
addresses between roots under exclusive operator control; inspect complete no-destroy
plans. There is no automated transfer here. The selected empty public-dev setup needs no such migration. Never duplicate/import the same
resource into both states, or use `terraform -target` as a bootstrap workaround.

## Private management, identity and explicit egress

The VM has **no public NIC IP**, no password login and no inbound SSH. An inbound deny
at NSG priority 100 also overrides Azure's default VNet inbound allow. Cloud-init masks
the SSH service/socket. Administration is Azure Run Command through the Azure Linux
Agent, not SSH/Bastion or an inbound exception. Run Command authority is root-level
machine administration: restrict operator Azure permissions and audit its use.

Two identities have deliberately different purposes:

- VM system-assigned identity: **no Azure roles** are granted by this root. Do not
  use `az login --identity` as a deployment shortcut or grant it Contributor/Owner.
  Untrusted jobs can reach IMDS; attaching a privileged deployment MI to the VM would
  bypass GitHub environment approval.
- Separate user-assigned deployment identity: exact federation subject
  `repo:REPLACE_WITH_GITHUB_OWNER/REPLACE_WITH_REPOSITORY:environment:aiflux-development`,
  issuer `https://token.actions.githubusercontent.com`, audience
  `api://AzureADTokenExchange`. Contributor and Role Based Access Control Administrator
  are scoped only to the existing dev RG. No subscription/Graph roles or app registration
  are created. RBAC Administrator is still powerful: it can delegate RG roles. The
  independent `deployment_identity_approved` gate requires explicit privilege review.
  Narrow/remove that role if an external operator will provision runtime assignments.

The previous private `deploy-control-plane.yml` workflow is disabled. Any future
private runner workflow must be separately reviewed and use protected environment
reviewers, branch restrictions and infrastructure approval gates. Do not schedule
fork/untrusted PR jobs on this runner. Review who may modify workflows or reference
the environment: exact-subject federation alone does not restrict a specific workflow.
The runner user belongs to `docker`, which is effectively root-level machine access.

Standard NAT gateway plus a Standard static public IPv4 is the **unapproved egress
candidate**. The IP belongs to NAT, never the NIC, and accepts no unsolicited inbound
connections. NAT is not a firewall/domain filter. `egress_approved` approves its cost
and outbound policy, not public ingress. Runner NSG allows:

- TCP 443 to Internet: GitHub Actions/OIDC/releases, Entra/ARM, Azure agent extension
  artifacts, package/registry downloads.
- TCP 443 to VNet: private state storage and private app/API health checks.
- UDP/TCP 53 to Azure DNS `168.63.129.16`.
- TCP 80/32526 to `168.63.129.16` for the Azure VM agent, and TCP 80 to
  `AzurePlatformIMDS` for managed identity/platform metadata.
- Explicit deny of other outbound traffic. Ubuntu package mirrors use HTTPS.

If policy requires FQDN restriction, replace this candidate with a separately priced
firewall/proxy/UDR design; do not assume NAT supplies allowlisting. Corporate DNS,
peering and custom routing must preserve agent/IMDS/DNS access. Later direct private SQL
migrations need a separately reviewed SQL endpoint/connection-policy/port rule (currently
blocked by this HTTPS-only private egress); do not broaden all VNet egress to fix them.
This bootstrap is for machine/state/APIM preparation, not yet acceptance of the full
control-plane deployment workflow.

## No-secret bootstrap and manual registration boundary

Cloud-init only installs Ubuntu base dependencies, Docker and the runner's non-login
password-locked account/directory. It contains **no PAT, GitHub registration token,
client secret or state credentials**. Failure remains visible in `cloud-init status`;
the completion marker is only machine-bootstrap evidence. It does not install/register
the GitHub Actions runner or claim Azure CLI/Terraform are installed.

After deployment is explicitly authorized, use nonsecret Run Command for acceptance.
This is an operator example, **not executed by this change**:

```powershell
az vm run-command invoke `
  --subscription 00000000-0000-0000-0000-000000000000 `
  --resource-group rg-aiflux-example-dev --name aiflux-example-dev-runner `
  --command-id RunShellScript --scripts "@infra\operator\check-machine.sh"
```

Check agent readiness/cloud-init status before retrying; do not open SSH to repair
egress. Install Azure CLI from Microsoft's signed package repository, Terraform
`1.16.5` from checksum/signature-verified HashiCorp packages, and an explicitly selected
GitHub runner Linux x64 release using its published SHA-256. Recheck disk capacity and
Docker builds: B2s is burstable and a 32 GiB disk can be insufficient for image caches.
Run the runner as `runner`, not root; do not install unrelated toolchains by default.

Registration is a **later manual secure action**:

1. An authorized repository administrator interactively requests the short-lived
   repository registration token in GitHub (normally expires after one hour).
   This is not a PAT or the Azure OIDC identity.
2. Review/approve a secret-safe handoff for registration on the private machine.
   **Action Run Command has no interactive TTY/stdin prompt**: `read -s` on the VM
   through it is not interactive. Do not paste a token into `--scripts`, `--parameters`,
   Terraform, custom data, shell history, an issue, workflow logs or a saved script.
   `--output none` only suppresses client display; it does not make payloads/agent
   logging secret-safe. No unsafe token-injection command is supplied here.
3. An operator may orchestrate the nonsecret script/service steps through Run Command
   only after an independently approved protected secret handoff/registration mechanism
   exists. Keep the registration token transient, disable tracing/token outputs, and
   verify configuration/agent logs do not retain it. Standard runner `.credentials`
   files are persistent credentials and must stay access-controlled on the runner disk;
   no registration token or credential output belongs in Terraform/state.
4. Register for **only** `REPLACE_WITH_GITHUB_OWNER/REPLACE_WITH_REPOSITORY` with labels
   `self-hosted,linux,aiflux-private`, configure its service under `runner`, restrict
   scheduling to trusted reviewed workflows and revoke/expire registration material.
   Verify GitHub reports the runner online, then separately test protected-environment
   OIDC and private blob access before enabling any deployment.

The secure registration handoff is deliberately **not implemented/approved**.
Do not claim an operational runner until these steps and actual connectivity checks pass.

## Pricing worksheet and remaining gates

These are extracted **comparison candidates**, not selected/approved spend. Azure Retail
Prices lookup on 2026-10-11 returned East US USD consumption Linux `Standard_B2s`
at `$0.0416/hour` (`$30.37` at 730 hours), Standard SSD E4 LRS disk at `$2.40/month`,
and Standard IPv4 static public IP at `$0.005/hour` (`$3.65` at 730 hours).
The VM+disk+IP subtotal is **$36.42/month before NAT, usage and all other services**.
NAT retail lookups returned no matching rows; its gateway-hour and processed-GB rates
must still be resolved before a total is quoted or approved.

| Candidate | Quantity / billing basis to price |
| --- | --- |
| Linux `Standard_B2s`, Ubuntu 24.04 | 1 x 730 VM hours; 2 vCPU/4 GiB, burstable |
| `StandardSSD_LRS`, 32 GiB / E4 | 1 managed OS disk/month plus disk transactions |
| Standard NAT gateway | 1 x 730 gateway hours **plus processed GB**; meter unresolved |
| Standard static IPv4 | 1 x 730 IP hours; still billed when VM deallocated |
| Private DNS | 1 blob zone + queries here; main adds other zones |
| State root, not created here | Standard_ZRS storage GB/versions/operations + 1 private endpoint hours/data |
| Traffic/other | Internet egress, registry/image traffic, optional logs/firewall, later platform resources |

Deallocating the VM stops compute charges, not disk/NAT/IP/storage/endpoint charges.
Refresh rates in the [Azure pricing calculator](https://azure.microsoft.com/pricing/calculator/)
or [Retail Prices API](https://learn.microsoft.com/rest/api/cost-management/retail-prices/azure-retail-prices);
exclude Windows/Spot/reservation meters from this Linux PAYG comparison. Region, offers,
discounts, taxes and workload usage can change the final estimate. No cost approval is implied.

Before any real plan/apply: resolve the NAT/full estimate and approve VM/disk sizing,
confirm B2s Ubuntu Gen2 Trusted Launch/secure boot/vTPM and East US capacity, obtain
corporate overlap/peering clearance and outbound-policy approval, approve federation/RBAC
and trusted workflow controls, supply an existing public SSH key without generating one,
verify required resource providers including `Microsoft.Compute`, and authorize/protect
local state. Separate registration, tool installation, state-name approval, private SQL
egress, live DNS/RBAC/connectivity, APIM capacity, Entra/images/SKUs, external TLS certificates
and public WAF release gates remain unresolved. Inference remains disabled.

## References

- [Azure Linux Run Command and prerequisites](https://learn.microsoft.com/azure/virtual-machines/linux/run-command)
- [Azure Linux Agent troubleshooting / required connectivity](https://learn.microsoft.com/troubleshoot/azure/virtual-machines/linux/linux-azure-guest-agent)
- [NAT gateway outbound-only connectivity](https://learn.microsoft.com/azure/nat-gateway/nat-gateway-resource)
- [Default outbound access](https://learn.microsoft.com/azure/virtual-network/ip-services/default-outbound-access)
- [Azure CLI signed package installation](https://learn.microsoft.com/cli/azure/install-azure-cli-linux)
- [GitHub Azure OIDC](https://docs.github.com/actions/security-for-github-actions/security-hardening-your-deployments/configuring-openid-connect-in-azure)
- [Adding a self-hosted runner](https://docs.github.com/actions/hosting-your-own-runners/managing-self-hosted-runners/adding-self-hosted-runners)
