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

## Architecture

The diagrams below illustrate the system topology and traffic flows reflecting all current development and infrastructure changes:
- **Application Gateway v2 HTTPS & Key Vault integration:** Key Vault network ACLs permit `bypass = "AzureServices"` so Application Gateway v2 can retrieve and reload its SSL certificate via its User-Assigned Managed Identity (`edge-identity`).
- **Unified CORS coverage:** Application Gateway FQDN (`https://aiflux-gateway-dev.eastus.cloudapp.azure.com`) is configured as an allowed CORS origin across both the Control Plane API and the APIM guarded adapter.
- **Guarded `/dev/llm/v1` adapter:** Eleven accepted models: the original `gpt-5.6-luna`, `gpt-5.6-sol`, and `claude-haiku-5-5`, plus `gpt-6-astra`, `gpt-6-luna`, `gpt-6-sol`, `Kimi-K2.6`, `DeepSeek-V4-Flash-0731`, `DeepSeek-V4-Pro`, `claude-sonnet-5-5`, and `claude-opus-5-5`. Guarded non-streaming text chat retains thinking-block normalization, the 20,000 TPM per-subscription/model limit, and 10 team subscriptions. New models have a 4,096-token request output ceiling; original limits are unchanged.
- **Playground and showback:** Configured base/REST endpoint details and secret-free cURL/OpenAI Python examples; synchronized, zoomable minute charts for requests, reported tokens, and average latency. Usage-page latency is displayed in seconds; existing millisecond API/CSV fields remain unchanged.
- **Hybrid private data path:** Azure SQL (Australia East S0), Azure Key Vault, and Function Storage run with public access disabled via Private Endpoints in VNet `10.240.3.0/24`. Outbound access from App Service uses regional VNet integration (`10.240.2.0/24`).

An editable Draw.io version is also maintained at [`docs/architecture.drawio`](docs/architecture.drawio).

### System Topology & Routing

