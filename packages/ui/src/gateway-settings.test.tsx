import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { ControlApi } from "./client";
import { GatewaySettingsPage, validateGatewaySettings } from "./pages/GatewaySettingsPage";
import { SessionProvider } from "./session";
import type { GatewayConfiguration, GatewaySettings } from "./types";

const configuration: GatewayConfiguration = { safety_threshold: 3, rpm: 2, tpm: 1024, token_quota: 10000, quota_period: "Daily" };
const blank = (): GatewaySettings => ({ scope: "dev-openai", max_rpm: 2, max_tpm: 2048, version: 0, published_version: null, desired: null });
const revision = (version: number, state: "published" | "failed" = "published") => ({
  version, configuration, reason: "Reviewed", object_id: "admin", occurred_at: "2026-01-01T00:00:00Z", state, error: state === "failed" ? "APIM unavailable" : null,
});

function mount(handler: (url: string, init?: RequestInit) => unknown) {
  const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const result = handler(String(input), init);
    return result instanceof Response ? result : new Response(JSON.stringify(result));
  });
  const api = new ControlApi("/api", async () => "synthetic-token", fetcher);
  render(<MemoryRouter><SessionProvider
    me={{ organization_id: "o", organization_name: "IDS", tenant_id: "t", object_id: "admin", role: "ids_admin" }}
    api={api} config={{ clientId: "c", authority: "a", apiScope: "s", controlApiUrl: "/api", gatewayUrl: "https://g" }}
    onSignOut={() => undefined}
  ><GatewaySettingsPage /></SessionProvider></MemoryRouter>);
  return fetcher;
}

describe("gateway settings validation", () => {
  const draft = { safety_threshold: "3", rpm: "2", tpm: "1024", token_quota: "10000", quota_period: "Daily" };
  it("does not invent defaults or allow unbounded, fractional or malformed values", () => {
    expect(validateGatewaySettings(draft, 2048)).toEqual(configuration);
    for (const [key, value] of [
      ["safety_threshold", ""], ["safety_threshold", "8"], ["rpm", "3"], ["tpm", "2049"],
      ["token_quota", "0"], ["token_quota", "2147483648"], ["tpm", "1.5"], ["quota_period", "Never"],
    ]) expect(validateGatewaySettings({ ...draft, [key!]: value }, 2048)).toBeNull();
    expect(validateGatewaySettings({ ...draft, safety_threshold: "0", tpm: "20000" }, 20000)?.safety_threshold).toBe(0);
  });
});

describe("GatewaySettingsPage", () => {
  it("explains opt-in when no settings surface is enabled", async () => {
    mount(() => ({ items: [], total: 0 }));
    expect(await screen.findByText("Admin settings are not enabled")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Publish settings" })).not.toBeInTheDocument();
  });

  it("requires explicit values and approval, then publishes an audited revision", async () => {
    let row = blank();
    let body: unknown;
    const fetcher = mount((url, init) => {
      if (url.includes("/history")) return { items: row.desired ? [row.desired] : [], total: row.version };
      if (init?.method === "PUT") {
        body = JSON.parse(String(init.body));
        row = { ...row, version: 1, published_version: 1, desired: revision(1) };
        return row;
      }
      return { items: [row], total: 1 };
    });
    const group = await screen.findByRole("region", { name: "dev-openai settings" });
    const ui = within(group);
    expect(ui.getByLabelText("Safety threshold (0-7)")).toHaveValue(null);
    expect(ui.getByRole("button", { name: "Publish settings" })).toBeDisabled();
    await userEvent.type(ui.getByLabelText("Safety threshold (0-7)"), "3");
    await userEvent.type(ui.getByLabelText("Requests per minute (RPM)"), "2");
    await userEvent.type(ui.getByLabelText("Tokens per minute (TPM)"), "1024");
    await userEvent.type(ui.getByLabelText("Token quota"), "10000");
    await userEvent.selectOptions(ui.getByLabelText("Quota period (UTC fixed window)"), "Daily");
    await userEvent.type(ui.getByLabelText("Reason for this revision"), "Approved budget");
    await userEvent.click(ui.getByRole("checkbox"));
    await userEvent.click(ui.getByRole("button", { name: "Publish settings" }));
    await waitFor(() => expect(ui.getByRole("status")).toHaveTextContent("status: published"));
    expect(body).toEqual({ configuration, expected_version: 0, reason: "Approved budget" });
    const mutation = fetcher.mock.calls.find(([, init]) => init?.method === "PUT")!;
    expect(new Headers(mutation[1]?.headers).get("Authorization")).toBe("Bearer synthetic-token");
    expect(ui.getByText(/not that every gateway has applied it/i)).toBeInTheDocument();
  });

  it("preserves edits on a stale-write conflict and requires an explicit reload", async () => {
    let row: GatewaySettings = { ...blank(), version: 1, published_version: 1, desired: revision(1) };
    mount((url, init) => {
      if (url.includes("/history")) return { items: [row.desired], total: 1 };
      if (init?.method === "PUT") {
        row = { ...row, version: 2, published_version: 2, desired: revision(2) };
        return new Response(JSON.stringify({ detail: "Settings changed; refresh before saving" }), { status: 409 });
      }
      return { items: [row], total: 1 };
    });
    const threshold = await screen.findByLabelText("Safety threshold (0-7)");
    await userEvent.clear(threshold);
    await userEvent.type(threshold, "2");
    await userEvent.type(screen.getByLabelText("Reason for this revision"), "Stricter");
    await userEvent.click(screen.getByRole("checkbox"));
    await userEvent.click(screen.getByRole("button", { name: "Publish settings" }));
    await screen.findByText(/Your edits are preserved/);
    expect(threshold).toHaveValue(2);
    expect(screen.getByRole("button", { name: "Publish settings" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Reload desired settings" }));
    expect(threshold).toHaveValue(3);
    expect(screen.getByRole("checkbox")).not.toBeChecked();
  });

  it("retries a failed publication and can restore history as a new revision", async () => {
    let row: GatewaySettings = { ...blank(), version: 1, desired: revision(1, "failed") };
    mount((url, init) => {
      if (url.includes("/history")) return { items: [revision(1)], total: 1 };
      if (url.endsWith("/reconcile") && init?.method === "POST") {
        expect(JSON.parse(String(init.body))).toEqual({ expected_version: 1 });
        row = { ...row, published_version: 1, desired: revision(1) };
        return row;
      }
      return { items: [row], total: 1 };
    });
    await screen.findByText("APIM unavailable");
    expect(screen.getByRole("button", { name: "Publish settings" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Retry publication" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("status: published"));
    await userEvent.click(screen.getByRole("button", { name: "Use revision 1 values" }));
    expect(screen.getByLabelText("Tokens per minute (TPM)")).toHaveValue(1024);
    expect(screen.getByRole("checkbox")).not.toBeChecked();
  });

  it("retains draft fields when refreshing publication status fails", async () => {
    let unavailable = false;
    mount((url) => {
      if (url.includes("/history")) return { items: [], total: 0 };
      if (unavailable) return new Response(JSON.stringify({ detail: "Control plane unavailable" }), { status: 503 });
      return { items: [blank()], total: 1 };
    });
    const threshold = await screen.findByLabelText("Safety threshold (0-7)");
    await userEvent.type(threshold, "2");
    unavailable = true;
    await userEvent.click(screen.getByRole("button", { name: "Refresh publication status" }));
    await screen.findByText("Control plane unavailable");
    expect(threshold).toHaveValue(2);
    expect(screen.getByRole("region", { name: "dev-openai settings" })).toBeInTheDocument();
  });
});
