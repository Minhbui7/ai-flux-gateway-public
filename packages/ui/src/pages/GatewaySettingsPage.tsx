import { useEffect, useState, type FormEvent } from "react";
import { ApiError } from "../client";
import { AsyncView, ErrorState, Field, PageHeader, Pager, fmtDate, useAsync } from "../components/ui";
import { useSession } from "../session";
import { legacyOf } from "../managed";
import type { GatewayConfiguration, GatewaySettings, QuotaPeriod } from "../types";
import { ManagedGatewayForm } from "./ManagedGatewayForm";

const periods: QuotaPeriod[] = ["Hourly", "Daily", "Weekly", "Monthly", "Yearly"];
type Draft = Record<keyof GatewayConfiguration, string>;
const draftOf = (config?: GatewayConfiguration): Draft => ({
  safety_threshold: config ? String(config.safety_threshold) : "",
  rpm: config ? String(config.rpm) : "",
  tpm: config ? String(config.tpm) : "",
  token_quota: config ? String(config.token_quota) : "",
  quota_period: config?.quota_period ?? "",
});

export function validateGatewaySettings(draft: Draft, maxTpm: number): GatewayConfiguration | null {
  const bounds = { safety_threshold: [0, 7], rpm: [1, 2], tpm: [1, maxTpm], token_quota: [1, 2147483647] } as const;
  for (const name of Object.keys(bounds) as (keyof typeof bounds)[]) {
    const value = Number(draft[name]);
    if (!/^\d+$/.test(draft[name]) || !Number.isSafeInteger(value) || value < bounds[name][0] || value > bounds[name][1]) return null;
  }
  const period = periods.find((p) => p === draft.quota_period);
  if (!period) return null;
  return {
    safety_threshold: Number(draft.safety_threshold), rpm: Number(draft.rpm),
    tpm: Number(draft.tpm), token_quota: Number(draft.token_quota), quota_period: period,
  };
}

