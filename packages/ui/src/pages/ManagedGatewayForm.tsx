import { useMemo, useState, type FormEvent } from "react";
import { ApiError } from "../client";
import { ErrorState, Field, Pager, useAsync } from "../components/ui";
import {
  CONCURRENCY_TIERS, QUOTA_PERIODS, STANDARD_SAFETY, buildManaged, currentSafety, describeLimits,
  managedDraftOf, subKey, teamKey, validateLimits, type LimitsDraft, type ManagedDraft,
} from "../managed";
import { useSession } from "../session";
import type { GatewayConfigurationUnion, GatewaySettings } from "../types";
import { RevisionHistory } from "./RevisionHistory";

const TARGET_PAGE = 100;

function LimitsEditor({ title, draft, row, onChange }: {
  title: string; draft: LimitsDraft; row: GatewaySettings; onChange: (name: keyof LimitsDraft, value: string) => void;
}) {
  const caps = row.capabilities;
  const tiers = CONCURRENCY_TIERS.filter((t) => caps?.concurrency_tiers.includes(t));
  const monthly = caps?.monthly_request_quota_available ?? false;
  const set = (name: keyof LimitsDraft) => (e: { target: { value: string } }) => onChange(name, e.target.value);
  return <fieldset className="gateway-limit-fields" aria-label={`${title} limits`}>
    <legend>{title}</legend>
    <Field label={`${title} requests per minute (RPM)`}>{(id) => <input id={id} type="number" min={1} max={row.max_rpm} step={1} value={draft.rpm} onChange={set("rpm")} />}</Field>
    <Field label={`${title} concurrency`}>{(id) => <select id={id} value={draft.concurrency} onChange={set("concurrency")}><option value="">Select a tier</option>{tiers.map((t) => <option key={t} value={t}>{t}</option>)}</select>}</Field>
    <Field label={`${title} request quota`} hint="Leave blank for no request quota.">{(id, d) => <input id={id} aria-describedby={d} type="number" min={1} max={2147483647} step={1} value={draft.request_quota} onChange={set("request_quota")} />}</Field>
    <Field label={`${title} request quota period`}>{(id) => <select id={id} value={draft.request_quota_period} onChange={set("request_quota_period")}><option>Daily</option><option disabled={!monthly}>Monthly</option></select>}</Field>
    <details className="gateway-advanced">
      <summary>Token limits</summary>
      <div className="gateway-limit-fields">
        <Field label={`${title} tokens per minute (TPM)`} hint={`Maximum ${row.max_tpm}.`}>{(id, d) => <input id={id} aria-describedby={d} type="number" min={1} max={row.max_tpm} step={1} value={draft.tpm} onChange={set("tpm")} />}</Field>
        <Field label={`${title} token quota`}>{(id) => <input id={id} type="number" min={1} max={2147483647} step={1} value={draft.token_quota} onChange={set("token_quota")} />}</Field>
        <Field label={`${title} token quota period`}>{(id) => <select id={id} value={draft.quota_period} onChange={set("quota_period")}><option value="">Select a period</option>{QUOTA_PERIODS.map((p) => <option key={p}>{p}</option>)}</select>}</Field>
      </div>
    </details>
  </fieldset>;
}

