import { useState, type FormEvent } from "react";
import { ApiError } from "../client";
import { useSession } from "../session";
import type { Member, Price, PriceInput, Role } from "../types";
import { isDecimal, isGuid } from "../validation";
import { AsyncView, Badge, ErrorState, Field, PageHeader, Pager, Table, fmtDate, useAsync } from "../components/ui";

const errText = (e: unknown, fb: string) => (e instanceof ApiError ? e.detail : fb);

export function OrganizationsPage() {
  const { api } = useSession();
  const [v, setV] = useState(0);
  const state = useAsync(() => api.organizations(), [api, v]);
  const [name, setName] = useState("");
  const [tenant, setTenant] = useState("");
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const valid = name.trim().length >= 2 && isGuid(tenant);

  async function create(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(undefined);
    try {
      await api.createOrganization({ name: name.trim(), tenant_id: tenant.trim().toLowerCase() });
      setName("");
      setTenant("");
      setV((x) => x + 1);
    } catch (err) {
      setError(errText(err, "Could not create the organization."));
    } finally {
      setBusy(false);
    }
  }
  async function toggle(id: string, enabled: boolean) {
    setError(undefined);
    try {
      await api.setOrganizationEnabled(id, enabled);
      setV((x) => x + 1);
    } catch (err) {
      setError(errText(err, "Could not update the organization."));
    }
  }

  return (
    <>
      <PageHeader title="Organizations" subtitle="Approved customer tenants. A tenant must be enabled here and each user approved separately under Members." />
      <section className="panel">
        <h2>Approve a tenant</h2>
        <form className="form-row" onSubmit={(e) => void create(e)}>
          <Field label="Organization name">{(id) => <input id={id} value={name} onChange={(e) => setName(e.target.value)} required />}</Field>
          <Field label="Entra tenant ID" error={tenant && !isGuid(tenant) ? "Enter a tenant GUID." : undefined}>{(id, d) => <input id={id} aria-describedby={d} value={tenant} onChange={(e) => setTenant(e.target.value)} required />}</Field>
          <button className="btn primary" disabled={!valid || busy}>Add organization</button>
        </form>
      </section>
      {error && <ErrorState message={error} />}
      <AsyncView state={state} isEmpty={(d) => d.items.length === 0} emptyTitle="No organizations approved" emptyHint="Add a customer tenant above to begin onboarding.">
        {(d) => (
          <Table caption="Organizations" head={["Name", "Tenant ID", "Status", "Action"]}>
            {d.items.map((o) => (
              <tr key={o.id}>
                <th scope="row">{o.name}</th>
                <td><code>{o.tenant_id}</code></td>
                <td><Badge tone={o.enabled ? "ok" : "neutral"}>{o.enabled ? "enabled" : "disabled"}</Badge></td>
                <td><button className="btn" onClick={() => void toggle(o.id, !o.enabled)}>{o.enabled ? "Disable" : "Enable"}</button></td>
              </tr>
            ))}
          </Table>
        )}
      </AsyncView>
    </>
  );
}