function SettingsForm({ row, refresh }: { row: GatewaySettings; refresh: () => void }) {
  const { api } = useSession();
  const [draft, setDraft] = useState(() => draftOf(legacyOf(row.desired?.configuration)));
  const [expectedVersion, setExpectedVersion] = useState(row.version);
  const [reason, setReason] = useState("");
  const [approved, setApproved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [offset, setOffset] = useState(0);
  const history = useAsync(() => api.gatewaySettingsHistory(row.scope, offset), [api, row.scope, row.version, row.desired?.state, offset]);
  const configuration = validateGatewaySettings(draft, row.max_tpm);
  const pending = row.desired != null && row.desired.state !== "published";
  const conflict = expectedVersion !== row.version;
  const change = (name: keyof Draft) => (e: { target: { value: string } }) => {
    setDraft((previous) => ({ ...previous, [name]: e.target.value }));
    setApproved(false);
  };

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!configuration || !reason.trim() || !approved || conflict || pending) return;
    setBusy(true);
    setError(undefined);
    try {
      const next = await api.saveGatewaySettings(row.scope, expectedVersion, configuration, reason.trim());
      setExpectedVersion(next.version);
      setReason("");
      setApproved(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Could not publish gateway settings.");
    } finally {
      setBusy(false);
      refresh();
    }
  }

  async function reconcile() {
    setBusy(true);
    setError(undefined);
    try {
      const next = await api.reconcileGatewaySettings(row.scope, row.version);
      setExpectedVersion(next.version);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Could not reconcile gateway settings.");
    } finally {
      setBusy(false);
      refresh();
    }
  }

  function load(config?: GatewayConfiguration) {
    setDraft(draftOf(config));
    setExpectedVersion(row.version);
    setReason("");
    setApproved(false);
    setError(undefined);
  }

  return (
    <section className="panel" aria-label={`${row.scope} settings`}>
      <h2>{row.scope === "dev-openai" ? "API interface (/dev/v1)" : "Chatbot interface (/dev/llm/v1)"}</h2>
      <p>API-wide settings, with separate counters per API, subscription and model. Completion ceilings remain operator-managed.</p>
      <p role="status">Desired revision: {row.version || "Unconfigured"}; last published revision: {row.published_version ?? "None"}; status: {row.desired?.state ?? "unconfigured"}.</p>
      <p className="notice">Published means APIM management-plane readback matched, not that every gateway has applied it. Propagation is eventual; old settings can remain effective during a change.</p>
      {row.desired?.error && <ErrorState message={row.desired.error} />}
      {error && <ErrorState message={error} />}
      {conflict && <p role="alert">The server revision changed. Your edits are preserved. Reload desired settings or choose a historical configuration before publishing.</p>}
      <button className="btn" disabled={busy} onClick={() => load(legacyOf(row.desired?.configuration))}>Reload desired settings</button>
      {row.desired && <button className="btn" disabled={busy} onClick={() => void reconcile()}>{pending ? "Retry publication" : "Check APIM / reconcile"}</button>}
      <p className="notice">Managed controls are not enabled: concurrency limits, per-team and per-subscription limits, monthly request quotas and protected material detection are unavailable and are not configured by this form.</p>
      <form className="grid-form" onSubmit={(e) => void save(e)}>
        <Field label="Safety threshold (0-7)" hint="One threshold for Hate, SelfHarm, Sexual and Violence at all three inspection passes. Higher is more permissive; 0 blocks every severity, not off.">{(id, d) => <input id={id} aria-describedby={d} type="number" min={0} max={7} step={1} required value={draft.safety_threshold} onChange={change("safety_threshold")} />}</Field>
        <Field label="Requests per minute (RPM)" hint={`Whole number from 1 to ${row.max_rpm}.`}>{(id, d) => <input id={id} aria-describedby={d} type="number" min={1} max={row.max_rpm} step={1} required value={draft.rpm} onChange={change("rpm")} />}</Field>
        <Field label="Tokens per minute (TPM)" hint={`Whole number from 1 to ${row.max_tpm}.`}>{(id, d) => <input id={id} aria-describedby={d} type="number" min={1} max={row.max_tpm} step={1} required value={draft.tpm} onChange={change("tpm")} />}</Field>
        <Field label="Token quota" hint="Explicit prompt + completion token budget, 1-2147483647. No unlimited or guessed default.">{(id, d) => <input id={id} aria-describedby={d} type="number" min={1} max={2147483647} step={1} required value={draft.token_quota} onChange={change("token_quota")} />}</Field>
        <Field label="Quota period (UTC fixed window)">{(id) => <select id={id} required value={draft.quota_period} onChange={change("quota_period")}><option value="">Select a period</option>{periods.map((p) => <option key={p}>{p}</option>)}</select>}</Field>
        <Field label="Reason for this revision">{(id) => <input id={id} required maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field>
        <p className="notice">Native limits are gateway-local estimates and may overshoot under concurrency. Changing quota periods can change reset behavior. Settings changes do not rename counters. Do not enter prompts, secrets or customer content in the reason.</p>
        <label><input type="checkbox" checked={approved} onChange={(e) => setApproved(e.target.checked)} /> I approve these safety and budget values, including any relaxation, quota-period change and propagation delay.</label>
        <div className="form-actions"><button className="btn primary" disabled={busy || !configuration || !reason.trim() || !approved || pending || conflict}>{busy ? "Publishing..." : "Publish settings"}</button></div>
      </form>
      <h3>Revision history</h3>
      <AsyncView state={history} isEmpty={(d) => d.items.length === 0} emptyTitle="No settings revisions" emptyHint="An IDS administrator must explicitly configure the settings.">
        {(data) => <>
          <ul>{data.items.map((revision) => <li key={revision.version}>
            Revision {revision.version}: {revision.state}, {fmtDate(revision.occurred_at)}. Actor: <code>{revision.object_id}</code>. Reason: {revision.reason}.
            <button className="btn" disabled={busy || pending} onClick={() => load(legacyOf(revision.configuration))}>Use revision {revision.version} values</button>
          </li>)}</ul>
          <Pager offset={offset} limit={10} total={data.total} onChange={setOffset} />
        </>}
      </AsyncView>
    </section>
  );
}

export function GatewaySettingsPage() {
  const { api } = useSession();
  const [version, setVersion] = useState(0);
  const [previous, setPrevious] = useState<GatewaySettings[]>();
  const refresh = () => setVersion((v) => v + 1);
  const state = useAsync(() => api.gatewaySettings(), [api, version]);
  useEffect(() => {
    if (state.data) setPrevious(state.data.items);
  }, [state.data]);
  const rows = state.data?.items ?? previous;
  return <>
    <PageHeader title="Gateway settings" subtitle="Configure request limits by team or API key." actions={<button className="btn" onClick={refresh}>Refresh publication status</button>} />
    {state.error && rows !== undefined && <ErrorState message={state.error} onRetry={refresh} />}
    <AsyncView state={{ ...state, data: rows, error: rows === undefined ? state.error : undefined }} isEmpty={(data) => data.length === 0} emptyTitle="Admin settings are not enabled" emptyHint="An operator must opt in through Terraform. Existing code-managed settings remain unchanged.">
      {(data) => {
        const managed = data.filter((row) => row.capabilities?.managed_controls_enabled);
        const shared = managed.find((row) => row.scope === "dev-openai") ?? managed[0];
        return <>
          {shared && <>
            <div className="gateway-interfaces" aria-label="Configured interfaces">
              {managed.map((row) => <section className="panel" key={row.scope}>
                <h2>{row.scope === "dev-openai" ? "API interface (/dev/v1)" : "Chatbot interface (/dev/llm/v1)"}</h2>
              </section>)}
            </div>
            <p className="muted">Settings below apply to {managed.length > 1 ? "both interfaces" : "this interface"}.</p>
            <ManagedGatewayForm key={shared.scope} row={shared} refresh={refresh} />
          </>}
          {data.filter((row) => !row.capabilities?.managed_controls_enabled).map((row) =>
            <SettingsForm key={row.scope} row={row} refresh={refresh} />)}
        </>;
      }}
    </AsyncView>
  </>;
}
