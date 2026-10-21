# AIFLUX portals (customer + IDS admin)

## Subscription administration

IDS admins manage subscriptions at `/admin/subscriptions` across organizations.
The page lists all organizations' subscriptions; select an enabled organization
to create a named team subscription. Existing reveal/mask/copy/hide, rotation,
suspend/activate and reconcile actions remain. Keys are memory-only and cleared
on organization changes, leaving this page, rotation and sign-out.
The customer navigation no longer includes Subscriptions; old `/subscriptions`
bookmarks redirect to `/models`. Customer management APIs also reject writes.

Playground retains organization-scoped subscription selection and automatic key
retrieval on its Reveal action. Customers can still obtain their own active keys;
this is not an admin-only-key model. Usage subscription filters are unchanged.
New subscriptions automatically refresh gateway bindings from published settings
without changing limits/safety. Provisioning state and gateway access pending
are displayed separately; explicit errors and Reconcile support recovery.
Initial Gateway settings still require administrator publication, and unrelated
pending configuration edits must be reconciled in Gateway settings first.

Admin Gateway and Content safety settings label `/dev/v1` as **API interface**
and `/dev/llm/v1` as **Chatbot interface**. These are friendly labels, not access
restrictions: API clients can also use the chatbot-compatible endpoint.
Managed settings and revisions are shared across both interfaces.
Gateway settings shows both endpoint labels above one shared editor. RPM,
concurrency and daily/monthly request quotas appear first; token controls are
collapsed under **Token limits**. Team/subscription selection and overrides remain
available. Revision history/recovery and **Important notes** are collapsed at the
bottom. Publication errors, conflicts and disabled-enforcement warnings remain
visible; collapsing guidance does not change limits or publication behavior.
Content safety likewise shows both endpoint labels above one shared safety editor.
Its profile, thresholds and protection toggles appear first,
with **Revision history and recovery** and **Important notes** collapsed below
the form. It uses the canonical API scope when present, or the single available
scope, for publication and history. Operator-floor and propagation guidance live
in the notes; blocking
capability errors, invalid values, conflicts and pending-publication retry remain
visible. This layout does not change safety values or enforcement.

React/TypeScript (Vite, npm workspaces). Distinct entry points share `packages/ui` (typed control-plane client, SSE/chat client, components).

See the [PRD](prd.md), [technical specification](technical-specification.md) and
[security/approval guide](security-and-approvals.md) for requirements and review
boundaries. [Capabilities](capabilities.md) is the canonical status reference.
The current source development catalog contains eleven enabled aliases; dated
three-model records below precede that expansion. #10 / PR #14's model filters,
collapsed transaction details and pricing disclosures are pending changes,
not merged behavior described by this baseline.

| Path | Purpose |
|------|---------|
| `apps/customer-portal` | Served at `/` — catalog, team subscriptions & key reveal, guarded text playground, usage/showback |
| `apps/admin-portal` | Served at `/admin/` (Vite `base: /admin/`, router basename `/admin`) — showback, safety metadata, gateway settings, organizations, members, prices |
| `packages/ui` | Shared client (`ControlApi`), `chatCompletion` (SSE), validation, pages, styles |
| `tests/e2e` | Playwright (deny-by-default, mobile) |

## Commands
`npm install`, `npm run typecheck`, `npm test` (vitest), `npm run build`, `npm run e2e`, `npm run dev:customer` (5173) / `dev:admin` (5174/admin/). Set `CONTROL_API_PROXY_TARGET` to proxy `/api` in dev.

## Customer model-token chart

The customer Usage & cost page adds **Token consumption by model** below the
three existing charts. Each UTC time bar stacks known input-plus-output tokens
by model, with a model legend, keyboard/hover bucket selection and collapsed
exact-data table. All models remain visible; no top-model cutoff is applied.
Period, Subscription, Model and shared zoom/pan/reset controls apply. Transaction
pagination and CSV retain their existing behavior. Admin showback is unchanged.

The customer-scoped `/api/usage/model-tokens` endpoint aggregates all matching
records in SQL, not the transaction page. Adaptive buckets (1/5/15 minutes,
1/6/12 hours, 1/7 days) keep each viewport to at most 120 bars. Bucket totals
are not per-minute rates. UTC boundary buckets are clipped to the viewport.
Only records with both input and output counts contribute to known token totals.
Missing measurements remain unknown, with partial-data notices and per-bucket
missing-request counts; idle buckets show zero. Failed/throttled requests count
if telemetry reports token consumption. No migration or ingestion change is needed.
This view requires the matching control-plane API version before customer rollout.

