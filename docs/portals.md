# AIFLUX portals (customer + IDS admin)

React/TypeScript (Vite, npm workspaces). Distinct entry points share `packages/ui` (typed control-plane client, SSE/chat client, components).

| Path | Purpose |
|------|---------|
| `apps/customer-portal` | Served at `/` — catalog, team subscriptions & key reveal, streaming playground, usage/showback |
| `apps/admin-portal` | Served at `/admin/` (Vite `base: /admin/`, router basename `/admin`) — showback, safety metadata, organizations, members, prices |
| `packages/ui` | Shared client (`ControlApi`), `chatCompletion` (SSE), validation, pages, styles |
| `tests/e2e` | Playwright (deny-by-default, mobile) |

## Commands
`npm install`, `npm run typecheck`, `npm test` (vitest), `npm run build`, `npm run e2e`, `npm run dev:customer` (5173) / `dev:admin` (5174/admin/). Set `CONTROL_API_PROXY_TARGET` to proxy `/api` in dev.

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
- The dev bootstrap registers both the future Application Gateway callbacks and the direct App Service callbacks: `https://aiflux-fdpo-dev-customer.azurewebsites.net/redirect.html` and `https://aiflux-fdpo-dev-admin.azurewebsites.net/admin/redirect.html`. Existing SPA callbacks are preserved. MSAL derives its callback from the current origin and portal base path; registering only the gateway hostname causes `AADSTS50011` when signing in on App Service.
- `/api/me` is called before any view; 401/403/404 deny. Role check in the UI (admin portal requires `ids_admin`; customer portal accepts `customer`/`ids_admin`) is a convenience — the backend is the authority. Tenant from the token must equal `tenant_id` from `/api/me`.
- All control-plane and gateway fetches use `cache: no-store`, `credentials: omit`. CSV export is an authenticated fetch + blob download (no token in URL).
- Subscription keys are revealed only on explicit click, kept in React memory, cleared on Hide, rotation and sign-out. Nothing is logged.
- Playground calls the gateway directly with `Ocp-Apim-Subscription-Key`; there is no model proxy. Streaming is disabled unless the catalog advertises `stream`, and an advertised `max_completion_tokens` bound is sent explicitly. Tool calls are displayed as proposed and never executed. Streams missing `[DONE]`/finish reason are shown as abnormal; `content_filter` is reported only when the server sent that finish reason; cancel is distinct; no retries.

## Development verification boundary

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
written by the ingestion Function, which is currently disabled and has
`AIFLUX_CATALOG_CONFIGURED=false`. Live Log Analytics checks confirm gateway and
model token records are arriving, but this does not populate SQL automatically.
Estimates additionally require effective model/provider/region price versions;
unpriced or missing usage must remain Unknown, never zero. FinOps activation
requires validated adapter attribution, ingestion deployment/backfill and pricing,
not merely changing the portal display or turning on the Function.

For future deployments, the user must perform signed-in acceptance, not the agent:
open `https://aiflux-fdpo-dev-customer.azurewebsites.net`, sign in with the approved
home-tenant account, create a team subscription, explicitly reveal its key, then
send a short prompt with `gpt-5.6-luna` and `claude-haiku-5-5` in the playground.
Report the failing step, HTTP/error code or redacted screenshot if blocked.
Do not share access tokens or subscription keys. A CLI model completion and an
HTTP-200 callback are not proof of this signed-in journey.

On 2026-10-12, CLI readback confirmed both portal registrations retain their direct
App Service and future gateway SPA callbacks. The API exposes the enabled
`access_as_user` scope, requests v2 tokens, and preauthorizes both portal clients.
These checks confirm registration configuration, not a completed signed-in journey.

Direct App Service access remains restricted to the reviewed operator `/32` and
Application Gateway subnet, with default Deny. The verification shell currently
uses rotating egress IPs: adding one explicitly approved `/32` did not make repeated
requests reachable. That ineffective additional rule was removed; the original
restrictions remain intact. Continued direct HTTPS checks need an approved stable
egress path, not an Internet-wide allow rule.

Callback registration alone does not wire the direct portal to the control plane.
The deployed portal runtime CSP origins still name the future gateway, and the
control-plane CORS allowlist is empty. A direct cross-origin API configuration
therefore needs matching compiled API URLs, explicit CSP origins and exact CORS
origins before it can be accepted. The current main catalog release flag remains
closed. Do not claim catalog, playground or team-key acceptance from callback
readback or successful direct APIM inference.

## Assumptions to confirm with backend/gateway
- Model `capabilities` strings: tools = `tools|tool_calling|tool_use|function_calling`; structured output = `structured_output(s)|json_schema|response_format` (see `validation.ts`).
- The customer `/api/usage` accepts `subscription_id`; admin accepts `organization_id`. `UsageSummary.known_cost` is treated as a lower bound when `incomplete_requests > 0`; null cost renders as "Unknown", never 0.
- Price POST sends ISO datetimes for `effective_from/to`.
- Gateway CORS must allow the portal origin when it differs (same Application Gateway host avoids this).

## Container hosting
Build from repo root (build args required; build fails if missing):
`docker build -f apps/customer-portal/Dockerfile --build-arg VITE_ENTRA_CLIENT_ID=... --build-arg VITE_API_SCOPE=... --build-arg VITE_GATEWAY_URL=... .` (same for `apps/admin-portal`).
Image: unprivileged nginx on port **8080**; health path `/healthz` (admin also `/admin/healthz`). Runtime env `GATEWAY_ORIGIN`/`CONTROL_ORIGIN` (origins only, optional when same-origin) extend the CSP `connect-src`. SPA fallback, `nosniff`, HSTS, CSP, frame-deny, no-referrer headers included. Admin serves under `/admin/`; `/` redirects there.

## Tests
Vitest covers SSE parser (CRLF, split UTF-8, multi-line), chat streaming (tool-call assembly, truncation, cancel, errors, non-stream), validation, config, client, key reveal/clear, unknown-cost/unavailable-metric rendering. Playwright covers deny-by-default and mobile. Authenticated e2e with mocked endpoints is not provided: real MSAL login cannot be mocked without adding an auth bypass, which is deliberately absent.