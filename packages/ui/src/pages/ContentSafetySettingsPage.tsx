import { useState, type FormEvent } from "react";
import { ApiError } from "../client";
import { AsyncView, ErrorState, Field, PageHeader, useAsync } from "../components/ui";
import {
  SAFETY_CATEGORIES, SAFETY_TOGGLES, STANDARD_SAFETY, applyFloor, currentSafety, isFloorToggle, isManaged, isRelaxation, presetFor, safetyLabel, validateSafety,
} from "../managed";
import { useSession } from "../session";
import type { GatewayConfigurationUnion, GatewaySettings, SafetyConfiguration } from "../types";
import { RevisionHistory } from "./RevisionHistory";

function SafetyForm({ row, refresh }: { row: GatewaySettings; refresh: () => void }) {
  const { api } = useSession();
  const caps = row.capabilities;
  const current = currentSafety(row.desired?.configuration, row.capabilities?.initial_safety_threshold);
  const ready = isManaged(row.desired?.configuration);
  const [draft, setDraft] = useState<SafetyConfiguration>(() => current ?? STANDARD_SAFETY);
  const [expectedVersion, setExpectedVersion] = useState(row.version);
  const [reason, setReason] = useState("");
  const [approved, setApproved] = useState(false);
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const pending = row.desired != null && row.desired.state !== "published";
  const conflict = expectedVersion !== row.version;
  const relaxing = isRelaxation(draft, current);
  const invalid = validateSafety(draft, caps);
  const locked = !caps?.safety_relaxation_allowed;
  const blocked = !ready || !caps?.managed_controls_enabled;

  const edit = (next: SafetyConfiguration) => { setDraft(next); setApproved(false); setAck(false); };
  const setProfile = (profile: SafetyConfiguration["profile"]) => edit(applyFloor(presetFor(profile, draft), caps));
  const setCategory = (k: (typeof SAFETY_CATEGORIES)[number], v: string) => edit({ ...draft, profile: "Custom", [k]: v === "" ? Number.NaN : Number(v) });
  const setToggle = (k: (typeof SAFETY_TOGGLES)[number], v: boolean) => edit({ ...draft, profile: "Custom", [k]: v });

  async function save(e: FormEvent) {
    e.preventDefault();
    if (blocked || invalid || !reason.trim() || !approved || conflict || pending || (relaxing && !ack)) return;
    setBusy(true);
    setError(undefined);
    try {
      const next = await api.saveContentSafetySettings(row.scope, expectedVersion, draft, reason.trim(), relaxing && ack);
      setExpectedVersion(next.version);
      setReason("");
      setApproved(false);
      setAck(false);
    } catch (err) {
      setError(err instanceof ApiError
        ? err.status === 409 ? `${err.detail} Your edits are preserved; reload desired settings before publishing.` : err.detail
        : "Could not publish content safety settings.");
    } finally {
      setBusy(false);
      refresh();
    }
  }

  async function reconcile() {
    setBusy(true);
    setError(undefined);
    try {
      const next = await api.reconcileContentSafetySettings(row.scope, row.version);
      setExpectedVersion(next.version);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Could not reconcile content safety settings.");
    } finally {
      setBusy(false);
      refresh();
    }
  }

  function load(config?: GatewayConfigurationUnion) {
    setDraft(currentSafety(config, row.capabilities?.initial_safety_threshold) ?? STANDARD_SAFETY);
    setExpectedVersion(row.version);
    setReason("");
    setApproved(false);
    setAck(false);
    setError(undefined);
  }

  return (
    <section className="panel" aria-label={`${row.scope} content safety`}>
      <h2>Shared safety settings</h2>
      <p role="status" className="muted">{row.desired?.state ?? "Unconfigured"} - Revision {row.version} - Published {row.published_version ?? "none"}</p>
      {caps && !caps.managed_controls_enabled && <p role="alert">Managed controls are not enabled by the operator, so content safety cannot be changed here.</p>}
      {caps?.managed_controls_enabled && !ready && <p role="alert">Content safety needs an initialized managed gateway configuration. Publish managed gateway settings first.</p>}
      {caps && !caps.protected_material_available && <p role="alert">Protected material detection is unavailable in this environment. Configurations enabling it cannot be published.</p>}
      {row.desired?.error && <ErrorState message={row.desired.error} />}
      {error && <ErrorState message={error} />}
      {conflict && <p role="alert">The server revision changed. Your edits are preserved. Reload desired settings before publishing.</p>}
      {pending && <button className="btn" disabled={busy} onClick={() => void reconcile()}>Retry publication</button>}
      <form className="gateway-form" onSubmit={(e) => void save(e)}>
        <fieldset disabled={blocked} className="gateway-limit-fields">
          <Field label="Safety profile">{(id) => <select id={id} value={draft.profile} onChange={(e) => setProfile(e.target.value as SafetyConfiguration["profile"])}><option>Standard</option><option>Strict</option><option>Custom</option></select>}</Field>
          {SAFETY_CATEGORIES.map((k) => <Field key={k} label={`${safetyLabel[k]} severity threshold (0-7)`}>{(id) =>
            <input id={id} type="number" min={0} max={7} step={1} disabled={draft.profile !== "Custom"} value={Number.isNaN(draft[k]) ? "" : draft[k]} onChange={(e) => setCategory(k, e.target.value)} />}</Field>)}
          {SAFETY_TOGGLES.map((k) => <label key={k}><input type="checkbox" checked={draft[k]} disabled={(isFloorToggle(k, caps) && draft[k]) || (k === "protected_material" && !caps?.protected_material_available && !draft[k])} onChange={(e) => setToggle(k, e.target.checked)} /> {safetyLabel[k]}</label>)}
          {invalid && !blocked && <p role="alert">{invalid}</p>}
          {relaxing && <label><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} /> I acknowledge this change relaxes content safety protection.</label>}
          <Field label="Reason for this revision">{(id) => <input id={id} required maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field>
          <label><input type="checkbox" checked={approved} onChange={(e) => setApproved(e.target.checked)} /> I approve these content safety values.</label>
          <div className="form-actions"><button className="btn primary" disabled={busy || blocked || !!invalid || !reason.trim() || !approved || pending || conflict || (relaxing && !ack)}>{busy ? "Publishing..." : "Publish safety settings"}</button></div>
        </fieldset>
      </form>
      <details className="gateway-advanced">
        <summary>Revision history and recovery</summary>
        <button className="btn" disabled={busy} onClick={() => load(row.desired?.configuration)}>Reload desired settings</button>
        {row.desired && <button className="btn" disabled={busy} onClick={() => void reconcile()}>Check APIM / reconcile</button>}
        <RevisionHistory load={(o) => api.contentSafetySettingsHistory(row.scope, o)} deps={[api, row.scope, row.version, row.desired?.state]} disabled={busy || pending} onUse={load} />
      </details>
      <details className="gateway-advanced">
        <summary>Important notes</summary>
        <ul>
          <li>Both interfaces share the same safety configuration and revision. Saving here updates both interfaces without changing request limits.</li>
          <li>Published confirms APIM readback, not immediate gateway propagation. Old settings may apply briefly.</li>
          {locked && caps?.managed_controls_enabled && <li>The operator floor requires prompt attack, input and output filtering to be on; they cannot be turned off. Protected material is not part of the floor.</li>}
          <li>Lower severity thresholds are stricter. A threshold of 0 blocks every severity; it does not disable filtering.</li>
          <li>Protected material detection covers known protected text, not code or a copyright guarantee. Input PII redaction remains mandatory.</li>
          <li>Do not put secrets, prompts or customer content in revision reasons.</li>
        </ul>
      </details>
    </section>
  );
}

export function ContentSafetySettingsPage() {
  const { api } = useSession();
  const [tick, setTick] = useState(0);
  const state = useAsync(() => api.contentSafetySettings(), [api, tick]);
  const refresh = () => setTick((t) => t + 1);
  return <>
    <PageHeader title="Content safety" subtitle="Profiles, thresholds and protections applied to guarded gateway traffic" actions={<button className="btn" onClick={refresh}>Refresh publication status</button>} />
    <AsyncView state={state} isEmpty={(d) => d.items.length === 0} emptyTitle="No content safety scopes">
      {(data) => {
        const shared = data.items.find((row) => row.scope === "dev-openai") ?? data.items[0];
        return <>
          <div className="gateway-interfaces" aria-label="Configured interfaces">
            {data.items.map((row) => <section className="panel" key={row.scope}>
              <h2>{row.scope === "dev-openai" ? "API interface (/dev/v1)" : "Chatbot interface (/dev/llm/v1)"}</h2>
            </section>)}
          </div>
          <p className="muted">Settings below apply to {data.items.length > 1 ? "both interfaces" : "this interface"}.</p>
          {shared && <SafetyForm key={shared.scope} row={shared} refresh={refresh} />}
        </>;
      }}
    </AsyncView>
  </>;
}