```mermaid
flowchart TB
    subgraph Clients["Clients & Identity"]
        direction TB
        Browser["User Browser<br/>(Customer / IDS Admin Portals)"]
        APIClients["API Clients / SDKs<br/>(OpenAI-Compatible Apps)"]
        Entra["Microsoft Entra ID<br/>(Single-Tenant OAuth2 / PKCE)"]
        Browser <-->|"Auth / Tokens"| Entra
    end

    subgraph Edge["Edge Layer (East US)"]
        direction TB
        AppGwPIP["Public IP & FQDN<br/><code>aiflux-gateway-dev.eastus.cloudapp.azure.com</code><br/>Ports 80 (ACME), 443 (HTTPS)"]
        WAF["WAF Policy (Prevention Mode)<br/>• OWASP 3.2 Core Rules<br/>• Custom: Block <code>/v1*</code> Inference<br/>• Custom: ACME HTTP-01 Challenge"]
        AppGw["Application Gateway v2 (WAF_v2)<br/>• Managed Identity: <code>edge-identity</code><br/>• HTTPS Listener (Key Vault SSL cert)"]
        AppGwPIP --> WAF --> AppGw
    end

    subgraph VNet["Azure Virtual Network (10.240.0.0/16 - East US)"]
        direction TB

        subgraph SubnetAppGw["Subnet: appgw (10.240.1.0/24)"]
            AppGwBox["App Gateway Subnet Routing"]
        end

        subgraph SubnetInteg["Subnet: app-service-integration (10.240.2.0/24)"]
            VNetInteg["Regional VNet Integration<br/>(Delegated to Web ServerFarms)<br/>NSG: Outbound 1433/443 to PE Subnet"]
        end

        subgraph SubnetPE["Subnet: private-endpoints (10.240.3.0/24)"]
            direction TB
            PESQL["Private Endpoint: SQL<br/><code>privatelink.database.windows.net</code>"]
            PEKV["Private Endpoint: Key Vault<br/><code>privatelink.vaultcore.azure.net</code>"]
            PEStore["Private Endpoint: Storage<br/><code>privatelink.{blob,queue,table}</code>"]
        end
    end

    subgraph Compute["App Services Tier (Linux B1 Plan)"]
        direction TB
        CustApp["Customer Portal Web App<br/><code>aiflux-dev-customer</code><br/>(React SPA: Playground, Keys, Showback)"]
        AdminApp["IDS Admin Portal Web App<br/><code>aiflux-dev-admin</code><br/>(React SPA: Onboarding, Quotas, Audits)"]
        APIApp["Control Plane API Web App<br/><code>aiflux-dev-api</code> (FastAPI / Python)<br/>• APIM ARM Subscription Management<br/>• MSSQL-safe Queries (<code>= 1</code>)<br/>• <b>CORS: AppGw FQDN + Portals</b>"]
    end

    subgraph PrivateData["Hybrid Private Data Tier (Public Access Disabled)"]
        direction TB
        AzureSQL[("Azure SQL Database S0<br/>Location: Australia East<br/>• Tenants, Users, Subscriptions<br/>• Pricing Rules & Audit Logs")]
        KeyVault["Azure Key Vault<br/><code>aifluxdevkv</code> (RBAC)<br/>• TLS/SSL Origin Cert<br/>• <b>bypass = 'AzureServices'</b>"]
        FnStorage["Function App Storage<br/>(State, Blobs, Queues, Tables)"]
    end

    subgraph Gateway["AI Gateway Tier (Azure APIM Basic v2)"]
        direction TB
        APIMAdapter["Guarded Dev Adapter: <code>/dev/llm/v1</code><br/>Product: <code>aiflux-dev-unified</code> (Cap: 10 Subs)"]
        
        subgraph Pipeline["Gateway Inbound Policy Pipeline"]
            direction TB
            P_CORS["1. CORS Policy: Allow AppGw FQDN + Portals"]
            P_Auth["2. Auth: <code>Ocp-Apim-Subscription-Key</code>"]
            P_Rate["3. Throttling: 2 RPM / 20k TPM<br/>Output: originals 100k / new models 4096"]
            P_PII["4. Synchronous PII Redaction (5-doc Batches)"]
            P_Shield["5. Prompt Shields & Input Moderation"]
            P_Trans["6. Provider Normalization & Translation"]
            P_OutMod["7. Output Safety Moderation & Thinking Filter"]
            P_CORS --> P_Auth --> P_Rate --> P_PII --> P_Shield --> P_Trans --> P_OutMod
        end
        APIMAdapter --> Pipeline
    end

    subgraph AIBackends["AI Services & Model Backends"]
        direction TB
        OAI["Azure OpenAI (East US + Sweden Central)<br/>Original GPT-5.6: 120k TPM per deployment<br/>GPT-6 Astra/Luna/Sol: 100k TPM per deployment"]
        Foundry["Foundry Direct (existing regional accounts)<br/>DeepSeek Flash/Pro: 100k TPM per deployment<br/>Kimi: East US 100k TPM<br/>Anthropic Messages: Haiku/Sonnet/Opus<br/>Sonnet/Opus: East US 50k/40k TPM"]
        Safety["Azure AI Content Safety<br/><code>aiflux-dev-safety</code><br/>(Prompt Shields & Text Moderation)"]
        Language["Azure AI Language Services<br/><code>aiflux-dev-foundry</code><br/>(Synchronous PII Detection)"]
    end

    subgraph FinOpsObs["Observability & FinOps"]
        direction TB
        LogAnalytics["Azure Log Analytics<br/><code>aiflux-dev-logs</code>"]
        AppInsights["Application Insights<br/><code>aiflux-dev-insights</code>"]
        FinOpsFn["FinOps Ingestion Timer Function<br/><code>aiflux-dev-ingestion</code> (5-min schedule)<br/>Reconciles logs with pricing rules"]
    end

    %% Edge Traffic Flows
    Browser -->|"HTTPS (443) Web Traffic"| AppGwPIP
    AppGw -->|"Path: / (Default)"| CustApp
    AppGw -->|"Path: /admin/*"| AdminApp
    AppGw -->|"Path: /api/*, /health, /ready"| APIApp
    AppGw -.->|"SSL Cert Fetch (AzureServices Bypass)"| KeyVault

    %% Direct Portal & Client API Flows
    CustApp -->|"REST API (CORS)"| APIApp
    AdminApp -->|"REST API (CORS)"| APIApp
    CustApp -->|"Playground Chat (CORS)"| APIMAdapter
    APIClients -->|"Direct Inference (/dev/llm/v1)"| APIMAdapter

    %% Outbound Private Integration
    APIApp -->|"Outbound VNet Integration"| VNetInteg
    VNetInteg --> PESQL --> AzureSQL
    VNetInteg --> PEKV --> KeyVault

    %% Gateway to AI Services
    P_PII -.->|"Redact PII"| Language
    P_Shield -.->|"Input Shield Check"| Safety
    P_OutMod -.->|"Output Safety Check"| Safety
    P_Trans -->|"OpenAI Chat/Completions"| OAI
    P_Trans -->|"Anthropic Messages (thinking stripped)"| Foundry

    %% Observability & FinOps Flows
    APIMAdapter -.->|"Diagnostic Logs"| LogAnalytics
    APIApp -.->|"Telemetry"| AppInsights
    FinOpsFn -->|"1. Query Request Logs"| LogAnalytics
    FinOpsFn -->|"2. Outbound Integration"| VNetInteg
    FinOpsFn -->|"3. Write Showback Costs"| PESQL
```

