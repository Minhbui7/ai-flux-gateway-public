import type { ReactElement } from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { ControlApi } from "./client";
import { applyFloor, currentSafety, migrateLegacySafety, validateSafety } from "./managed";
import { ContentSafetySettingsPage } from "./pages/ContentSafetySettingsPage";
import { GatewaySettingsPage } from "./pages/GatewaySettingsPage";
import { SessionProvider } from "./session";
import type { GatewayCapabilities, GatewaySettings, ManagedGatewayConfiguration, SafetyConfiguration } from "./types";

const caps: GatewayCapabilities = { managed_controls_enabled: true, concurrency_tiers: [1, 2, 4], protected_material_available: true, safety_relaxation_allowed: true, monthly_request_quota_available: false, enforcement_enabled: true };
const limits = { rpm: 2, tpm: 1024, token_quota: 10000, quota_period: "Daily" as const, concurrency: 2 as const, request_quota: null, request_quota_period: "Daily" as const };
const safety: SafetyConfiguration = { profile: "Standard", hate: 4, violence: 4, sexual: 4, self_harm: 4, prompt_attack: true, protected_material: true, input_filtering: true, output_filtering: true };
const managed: ManagedGatewayConfiguration = { schema_version: 2, defaults: limits, teams: [], subscriptions: [], safety };
const rev = (version: number, configuration: ManagedGatewayConfiguration = managed) => ({ version, configuration, reason: "Reviewed", object_id: "admin", occurred_at: "2026-01-01T00:00:00Z", state: "published" as const, error: null });
const row = (over: Partial<GatewaySettings> = {}): GatewaySettings => ({ scope: "dev-openai", max_rpm: 2, max_tpm: 2048, version: 1, published_version: 1, desired: rev(1), capabilities: caps, ...over });

function mount(page: ReactElement, handler: (url: string, init?: RequestInit) => unknown) {
  const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const r = handler(String(input), init);
    return r instanceof Response ? r : new Response(JSON.stringify(r));
  });
  const api = new ControlApi("/api", async () => "t", fetcher);
  render(<MemoryRouter><SessionProvider
    me={{ organization_id: "o", organization_name: "IDS", tenant_id: "t", object_id: "admin", role: "ids_admin" }}
    api={api} config={{ clientId: "c", authority: "a", apiScope: "s", controlApiUrl: "/api", gatewayUrl: "https://g" }} onSignOut={() => undefined}
  >{page}</SessionProvider></MemoryRouter>);
  return fetcher;
}

