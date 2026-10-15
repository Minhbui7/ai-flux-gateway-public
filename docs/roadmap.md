# Roadmap and future improvements

This is an issue-linked backlog, not a delivery schedule or a supported-feature
list. Current behavior and evidence live in [capabilities](capabilities.md).
No new feature, Azure deployment or governance decision is implemented here.

## Confirmed issue sequence

Only planning runs in parallel. Intended implementation order is #10, #12, #9,
#11, then #8. The user authorized #12 to start while #10's PR is open; therefore
the documentation distinguishes pending contracts from merged behavior.

| Issue / state at authoring | Value and requested scope | Dependencies / decisions | Documentation obligation |
| --- | --- | --- | --- |
| [#10](https://github.com/ajanakiraman_microsoft/ai-flux-gateway/issues/10), [PR #14](https://github.com/ajanakiraman_microsoft/ai-flux-gateway/pull/14) open | Model cost filtering, initially collapsed transaction detail retained in CSV, explicit public/list-price and Singtel-discount/not-invoice disclosure | Final contract must preserve authorization, historical aliases, null/partial semantics and scope changes | Update portal/control-plane docs in feature PR; reconcile PRD/spec/capability status when merged |
| [#12](https://github.com/ajanakiraman_microsoft/ai-flux-gateway/issues/12), this documentation | PRD, technical/components/configuration reference, approval readiness and improvement backlog | Source/provenance reconciliation; customer governance decisions can remain explicitly TBD | One documentation set, not deployment approval or vulnerability certification |
| [#9](https://github.com/ajanakiraman_microsoft/ai-flux-gateway/issues/9), proposed | Admin UI control of content-safety thresholds and APIM quota/rate limits | Authorization, validation, bounds, audit, concurrent updates, publish failure/rollback and drift policy need design; current API runtime role cannot write policies | Update stories, admin API/config contracts, role matrix and operator runbook |
| [#11](https://github.com/ajanakiraman_microsoft/ai-flux-gateway/issues/11), proposed | Customer-side one-click deployment with every manual CLI/portal exception highlighted | Tenant/consent, model eligibility/quota, RBAC, private SQL execution, DNS/certificates, state custody and costs | Own customer deployment guide and automation boundary; link rather than duplicate approval inventory |
| [#8](https://github.com/ajanakiraman_microsoft/ai-flux-gateway/issues/8), proposed | Stateless Auto choice using requested Microsoft-Decision-1 classifier, supported model set and supplied criteria, then existing backend route | Endpoint access, identity, additional prompt processing, classifier schema, eligible aliases, safety ordering, latency/cost, error/fallback and accounting decisions | Update request flow, model/API contracts, classifier approval/regions and operational diagnostics |

The classifier endpoint/criteria in #8 are requirements to evaluate, not evidence
of endpoint access, a deployed classifier or permission to send customer prompts.
Stateless scope excludes model-level caching in its initial version.

### Pending #10 contract handoff

The implementation session reports a model parameter across customer/admin
summaries, p95, capabilities, rows, charts and CSV; CSV also honors subscription.
`GET /api/usage/models` and `/api/admin/usage/models` return `Page[str]` of distinct
authorized historical aliases within days/subscription/organization, independent
of selected model, row page and chart viewport.

Unavailable selection resets visibly to All only after a successful current-scope
lookup; stale/failed lookups must not silently broaden filters. Transactions start
collapsed and CSV keeps their detail. These are **pending PR contracts**, not a
claim those endpoints exist in this branch's merged baseline. Re-read the actual
merged code/docs before changing their status.

## Optional improvement ideas

| Idea | Value | Dependency, risk and acceptance boundary |
| --- | --- | --- |
| Resolve unowned ingestion telemetry | Restore fresh, complete showback | Preserve exact APIM identity, explicitly reconcile test ownership; never advance watermark/drop rows silently |
| Accepted native unified API | Reduce custom translation and unlock proven native capabilities | Reproducible SKU/rollout artifact, bearer/product scope and all native inspection/telemetry gates; no claim from ordinary text success |
| Final TLS/origin protection and automated renewal | Accepted edge and sustainable certificate operations | Prove vault certificate read, trusted serving chain, renewal ownership, WAF/backend/origin/direct-bypass behavior |
| Comprehensive safety/failover acceptance | Demonstrate behavior beyond bounded smoke checks | Shape/Unicode/dependency-failure evidence, actual region selection, Retry-After and retry completeness; paid tests need separate scope |
| Improved usage coverage | Better cost confidence | Proven cache categories, every paid retry attempt and true first-token source; never substitute E2E for TTFT |
| Production multi-tenant onboarding | Customer deployment reuse | Customer consent/approval model, tenant-specific validation, negative isolation and full admin journeys |
| Gateway-region recovery | Recover beyond model backend failover | Customer RTO/RPO, replication, cost and operational exercises remain TBD |
| Semantic caching | Lower latency/cost for eligible workloads | Privacy, tenant isolation, correctness/invalidation, safety and cost measurement; not implemented |
| Customer-editable limits within IDS allocations | Controlled self-service | #9's authoritative bounds, delegation/audit and quota semantics first |
| Explicitly consented subscription memory | Optional continuity | Retention/deletion, data classification, Cosmos cost/access and explicit customer consent; stateless default must not change silently |

## Change and release discipline

Future feature PRs update the PRD, technical specification, capability status,
approval guide and relevant runbooks together. Record source behavior separately
from dated acceptance and proposed outcomes. A source declaration, green local
test or reviewer approval of prose does not activate a model or approve data
processing.

Each issue remains a separate PR targeting `main`, reviewed with existing CI;
merge requires explicit authorization and branch protections. Verify actual merge
and issue closure rather than equating an open PR with delivery. Do not bundle
new controls, grants, deployment automation or routing into #12.