export function ManagedGatewayForm({ row, refresh }: { row: GatewaySettings; refresh: () => void }) {
  const { api } = useSession();
  const caps = row.capabilities;
  const [draft, setDraft] = useState<ManagedDraft>(() => managedDraftOf(row.desired?.configuration));
  const [expectedVersion, setExpectedVersion] = useState(row.version);
  const [reason, setReason] = useState("");
  const [approved, setApproved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [orgId, setOrgId] = useState("");
  const [teamId, setTeamId] = useState("");
  const [subId, setSubId] = useState("");
  const [offset, setOffset] = useState(0);
  const orgs = useAsync(() => api.organizations(), [api]);
  const targets = useAsync(() => (orgId ? api.gatewayTargets(offset, TARGET_PAGE, orgId) : Promise.resolve(undefined)), [api, orgId, offset]);
  const max = { rpm: row.max_rpm, tpm: row.max_tpm };
  const safety = currentSafety(row.desired?.configuration, row.capabilities?.initial_safety_threshold) ?? STANDARD_SAFETY;
  const configuration = useMemo(() => buildManaged(draft, safety, max, caps), [draft, safety, max.rpm, max.tpm, caps]);
  const pending = row.desired != null && row.desired.state !== "published";
  const conflict = expectedVersion !== row.version;
  const pageTargets = targets.data?.items ?? [];
  const teams = [...new Map(pageTargets.map((t) => [t.team_id, t.team])).entries()];
  const subs = pageTargets.filter((t) => !teamId || t.team_id === teamId);
  const tKey = orgId && teamId ? teamKey(orgId, teamId) : "";
  const sKey = orgId && subId ? subKey(orgId, subId) : "";
  const teamDraft = tKey ? draft.teams[tKey] : undefined;
  const subDraft = sKey ? draft.subscriptions[sKey] : undefined;
  const team = teams.find(([id]) => id === teamId)?.[1];
  const sub = pageTargets.find((t) => t.subscription_id === subId);

  const edit = (apply: (d: ManagedDraft) => ManagedDraft) => { setDraft(apply); setApproved(false); };
  const setField = (kind: "defaults" | "teams" | "subscriptions", key: string) => (name: keyof LimitsDraft, value: string) =>
    edit((d) => kind === "defaults" ? { ...d, defaults: { ...d.defaults, [name]: value } } : { ...d, [kind]: { ...d[kind], [key]: { ...d[kind][key]!, [name]: value } } });
  const addOverride = (kind: "teams" | "subscriptions", key: string) => edit((d) => ({ ...d, [kind]: { ...d[kind], [key]: { ...d.defaults } } }));
  const removeOverride = (kind: "teams" | "subscriptions", key: string) => edit((d) => {
    const { [key]: _removed, ...rest } = d[kind];
    return { ...d, [kind]: rest };
  });

  const defaults = validateLimits(draft.defaults, max, caps);
  const teamLimits = teamDraft ? validateLimits(teamDraft, max, caps) : defaults;
  const effective = subDraft ? validateLimits(subDraft, max, caps) : teamLimits;
  const effectiveSource = subDraft ? "subscription override" : teamDraft ? "team override" : "defaults";

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
      setError(err instanceof ApiError
        ? err.status === 409 ? `${err.detail} Your edits are preserved; reload desired settings or choose a historical configuration before publishing.` : err.detail
        : "Could not publish gateway settings.");
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

  function load(config?: GatewayConfigurationUnion) {
    setDraft(managedDraftOf(config));
    setExpectedVersion(row.version);
    setReason("");
    setApproved(false);
    setError(undefined);
  }

  return (
    <section className="panel" aria-label={`${row.scope} settings`}>
      <h2>Shared limits</h2>
      <p role="status" className="muted">{row.desired?.state ?? "Unconfigured"} - Revision {row.version} - Published {row.published_version ?? "none"}</p>
      {caps && !caps.enforcement_enabled && <p role="alert">Enforcement is not enabled by the operator. Published limits are recorded but are not enforced yet.</p>}
      {row.desired?.error && <ErrorState message={row.desired.error} />}
      {error && <ErrorState message={error} />}
      {conflict && <p role="alert">The server revision changed. Your edits are preserved. Reload desired settings or choose a historical configuration before publishing.</p>}
      {pending && <button className="btn" disabled={busy} onClick={() => void reconcile()}>Retry publication</button>}
      <form className="gateway-form" onSubmit={(e) => void save(e)}>
        <LimitsEditor title="Defaults" draft={draft.defaults} row={row} onChange={setField("defaults", "")} />
        <fieldset className="grid-form" aria-label="Target selection">
          <legend>Team and subscription targets</legend>
          <Field label="Organization">{(id) => <select id={id} value={orgId} onChange={(e) => { setOrgId(e.target.value); setTeamId(""); setSubId(""); setOffset(0); }}><option value="">Select an organization</option>{(orgs.data?.items ?? []).map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}</select>}</Field>
          <Field label="Team">{(id) => <select id={id} disabled={!orgId} value={teamId} onChange={(e) => { setTeamId(e.target.value); setSubId(""); }}><option value="">Select a team</option>{teams.map(([tid, name]) => <option key={tid} value={tid}>{name}</option>)}</select>}</Field>
          <Field label="Subscription">{(id) => <select id={id} disabled={!orgId} value={subId} onChange={(e) => setSubId(e.target.value)}><option value="">Select a subscription</option>{subs.map((t) => <option key={t.subscription_id} value={t.subscription_id}>{t.name} ({t.state})</option>)}</select>}</Field>
          {targets.error && <ErrorState message={targets.error} />}
          {targets.data && <Pager offset={offset} limit={TARGET_PAGE} total={targets.data.total} onChange={setOffset} />}
        </fieldset>
        {tKey && !teamDraft && <div><p>{team} uses the defaults.</p><button type="button" className="btn" onClick={() => addOverride("teams", tKey)}>Add team override for {team}</button></div>}
        {tKey && teamDraft && <>
          <LimitsEditor title={`Team ${team ?? ""}`.trim()} draft={teamDraft} row={row} onChange={setField("teams", tKey)} />
          <button type="button" className="btn" onClick={() => removeOverride("teams", tKey)}>Remove team override (inherit defaults)</button>
        </>}
        {sKey && !subDraft && <div><p>{sub?.name} inherits {teamDraft ? "its team override" : "the defaults"}.</p><button type="button" className="btn" onClick={() => addOverride("subscriptions", sKey)}>Add subscription override for {sub?.name}</button></div>}
        {sKey && subDraft && <>
          <LimitsEditor title={`Subscription ${sub?.name ?? ""}`.trim()} draft={subDraft} row={row} onChange={setField("subscriptions", sKey)} />
          <button type="button" className="btn" onClick={() => removeOverride("subscriptions", sKey)}>Remove subscription override (inherit)</button>
        </>}
        <p role="status" aria-label="Effective limits">Effective limits ({effectiveSource}): {effective ? describeLimits(effective) : "incomplete or invalid values"}.</p>
        <Field label="Reason for this revision">{(id) => <input id={id} required maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field>
        <label><input type="checkbox" checked={approved} onChange={(e) => setApproved(e.target.checked)} /> I approve these budget values.</label>
        <div className="form-actions"><button className="btn primary" disabled={busy || !configuration || !reason.trim() || !approved || pending || conflict}>{busy ? "Publishing..." : "Publish settings"}</button></div>
      </form>
      <details className="gateway-advanced">
        <summary>Revision history and recovery</summary>
        <button className="btn" disabled={busy} onClick={() => load(row.desired?.configuration)}>Reload desired settings</button>
        {row.desired && <button className="btn" disabled={busy} onClick={() => void reconcile()}>Check APIM / reconcile</button>}
        <RevisionHistory load={(o) => api.gatewaySettingsHistory(row.scope, o)} deps={[api, row.scope, row.version, row.desired?.state]} disabled={busy || pending} onUse={load} />
      </details>
      <details className="gateway-advanced">
        <summary>Important notes</summary>
        <ul>
          <li>Changes apply to both interfaces. Counters are shared across models and primary/secondary API keys.</li>
          <li>Team overrides enforce an aggregate team budget. Subscription overrides apply to that API key pair.</li>
          <li>New subscriptions cannot send requests until gateway membership is published. Admin creation refreshes membership automatically; pending access requires reconciliation.</li>
          <li>Published confirms APIM readback, not immediate gateway propagation. Old settings may apply briefly.</li>
          <li>Native counters are approximate and can overshoot. Quota-period changes can affect reset behavior.</li>
          <li>Daily and monthly quotas reset at UTC calendar boundaries. Token quotas count prompt and completion tokens. The TPM maximum is the lowest supported across configured interfaces.</li>
          <li>Content safety ({safety.profile}) is configured on the Content safety page and is unchanged by this form.</li>
          <li>Do not put secrets, prompts or customer content in revision reasons. Completion limits remain operator-managed.</li>
          {!caps?.monthly_request_quota_available && <li>Monthly request quotas are unavailable until the operator validates native monthly quota support.</li>}
        </ul>
      </details>
    </section>
  );
}