## Compile-time public configuration (no secrets)
| Variable | Value |
|----------|-------|
| `VITE_ENTRA_CLIENT_ID` | Portal's app registration client ID (GUID) — required |
| `VITE_ENTRA_AUTHORITY` | `https://login.microsoftonline.com/organizations` by default; a tenant-GUID authority is supported for a single-tenant environment |
| `VITE_API_SCOPE` | e.g. `api://<api-app-id>/access_as_user` — required |
| `VITE_CONTROL_API_URL` | default `/api` (same origin) |
| `VITE_GATEWAY_URL` | HTTPS gateway base including the API path; development uses direct APIM `/dev/llm/v1` (chat posts to `<url>/chat/completions`) |

If any required value is missing/invalid the portal renders a "Portal not configured" screen and nothing else (deny by default).

## Security model
- MSAL authorization-code + PKCE via popup, `cacheLocation: memoryStorage` (no token/key in localStorage/sessionStorage; reload requires sign-in). Register SPA redirect URIs `https://<host>/redirect.html` (customer) and `https://<host>/admin/redirect.html` (admin). Do not send `Cross-Origin-Opener-Policy: same-origin` (breaks popup).
- The development registrations are intentionally single-tenant and use the home tenant GUID authority. This is a DEV-only choice; multi-tenant registration requirements are deferred to the customer environment. Production behavior remains organizational/multi-tenant when the authority is not overridden.
- The dev bootstrap registers both the future Application Gateway callbacks and the direct App Service callbacks: `https://aiflux-example-dev-customer.azurewebsites.net/redirect.html` and `https://aiflux-example-dev-admin.azurewebsites.net/admin/redirect.html`. Existing SPA callbacks are preserved. MSAL derives its callback from the current origin and portal base path; registering only the gateway hostname causes `AADSTS50011` when signing in on App Service.
- `/api/me` is called before any view; 401/403/404 deny. Role check in the UI (admin portal requires `ids_admin`; customer portal accepts `customer`/`ids_admin`) is a convenience — the backend is the authority. Tenant from the token must equal `tenant_id` from `/api/me`.
- All control-plane and gateway fetches use `cache: no-store`, `credentials: omit`. CSV export is an authenticated fetch + blob download (no token in URL).
- The shared customer/admin usage page offers a Model filter for summaries (including p95 and completeness), minute charts, transactions, and CSV. Choices come from authorized historical usage within the selected period and subscription/organization, not the active catalog, selected model, transaction page, or chart viewport. If changing scope removes the selected model, the selector visibly resets to All models with a notice; failed option lookups show an error/retry rather than broadening the filter.
- Transaction details and their pagination are collapsed by default behind an accessible disclosure. CSV remains available while details are collapsed and includes the complete filtered period, including the selected subscription and model, not just the current page or chart viewport. The existing 10,000-row cap, columns, spreadsheet escaping, and raw millisecond fields remain unchanged.
- Both usage views disclose configured list-price estimates, possible Singtel-specific discounts affecting actual charges, and not-an-invoice status. Unknown costs are not zero, incomplete known costs remain lower bounds, and mixed currencies are not combined. Discounts are not calculated or applied by this view.
- Subscription keys are revealed only on explicit click, kept in React memory, cleared on Hide, rotation and sign-out. Nothing is logged.
- Playground calls the configured gateway directly with `Ocp-Apim-Subscription-Key`; there is no model proxy. The development catalog permits guarded, non-streaming text chat only, while existing capability-gated streaming, tool, and structured-output controls remain available for catalogs that advertise those capabilities. Requests include the selected model's advertised `max_completion_tokens` bound. Its Code dialog shows the configured gateway base URI, exact `/chat/completions` endpoint, a cURL REST request, and an OpenAI Python SDK example. Both snippets use the selected model/settings, an environment-variable key placeholder, and no live key or token. The Python example sets `max_retries=0`; clipboard success/failure is shown in the dialog.
- Usage summary, request table, and CSV keep their existing millisecond fields/contracts. The portal displays p95, request E2E, and TTFT in seconds. Three synchronized UTC minute charts (requests, reported total tokens, and average E2E seconds) use the customer `/usage/timeseries` or admin `/admin/usage/timeseries` API, independent of request-table pagination. The API accepts `days` (1–366), customer `subscription_id`, admin `organization_id`, and optional ISO-UTC `start`/`end` viewport bounds. Its response includes minute timestamps, request/input/output/paired-total counts, average E2E seconds, missing-token request counts, latency sample counts, and `interval_seconds: 60`. Missing token observations remain null; paired known token totals with missing observations are shown as partial. Idle request/token minutes render as zero, while latency minutes without samples remain gaps, never zero. Charts share zoom, pan, and reset controls and refetch for the selected UTC viewport. Long ranges are visually downsampled while keyboard minute selection, exact tooltips, and paginated exact-minute data remain available.

