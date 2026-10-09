import { useState } from "react";
import { ApiError } from "../client";
import { useSession } from "../session";
import type { Organization, Paged, UsagePage as UsageData, UsageSummary } from "../types";
import { AsyncView, Badge, EmptyState, ErrorState, Field, NA, PageHeader, Pager, Table, downloadBlob, fmtDate, fmtInt, fmtMs, useAsync } from "../components/ui";

const LIMIT = 50;
const DAY_OPTIONS = [1, 7, 30, 90];

export function UsagePage({ admin = false }: { admin?: boolean }) {
  const { api } = useSession();
  const [days, setDays] = useState(30);
  const [subscriptionId, setSubscriptionId] = useState("");
  const [orgId, setOrgId] = useState("");
  const [offset, setOffset] = useState(0);
  const [exportError, setExportError] = useState<string>();
  const [exporting, setExporting] = useState(false);

  const orgs = useAsync<Paged<Organization>>(() => (admin ? api.organizations() : Promise.resolve({ items: [], total: 0 })), [api, admin]);
  const subs = useAsync(() => (admin ? Promise.resolve({ items: [], total: 0 }) : api.subscriptions(0, 100)), [api, admin]);
  const state = useAsync(
    () => {
      const q = { days, offset, limit: LIMIT, subscription_id: subscriptionId || undefined, organization_id: orgId || undefined };
      return admin ? api.adminUsage(q) : api.usage(q);
    },
    [api, admin, days, subscriptionId, orgId, offset],
  );

  async function exportCsv() {
    setExporting(true);
    setExportError(undefined);
    try {
      downloadBlob(await api.exportCsv(admin, days, orgId || undefined), `aiflux-usage-${admin ? "all" : "org"}-${days}d.csv`);
    } catch (e) {
      setExportError(e instanceof ApiError ? e.detail : "Export failed.");
    } finally {
      setExporting(false);
    }
  }

  return (
    <>
      <PageHeader
        title={admin ? "Cross-organization showback" : "Usage & estimated cost"}
        subtitle="Estimated showback from gateway telemetry and IDS-configured prices. It is not an invoice."
        actions={<button className="btn" onClick={() => void exportCsv()} disabled={exporting}>{exporting ? "Preparing…" : "Export CSV"}</button>}
      />
      {exportError && <ErrorState message={exportError} />}
      <div className="filters">
        <Field label="Period">{(id) => (
          <select id={id} value={days} onChange={(e) => { setDays(Number(e.target.value)); setOffset(0); }}>
            {DAY_OPTIONS.map((d) => <option key={d} value={d}>Last {d} day{d > 1 ? "s" : ""}</option>)}
          </select>
        )}</Field>
        {admin ? (
          <Field label="Organization">{(id) => (
            <select id={id} value={orgId} onChange={(e) => { setOrgId(e.target.value); setOffset(0); }}>
              <option value="">All organizations</option>
              {orgs.data?.items.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
            </select>
          )}</Field>
        ) : (
          <Field label="Subscription">{(id) => (
            <select id={id} value={subscriptionId} onChange={(e) => { setSubscriptionId(e.target.value); setOffset(0); }}>
              <option value="">All subscriptions</option>
              {subs.data?.items.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          )}</Field>
        )}
      </div>
      <AsyncView state={state}>
        {(d) => <UsageBody data={d} offset={offset} onPage={setOffset} showOrgNote={admin} />}
      </AsyncView>
    </>
  );
}

function Stat({ label, value, note, tone }: { label: string; value: string; note?: string; tone?: "warn" | "bad" }) {
  return (
    <div className={`stat ${tone ?? ""}`}>
      <dt>{label}</dt>
      <dd>{value}</dd>
      {note && <small>{note}</small>}
    </div>
  );
}

export function costLabel(s: UsageSummary): { value: string; note: string; tone?: "warn" } {
  if (s.known_cost === null) return { value: "Unknown", note: "No priced usage available. This is not zero.", tone: "warn" };
  const v = s.currency ? `${s.currency} ${s.known_cost}` : s.known_cost;
  return s.incomplete_requests > 0
    ? { value: v, note: `Lower bound: ${fmtInt(s.incomplete_requests)} request(s) lack complete usage or pricing.`, tone: "warn" }
    : { value: v, note: "Estimated from configured prices." };
}

function UsageBody({ data, offset, onPage, showOrgNote }: { data: UsageData; offset: number; onPage: (o: number) => void; showOrgNote: boolean }) {
  const s = data.summary;
  const cost = costLabel(s);
  return (
    <>
      {s.incomplete_requests > 0 && (
        <p className="notice" role="status">
          <Badge tone="warn">Incomplete</Badge> {fmtInt(s.incomplete_requests)} request(s) have missing token usage or pricing. Totals exclude them and are not complete.
        </p>
      )}
      <dl className="stats">
        <Stat label="Requests" value={fmtInt(s.requests)} />
        <Stat label="Input tokens" value={fmtInt(s.input_tokens)} />
        <Stat label="Output tokens" value={fmtInt(s.output_tokens)} />
        <Stat label="Known cost (estimated)" value={cost.value} note={cost.note} tone={cost.tone} />
        <Stat label="Failed requests" value={fmtInt(s.failed_requests)} tone={s.failed_requests > 0 ? "bad" : undefined} />
        <Stat label="Throttled requests" value={fmtInt(s.throttled_requests)} tone={s.throttled_requests > 0 ? "warn" : undefined} />
        <Stat label="End-to-end p95" value={fmtMs(s.e2e_p95_ms)} note={s.e2e_p95_ms === null ? "Not available" : "Gateway end-to-end latency"} />
        <Stat label="Time to first token" value={s.ttft_supported ? "Supported" : "Unavailable"} note={s.ttft_supported ? undefined : "Not natively measurable for all callers"} />
        <Stat label="Cache tokens" value={s.cache_tokens_supported ? "Supported" : "Unavailable"} note={s.cache_tokens_supported ? undefined : "Not natively reported for all callers"} />
        <Stat label="Last ingested" value={fmtDate(s.last_ingested_at)} note={s.last_ingested_at ? "Data may lag the latest requests" : "No telemetry ingested yet"} />
      </dl>
      {data.items.length === 0 ? (
        <EmptyState title="No requests in this period" hint="Usage appears here after requests are made through the gateway and telemetry is ingested." />
      ) : (
        <>
          {showOrgNote && <p className="muted">Showing requests across organizations.</p>}
          <Table caption="Request usage" head={["Time", "Model", "Region", "Status", "Input", "Output", ...(s.cache_tokens_supported ? ["Cached in", "Cache write"] : []), "Cost", "E2E", ...(s.ttft_supported ? ["TTFT"] : []), "Completeness"]}>
            {data.items.map((r) => (
              <tr key={r.id}>
                <td>{fmtDate(r.occurred_at)}</td>
                <td>{r.model}<small className="muted block">{r.provider}</small></td>
                <td>{r.region}</td>
                <td><Badge tone={r.status_code < 400 ? "ok" : r.status_code === 429 ? "warn" : "bad"}>{r.status_code}</Badge></td>
                <td className="num">{fmtInt(r.input_tokens)}</td>
                <td className="num">{fmtInt(r.output_tokens)}</td>
                {s.cache_tokens_supported && <td className="num">{fmtInt(r.cached_input_tokens)}</td>}
                {s.cache_tokens_supported && <td className="num">{fmtInt(r.cache_write_tokens)}</td>}
                <td className="num">{r.cost === null ? <span title="Usage or price missing; not zero">Unknown</span> : `${r.currency ?? ""} ${r.cost}`.trim()}</td>
                <td className="num">{fmtMs(r.e2e_ms)}</td>
                {s.ttft_supported && <td className="num">{r.ttft_ms === null ? NA : fmtMs(r.ttft_ms)}</td>}
                <td>{r.completeness === "complete" ? <Badge tone="ok">complete</Badge> : <Badge tone="warn">{r.completeness}</Badge>}</td>
              </tr>
            ))}
          </Table>
          <Pager offset={offset} limit={LIMIT} total={data.total} onChange={onPage} />
        </>
      )}
    </>
  );
}