describe("managed gateway form", () => {
  it.each([
    ["Gateway", <GatewaySettingsPage />],
    ["Content safety", <ContentSafetySettingsPage />],
  ])("uses friendly interface names on the %s page", async (_name, page) => {
    mount(page, (url) => {
      if (url.includes("/history") || url.includes("/organizations")) return { items: [], total: 0 };
      return { items: [row(), row({ scope: "dev-unified" })], total: 2 };
    });
    expect(await screen.findByRole("heading", { name: "API interface (/dev/v1)" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Chatbot interface (/dev/llm/v1)" })).toBeInTheDocument();
  });

  it("shows one shared editor with primary controls first and notes collapsed at the bottom", async () => {
    mount(<GatewaySettingsPage />, (url) => {
      if (url.includes("/history") || url.includes("/organizations")) return { items: [], total: 0 };
      return { items: [row({ scope: "dev-unified" }), row()], total: 2 };
    });
    const ui = within(await screen.findByRole("region", { name: "dev-openai settings" }));
    expect(screen.getAllByRole("button", { name: "Publish settings" })).toHaveLength(1);
    expect(screen.getByText("Settings below apply to both interfaces.")).toBeVisible();
    expect(ui.getByLabelText("Defaults requests per minute (RPM)")).toBeVisible();
    expect(ui.getByLabelText("Defaults concurrency")).toBeVisible();
    expect(ui.getByLabelText("Defaults request quota")).toBeVisible();
    expect(ui.getByLabelText("Defaults request quota period")).toBeVisible();
    expect(ui.getByLabelText("Defaults tokens per minute (TPM)")).not.toBeVisible();
    const notes = ui.getByText(/Native counters are approximate/);
    expect(notes).not.toBeVisible();
    await userEvent.click(ui.getByText("Token limits"));
    expect(ui.getByLabelText("Defaults tokens per minute (TPM)")).toBeVisible();
    await userEvent.click(ui.getByText("Important notes"));
    expect(notes).toBeVisible();
    const form = ui.getByRole("button", { name: "Publish settings" }).closest("form")!;
    expect(form.compareDocumentPosition(notes) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("keeps recovery controls accessible in their disclosure", async () => {
    mount(<GatewaySettingsPage />, (url) => url.includes("/history") || url.includes("/organizations")
      ? { items: [], total: 0 } : { items: [row()], total: 1 });
    const ui = within(await screen.findByRole("region", { name: "dev-openai settings" }));
    expect(ui.getByRole("button", { name: "Reload desired settings" })).not.toBeVisible();
    await userEvent.click(ui.getByText("Revision history and recovery"));
    expect(ui.getByRole("button", { name: "Reload desired settings" })).toBeVisible();
    expect(ui.getByRole("button", { name: "Check APIM / reconcile" })).toBeVisible();
  });

  it("limits concurrency to approved tiers, disables monthly quota and saves without safety changes", async () => {
    let body: any;
    mount(<GatewaySettingsPage />, (url, init) => {
      if (url.includes("/history")) return { items: [], total: 0 };
      if (url.includes("/organizations")) return { items: [], total: 0 };
      if (url.includes("/gateway-targets")) return { items: [], total: 0 };
      if (init?.method === "PUT") { body = JSON.parse(String(init.body)); return row({ version: 2 }); }
      return { items: [row()], total: 1 };
    });
    const ui = within(await screen.findByRole("region", { name: "dev-openai settings" }));
    const conc = ui.getByLabelText("Defaults concurrency") as HTMLSelectElement;
    expect([...conc.options].map((o) => o.value)).toEqual(["", "1", "2", "4"]);
    expect(within(ui.getByLabelText("Defaults request quota period")).getByRole("option", { name: "Monthly" })).toBeDisabled();
    expect(ui.getAllByText(/Monthly request quotas are unavailable/).length).toBeGreaterThan(0);
    const publish = ui.getByRole("button", { name: "Publish settings" });
    expect(publish).toBeDisabled();
    await userEvent.type(ui.getByLabelText("Reason for this revision"), "Raise budget");
    await userEvent.click(ui.getByLabelText(/I approve these budget values/));
    await userEvent.click(publish);
    expect(body.expected_version).toBe(1);
    expect(body.configuration.schema_version).toBe(2);
    expect(body.configuration.safety).toEqual(safety);
    expect(body.reason).toBe("Raise budget");
  });

  it("keeps the legacy form with an unavailable-features notice when managed controls are off", async () => {
    mount(<GatewaySettingsPage />, (url) => url.includes("/history") ? { items: [], total: 0 } : { items: [row({ desired: null, version: 0, published_version: null, capabilities: { ...caps, managed_controls_enabled: false } })], total: 1 });
    const ui = within(await screen.findByRole("region", { name: "dev-openai settings" }));
    expect(ui.getByLabelText("Safety threshold (0-7)")).toBeInTheDocument();
    expect(ui.getByText(/Managed controls are not enabled/)).toBeInTheDocument();
    expect(ui.queryByLabelText("Defaults concurrency")).not.toBeInTheDocument();
  });
});

describe("ContentSafetySettingsPage", () => {
  it.each([
    ["API first", [row(), row({ scope: "dev-unified" })], "dev-openai"],
    ["Chatbot first", [row({ scope: "dev-unified" }), row()], "dev-openai"],
    ["Chatbot only", [row({ scope: "dev-unified" })], "dev-unified"],
  ])("uses one shared safety editor and publishes once through the canonical scope (%s)", async (_name, rows, scope) => {
    let currentRows = rows;
    const fetcher = mount(<ContentSafetySettingsPage />, (url, init) => {
      if (url.includes("/history")) return { items: [], total: 0 };
      if (init?.method === "PUT") {
        const configuration = { ...managed, safety: { ...safety, profile: "Strict" as const, hate: 1, violence: 1, sexual: 1, self_harm: 1 } };
        currentRows = rows.map((item) => ({ ...item, version: 2, published_version: 2, desired: rev(2, configuration) }));
        return currentRows.find((item) => item.scope === scope);
      }
      return { items: currentRows, total: currentRows.length };
    });
    const ui = within(await screen.findByRole("region", { name: `${scope} content safety` }));
    expect(screen.getAllByLabelText("Safety profile")).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: "Publish safety settings" })).toHaveLength(1);
    expect(screen.getByText(`Settings below apply to ${rows.length > 1 ? "both interfaces" : "this interface"}.`)).toBeVisible();
    await userEvent.selectOptions(ui.getByLabelText("Safety profile"), "Strict");
    await userEvent.type(ui.getByLabelText("Reason for this revision"), "Shared safety review");
    await userEvent.click(ui.getByLabelText(/I approve these content safety values/));
    await userEvent.click(ui.getByRole("button", { name: "Publish safety settings" }));
    const writes = fetcher.mock.calls.filter(([, init]) => init?.method === "PUT");
    expect(writes).toHaveLength(1);
    const write = writes[0];
    if (!write) throw new Error("Expected one safety settings publication");
    expect(String(write[0])).toContain(scope);
    expect(JSON.parse(String(write[1]?.body))).toMatchObject({
      expected_version: 1, configuration: { profile: "Strict", hate: 1 },
    });
    await waitFor(() => expect(screen.queryByText(/The server revision changed/)).not.toBeInTheDocument());
  });

  const safetyRoutes = (state: { body?: any; status?: number; row: GatewaySettings }) => (url: string, init?: RequestInit) => {
    if (url.includes("/history")) return { items: [], total: 0 };
    if (init?.method === "PUT") {
      if (state.status === 409) return new Response(JSON.stringify({ detail: "stale" }), { status: 409 });
      state.body = JSON.parse(String(init.body)); return state.row;
    }
    return { items: [state.row], total: 1 };
  };

  it("keeps controls first and explanatory notes and recovery collapsed below the form", async () => {
    mount(<ContentSafetySettingsPage />, safetyRoutes({ row: row({ capabilities: { ...caps, safety_relaxation_allowed: false } }) }));
    const ui = within(await screen.findByRole("region", { name: "dev-openai content safety" }));
    expect(ui.getByLabelText("Safety profile")).toBeVisible();
    expect(ui.getByLabelText("Hate severity threshold (0-7)")).toBeVisible();
    expect(ui.getByLabelText("Prompt attack detection")).toBeVisible();
    expect(ui.getByLabelText("Reason for this revision")).toBeVisible();
    const propagation = ui.getByText(/Published confirms APIM readback/);
    const floor = ui.getByText(/The operator floor requires/);
    expect(propagation).not.toBeVisible();
    expect(floor).not.toBeVisible();
    expect(ui.getByRole("button", { name: "Reload desired settings" })).not.toBeVisible();
    const form = ui.getByRole("button", { name: "Publish safety settings" }).closest("form")!;
    expect(form.compareDocumentPosition(propagation) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    await userEvent.click(ui.getByText("Important notes"));
    expect(propagation).toBeVisible();
    expect(floor).toBeVisible();
    await userEvent.click(ui.getByText("Revision history and recovery"));
    expect(ui.getByRole("button", { name: "Reload desired settings" })).toBeVisible();
    expect(ui.getByRole("button", { name: "Check APIM / reconcile" })).toBeVisible();
  });

  it("keeps pending-publication recovery visible above the form", async () => {
    const pendingRow = row({ desired: { ...rev(2), state: "failed", error: "APIM publication failed." }, version: 2 });
    mount(<ContentSafetySettingsPage />, safetyRoutes({ row: pendingRow }));
    const ui = within(await screen.findByRole("region", { name: "dev-openai content safety" }));
    expect(ui.getByRole("alert")).toHaveTextContent("APIM publication failed.");
    expect(ui.getByRole("button", { name: "Retry publication" })).toBeVisible();
    expect(ui.getByRole("button", { name: "Publish safety settings" })).toBeDisabled();
  });

  it("applies the Strict preset and requires relaxation-free approval before publishing", async () => {
    const state: { body?: any; row: GatewaySettings } = { row: row() };
    mount(<ContentSafetySettingsPage />, safetyRoutes(state));
    const ui = within(await screen.findByRole("region", { name: "dev-openai content safety" }));
    await userEvent.selectOptions(ui.getByLabelText("Safety profile"), "Strict");
    expect(ui.getByLabelText("Hate severity threshold (0-7)")).toHaveValue(1);
    expect(ui.getByLabelText("Hate severity threshold (0-7)")).toBeDisabled();
    await userEvent.type(ui.getByLabelText("Reason for this revision"), "Tighten");
    await userEvent.click(ui.getByLabelText(/I approve these content safety values/));
    await userEvent.click(ui.getByRole("button", { name: "Publish safety settings" }));
    expect(state.body.configuration).toMatchObject({ profile: "Strict", hate: 1, protected_material: true });
    expect(state.body.expected_version).toBe(1);
    expect(state.body.acknowledge_relaxation).toBe(false);
  });

  it("requires acknowledgement to relax protections", async () => {
    const state: { body?: any; row: GatewaySettings } = { row: row() };
    mount(<ContentSafetySettingsPage />, safetyRoutes(state));
    const ui = within(await screen.findByRole("region", { name: "dev-openai content safety" }));
    await userEvent.click(ui.getByLabelText("Prompt attack detection"));
    await userEvent.type(ui.getByLabelText("Reason for this revision"), "Relax");
    await userEvent.click(ui.getByLabelText(/I approve these content safety values/));
    const publish = ui.getByRole("button", { name: "Publish safety settings" });
    expect(publish).toBeDisabled();
    await userEvent.click(ui.getByLabelText(/acknowledge this change relaxes/));
    await userEvent.click(publish);
    expect(state.body.acknowledge_relaxation).toBe(true);
  });

  it("locks toggles under the operator floor and blocks unavailable protected material", async () => {
    const state = { row: row({ capabilities: { ...caps, safety_relaxation_allowed: false, protected_material_available: false } }) };
    mount(<ContentSafetySettingsPage />, safetyRoutes(state));
    const ui = within(await screen.findByRole("region", { name: "dev-openai content safety" }));
    expect(ui.getByLabelText("Prompt attack detection")).toBeDisabled();
    expect(ui.getByText(/Protected material detection is unavailable/)).toBeInTheDocument();
    expect(ui.getByRole("button", { name: "Publish safety settings" })).toBeDisabled();
  });

  it("is blocked without an initialized managed gateway snapshot", async () => {
    const state = { row: row({ desired: null, version: 0, published_version: null }) };
    mount(<ContentSafetySettingsPage />, safetyRoutes(state));
    expect(await screen.findByText(/needs an initialized managed gateway configuration/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Publish safety settings" })).toBeDisabled();
  });

  it("preserves edits on a stale 409", async () => {
    const state: { status?: number; row: GatewaySettings } = { row: row(), status: 409 };
    mount(<ContentSafetySettingsPage />, safetyRoutes(state));
    const ui = within(await screen.findByRole("region", { name: "dev-openai content safety" }));
    await userEvent.type(ui.getByLabelText("Reason for this revision"), "Keep me");
    await userEvent.click(ui.getByLabelText(/I approve these content safety values/));
    await userEvent.click(ui.getByRole("button", { name: "Publish safety settings" }));
    expect(await screen.findByText(/Your edits are preserved/)).toBeInTheDocument();
    expect(ui.getByLabelText("Reason for this revision")).toHaveValue("Keep me");
  });
});

describe("managed helpers", () => {
  it("migrates legacy thresholds to Custom with prompt attack on and protected material off", () => {
    expect(migrateLegacySafety(3)).toEqual({ profile: "Custom", hate: 3, violence: 3, sexual: 3, self_harm: 3, prompt_attack: true, protected_material: false, input_filtering: true, output_filtering: true });
    expect(migrateLegacySafety(1).hate).toBe(1);
  });
  it("uses the operator initial threshold only when unconfigured", () => {
    expect(currentSafety(null, 0)?.hate).toBe(0);
    expect(currentSafety(null)?.self_harm).toBe(1);
    expect(currentSafety({ safety_threshold: 5, rpm: 2, tpm: 1, token_quota: 1, quota_period: "Daily" }, 0)?.sexual).toBe(5);
  });
  it("absolute floor requires prompt/input/output on, ignoring stored baseline, and excludes protected material", () => {
    const floor = { ...caps, safety_relaxation_allowed: false };
    const ok = { ...migrateLegacySafety(4) };
    expect(validateSafety(ok, floor)).toBeNull();
    expect(validateSafety({ ...ok, protected_material: true }, floor)).toBeNull();
    expect(validateSafety({ ...ok, protected_material: false }, floor)).toBeNull();
    for (const k of ["prompt_attack", "input_filtering", "output_filtering"] as const) expect(validateSafety({ ...ok, [k]: false }, floor)).toMatch(/must be enabled/);
    expect(validateSafety({ ...ok, input_filtering: false }, caps)).toBeNull();
    expect(applyFloor({ ...ok, input_filtering: false, protected_material: false }, floor)).toMatchObject({ input_filtering: true, protected_material: false });
    expect(validateSafety({ ...ok, protected_material: true }, { ...floor, protected_material_available: false })).toMatch(/not available/);
  });
});

describe("managed notices and floor UI", () => {
  it("keeps enforcement warnings visible and shared-route guidance in notes", async () => {
    mount(<GatewaySettingsPage />, (url) => url.includes("/history") || url.includes("/gateway-targets") || url.includes("/organizations") ? { items: [], total: 0 } : { items: [row({ capabilities: { ...caps, enforcement_enabled: false } })], total: 1 });
    const ui = within(await screen.findByRole("region", { name: "dev-openai settings" }));
    expect(ui.getByText(/Changes apply to both interfaces/)).not.toBeVisible();
    expect(ui.getByText(/New subscriptions cannot send requests/)).not.toBeVisible();
    expect(ui.getByRole("alert", { name: "" }).textContent).toMatch(/not enforced yet/);
  });
  it("keeps protected material enableable under the floor but disabled when unavailable", async () => {
    const legacy = { safety_threshold: 4, rpm: 2, tpm: 1024, token_quota: 1, quota_period: "Daily" as const };
    const r = row({ desired: { ...rev(1), configuration: legacy } as never, capabilities: { ...caps, safety_relaxation_allowed: false, protected_material_available: false } });
    mount(<ContentSafetySettingsPage />, (url) => url.includes("/history") ? { items: [], total: 0 } : { items: [r], total: 1 });
    const ui = within(await screen.findByRole("region", { name: "dev-openai content safety" }));
    expect(ui.getByLabelText("Prompt attack detection")).toBeDisabled();
    expect(ui.getByLabelText(/protected material/i)).toBeDisabled();
    expect(ui.getByText(/Protected material detection is unavailable/)).toBeTruthy();
  });
  it("allows enabling protected material when available under the floor", async () => {
    const r = row({ desired: rev(1, { ...managed, safety: { ...safety, profile: "Custom", protected_material: false } }), capabilities: { ...caps, safety_relaxation_allowed: false } });
    mount(<ContentSafetySettingsPage />, (url) => url.includes("/history") ? { items: [], total: 0 } : { items: [r], total: 1 });
    const ui = within(await screen.findByRole("region", { name: "dev-openai content safety" }));
    expect(ui.getByLabelText(/protected material/i)).toBeEnabled();
    expect(ui.getByLabelText(/protected material/i)).not.toBeChecked();
  });
});
describe("safety floor with a relaxed stored baseline", () => {
  it("lets an off floor toggle be re-enabled but blocks publishing while it is off; protected material can be turned off with acknowledgement", async () => {
    const stored = { ...safety, profile: "Custom" as const, input_filtering: false };
    const r = row({ desired: rev(1, { ...managed, safety: stored }), capabilities: { ...caps, safety_relaxation_allowed: false } });
    mount(<ContentSafetySettingsPage />, (url) => url.includes("/history") ? { items: [], total: 0 } : { items: [r], total: 1 });
    const ui = within(await screen.findByRole("region", { name: "dev-openai content safety" }));
    expect(ui.getByLabelText("Prompt attack detection")).toBeDisabled();
    expect(ui.getByLabelText(/Input filtering/i)).toBeEnabled();
    expect(ui.getByRole("alert").textContent).toMatch(/must be enabled/);
    await userEvent.click(ui.getByLabelText(/Input filtering/i));
    expect(ui.getByLabelText(/Input filtering/i)).toBeDisabled();
    expect(ui.queryByRole("alert")).toBeNull();
    const pm = ui.getByLabelText(/protected material/i);
    expect(pm).toBeEnabled();
    await userEvent.click(pm);
    expect(ui.getByText(/acknowledge this change relaxes/i)).toBeTruthy();
  });
});