### Gateway Request & Guardrails Flow

```mermaid
sequenceDiagram
    autonumber
    actor Client as User / Playground / Client
    participant GW as Azure APIM (/dev/llm/v1)
    participant PII as Azure AI Language (PII)
    participant Safety as Content Safety & Prompt Shields
    participant Model as Azure OpenAI / Foundry (Haiku)
    participant Logs as Log Analytics & FinOps

    Client->>GW: POST /chat/completions (Ocp-Apim-Subscription-Key)
    Note over GW: 1. Validate CORS origin (Portals + App Gateway FQDN)<br/>2. Validate Subscription Key (10-sub team pool)<br/>3. Check Throttling (2 RPM / 20k TPM)
    
    rect rgb(254, 249, 195)
        Note over GW,PII: Guardrail Inspection Phase
        GW->>PII: Synchronous PII detection in 5-document batches
        PII-->>GW: Redacted prompt content
        GW->>Safety: Prompt Shields & Input Moderation
        Safety-->>GW: Input passed (no jailbreak/harmful content)
    end

    rect rgb(236, 253, 245)
        Note over GW,Model: Execution & Translation Phase
        alt Model uses an OpenAI-compatible wire API
            GW->>Model: Forward native OpenAI request (using Gateway UAMI)
            Model-->>GW: OpenAI response + usage
        else Model is claude-haiku-5-5
            GW->>Model: APIM policy translates to /anthropic/v1/messages
            Model-->>GW: Anthropic response (with thinking + text blocks)
            Note over GW: Strip internal thinking blocks & map usage
        end
    end

    rect rgb(254, 249, 195)
        Note over GW,Safety: Output Moderation Phase
        GW->>Safety: Moderation check on response text
        Safety-->>GW: Output passed
    end

    GW-->>Client: 200 OK (OpenAI-compatible payload)
    GW-)Logs: Stream diagnostic log (tokens, model, latency, sub ID)
    Note over Logs: FinOps timer function ingests logs<br/>and computes showback costs in Azure SQL
```

## Deployment context

The user-selected FDPO subscription is `4d75ed7f-75ab-4db6-b1f3-263f240d1450`.
Resource group **`rg-aiflux-fdpo-dev`** has been created and verified in **East US**.
This is the group's metadata location, not proof of model/SKU availability.
All scripts must select this subscription explicitly; do not change shared CLI
defaults. Existing resource groups and workloads must not be modified.

Development uses Basic v2 APIM, public B1 apps/Foundry endpoints and private SQL S0
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
ingestion remains disabled. Haiku 5.5 is deployed in both model regions but is not
routed by this original development API. Basic customer acceptance is recorded
below; full admin/multi-tenant journeys, failover/quota/safety and live FinOps remain pending.

