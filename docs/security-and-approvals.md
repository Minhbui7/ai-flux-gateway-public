# Security and approvals readiness guide

## Scope and decision boundary

This is the #12 evidence-based security readiness deliverable: processing
boundaries, technical permissions and customer approval touchpoints. It is
**not a vulnerability assessment, penetration test, certification, CISO sign-off
or permission to deploy**. No approvals are inferred from source, telemetry
headers, sample attestations or historical developer acceptance.

Read [capabilities](capabilities.md) for evidence scope and
[technical specification](technical-specification.md) for configuration/flows.
The customer must name accountable owners and determine which actions need
administrative consent, security review, CISO approval or a documented exception.
Not every listed action universally requires the CISO or Global Administrator.

For example, Microsoft's tenant-wide consent guidance lists Cloud Application
Administrator or Application Administrator for permitted requests other than
Microsoft Graph application permissions, or an appropriately scoped custom
consent role. Privileged Role Administrator can consent to any API permission,
but that is not a recommendation to grant it for this application. Actual
authority depends on the requested permission set and customer tenant policy.
The current custom delegated scope does not justify adding Graph application
permissions. Entra administrative roles are separate from Azure RBAC roles.

## Data processing and trust boundaries

| Asset / flow | Implemented or intended control | Evidence / unresolved customer decision |
| --- | --- | --- |
| Browser access tokens | SPA PKCE, memory cache, API audience/scope; no token in CSV URLs | `packages/ui/src/auth.tsx`, `session.tsx`, `auth.py`; customer conditional-access/consent policy TBD |
| Revealed team keys | Explicit reveal, React memory, no-store; APIM is secret source, not SQL | `SubscriptionsPage.tsx`, `app.py`; customer distribution/rotation/revocation procedure TBD |
| Prompt/history | Original input reaches safety/PII services; redacted input is checked and forwarded to selected model | Gateway policy; PII redaction does not mean no service ever receives original personal data |
| Model answer | Buffered text normalized and moderated before release; internal thinking omitted | No tool executor or application conversation store; provider-side retention/terms require separate review |
| Usage / safety / audit metadata | SQL ownership, scoped APIs, effective prices and completeness; metadata-only diagnostics intended | Logs still identify model/subscription/time/consumption; classification, retention/deletion/access policy TBD |
| Regional movement | Shared model pools; private SQL region can differ from gateway and model regions | Customer-approved regions, cross-border basis, provider terms and residency commitments TBD |
| Certificates / state / operator artifacts | Managed identity, private data paths in hybrid mode; protected ignored local state | State and keys require restricted custody; no secret values or payload evidence in Git |

No application prompt/completion retention is intended. That does not establish
all providers' retention policies, prove every log sink excludes content or waive
customer privacy obligations. Original/redacted safety and fail-closed checks
must be evidenced for the actual accepted request shapes.

## Identity and authorization

There are distinct authorization planes:

| Plane | Authority | What it does not grant |
| --- | --- | --- |
| Entra registration / enterprise app | Tenant directory policy and allowed application owners/admins | Azure management rights or SQL application membership |
| OAuth delegated consent | API scope and configured consent policy/preauthorization | An approved AIFLUX tenant/member or runtime APIM policy-write access |
| AIFLUX application approval | Enabled SQL organization/member with appropriate role | Azure/Entra administrative role |
| Azure RBAC | Assigned principal, action and resource scope | SQL contained-user permissions or customer governance approval |
| SQL grants / migrations | Existing Entra SQL administrator and reviewed migration identity | Permission to open a public data endpoint or change tenant consent |
| Governance / CISO review | Customer-defined risk/exception decision | Technical execution rights unless separately assigned |

`bootstrap-entra.py` is a dedicated single-tenant developer/operator script, not
a reusable customer consent installer. It configures three registrations/SPs,
`access_as_user`, preauthorized SPA clients and `ids_admin`. The runtime backend
uses SQL membership/home-tenant checks; merely assigning an Entra app role is
not onboarding. Do not run that hard-coded bootstrap in a customer tenant.

`auth.py` supports an optional loopback MISE sidecar and a direct JWT
key-discovery branch. Confirm actual deployed mode and validation evidence
before claiming organizational SFI/MISE compliance; client headers alone cannot
certify it. No new Graph permission/consent is requested by this guide.

## Permission and approval inventory

All customer approval statuses below are **Pending customer decision / not
assessed**. Owner labels are suggested functions, not named approvers. Existing
development assignments are not transferable customer approvals.

