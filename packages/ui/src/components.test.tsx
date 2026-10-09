import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { AuthGate } from "./auth";
import { ControlApi } from "./client";
import { SessionProvider } from "./session";
import { SubscriptionsPage } from "./pages/SubscriptionsPage";
import { UsagePage, costLabel } from "./pages/UsagePage";
import { outcomeView } from "./pages/PlaygroundPage";
import { validatePrice } from "./pages/admin";
import type { UsagePage as UsageData } from "./types";

const me = { organization_id: "o", organization_name: "Acme", tenant_id: "t", object_id: "u", role: "customer" as const };
const config = { clientId: "c", authority: "a", apiScope: "s", controlApiUrl: "/api", gatewayUrl: "https://g/v1" };

function withApi(handler: (url: string, init: RequestInit) => unknown) {
  const f = (async (url: string, init: RequestInit) => {
    const r = handler(url, init);
    return r instanceof Response ? r : new Response(JSON.stringify(r), { status: 200 });
  }) as unknown as typeof fetch;
  return new ControlApi("/api", async () => "tok", f);
}
const wrap = (api: ControlApi, ui: React.ReactNode) => render(<MemoryRouter><SessionProvider me={me} api={api} config={config} onSignOut={() => undefined}>{ui}</SessionProvider></MemoryRouter>);

describe("AuthGate", () => {
  it("denies by default when config is missing and renders no children", () => {
    render(<AuthGate portalName="Customer portal" allowedRoles={["customer"]} env={{}}><p>SECRET VIEW</p></AuthGate>);
    expect(screen.getByRole("heading", { name: /not configured/i })).toBeInTheDocument();
    expect(screen.queryByText("SECRET VIEW")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /sign in/i })).not.toBeInTheDocument();
  });
});

describe("UsagePage", () => {
  const data = (over: Partial<UsageData["summary"]> = {}): UsageData => ({
    summary: { requests: 2, input_tokens: 10, output_tokens: 5, known_cost: null, currency: null, incomplete_requests: 2, failed_requests: 0, throttled_requests: 0, e2e_p95_ms: null, ttft_supported: false, cache_tokens_supported: false, last_ingested_at: null, ...over },
    items: [{ id: "1", subscription_id: "s", model: "m", provider: "p", region: "r", occurred_at: "2025-01-01T00:00:00Z", input_tokens: null, output_tokens: 5, cached_input_tokens: null, cache_write_tokens: null, cost: null, currency: null, status_code: 200, e2e_ms: null, ttft_ms: null, completeness: "missing_usage" }],
    total: 1,
  });
  it("shows unknown cost, incomplete warning and unavailable TTFT/cache rather than zeros", async () => {
    const api = withApi((url) => (url.includes("subscriptions") ? { items: [], total: 0 } : data()));
    wrap(api, <UsagePage />);
    expect(await screen.findByText("Unknown", { selector: "dd" })).toBeInTheDocument();
    expect(screen.getAllByText("Unavailable")).toHaveLength(2);
    expect(screen.getByText(/missing token usage or pricing/i)).toBeInTheDocument();
  });
  it("marks partially priced cost as lower bound", () => {
    expect(costLabel(data({ known_cost: "1.20", currency: "USD", incomplete_requests: 3 }).summary).note).toMatch(/Lower bound/);
    expect(costLabel(data({ known_cost: "1.20", currency: "USD", incomplete_requests: 0 }).summary).value).toBe("USD 1.20");
  });
});

describe("SubscriptionsPage", () => {
  it("shows an empty state and reveals keys only on click, clearing on Hide", async () => {
    const sub = { id: "s1", name: "Team A", team: "Data", state: "active", created_at: "2025-01-01T00:00:00Z" };
    const api = withApi((url) => (url.endsWith("/reveal") ? { key: "SECRETKEY123" } : { items: [sub], total: 1 }));
    wrap(api, <SubscriptionsPage />);
    await screen.findByText("Team A");
    expect(document.body.textContent).not.toContain("SECRETKEY123");
    await userEvent.click(screen.getAllByRole("button", { name: "Reveal" })[0]!);
    await waitFor(() => expect(screen.getByLabelText("primary key value")).toBeInTheDocument());
    expect(screen.getByLabelText("primary key value").textContent).not.toContain("SECRETKEY123");
    await userEvent.click(screen.getByRole("button", { name: "Show" }));
    expect(screen.getByLabelText("primary key value").textContent).toBe("SECRETKEY123");
    await userEvent.click(screen.getByRole("button", { name: "Hide" }));
    expect(document.body.textContent).not.toContain("SECRETKEY123");
    expect(localStorage.length + sessionStorage.length).toBe(0);
  });
  it("shows empty state with guidance", async () => {
    wrap(withApi(() => ({ items: [], total: 0 })), <SubscriptionsPage />);
    expect(await screen.findByText("No subscriptions yet")).toBeInTheDocument();
  });
  it("surfaces a backend error", async () => {
    const api = withApi(() => new Response(JSON.stringify({ detail: "Organization disabled" }), { status: 403 }));
    wrap(api, <SubscriptionsPage />);
    expect(await screen.findByText("Organization disabled")).toBeInTheDocument();
    vi.restoreAllMocks();
  });
});

describe("outcomeView", () => {
  const r = (o: string, extra = {}) => ({ outcome: o, content: "", toolCalls: [], finishReason: null, usage: null, sawDone: false, ...extra }) as never;
  it("keeps cancellation, filter, provider error and abnormal distinct", () => {
    const labels = ["cancelled", "content_filter", "provider_error", "abnormal", "completed"].map((o) => outcomeView(r(o))!.label);
    expect(new Set(labels).size).toBe(5);
  });
});

describe("validatePrice", () => {
  const f = { model: "m", provider: "p", region: "r", effective_from: "2025-01-01T00:00", effective_to: "", currency: "USD", input_per_million: "1.5", output_per_million: "3", cached_input_per_million: "", cache_write_per_million: "", input_includes_cached: "true" };
  it("keeps decimals as strings and nulls blank optionals", () => {
    const v = validatePrice(f);
    expect(v).toMatchObject({ ok: true, value: { input_per_million: "1.5", cached_input_per_million: null, effective_to: null, input_includes_cached: true } });
  });
  it("rejects bad input", () => {
    expect(validatePrice({ ...f, input_per_million: "abc" }).ok).toBe(false);
    expect(validatePrice({ ...f, effective_to: "2024-01-01T00:00" }).ok).toBe(false);
  });
});
