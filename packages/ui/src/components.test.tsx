import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { AuthGate } from "./auth";
import { ControlApi } from "./client";
import { SessionProvider } from "./session";
import { SubscriptionsPage } from "./pages/SubscriptionsPage";
import { UsagePage, costLabel } from "./pages/UsagePage";
import { PlaygroundPage, outcomeView } from "./pages/PlaygroundPage";
import { ModelsPage } from "./pages/ModelsPage";
import { UsageCharts } from "./components/UsageCharts";
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
    const api = withApi((url) => url.includes("timeseries")
      ? { items: [], start: "2026-01-01T00:00:00Z", end: "2026-01-01T01:00:00Z", interval_seconds: 60 }
      : url.includes("subscriptions") ? { items: [], total: 0 } : data());
    wrap(api, <UsagePage />);
    expect(await screen.findByText("Unknown", { selector: "dd" })).toBeInTheDocument();
    expect(screen.getAllByText("Unavailable")).toHaveLength(2);
    expect(screen.getByText(/missing token usage or pricing/i)).toBeInTheDocument();
  });
  it("renders second-based latency and a keyboard-accessible exact-minute chart", async () => {
    const api = withApi((url) => {
      if (url.includes("timeseries")) {
        const q = new URL(url, "https://portal").searchParams;
        const start = new Date(q.get("start")!);
        const end = new Date(q.get("end")!);
        const minute = start.toISOString();
        const next = new Date(start.getTime() + 60_000).toISOString();
        return {
          items: [
            { minute, requests: 2, input_tokens: 8, output_tokens: 4, total_tokens: 12, avg_e2e_seconds: 1.25, missing_token_requests: 0, latency_samples: 2 },
            { minute: next, requests: 1, input_tokens: null, output_tokens: 4, total_tokens: null, avg_e2e_seconds: null, missing_token_requests: 1, latency_samples: 0 },
          ],
          start: start.toISOString(), end: end.toISOString(), interval_seconds: 60,
        };
      }
      if (url.includes("subscriptions")) return { items: [], total: 0 };
      return data({ e2e_p95_ms: 1250, ttft_supported: true });
    });
    wrap(api, <UsagePage />);
    expect(await screen.findByText("1.25 s", { selector: "dd" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Requests per minute" })).toBeInTheDocument();
    const chart = screen.getByRole("slider", { name: /tokens per minute/i });
    await userEvent.click(chart);
    await userEvent.keyboard("{ArrowRight}");
    expect(screen.getByText(/partial, 1 request\(s\) missing token usage/i)).toBeInTheDocument();
    expect(screen.getByRole("slider", { name: /tokens per minute/i })).toHaveAttribute("aria-valuetext", expect.stringContaining("UTC"));
    await userEvent.click(screen.getAllByText("View exact minute data")[2]!);
    expect(screen.getByText("1.250 s", { selector: "td" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "E2E (s)" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "TTFT (s)" })).toBeInTheDocument();
  }, 10_000);
  it("requests minute aggregates independently and zooms the synchronized viewport", async () => {
    const urls: string[] = [];
    const api = withApi((url) => {
      urls.push(url);
      if (url.includes("timeseries")) {
        const q = new URL(url, "https://portal").searchParams;
        return { items: [], start: q.get("start"), end: q.get("end"), interval_seconds: 60 };
      }
      return url.includes("subscriptions") ? { items: [], total: 0 } : data();
    });
    wrap(api, <UsagePage />);
    await screen.findByRole("heading", { name: "Requests per minute" });
    const first = urls.filter((url) => url.includes("timeseries")).at(-1)!;
    await userEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    await waitFor(() => expect(urls.filter((url) => url.includes("timeseries")).length).toBeGreaterThan(1));
    const latest = urls.filter((url) => url.includes("timeseries")).at(-1)!;
    expect(new URL(first, "https://portal").searchParams.get("start")).not.toBe(new URL(latest, "https://portal").searchParams.get("start"));
    await userEvent.click(screen.getByRole("button", { name: "Reset chart zoom and pan" }));
    await waitFor(() => expect(urls.filter((url) => url.includes("timeseries")).at(-1)).toBe(first));
  }, 10_000);
  it("marks partially priced cost as lower bound", () => {
    expect(costLabel(data({ known_cost: "1.20", currency: "USD", incomplete_requests: 3 }).summary).note).toMatch(/Lower bound/);
    expect(costLabel(data({ known_cost: "1.20", currency: "USD", incomplete_requests: 0 }).summary).value).toBe("USD 1.20");
  });
});

describe("UsageCharts", () => {
  it("bounds plot marks for large periods without losing exact minute values", () => {
    const start = Date.parse("2026-10-01T00:00:00Z");
    const items = Array.from({ length: 130_000 }, (_, index) => ({
      minute: new Date(start + index * 60_000).toISOString(), requests: 1,
      input_tokens: 2, output_tokens: 3, total_tokens: 5, avg_e2e_seconds: 0.5,
      missing_token_requests: 0, latency_samples: 1,
    }));
    const end = start + items.length * 60_000;
    render(<UsageCharts start={start} end={end} series={{
      items, start: new Date(start).toISOString(), end: new Date(end).toISOString(), interval_seconds: 60,
    }} />);
    expect(document.querySelectorAll(".chart-mark").length).toBeLessThanOrEqual(2700);
    expect(screen.getByRole("slider", { name: /tokens per minute/i })).toHaveAttribute(
      "aria-valuetext", "2026-10-01 00:00 UTC: 5",
    );
  }, 20_000);

  it("plots single-valued minutes and excludes the half-open end boundary", async () => {
    const start = Date.parse("2026-10-14T00:00:00Z");
    render(<UsageCharts start={start} end={start + 60_000} series={{
      start: new Date(start).toISOString(), end: new Date(start + 60_000).toISOString(), interval_seconds: 60,
      items: [{ minute: new Date(start).toISOString(), requests: 1, input_tokens: 2, output_tokens: 3,
        total_tokens: 5, avg_e2e_seconds: 0.5, missing_token_requests: 0, latency_samples: 1 }],
    }} />);
    const marks = document.querySelectorAll(".chart-mark");
    expect(marks).toHaveLength(3);
    for (const mark of marks) expect(mark.getAttribute("y1")).not.toBe(mark.getAttribute("y2"));
    const chart = screen.getByRole("slider", { name: /requests per minute/i });
    await userEvent.click(chart);
    await userEvent.keyboard("{End}{ArrowRight}");
    expect(chart).toHaveAttribute("aria-valuenow", String(start));
    await userEvent.click(screen.getAllByText("View exact minute data")[0]!);
    expect(screen.getAllByText("1 of 1")).toHaveLength(3);
    expect(screen.getAllByText("2026-10-14 00:00 UTC", { selector: "td" })).toHaveLength(3);
    expect(screen.queryByText("2026-10-14 00:01 UTC", { selector: "td" })).not.toBeInTheDocument();
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

  describe("Guarded development catalog and playground", () => {
    const catalog = { items: [
      { id: "approved", provider: "OpenAI", enabled: true, capabilities: ["chat"], max_completion_tokens: 64 },
      { id: "another", provider: "OpenAI", enabled: true, capabilities: ["chat"], max_completion_tokens: 123 },
      { id: "preview", provider: "Anthropic", enabled: false, placeholder: true, capabilities: [] },
    ], total: 2 };

    it("renders preview tiles explicitly as uncallable", async () => {
      wrap(withApi(() => catalog), <ModelsPage />);
      expect(await screen.findByRole("heading", { name: "preview" })).toBeInTheDocument();
      expect(screen.getByText("Preview only - not callable")).toBeInTheDocument();
    });

    it("sends bounded non-streaming chat and never offers placeholders", async () => {
      const api = withApi((url) => url.endsWith("/models") ? catalog : {
        items: [{ id: "s1", name: "Team", state: "active" }], total: 1,
      });
      wrap(api, <PlaygroundPage />);
      await screen.findByRole("option", { name: "approved" });
      expect(screen.queryByRole("option", { name: "preview" })).not.toBeInTheDocument();
      expect(screen.getByText(/Guarded text-only requests/i)).toBeInTheDocument();
      await userEvent.type(screen.getByLabelText("Or paste a key"), "test-key");
      await userEvent.type(screen.getByLabelText("Message"), "Reply OK.");
      const gateway = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
        choices: [{ message: { role: "assistant", content: "OK" }, finish_reason: "stop" }],
        usage: { prompt_tokens: 9, completion_tokens: 4, total_tokens: 13 },
      })));
      try {
        await userEvent.click(screen.getByRole("button", { name: "Send" }));
        await screen.findByText("Completed");
        const [url, init] = gateway.mock.calls[0]!;
        expect(url).toBe("https://g/v1/chat/completions");
        expect(JSON.parse(init!.body as string)).toMatchObject({
          model: "approved", stream: false, max_completion_tokens: 64,
        });
        expect(init!.headers).toMatchObject({ "Ocp-Apim-Subscription-Key": "test-key" });
        expect(JSON.parse(init!.body as string)).not.toHaveProperty("stream_options");
      } finally {
        gateway.mockRestore();
      }
    }, 10_000);

    it("generates configured, selected-model examples without exposing subscription keys", async () => {
      const api = withApi((url) => url.endsWith("/models") ? catalog : { items: [{ id: "s1", name: "Team", state: "active" }], total: 1 });
      wrap(api, <PlaygroundPage />);
      await screen.findByRole("option", { name: "approved" });
      await userEvent.type(screen.getByLabelText("Or paste a key"), "SECRET-SUBSCRIPTION-KEY");
      await userEvent.click(screen.getByRole("button", { name: "Code" }));
      const dialog = screen.getByRole("dialog", { name: "Gateway request examples" });
      expect(dialog).toHaveTextContent("https://g/v1/chat/completions");
      expect(dialog).toHaveTextContent(/Ocp-Apim-Subscription-Key/);
      expect(dialog).toHaveTextContent("AIFLUX_SUBSCRIPTION_KEY");
      expect(dialog).toHaveTextContent('api_key="unused"');
      expect(dialog).toHaveTextContent("max_retries=0");
      expect(dialog).toHaveTextContent('"model":"approved"');
      expect(dialog).toHaveTextContent("Say hello in one sentence.");
      expect(dialog).not.toHaveTextContent("SECRET-SUBSCRIPTION-KEY");
      expect(dialog).not.toHaveTextContent('"stream":true');
      await userEvent.click(screen.getByRole("button", { name: "Copy cURL" }));
      expect(screen.getByRole("status")).toHaveTextContent("Could not copy the example");
      await userEvent.keyboard("{Escape}");
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Code" })).toHaveFocus();
    });

    it("copies a secret-free example and updates it for the selected model", async () => {
      const clipboardDescriptor = Object.getOwnPropertyDescriptor(navigator, "clipboard");
      const writeText = vi.fn().mockResolvedValue(undefined);
      Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
      try {
        const api = withApi((url) => url.endsWith("/models") ? catalog : { items: [{ id: "s1", name: "Team", state: "active" }], total: 1 });
        wrap(api, <PlaygroundPage />);
        await screen.findByRole("option", { name: "another" });
        await userEvent.selectOptions(screen.getByLabelText("Model"), "another");
        await userEvent.click(screen.getByRole("button", { name: "Code" }));
        const dialog = screen.getByRole("dialog", { name: "Gateway request examples" });
        expect(dialog).toHaveTextContent('"model":"another"');
        expect(dialog).toHaveTextContent('\\"max_completion_tokens\\":123');
        await userEvent.click(screen.getByRole("button", { name: "Copy Python" }));
        expect(writeText).toHaveBeenCalledWith(expect.stringContaining('\\"model\\":\\"another\\"'));
        expect(screen.getByRole("status")).toHaveTextContent("Example copied to clipboard.");
      } finally {
        if (clipboardDescriptor) Object.defineProperty(navigator, "clipboard", clipboardDescriptor);
        else Object.defineProperty(navigator, "clipboard", { configurable: true, value: undefined });
      }
    });
    it("preserves capability-gated settings and traps reverse tab inside code examples", async () => {
      const api = withApi((url) => url.endsWith("/models") ? {
        items: [{ id: "capable", provider: "test", enabled: true, capabilities: ["chat", "stream", "tools", "json_schema"], max_completion_tokens: 123 }],
        total: 1,
      } : { items: [{ id: "s1", name: "Team", state: "active" }], total: 1 });
      wrap(api, <PlaygroundPage />);
      await screen.findByRole("option", { name: "capable" });
      expect(screen.getByRole("checkbox", { name: /Stream response/ })).toBeEnabled();
      await userEvent.click(screen.getByRole("checkbox", { name: "Send tool definitions" }));
      await userEvent.click(screen.getByRole("button", { name: "Code" }));
      const dialog = screen.getByRole("dialog");
      expect(dialog).toHaveFocus();
      expect(dialog).toHaveTextContent('"stream":true');
      expect(dialog).toHaveTextContent('"tools":[');
      await userEvent.keyboard("{Shift>}{Tab}{/Shift}");
      expect(document.activeElement?.closest('[role="dialog"]')).toBe(dialog);
      await userEvent.keyboard("{Escape}");
      expect(screen.getByRole("button", { name: "Code" })).toHaveFocus();
    });
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