| Component / action | Technical authority and scope | Actor / proposed reviewer | Evidence and revocation / rollback |
| --- | --- | --- | --- |
| Create/update API/customer/admin app registrations and SPs | Directory ability to create/manage these application objects under tenant policy; ownership for updates | Authorized identity operator / identity owner | Exact audience, tenant, redirect URIs, scope, owners and SP IDs; remove unneeded ownership/configuration or disable app after impact review |
| Configure delegated `access_as_user`, SPA preauthorization and consent | App-owner/authorized directory management plus consent authority appropriate to requested permissions and policy | Identity operator / identity-security reviewer | Requested permission manifest and consent decision; revoke grants/preauthorization with reauthentication impact recorded |
| Assign enterprise app role | Authorized application role-assignment authority; no blanket directory privilege prescribed | Identity administrator / application access owner | Principal/role/scope and approval; remove assignment; SQL membership still independently enforced |
| Approve organizations/members | Existing home-tenant SQL-approved IDS administrator; bootstrap requires reviewed operator identity | IDS admin / business access owner | Onboarding record and audit; disable membership/org, then verify incomplete APIM suspensions and retry as needed |
| Create custom runtime role / assign Azure roles | `Microsoft.Authorization/roleDefinitions/write`, `roleAssignments/write` at allowed scope, subject to conditions | Authorized platform deployer / platform-security owner | Reviewed definition, principal and resource scope; remove assignments/role only after checking dependencies |
| Manage team APIM subscriptions | API UAMI custom role: service/product read, subscription read/write, `listSecrets`, primary/secondary regeneration on this APIM instance | Runtime API / gateway owner | `infra/terraform/rbac.tf`; no policy/backend/service write; suspend/revoke exact subscription, rotate keys and verify serving state |
| Change APIM policy / safety / quotas | Not granted by current subscription-manager runtime role; deployment operator needs separately scoped relevant resource writes | Platform operator / gateway and security owners | #9 must design authorization, validation/audit/publish/rollback; do not grant broader access speculatively |
| Call AI services | Gateway UAMI `Cognitive Services User` on declared AI resources; model-root access/assignments reviewed separately | Gateway identity / AI platform owner | `rbac.tf`, `infra/models/main.tf`; exact deployed model access/format/regions; revoke assignment/disable alias with impact review |
| Model deployment / quota / marketplace eligibility | Reviewed Cognitive Services deployment management and applicable provider/subscription eligibility | Authorized model operator / AI platform, procurement and finance | Pinned model spec, quota/cost and provider terms; remove route before retiring deployment; do not substitute versions silently |
| Read certificate secret | Edge identity `Key Vault Secrets User` at configured vault scope; gateway identity has a separate vault reader assignment | Edge runtime / certificate and security owners | Vault-scoped edge role is broader than a single secret; review need and network access independently; revoke reader after safe certificate transition |
| Issue/upload/renew certificate | Separately approved issuer/DNS/ACME and narrowly scoped writer; private vault access path | Certificate operator / network-security owner | Ownership, trusted chain, expiry, rotation and HTTPS readback; remove temporary writer; no PFX/private key in logs/state examples |
| SQL Entra admin / migrations | Configured administrator and reviewed operator DDL; runtime has no migration DDL | Database operator / data-platform owner | Schema version and exact grants via private reachable path; no runtime admin substitution; reviewed migration rollback, not destructive reset |
| Runtime SQL | API: SELECT/INSERT/UPDATE/DELETE on `dbo`; ingestion: SELECT subscriptions/prices and SELECT/INSERT/UPDATE usage/state/safety | API/ingestion identities / data owner | `infra/sql/bootstrap-identities.sql`; SID uses client IDs, not principal object IDs; revoke exact grants/users after impact review |
| Monitor read / publish | API/ingestion `Log Analytics Reader` on workspace; `Monitoring Metrics Publisher` on Insights for declared identities | Runtime identities / observability owner | Query scope, sink/body/header settings and access review; revoke unneeded assignments; retention policy separately approved |
| Function host storage | Ingestion `Storage Blob Data Owner`, `Storage Queue Data Contributor`, `Storage Table Data Contributor` on its storage account | Function identity / platform owner | Keyless host configuration and private DNS; these are current source roles, not a claim that all are minimal; narrow only through separate reviewed change |
| ACR image pull/build | Runtime `AcrPull` on registry; operator build/push authority separately approved | Runtime and build operator / supply-chain owner | Immutable image digests, registry scope and build provenance; remove pull grants or roll back to reviewed digest |
| Private endpoints/DNS/VNet integration | Scoped network/private DNS/resource connection writes and any required target-owner endpoint approval | Network operator / network and data owners | Five services, DNS/TCP plus actual identity/data readiness; remove only reviewed resources, preserve governance-owned associations |
| Public apps/APIM and WAF origins | Scoped App Service/APIM/App Gateway management; exact CORS/CSP/access restrictions | Platform/network operator / security owner | Direct-dev exception separate from final edge release; verify origin-bypass denial before accepting edge; no wildcard firewall workaround |
| State, operator access and CI | Approved local protected state and operator identity; validation CI has contents read, no deployment authorization | Deployment operator / platform-security owner | Access-controlled state/evidence and explicit subscription selection; revoke operator access, rotate exposed credentials, never publish state |

