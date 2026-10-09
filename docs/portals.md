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
| `VITE_ENTRA_CLIENT_ID` | Multitenant app registration client ID (GUID) — required |
| `VITE_ENTRA_AUTHORITY` | `https://login.microsoftonline.com/organizations` |
| `VITE_API_SCOPE` | e.g. `api://<api-app-id>/access_as_user` — required |
| `VITE_CONTROL_API_URL` | default `/api` (same origin) |
| `VITE_GATEWAY_URL` | Public Front Door base including `/v1` — required (chat posts to `<url>/chat/completions`) |

If any required value is missing/invalid the portal renders a "Portal not configured" screen and nothing else (deny by default).

## Security model
- MSAL authorization-code + PKCE via popup, `cacheLocation: memoryStorage` (no token/key in localStorage/sessionStorage; reload requires sign-in). Register SPA redirect URIs `https://<host>/redirect.html` (customer) and `https://<host>/admin/redirect.html` (admin). Do not send `Cross-Origin-Opener-Policy: same-origin` (breaks popup).
- `/api/me` is called before any view; 401/403/404 deny. Role check in the UI (admin portal requires `ids_admin`; customer portal accepts `customer`/`ids_admin`) is a convenience — the backend is the authority. Tenant from the token must equal `tenant_id` from `/api/me`.
- All control-plane and gateway fetches use `cache: no-store`, `credentials: omit`. CSV export is an authenticated fetch + blob download (no token in URL).
- Subscription keys are revealed only on explicit click, kept in React memory, cleared on Hide, rotation and sign-out. Nothing is logged.
- Playground calls the gateway directly with the chosen key; there is no model proxy. Tool calls are displayed as proposed and never executed. Streams missing `[DONE]`/finish reason are shown as abnormal; `content_filter` is reported only when the server sent that finish reason; cancel is distinct; no retries.

## Assumptions to confirm with backend/gateway
- Model `capabilities` strings: tools = `tools|tool_calling|tool_use|function_calling`; structured output = `structured_output(s)|json_schema|response_format` (see `validation.ts`).
- The customer `/api/usage` accepts `subscription_id`; admin accepts `organization_id`. `UsageSummary.known_cost` is treated as a lower bound when `incomplete_requests > 0`; null cost renders as "Unknown", never 0.
- Price POST sends ISO datetimes for `effective_from/to`.
- Gateway CORS must allow the portal origin when it differs (same Front Door host avoids this).

## Container hosting
Build from repo root (build args required; build fails if missing):
`docker build -f apps/customer-portal/Dockerfile --build-arg VITE_ENTRA_CLIENT_ID=... --build-arg VITE_API_SCOPE=... --build-arg VITE_GATEWAY_URL=... .` (same for `apps/admin-portal`).
Image: unprivileged nginx on port **8080**; health path `/healthz` (admin also `/admin/healthz`). Runtime env `GATEWAY_ORIGIN`/`CONTROL_ORIGIN` (origins only, optional when same-origin) extend the CSP `connect-src`. SPA fallback, `nosniff`, HSTS, CSP, frame-deny, no-referrer headers included. Admin serves under `/admin/`; `/` redirects there.

## Tests
Vitest covers SSE parser (CRLF, split UTF-8, multi-line), chat streaming (tool-call assembly, truncation, cancel, errors, non-stream), validation, config, client, key reveal/clear, unknown-cost/unavailable-metric rendering. Playwright covers deny-by-default and mobile. Authenticated e2e with mocked endpoints is not provided: real MSAL login cannot be mocked without adding an auth bypass, which is deliberately absent.