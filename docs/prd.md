# AIFLUX product requirements

## Purpose and outcomes

AIFLUX provides approved teams with one governed AI access point across supported
providers, controlled team credentials and transparent estimated consumption.
IDS administrators onboard organizations/members and inspect usage and safety
metadata without granting customers another organization's context.

The business outcomes are controlled access, reduced provider-integration effort,
visible list-rate consumption and reviewable governance. It is not an invoice
engine, a tool-execution platform, or an assertion of production readiness.
The [capability matrix](capabilities.md) distinguishes repository implementation,
historical acceptance, unverified live state and proposals.

## Personas and responsibilities

| Persona | Need | Authority boundary |
| --- | --- | --- |
| Customer team member | Discover models, manage team keys, try text chat and view owned usage | Enabled organization/member; cannot select another organization |
| IDS administrator | Onboard tenants/members, inspect showback/safety and maintain price periods | SQL-approved `ids_admin` in home tenant; not automatically an Azure/Entra administrator |
| Finance/showback reader | Understand known cost, incomplete estimates and export detail | Same authorized customer/admin scope; no separate finance role currently implemented |
| Deployment operator | Configure approved identities, images, network and runtime prerequisites | Separately authorized management-plane and SQL actions; not a portal privilege |
| Security/governance reviewer | Understand processing, permissions and approval dependencies | Customer policy defines sign-off authority; documentation cannot grant it |

## Feature and story acceptance

These criteria describe implemented contracts unless labeled proposed; they do
not claim every journey has been accepted live.

| ID / user story | Observable acceptance | Source / status |
| --- | --- | --- |
| US-01: As a user, I sign in to my approved organization | Missing/invalid identity is denied; unapproved tenant/member cannot access data; IDS is restricted to home tenant | `auth.py`, portal session/config; repository |
| US-02: As an IDS admin, I onboard or disable access | Organization and member changes are authorized/audited; disabling organization removes portal access and attempts key suspension; incomplete suspension is reported and retriable | `app.py`, `subscriptions.py`; repository |
| US-03: As a team, I obtain a managed API key | UUID idempotency key prevents duplicate ownership; ownership is committed before activation; ARM failure is visible; same request can reconcile | Subscription API/UI; repository; basic historical journey confirmed |
| US-04: As a key owner, I reveal/rotate/suspend credentials | Reveal is explicit, no-store and in-memory; hide/sign-out clears UI key; failed operations do not report success; reenabled organization does not reactivate keys implicitly | `SubscriptionsPage.tsx`, `app.py`; repository |
| US-05: As a developer, I discover supported models | Only eligible configured catalog entries are callable; provider-specific constraints and output ceilings apply; preview/unaccepted native capabilities are not advertised as guarded support | Catalog, `catalog.py`, gateway policy; repository |
| US-06: As a developer, I try guarded text chat | Browser calls APIM with a subscription key, input and output checks apply, unsupported streaming/tools/structured shapes are rejected; examples contain placeholders, not live keys | `PlaygroundPage.tsx`, guarded adapter; repository |
| US-07: As a customer, I inspect consumption | Summary, rows, CSV and UTC charts use owned ingested data; missing prices/usage remain Unknown; partial token/cost totals are disclosed; display seconds do not change API/CSV milliseconds | Usage API, `finops.py`, `UsagePage.tsx`; repository |
| US-08: As an IDS admin, I inspect showback and safety | Organization/subscription scope remains enforced; metadata, not conversations, is exposed; price periods are effective-dated and overlapping rules rejected | Admin API/pages; repository |
| US-09: As a user, I narrow usage to a historical model | Authorized model options and filtering agree across totals/p95/capabilities/rows/charts/CSV; collapsed transactions do not remove exported detail | #10, PR #14; pending, verify merged contract before release |
| US-10: As an admin, I change safety and APIM limits | Authorized, validated, auditable changes with failure/rollback semantics still to be designed | #9; proposed, no current admin write surface |
| US-11: As a customer operator, I deploy with minimal manual steps | Automation reports prerequisites and every consent/network/SQL/certificate exception; cannot call partial provisioning success | #11; proposed |
| US-12: As a developer, I choose Auto | Stateless classifier selects among supported models through the existing guarded path with defined errors/costs and no safety bypass | #8; proposed, fallback policy unresolved |

## Release scope

The guarded-development scope is non-streaming text Chat Completions via
`/dev/llm/v1`, explicit provider translation, eleven catalog aliases, team
subscription operations and estimated showback from SQL. Deployment remains
conditional on accepted inputs and runtime evidence.

The native production API remains gated. No promise is made for native bearer
keys, tools, strict JSON, live SSE, complete adversarial safety, all admin or
multi-tenant journeys, or final edge/origin acceptance. The separate legacy
`/dev/v1` route does not inherit the larger adapter surface.

## Nonfunctional requirements and constraints

| Area | Requirement / measurable boundary |
| --- | --- |
| Authorization | Enforce enabled SQL organization and `(tid, oid)` membership and delegated scope on protected requests; backend is authoritative |
| Secret handling | No credential in examples, SQL ownership data, URLs or application logs; explicit reveal with no-store response and memory-only portal handling |
| Content protection | Accepted shapes pass original/redacted input checks, PII and output safety; reject uninspectable/malformed output, do not invent an answer |
| Privacy | No application conversation persistence or tool execution; independently verify metadata-only telemetry and provider processing terms |
| Accounting | Unknown usage/prices cannot become zero; effective model/provider/region rates and incomplete attempts must remain visible |
| Resilience | Surface dependency/provisioning failures; bounded retries, no claim of hard spend cap or gateway-region DR |
| Usability | Configured endpoint/examples and units are explicit; no required-config fallback into an apparently working unauthorized app |
| Operations | Readiness is scoped; schema migration uses separate reviewed operator, not web startup or runtime DDL |

No numerical uptime, latency, financial accuracy or adoption target has been
approved. Suggested measures are onboarding completion, successful reconciliation,
guarded completion/error rates and known-cost/telemetry coverage, with business
owner, target and observation period **TBD**. Do not turn these into contractual
service levels without product/customer agreement.

## Dependencies and decisions

Customer identity model, consent policy, approved regions/provider terms, data
classification/retention, security approvers, deployment ownership and negotiated
pricing presentation remain customer decisions. See
[security readiness](security-and-approvals.md) for the approval register.

#10 is an open dependency for final usage-story acceptance. #12 supplies the
documentation foundation; #9, #11 and #8 must update these stories and the
technical/security documents when their actual contracts merge. Optional
improvements and exclusions are recorded in the [roadmap](roadmap.md).