Runtime permissions above describe source assignments, not the complete
management-plane permission set for every future customer deployment. The
deployment reviewer must inspect the full Terraform resource plan against
customer policy. Do not solve missing rights with subscription-wide Contributor,
Global Administrator or broad Graph consent.

## Residual risks and release constraints

Shared pools may process data outside the gateway/SQL region. Approximate limits
can overshoot and are not a financial cap; incomplete provider/retry telemetry
can understate estimates. One gateway region is not regional disaster recovery.
Direct public development origins are an exception, not final WAF/origin
protection. Native streaming moderation, if later accepted, cannot retract
content already delivered. Customer reviewers must explicitly evaluate these
constraints rather than treating historical smoke acceptance as risk acceptance.

## Required approval workflow

1. Product/data owner identifies environment, intended users, content classes,
   providers and processing regions.
2. Identity/platform/network/data owners review the exact manifests, scopes,
   images and proposed resource plan. Determine technical executor separately
   from risk approver.
3. Customer policy owner determines whether CISO or delegated security approval
   is required for cross-border processing, third-party terms, public endpoints,
   new application consent, policy changes or exceptions. These are review
   candidates, not universal CISO mandates.
4. Record decisions and conditions against a commit/artifact and environment.
   Unresolved decisions remain Pending; do not fabricate a signature.
5. Separately authorize execution, collect scoped runtime evidence and verify
   revocation/rollback paths. Re-review material changes and expiring exceptions.

## Readiness evidence checklist

| Area | Evidence needed before accepting the affected deployment |
| --- | --- |
| Identity | Actual app manifests, supported tenant model, consent policy, denied-user tests, SQL membership and chosen token-validation mode |
| Data/privacy | Approved regions/providers, classification/retention/deletion terms, no-sensitive-payload log inspection and scoped access review |
| Network/TLS | Private DNS/TCP and runtime identity readiness; trusted cert/read/renewal; WAF/origin and direct-bypass tests, not just resource provisioning |
| Gateway | Accepted model/shape matrix, PII/Prompt Shields/output safety including failures, limit/retry boundaries and actual selected endpoint |
| Accounting | Exact subscription ownership, effective rates, replay idempotence, completeness, unknown telemetry handling and freshness |
| Operations | Reviewed immutable images, migration/grant evidence, secret-safe state custody, monitoring/incident owner and rollback/revocation procedure |

Historical customer sign-in or one guarded completion cannot satisfy this entire
checklist. Latest recorded ingestion and edge gaps are in
[capabilities](capabilities.md); no current cloud evidence was collected here.

## Customer decision and exception register

| Decision | Proposed accountable function | Current state |
| --- | --- | --- |
| Single-tenant versus multi-tenant production, consent and app ownership | Customer identity owner | TBD |
| Which actions require CISO/delegated review, separation of duties, expiry | Customer governance owner | TBD |
| Provider terms, cross-border/residency and sensitive-data eligibility | Data/privacy and procurement owners | TBD |
| Retention/deletion, log access and incident response | Data/security operations | TBD |
| Public endpoint/origin exceptions, certificate renewal and private operator route | Network/platform security | TBD |
| Safety/limit change boundaries, financial guardrails and list-rate disclosures | Security and business/finance owners | TBD |

Use this approval/exception record without pre-populating a decision:

| Field | Required content |
| --- | --- |
| Request and environment | Change, customer scope, intended use and affected services |
| Artifact | Reviewed commit, manifest/plan/image hashes and evidence references |
| Executor / decision owner | Named authorized actor and independently accountable reviewer |
| Decision / conditions | Pending, approved, rejected or exception; exact constraints and rationale |
| Review / expiry | Decision record date, expiry and re-review trigger, where customer policy requires |
| Reversal | Rollback/revocation owner, steps, customer impact and verification |

An honest readiness guide may be published with TBD decisions. That is not
authorization for the affected deployment or production launch.

## Platform references

- [Tenant-wide consent](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/grant-admin-consent):
  review requested permissions; eligible consent roles depend on permission type.
- [Azure role assignment steps](https://learn.microsoft.com/en-us/azure/role-based-access-control/role-assignments-steps):
  principal, role and scope are distinct; assignment authority is separate.
- [Repository RBAC](../infra/terraform/rbac.tf),
  [SQL grants](../infra/sql/bootstrap-identities.sql),
  [Entra bootstrap](../infra/scripts/bootstrap-entra.py).

Vendor documentation supports platform semantics, not customer sign-off.
