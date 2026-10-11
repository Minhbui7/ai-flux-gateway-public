# AIFLUX - Access AI, Intelligently routed

An Azure API Management AI gateway and tenant-isolated customer/IDS control plane.

**Deployment is gated, not ready by default.** Native unified-model APIs are
preview/rollout-dependent. No model is exposed until the chosen APIM SKU,
provider translation, PII/safety behavior, and regional access are validated.
Tools and structured outputs cannot be advertised without inspection coverage.

## Components

| Component | Implementation |
| --- | --- |
| Public inference | APIM-only OpenAI-compatible `/v1/models` and `/v1/chat/completions` |
| Edge | Staged public Application Gateway WAF_v2 HTTPS -> public Basic v2 APIM/authenticated origins (no development Front Door) |
| Customer portal | React/TypeScript, Entra login, team keys, catalog, playground, showback |
| IDS portal | React/TypeScript, onboarding, organization/subscription showback, safety events |
| Control plane | Python FastAPI, APIM ARM operations, approved tenant/user authorization |
| Data | Azure SQL ownership, prices, usage projections, audit and safety metadata |
| Observability | Azure Monitor/Log Analytics and Python timer ingestion |
| Infrastructure | Terraform with AzureRM and narrowly scoped AzAPI resources |

The approved first-release design uses shared global model pools, approximate
round-robin routing, Retry-After-aware failover, best-effort RPM/token limits, and
estimated showback rather than invoice-grade chargeback.

Input PII is redacted with Azure Language. Content Safety and Prompt Shields
inspect input; output moderation uses sliding windows for SSE. A safety violation
may terminate a stream after earlier windows were delivered. No tool is executed
by the gateway or playground, and no prompts/completions are retained.

## Deployment context

The user-selected FDPO subscription is `4d75ed7f-75ab-4db6-b1f3-263f240d1450`.
Resource group **`rg-aiflux-fdpo-dev`** has been created and verified in **East US**.
This is the group's metadata location, not proof of model/SKU availability.
All scripts must select this subscription explicitly; do not change shared CLI
defaults. Existing resource groups and workloads must not be modified.

Development uses Basic v2 APIM, public P1v3 apps/Foundry endpoints and private SQL S0
in Australia East. SQL, Key Vault and Function storage have private endpoints;
API/ingestion use outbound VNet integration. Single-tenant Entra registrations,
application images and SQL migration/bootstrap are deployed.
Deploy locally with Azure CLI/Entra authentication and encrypted, access-controlled
ignored local Terraform state. No VM/private runner/operator or blob-state bootstrap
is required. Private operator/state designs are deferred. Examples remain unapproved
and provision nothing.

Guarded Luna/Sol text completions have succeeded through
`https://aiflux-fdpo-dev-apim.azure-api.net/dev/v1` with an approved APIM subscription
key. This separate limited dev product is not the final native unified API: streaming,
tools and structured outputs are rejected. The main `/v1` route remains denied and
ingestion remains disabled. Haiku 5.5 is deployed in both model regions but not routed.
Full portal journeys, failover/quota/safety acceptance and live FinOps remain pending.

Bounded dev acceptance now includes correct 401/400/415/429/403 status handling,
Luna/Sol inference, and a synthetic Prompt Shields rejection. RPM/TPM counters are separate;
2 RPM allowed three requests before throttling in one burst (best-effort overshoot of one).
Explicit metadata-only LLM diagnostics now correlate both fresh model completions with
subscription-owned gateway logs; body/message absence was checked after activation.
This is not full PII/failover/portal/FinOps acceptance or native bearer/Anthropic support.

**Current priority:** complete model routing, portal integration, unified API and
live FinOps before fixing Application Gateway HTTPS. Its trusted certificate is
issued, but Key Vault certificate access blocks HTTPS; renewal is not automated.
Direct APIM managed HTTPS remains the dev inference path. Deferring the edge fix
does not waive final TLS/origin-protection acceptance.
See the [dev runbook](docs/infrastructure.md).

## Development

Python setup, authentication, migrations and ingestion:
[Control plane](docs/control-plane.md).
Frontend setup and tests: [Portals](docs/portals.md).
Gateway policy/provisioning: [Gateway](docs/gateway.md).
Azure configuration: [Infrastructure](docs/infrastructure.md).
Supported/native capability gates: [Capabilities](docs/capabilities.md).

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\pytest.exe -q
.\.venv\Scripts\ruff.exe check services\control-plane\src tests\unit
.\.venv\Scripts\mypy.exe
npm ci
npm run typecheck
npm test
npm run build
```

CI validates Python, frontend builds and Terraform without provisioning Azure.
The old private-runner deployment workflow is disabled; use the reviewed local
operator route today. The approved hybrid root keeps SQL, vault and Function
storage public-disabled with private endpoints; API/ingestion integrate outbound.
Private SQL migrations/vault uploads require an approved VNet-connected execution
route, not a public firewall exception. See the infrastructure runbook.

## Native limitations

Per-request cached-read/cache-write tokens and true streaming time-to-first-token
are not available in the documented native LLM log schema. They are nullable and
explicitly marked unsupported unless native coverage is proven. Gateway total
latency is **not** a TTFT substitute. Missing prices/usage/backend attribution
cannot become zero-cost records.

There is one gateway region in this release; model-backend failover does not
provide gateway-region disaster recovery. Customers share a global backend pool:
cross-border processing must be disclosed during onboarding.

## Backlog

Managed Redis semantic caching, customer-editable limits within IDS allocations,
and explicitly consented Cosmos DB subscription memory are not implemented in
the first release.

## References

- [Canonical APIM AI Gateway labs](https://github.com/Azure-Samples/AI-Gateway)
- [AI Hub Gateway accelerator](https://github.com/Azure-Samples/ai-hub-gateway-solution-accelerator)
- [Terraform landing-zone counterpart](https://github.com/Azure/terraform-ai-gateway-landing-zone)
- [Native unified model API](https://learn.microsoft.com/azure/api-management/unified-model-api)
