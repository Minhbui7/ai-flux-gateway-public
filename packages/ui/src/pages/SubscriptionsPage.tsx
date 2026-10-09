import { useRef, useState, type FormEvent } from "react";
import { ApiError } from "../client";
import { useSession } from "../session";
import type { KeyName, Subscription } from "../types";
import { AsyncView, Badge, ErrorState, Field, PageHeader, Pager, StateBadge, fmtDate, useAsync } from "../components/ui";

const LIMIT = 25;

export function SubscriptionsPage() {
  const { api } = useSession();
  const [offset, setOffset] = useState(0);
  const [version, setVersion] = useState(0);
  const state = useAsync(() => api.subscriptions(offset, LIMIT), [api, offset, version]);
  return (
    <>
      <PageHeader title="Team subscriptions" subtitle="Each subscription has primary and secondary keys. Keys are shown only when you reveal them and are never stored." />
      <CreateForm onCreated={() => { setOffset(0); setVersion((v) => v + 1); }} />
      <AsyncView state={state} isEmpty={(d) => d.items.length === 0} emptyTitle="No subscriptions yet" emptyHint="Create a team subscription above to get your first API keys.">
        {(d) => (
          <>
            <ul className="cards">
              {d.items.map((s) => <SubscriptionCard key={s.id} sub={s} onChanged={() => setVersion((v) => v + 1)} />)}
            </ul>
            <Pager offset={offset} limit={LIMIT} total={d.total} onChange={setOffset} />
          </>
        )}
      </AsyncView>
    </>
  );
}

function CreateForm({ onCreated }: { onCreated: () => void }) {
  const { api } = useSession();
  const [name, setName] = useState("");
  const [team, setTeam] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [created, setCreated] = useState<Subscription>();
  // One idempotency key per logical submission; retries after an error reuse it.
  const idem = useRef<string>(crypto.randomUUID());

  const nameErr = name.length > 0 && name.trim().length < 3 ? "Use at least 3 characters." : undefined;
  const valid = name.trim().length >= 3 && team.trim().length >= 2;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!valid) return;
    setBusy(true);
    setError(undefined);
    try {
      const sub = await api.createSubscription({ name: name.trim(), team: team.trim() }, idem.current);
      setCreated(sub);
      setName("");
      setTeam("");
      idem.current = crypto.randomUUID();
      onCreated();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Could not create the subscription.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel" aria-labelledby="create-h">
      <h2 id="create-h">New subscription</h2>
      <form onSubmit={(e) => void submit(e)} className="form-row">
        <Field label="Name" error={nameErr}>{(id, d) => <input id={id} aria-describedby={d} value={name} maxLength={80} onChange={(e) => setName(e.target.value)} required />}</Field>
        <Field label="Team">{(id) => <input id={id} value={team} maxLength={80} onChange={(e) => setTeam(e.target.value)} required />}</Field>
        <button className="btn primary" disabled={!valid || busy}>{busy ? "Creating…" : "Create subscription"}</button>
      </form>
      {error && <ErrorState message={error} />}
      {created && (
        <p role="status" className="notice">
          “{created.name}” was submitted and is <StateBadge state={created.state} />.
          {created.state === "pending" && " Provisioning is in progress; use Reconcile on the card to refresh."}
          {created.state === "failed" && " Provisioning failed; use Reconcile to retry, or contact IDS."}
        </p>
      )}
    </section>
  );
}

function SubscriptionCard({ sub, onChanged }: { sub: Subscription; onChanged: () => void }) {
  const { api, keys, setKey, clearKeys } = useSession();
  const [busy, setBusy] = useState<string>();
  const [msg, setMsg] = useState<{ tone: "ok" | "bad"; text: string }>();
  const [visible, setVisible] = useState<Partial<Record<KeyName, boolean>>>({});
  const revealed = keys[sub.id] ?? {};

  async function act(label: string, fn: () => Promise<string | void>) {
    setBusy(label);
    setMsg(undefined);
    try {
      const text = await fn();
      if (text) setMsg({ tone: "ok", text });
    } catch (e) {
      setMsg({ tone: "bad", text: e instanceof ApiError ? e.detail : "The action failed." });
    } finally {
      setBusy(undefined);
    }
  }

  const reveal = (k: KeyName) => act(`reveal-${k}`, async () => {
    setKey(sub.id, k, await api.revealKey(sub.id, k));
    setVisible((v) => ({ ...v, [k]: false }));
    return `${k} key revealed. It is held in memory only until you hide it or sign out.`;
  });
  const rotate = (k: KeyName) => {
    if (!window.confirm(`Rotate the ${k} key? Clients using the current ${k} key will stop working.`)) return;
    return act(`rotate-${k}`, async () => {
      const r = await api.rotateKey(sub.id, k);
      clearKeys(sub.id);
      onChanged();
      return r.state === "active" ? `${k} key rotated. Reveal it again to get the new value.` : `Rotation returned state “${r.state}”. Use Reconcile and then reveal the new key.`;
    });
  };
  const setState = (s: "active" | "suspended") => act(`state-${s}`, async () => { await api.setState(sub.id, s); onChanged(); return `Subscription ${s === "active" ? "activated" : "suspended"}.`; });
  const reconcile = () => act("reconcile", async () => { const r = await api.reconcile(sub.id); onChanged(); return `Reconciled: state is ${r.state}.`; });
  const copy = (v: string) => act("copy", async () => { await navigator.clipboard.writeText(v); return "Copied to clipboard."; });

  return (
    <li className="card">
      <div className="card-head">
        <div>
          <h2>{sub.name}</h2>
          <p className="muted">Team {sub.team} · created {fmtDate(sub.created_at)}</p>
        </div>
        <StateBadge state={sub.state} />
      </div>
      {sub.state === "failed" && <p className="notice bad">Provisioning failed. Reconcile to retry or contact IDS.</p>}
      {sub.state === "pending" && <p className="notice">Provisioning is pending. Keys are unavailable until the subscription is active.</p>}
      <div className="keys">
        {(["primary", "secondary"] as KeyName[]).map((k) => (
          <div key={k} className="key-row">
            <span className="key-label">{k} key</span>
            {revealed[k] ? (
              <>
                <code aria-label={`${k} key value`}>{visible[k] ? revealed[k] : "•".repeat(24)}</code>
                <button className="btn" aria-pressed={!!visible[k]} onClick={() => setVisible((v) => ({ ...v, [k]: !v[k] }))}>{visible[k] ? "Mask" : "Show"}</button>
                <button className="btn" onClick={() => void copy(revealed[k]!)}>Copy</button>
                <button className="btn" onClick={() => clearKeys(sub.id)}>Hide</button>
              </>
            ) : (
              <button className="btn" disabled={sub.state !== "active" || !!busy} onClick={() => void reveal(k)}>Reveal</button>
            )}
            <button className="btn danger" disabled={sub.state !== "active" || !!busy} onClick={() => void rotate(k)}>Rotate</button>
          </div>
        ))}
      </div>
      <div className="actions">
        {sub.state === "active" && <button className="btn" disabled={!!busy} onClick={() => void setState("suspended")}>Suspend</button>}
        {sub.state === "suspended" && <button className="btn" disabled={!!busy} onClick={() => void setState("active")}>Activate</button>}
        <button className="btn" disabled={!!busy} onClick={() => void reconcile()}>Reconcile</button>
        {busy && <Badge tone="info">Working…</Badge>}
      </div>
      {msg && <p role={msg.tone === "bad" ? "alert" : "status"} className={`notice ${msg.tone === "bad" ? "bad" : ""}`}>{msg.text}</p>}
    </li>
  );
}