**Latest development path (2026-10-14):** the user-approved, Terraform-managed
text adapter at `https://aiflux-fdpo-dev-apim.azure-api.net/dev/llm/v1` returns
real OpenAI-shaped completions for all eleven accepted catalog models listed
above. This is explicit APIM policy translation, **not** the native
unified-model preview. Its separate `aiflux-dev-unified` product is used by the
control plane for new team keys. The original `/dev/v1` remains available for
its original approved subscriptions; `/v1` and the experimental `/llm/v1` remain
denied. Both providers retain original/redacted input safety, Prompt Shields,
five-document PII batches, output safety, UAMI authentication and bounded retry.
Streaming/tools/structured output are rejected. The user-approved adapter bounds
are 2 RPM/model/subscription and 20,000 TPM, with 100,000 completion tokens per
request for original models and 4,096 for the eight new aliases,
with a 240-second backend timeout. Legacy `/dev/v1` retains 2,048 TPM and 64 output
tokens. A live Sol request completed a 6,364-word essay with 8,571 completion tokens.
The Haiku response-conversion failure is repaired: validated internal thinking
blocks are omitted, full usage is retained, and final text must pass output
safety. Haiku completed a live 5,241-word essay with normal `stop`; malformed,
unknown or internal-only responses still fail closed. The ceiling does not
guarantee generation length or completion before a timeout.

Direct customer/admin App Service endpoints are intentionally public as the
approved stopgap; Entra and SQL membership authorization remain mandatory.
The portals use the direct API and APIM origins, with exact CORS/CSP settings,
native subscription-key headers and capability-aware non-streaming requests.
The development catalog contains eleven callable models, all checked before
publication. The API and enabled ingestion Function bundle the same accepted
catalog. Production inference remains disabled. New aliases do not inherit
prices from other models; unpriced usage remains Unknown.
The user confirmed the signed-in customer journey: team subscription
reconciliation succeeds, its key reveals, and both OpenAI and Anthropic respond
in the playground. The deployment-only blockers were SQL Server-invalid Boolean
approval predicates and the adapter product's one-subscription cap. Both are fixed;
the user-approved cap is 10, and disposable test subscriptions have been deleted.

Bounded dev acceptance now includes correct 401/400/415/429/403 status handling,
Luna/Sol inference, and a synthetic Prompt Shields rejection. RPM/TPM counters are separate;
2 RPM allowed three requests before throttling in one burst (best-effort overshoot of one).
Explicit metadata-only LLM diagnostics now correlate both fresh model completions with
subscription-owned gateway logs; body/message absence was checked after activation.
This is not full PII/failover/portal/FinOps acceptance or native bearer/Anthropic support.
The synchronous PII five-document limit is now respected while preserving the 25-message
API bound; 5/6/25-message role/Unicode cases pass. Buffered transient model 5xx gets one
bounded retry; unknown usage from prior attempts remains incomplete in FinOps.

**Basic development deployment accepted.** Remaining work: native unified API,
complete safety/failover acceptance and live FinOps. Application
Gateway HTTPS remains deferred. Its trusted certificate is
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

Resolve native unified-model routing/translation, replace the six
preview tiles with genuinely deployed/validated models, enable validated
FinOps ingestion, and fix Application Gateway certificate access/renewal.
Public App Service access is a development stopgap, not final edge acceptance.

Managed Redis semantic caching, customer-editable limits within IDS allocations,
and explicitly consented Cosmos DB subscription memory are not implemented in
the first release.

## References

- [Canonical APIM AI Gateway labs](https://github.com/Azure-Samples/AI-Gateway)
- [AI Hub Gateway accelerator](https://github.com/Azure-Samples/ai-hub-gateway-solution-accelerator)
- [Terraform landing-zone counterpart](https://github.com/Azure/terraform-ai-gateway-landing-zone)
- [Native unified model API](https://learn.microsoft.com/azure/api-management/unified-model-api)