export function MembersPage() {
  const { api } = useSession();
  const orgs = useAsync(() => api.organizations(), [api]);
  const [orgId, setOrgId] = useState("");
  const [v, setV] = useState(0);
  const members = useAsync(() => (orgId ? api.members(orgId) : Promise.resolve({ items: [] as Member[], total: 0 })), [api, orgId, v]);
  const [objectId, setObjectId] = useState("");
  const [role, setRole] = useState<Role>("customer");
  const [error, setError] = useState<string>();
  const valid = !!orgId && isGuid(objectId);

  async function add(e: FormEvent) {
    e.preventDefault();
    setError(undefined);
    try {
      await api.createMember({ organization_id: orgId, object_id: objectId.trim().toLowerCase(), role });
      setObjectId("");
      setV((x) => x + 1);
    } catch (err) {
      setError(errText(err, "Could not add the member."));
    }
  }
  async function toggle(m: Member) {
    setError(undefined);
    try {
      await api.setMemberEnabled(m.id, !m.enabled);
      setV((x) => x + 1);
    } catch (err) {
      setError(errText(err, "Could not update the member."));
    }
  }

  return (
    <>
      <PageHeader title="Members" subtitle="Users are identified by Entra object ID. The IDS administrator role is only valid in the configured IDS home tenant; the backend enforces this." />
      <AsyncView state={orgs} isEmpty={(d) => d.items.length === 0} emptyTitle="Add an organization first" emptyHint="Members belong to an approved organization.">
        {(o) => (
          <>
            <div className="filters">
              <Field label="Organization">{(id) => (
                <select id={id} value={orgId} onChange={(e) => setOrgId(e.target.value)}>
                  <option value="">Select an organization…</option>
                  {o.items.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
                </select>
              )}</Field>
            </div>
            {orgId && (
              <section className="panel">
                <h2>Approve a user</h2>
                <form className="form-row" onSubmit={(e) => void add(e)}>
                  <Field label="User object ID" error={objectId && !isGuid(objectId) ? "Enter an object ID GUID." : undefined}>{(id, d) => <input id={id} aria-describedby={d} value={objectId} onChange={(e) => setObjectId(e.target.value)} required />}</Field>
                  <Field label="Role">{(id) => <select id={id} value={role} onChange={(e) => setRole(e.target.value as Role)}><option value="customer">Customer</option><option value="ids_admin">IDS administrator</option></select>}</Field>
                  <button className="btn primary" disabled={!valid}>Add member</button>
                </form>
              </section>
            )}
            {error && <ErrorState message={error} />}
            {orgId && (
              <AsyncView state={members} isEmpty={(d) => d.items.length === 0} emptyTitle="No approved members" emptyHint="No user can sign in to this organization until approved.">
                {(d) => (
                  <Table caption="Members" head={["Object ID", "Role", "Status", "Action"]}>
                    {d.items.map((m) => (
                      <tr key={m.id}>
                        <th scope="row"><code>{m.object_id}</code></th>
                        <td>{m.role === "ids_admin" ? "IDS administrator" : "Customer"}</td>
                        <td><Badge tone={m.enabled ? "ok" : "neutral"}>{m.enabled ? "enabled" : "disabled"}</Badge></td>
                        <td><button className="btn" onClick={() => void toggle(m)}>{m.enabled ? "Disable" : "Enable"}</button></td>
                      </tr>
                    ))}
                  </Table>
                )}
              </AsyncView>
            )}
          </>
        )}
      </AsyncView>
    </>
  );
}

const SAFETY_LIMIT = 50;

export function SafetyPage() {
  const { api } = useSession();
  const [days, setDays] = useState(30);
  const [orgId, setOrgId] = useState("");
  const [offset, setOffset] = useState(0);
  const orgs = useAsync(() => api.organizations(), [api]);
  const state = useAsync(() => api.safety(days, orgId || undefined, offset, SAFETY_LIMIT), [api, days, orgId, offset]);
  return (
    <>
      <PageHeader title="Safety events" subtitle="Metadata only: category, action and correlation ID. Original prompts and responses are never shown here." />
      <div className="filters">
        <Field label="Period">{(id) => <select id={id} value={days} onChange={(e) => { setDays(Number(e.target.value)); setOffset(0); }}>{[1, 7, 30, 90].map((d) => <option key={d} value={d}>Last {d} day{d > 1 ? "s" : ""}</option>)}</select>}</Field>
        <Field label="Organization">{(id) => (
          <select id={id} value={orgId} onChange={(e) => { setOrgId(e.target.value); setOffset(0); }}>
            <option value="">All organizations</option>
            {orgs.data?.items.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
          </select>
        )}</Field>
      </div>
      <AsyncView state={state} isEmpty={(d) => d.items.length === 0} emptyTitle="No safety events in this period" emptyHint="An empty list means no events were recorded; confirm telemetry ingestion on the usage page.">
        {(d) => (
          <>
            <p className="muted">{d.total.toLocaleString("en-US")} event(s)</p>
            <Table caption="Safety events" head={["Time", "Organization", "Subscription", "Category", "Action", "Correlation ID"]}>
              {d.items.map((e) => (
                <tr key={e.id}>
                  <td>{fmtDate(e.occurred_at)}</td>
                  <td><code>{e.organization_id}</code></td>
                  <td><code>{e.subscription_id}</code></td>
                  <td>{e.category}</td>
                  <td><Badge tone="warn">{e.action}</Badge></td>
                  <td><code>{e.correlation_id}</code></td>
                </tr>
              ))}
            </Table>
            <Pager offset={offset} limit={SAFETY_LIMIT} total={d.total} onChange={setOffset} />
          </>
        )}
      </AsyncView>
    </>
  );
}

const BLANK: Record<keyof PriceInput, string> = {
  model: "", provider: "", region: "", effective_from: "", effective_to: "", currency: "USD",
  input_per_million: "", output_per_million: "", cached_input_per_million: "", cache_write_per_million: "", input_includes_cached: "false",
};

export function validatePrice(f: Record<keyof PriceInput, string>): { ok: true; value: PriceInput } | { ok: false; error: string } {
  if (!f.model.trim() || !f.provider.trim() || !f.region.trim()) return { ok: false, error: "Model, provider and region are required." };
  if (!/^[A-Z]{3}$/.test(f.currency.trim())) return { ok: false, error: "Currency must be a 3-letter ISO code such as USD." };
  if (!f.effective_from) return { ok: false, error: "Effective-from is required." };
  const from = new Date(f.effective_from);
  if (Number.isNaN(from.getTime())) return { ok: false, error: "Effective-from is not a valid date." };
  let to: string | null = null;
  if (f.effective_to) {
    const t = new Date(f.effective_to);
    if (Number.isNaN(t.getTime()) || t <= from) return { ok: false, error: "Effective-to must be after effective-from." };
    to = t.toISOString();
  }
  if (!isDecimal(f.input_per_million) || !isDecimal(f.output_per_million)) return { ok: false, error: "Input and output prices must be non-negative decimals (e.g. 2.50)." };
  for (const k of ["cached_input_per_million", "cache_write_per_million"] as const) {
    if (f[k].trim() && !isDecimal(f[k])) return { ok: false, error: "Cache prices must be blank or non-negative decimals." };
  }
  return {
    ok: true,
    value: {
      model: f.model.trim(), provider: f.provider.trim(), region: f.region.trim(), currency: f.currency.trim(),
      effective_from: from.toISOString(), effective_to: to,
      input_per_million: f.input_per_million.trim(), output_per_million: f.output_per_million.trim(),
      cached_input_per_million: f.cached_input_per_million.trim() || null, cache_write_per_million: f.cache_write_per_million.trim() || null,
      input_includes_cached: f.input_includes_cached === "true",
    },
  };
}

export function PricesPage() {
  const { api } = useSession();
  const [v, setV] = useState(0);
  const state = useAsync(() => api.prices(), [api, v]);
  const [form, setForm] = useState(BLANK);
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [closing, setClosing] = useState<string>();
  const [closeAt, setCloseAt] = useState("");
  const set = (k: keyof PriceInput) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }));

  async function closePeriod(p: Price) {
    const at = new Date(closeAt);
    if (Number.isNaN(at.getTime())) return setError("Choose a valid end date and time.");
    if (at <= new Date(p.effective_from)) return setError("The end must be after the effective-from time.");
    setError(undefined);
    try {
      await api.endPrice(p.id, at.toISOString());
      setClosing(undefined);
      setCloseAt("");
      setV((x) => x + 1);
    } catch (err) {
      setError(errText(err, "Could not close the price period."));
    }
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    const r = validatePrice(form);
    if (!r.ok) return setError(r.error);
    setBusy(true);
    setError(undefined);
    try {
      await api.createPrice(r.value);
      setForm(BLANK);
      setV((x) => x + 1);
    } catch (err) {
      setError(errText(err, "Could not create the price."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="Price configuration" subtitle="Effective-dated prices per million tokens drive estimated showback. Prices are append-only; add a new row to change a rate." />
      <section className="panel">
        <h2>Add an effective-dated price</h2>
        <form onSubmit={(e) => void submit(e)} className="grid-form">
          <Field label="Model">{(id) => <input id={id} value={form.model} onChange={set("model")} />}</Field>
          <Field label="Provider">{(id) => <input id={id} value={form.provider} onChange={set("provider")} />}</Field>
          <Field label="Region">{(id) => <input id={id} value={form.region} onChange={set("region")} />}</Field>
          <Field label="Currency">{(id) => <input id={id} value={form.currency} maxLength={3} onChange={set("currency")} />}</Field>
          <Field label="Effective from">{(id) => <input id={id} type="datetime-local" value={form.effective_from} onChange={set("effective_from")} />}</Field>
          <Field label="Effective to (optional)">{(id) => <input id={id} type="datetime-local" value={form.effective_to} onChange={set("effective_to")} />}</Field>
          <Field label="Input / 1M tokens">{(id) => <input id={id} inputMode="decimal" value={form.input_per_million} onChange={set("input_per_million")} />}</Field>
          <Field label="Output / 1M tokens">{(id) => <input id={id} inputMode="decimal" value={form.output_per_million} onChange={set("output_per_million")} />}</Field>
          <Field label="Cached input / 1M (optional)" hint="Leave blank if unpriced.">{(id, d) => <input id={id} aria-describedby={d} inputMode="decimal" value={form.cached_input_per_million} onChange={set("cached_input_per_million")} />}</Field>
          <Field label="Cache write / 1M (optional)">{(id) => <input id={id} inputMode="decimal" value={form.cache_write_per_million} onChange={set("cache_write_per_million")} />}</Field>
          <Field label="Input tokens include cached?">{(id) => <select id={id} value={form.input_includes_cached} onChange={set("input_includes_cached")}><option value="false">No (reported separately)</option><option value="true">Yes (included in input)</option></select>}</Field>
          <div className="form-actions"><button className="btn primary" disabled={busy}>{busy ? "Saving…" : "Add price"}</button></div>
        </form>
        {error && <p role="alert" className="notice bad">{error}</p>}
      </section>
      <AsyncView state={state} isEmpty={(d) => d.items.length === 0} emptyTitle="No prices configured" emptyHint="Without prices, cost is shown as Unknown (never zero).">
        {(d) => (
          <Table caption="Configured prices" head={["Model", "Provider / region", "Effective", "Input", "Output", "Cached in", "Cache write", "Cached incl.", "Period"]}>
            {d.items.map((p: Price) => (
              <tr key={p.id}>
                <th scope="row">{p.model}</th>
                <td>{p.provider} · {p.region}</td>
                <td>{fmtDate(p.effective_from)} → {p.effective_to ? fmtDate(p.effective_to) : "open"}</td>
                <td className="num">{p.currency} {p.input_per_million}</td>
                <td className="num">{p.currency} {p.output_per_million}</td>
                <td className="num">{p.cached_input_per_million ?? "Not priced"}</td>
                <td className="num">{p.cache_write_per_million ?? "Not priced"}</td>
                <td>{p.input_includes_cached ? "Yes" : "No"}</td>
                <td>
                  {p.effective_to ? <Badge tone="neutral">closed</Badge> : closing === p.id ? (
                    <span className="actions">
                      <input type="datetime-local" aria-label={`End time for ${p.model} price`} value={closeAt} onChange={(e) => setCloseAt(e.target.value)} />
                      <button className="btn danger" onClick={() => void closePeriod(p)}>Confirm close</button>
                      <button className="btn" onClick={() => setClosing(undefined)}>Cancel</button>
                    </span>
                  ) : <button className="btn" onClick={() => { setClosing(p.id); setCloseAt(""); setError(undefined); }}>Close period</button>}
                </td>
              </tr>
            ))}
          </Table>
        )}
      </AsyncView>
    </>
  );
}