## Historical development verification records

The following dated records preserve bounded acceptance and superseded repair
steps; present-tense wording inside them describes that snapshot, not fresh
Azure state. In particular, later records supersede three-model/preview,
ingestion-disabled and direct-origin-restriction statements. Latest recorded
ingestion is paused on unowned test telemetry; current live freshness is unverified.

The IDS **Gateway settings** page (`/admin/settings`) configures the guarded APIs
only after an operator opts in. It shows desired and published revisions, explicit
safety/RPM/TPM/token-quota inputs, reasons, publication failures and history.
Values are blank until explicitly approved, not populated with guessed defaults.
Publishing requires confirmation of any safety relaxation, quota-period change
and propagation delay. Conflicts preserve edits until an explicit reload; failed
publication supports retry, and history values can be published as a new revision.
The customer portal exposes none of these controls. See
[the canonical bounds, authorization and publication contract](control-plane.md#admin-managed-gateway-settings).
The workflow has local API/UI/contract coverage; live admin/APIM propagation and
enforcement acceptance must be performed in an authorized deployment.

With versioned controls provisioned, Gateway settings adds organization/team/
subscription selection, aggregate team budgets, explicit subscription overrides,
RPM/concurrency/request quotas and advanced token limits. Primary/secondary keys
share counters, as do model aliases and the two guarded routes. The page shows
effective/inherited values, operator maxima, publication state and the warning
when controls are provisioned but not enforced.

The separate **Content Safety settings** page (`/admin/content-safety`) offers
Standard/Strict/Custom, four harm thresholds, prompt protection, protected-text
detection and input/output controls. Safety events stays at `/admin/safety`.
Locked/unverified capabilities are explained rather than silently skipped.
Safety changes and gateway changes share the same optimistic version, so edits
from one page cannot overwrite newer changes from the other. Neither feature is
activated by deploying a portal alone.

The 2026-10-12 deployment repair supersedes the earlier restrictions/gaps below:
the explicitly approved direct App Service origins are public, their compiled
API and adapter URLs and runtime CSP agree, and both control-plane/APIM CORS
allow only the exact two portal origins. `/ready` and portal callbacks are 200;
unauthenticated control-plane calls remain denied. New team keys target the
verified guarded adapter product. The six preview tiles are marked
"Preview only - not callable"; only the three real development aliases appear
in the playground, with streaming disabled. The user subsequently approved
20,000 TPM and a 100,000-token completion ceiling for the adapter.
`AIFLUX_GATEWAY_MAX_COMPLETION_TOKENS` clamps the API catalog to the configured
gateway limit, so the playground cannot advertise/send the bundled catalog's
higher ceiling when deployment inputs select a lower limit.

The user confirmed Entra sign-in succeeds but reported a database 503 during
control-plane authorization. The deployed repair replaces the organization and
member `IS TRUE` predicates, which SQLAlchemy compiled to SQL Server-invalid
`IS 1`, with Boolean equality. `/ready` now checks read access to all application
tables, not just `SELECT 1`. Live synthetic unapproved-tenant lookup now returns
the expected 403 instead of the database 503; anonymous access remains 401.
This proves the organization query executes, not a completed signed-in journey.
Both providers passed fresh bounded gateway completions after this API repair;
the disposable acceptance subscription was suspended, then deleted after the
subscription-cap repair below.

The next signed-in attempt reached team provisioning but APIM returned
`ValidationError: Subscriptions limit reached for same user`. Its development
product had a one-subscription cap consumed by the synthetic test subscription;
suspension does not release that slot. The user approved raising the adapter cap
to 10. SQL-owned team subscriptions have no APIM developer owner and share this
per-user cap; per-subscription inference bounds are unchanged. After the fix,
use **Reconcile** on the existing failed team subscription rather than creating
duplicates. Key reveal stays disabled until reconciliation makes it active.
Live readback confirms the cap is 10, and two exact `ApimClient.ensure` requests
succeeded with operator credentials. Those disposable subscriptions were deleted;
the operator check alone did not prove signed-in runtime reconciliation.

The user subsequently confirmed **Reconcile succeeds, the key reveals, and both
providers respond**. The basic signed-in customer flow is accepted through the
guarded development adapter. This is not native unified translation, full
admin/multi-tenant coverage, final public-edge acceptance or FinOps acceptance.

After the higher limits were deployed, all three aliases accepted a 100,000-token
budget and Sol completed a 6,364-word essay through the guarded route. Refresh the
playground to reload the catalog. The Haiku 503 was traced to mixed internal
thinking/text response blocks, not a proven timeout. The adapter now returns
only validated answer text after output safety and retains full provider usage.
A live gateway request completed a 5,241-word Haiku essay with normal `stop`;
signed-in long-essay browser acceptance is still separate. Internal-only or
unsupported provider responses return `provider_response_invalid` without
releasing an answer. Input/history character bounds remain unchanged; reset the
conversation if a long previous answer exceeds them.

Usage is not read directly from APIM. The page queries SQL usage projections
written by the ingestion Function. At this earlier repair snapshot it was
disabled with `AIFLUX_CATALOG_CONFIGURED=false`; later historical activation and
a subsequent pause are recorded in the infrastructure runbook.
Log Analytics checks at that snapshot confirmed gateway and
model token records are arriving, but this does not populate SQL automatically.
Estimates additionally require effective model/provider/region price versions;
unpriced or missing usage must remain Unknown, never zero. FinOps activation
requires validated adapter attribution, ingestion deployment/backfill and pricing,
not merely changing the portal display or turning on the Function.

For future deployments, the user must perform signed-in acceptance, not the agent:
open `https://aiflux-example-dev-customer.azurewebsites.net`, sign in with the approved
home-tenant account, create a team subscription, explicitly reveal its key, then
send a short prompt with `gpt-5.6-luna` and `claude-haiku-5-5` in the playground.
Report the failing step, HTTP/error code or redacted screenshot if blocked.
Do not share access tokens or subscription keys. A CLI model completion and an
HTTP-200 callback are not proof of this signed-in journey.

On 2026-10-12, CLI readback confirmed both portal registrations retain their direct
App Service and future gateway SPA callbacks. The API exposes the enabled
`access_as_user` scope, requests v2 tokens, and preauthorizes both portal clients.
These checks confirm registration configuration, not a completed signed-in journey.

Before the approved direct-dev stopgap, App Service access was restricted to the
reviewed operator `/32` and Application Gateway subnet, with default Deny. The
verification shell used rotating egress IPs: adding one explicitly approved `/32` did not make repeated
requests reachable. That ineffective additional rule was removed; the original
restrictions remain intact. Continued direct HTTPS checks need an approved stable
egress path, not an Internet-wide allow rule.

Callback registration alone does not wire the direct portal to the control plane.
Before the direct-dev repair, runtime CSP named the future gateway and the
control-plane CORS allowlist was empty. A direct cross-origin API configuration
therefore needs matching compiled API URLs, explicit CSP origins and exact CORS
origins before it can be accepted. The current main catalog release flag remains
closed. Do not claim catalog, playground or team-key acceptance from callback
readback or successful direct APIM inference.

## Assumptions to confirm with backend/gateway
- Model `capabilities` strings: tools = `tools|tool_calling|tool_use|function_calling`; structured output = `structured_output(s)|json_schema|response_format` (see `validation.ts`).
- Both usage APIs accept `model` and `subscription_id`; admin additionally accepts `organization_id`. `UsageSummary.known_cost` is treated as a lower bound when `incomplete_requests > 0`; null cost renders as "Unknown", never 0.
- Price POST sends ISO datetimes for `effective_from/to`.
- Gateway CORS must allow the portal origin when it differs (same Application Gateway host avoids this).

## Container hosting
Build from repo root (build args required; build fails if missing):
`docker build -f apps/customer-portal/Dockerfile --build-arg VITE_ENTRA_CLIENT_ID=... --build-arg VITE_API_SCOPE=... --build-arg VITE_GATEWAY_URL=... .` (same for `apps/admin-portal`).
Image: unprivileged nginx on port **8080**; health path `/healthz` (admin also `/admin/healthz`). Runtime env `GATEWAY_ORIGIN`/`CONTROL_ORIGIN` (origins only, optional when same-origin) extend the CSP `connect-src`. SPA fallback, `nosniff`, HSTS, CSP, frame-deny, no-referrer headers included. Admin serves under `/admin/`; `/` redirects there.

## Tests
Vitest covers SSE parser (CRLF, split UTF-8, multi-line), chat transport, validation, config, client, key reveal/clear, endpoint/example generation, secret-free clipboard content, second-based latency, time-series queries, chart viewport controls, and missing-metric rendering. Playwright covers deny-by-default and mobile. Authenticated e2e with mocked endpoints is not provided: real MSAL login cannot be mocked without adding an auth bypass, which is deliberately absent.