import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { ControlApi } from "./client";
import { SessionProvider } from "./session";
import { SubscriptionsPage } from "./pages/SubscriptionsPage";

const me = { organization_id: "home", organization_name: "IDS", tenant_id: "t", object_id: "admin", role: "ids_admin" as const };
const config = { clientId: "c", authority: "a", apiScope: "s", controlApiUrl: "/api", gatewayUrl: "https://g/v1" };
const orgs = { items: [{ id: "a", name: "Acme", enabled: true }, { id: "b", name: "Beta", enabled: true }], total: 2 };
const sub = { id: "s", name: "Finance key", team: "Finance", state: "active", created_at: "2026-01-01T00:00:00Z",
  organization_id: "a", organization_name: "Acme", team_id: "team", gateway_access: "pending", gateway_message: "Publication needs reconciliation." };

function setup(handler: (url: URL, init: RequestInit) => unknown | Promise<unknown>) {
  const calls: { url: URL; init: RequestInit }[] = [];
  const api = new ControlApi("/api", async () => "test", async (input, init = {}) => {
    const url = new URL(String(input), "https://test");
    calls.push({ url, init });
    const data = url.pathname.endsWith("/organizations") ? orgs : await handler(url, init);
    return data instanceof Response ? data : new Response(JSON.stringify(data));
  });
  const view = render(<MemoryRouter><SessionProvider me={me} config={config} api={api} onSignOut={() => undefined}><SubscriptionsPage /></SessionProvider></MemoryRouter>);
  return { calls, api, ...view };
}

describe("admin subscriptions", () => {
  it("requires an organization for creation and uses admin paths with explicit target", async () => {
    const { calls } = setup((_url, init) => init.method === "POST" ? sub : { items: [sub], total: 1 });
    expect(await screen.findByText("Finance key")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create subscription" })).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Gateway access pending");
    await userEvent.selectOptions(screen.getByLabelText("Organization"), "a");
    await userEvent.type(screen.getByLabelText("Name"), "New finance key");
    await userEvent.type(screen.getByLabelText("Team"), "Finance");
    await userEvent.click(screen.getByRole("button", { name: "Create subscription" }));
    await screen.findByText(/was submitted/);
    const create = calls.find(call => call.init.method === "POST");
    expect(create?.url.pathname).toBe("/api/admin/subscriptions");
    expect(JSON.parse(String(create?.init.body))).toEqual({ organization_id: "a", name: "New finance key", team: "Finance" });
    expect(calls.some(call => call.url.searchParams.get("organization_id") === "a")).toBe(true);
    expect(calls.every(call => call.url.pathname.startsWith("/api/admin/"))).toBe(true);
  });

  it("keeps publication failure visible after reconcile", async () => {
    setup((url) => url.pathname.endsWith("/reconcile") ? sub : { items: [sub], total: 1 });
    await screen.findByText("Finance key");
    await userEvent.click(screen.getByRole("button", { name: "Reconcile" }));
    await waitFor(() => expect(screen.getAllByRole("alert")).toHaveLength(2));
    expect(screen.getAllByRole("alert").every(e => e.textContent?.includes("Gateway access pending"))).toBe(true);
  });

  it("discards a late revealed key after changing organization", async () => {
    let resolve: ((data: unknown) => void) | undefined;
    const { calls } = setup(url => url.pathname.endsWith("/reveal")
      ? new Promise(r => { resolve = r; })
      : { items: [sub], total: 1 });
    await screen.findByText("Finance key");
    await userEvent.click(screen.getAllByRole("button", { name: "Reveal" })[0]!);
    await userEvent.selectOptions(screen.getByLabelText("Organization"), "b");
    await act(async () => resolve?.({ key: "late-secret" }));
    expect(screen.queryByLabelText("primary key value")).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain("late-secret");
    expect(calls.some(call => call.url.pathname === "/api/admin/subscriptions/s/reveal")).toBe(true);
  });

  it("moves the entry point and redirects the old customer bookmark", () => {
    const customer = readFileSync("apps/customer-portal/src/main.tsx", "utf8");
    const admin = readFileSync("apps/admin-portal/src/main.tsx", "utf8");
    expect(customer).not.toContain('label: "Subscriptions"');
    expect(customer).toContain('<Route path="/subscriptions" element={<Navigate to="/models" replace />}');
    expect(admin).toContain('label: "Subscriptions"');
    expect(admin).toContain('<Route path="/subscriptions" element={<SubscriptionsPage />}');
  });
});
