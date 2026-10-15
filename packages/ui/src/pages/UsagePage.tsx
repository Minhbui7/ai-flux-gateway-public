import { useEffect, useState } from "react";
import { ApiError } from "../client";
import { useSession } from "../session";
import type { Organization, Paged, UsagePage as UsageData, UsageSeries, UsageSummary } from "../types";
import { UsageCharts } from "../components/UsageCharts";
import { AsyncView, Badge, EmptyState, ErrorState, Field, NA, PageHeader, Pager, Table, downloadBlob, fmtDate, fmtInt, fmtSecondsFromMs, useAsync } from "../components/ui";

const LIMIT = 50;
const DAY_OPTIONS = [1, 7, 30, 90];
const MINUTE_MS = 60_000;

interface Viewport {
  start: number;
  end: number;
}

function initialViewport(days: number): Viewport {
  const end = Math.floor(Date.now() / MINUTE_MS) * MINUTE_MS + MINUTE_MS;
  return { start: end - days * 24 * 60 * MINUTE_MS, end };
}

export function UsagePage({ admin = false }: { admin?: boolean }) {
  const { api } = useSession();
  const [days, setDays] = useState(30);
  const [subscriptionId, setSubscriptionId] = useState("");
  const [orgId, setOrgId] = useState("");
  const [model, setModel] = useState("");
  const [modelNotice, setModelNotice] = useState("");
  const [viewport, setViewport] = useState(() => initialViewport(30));
  const [offset, setOffset] = useState(0);
  const [exportError, setExportError] = useState<string>();
  const [exporting, setExporting] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);

  const orgs = useAsync<Paged<Organization>>(() => (admin ? api.organizations() : Promise.resolve({ items: [], total: 0 })), [api, admin]);
  const subs = useAsync(() => (admin ? Promise.resolve({ items: [], total: 0 }) : api.subscriptions(0, 100)), [api, admin]);
  const scope = JSON.stringify([admin, days, subscriptionId, orgId]);
  const models = useAsync(async () => {
    const q = { days, subscription_id: subscriptionId || undefined, organization_id: orgId || undefined };
    const result = await (admin ? api.adminUsageModels(q) : api.usageModels(q));
    return { scope, ...result };
  }, [api, admin, days, subscriptionId, orgId]);
  const availableModels = !models.loading && !models.error && models.data?.scope === scope ? models.data.items : undefined;
  const modelsReady = availableModels !== undefined;
  const modelRemoved = availableModels !== undefined && model !== "" && !availableModels.includes(model);
  const selectedModel = modelRemoved ? "" : model;
  const filterKey = JSON.stringify([scope, selectedModel, offset]);
  const seriesKey = JSON.stringify([scope, selectedModel, viewport.start, viewport.end]);

  useEffect(() => {
    if (modelRemoved) {
      setModel("");
      setOffset(0);
      setModelNotice(`Model "${model}" has no usage in this scope. Reset to All models.`);
    }
  }, [modelRemoved, model]);

  const state = useAsync(
    async () => {
      const q = { days, offset, limit: LIMIT, subscription_id: subscriptionId || undefined, organization_id: orgId || undefined, model: selectedModel || undefined };
      const data = await (admin ? api.adminUsage(q) : api.usage(q));
      return { key: filterKey, data };
    },
    [api, admin, days, subscriptionId, orgId, selectedModel, offset],
  );
  const seriesState = useAsync<{ key: string; data: UsageSeries }>(
    async () => {
      const q = {
        days,
        subscription_id: subscriptionId || undefined,
        organization_id: orgId || undefined,
        model: selectedModel || undefined,
        start: new Date(viewport.start).toISOString(),
        end: new Date(viewport.end).toISOString(),
      };
      const data = await (admin ? api.adminUsageSeries(q) : api.usageSeries(q));
      return { key: seriesKey, data };
    },
    [api, admin, days, subscriptionId, orgId, selectedModel, viewport.start, viewport.end],
  );

  function resetViewport(rangeDays = days) {
    setViewport(initialViewport(rangeDays));
  }

  function zoom(factor: number) {
    const base = initialViewport(days);
    const width = viewport.end - viewport.start;
    const nextWidth = Math.max(MINUTE_MS, Math.min(base.end - base.start, Math.round(width * factor / MINUTE_MS) * MINUTE_MS));
    const center = (viewport.start + viewport.end) / 2;
    let start = center - nextWidth / 2;
    let end = center + nextWidth / 2;
    if (start < base.start) { end += base.start - start; start = base.start; }
    if (end > base.end) { start -= end - base.end; end = base.end; }
    const alignedStart = Math.floor(Math.max(base.start, start) / MINUTE_MS) * MINUTE_MS;
    setViewport({ start: alignedStart, end: Math.min(base.end, alignedStart + nextWidth) });
  }

  function pan(direction: -1 | 1) {
    const base = initialViewport(days);
    const offset = Math.max(MINUTE_MS, Math.round((viewport.end - viewport.start) * 0.25 / MINUTE_MS) * MINUTE_MS) * direction;
    const span = viewport.end - viewport.start;
    let start = viewport.start + offset;
    let end = viewport.end + offset;
    if (start < base.start) { start = base.start; end = start + span; }
    if (end > base.end) { end = base.end; start = end - span; }
    setViewport({ start, end });
  }

  async function exportCsv() {
    setExporting(true);
    setExportError(undefined);
    try {
      downloadBlob(await api.exportCsv(admin, {
        days, organization_id: orgId || undefined, subscription_id: subscriptionId || undefined, model: selectedModel || undefined,
      }), `aiflux-usage-${admin ? "all" : "org"}-${days}d.csv`);
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
        subtitle="Costs are estimates based on configured list prices. Actual charges may differ due to Singtel-specific discounts. This is not an invoice."
        actions={<button className="btn" onClick={() => void exportCsv()} disabled={exporting || !modelsReady}>{exporting ? "Preparing…" : "Export CSV"}</button>}
      />
      {exportError && <ErrorState message={exportError} />}
      {models.error && <ErrorState message={`Could not load usage models: ${models.error}`} onRetry={models.reload} />}
      {modelNotice && <p role="status" className="notice">{modelNotice}</p>}
      <div className="filters">
        <Field label="Period">{(id) => (
          <select id={id} value={days} onChange={(e) => { const next = Number(e.target.value); setModelNotice(""); setDays(next); setOffset(0); resetViewport(next); }}>
            {DAY_OPTIONS.map((d) => <option key={d} value={d}>Last {d} day{d > 1 ? "s" : ""}</option>)}
          </select>
        )}</Field>
        {admin ? (
          <Field label="Organization">{(id) => (
            <select id={id} value={orgId} onChange={(e) => { setModelNotice(""); setOrgId(e.target.value); setOffset(0); resetViewport(); }}>
              <option value="">All organizations</option>
              {orgs.data?.items.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
            </select>
          )}</Field>
        ) : (
          <Field label="Subscription">{(id) => (
            <select id={id} value={subscriptionId} onChange={(e) => { setModelNotice(""); setSubscriptionId(e.target.value); setOffset(0); resetViewport(); }}>
              <option value="">All subscriptions</option>
              {subs.data?.items.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          )}</Field>
        )}
        <Field label="Model">{(id) => (
          <select id={id} value={selectedModel} disabled={!modelsReady} onChange={(e) => { setModel(e.target.value); setModelNotice(""); setOffset(0); resetViewport(); }}>
            <option value="">All models</option>
            {!modelsReady && selectedModel && <option value={selectedModel}>{selectedModel}</option>}
            {availableModels?.map((name) => <option key={name} value={name}>{name}</option>)}
          </select>
        )}</Field>
      </div>
      <section className="usage-chart-section" aria-labelledby="usage-chart-heading">
        <div className="usage-chart-head">
          <div><h2 id="usage-chart-heading">Usage over time</h2><p className="muted">UTC minute aggregates across the selected period; independent of request-table pagination.</p></div>
          <div className="chart-controls" role="group" aria-label="Shared chart viewport controls">
            <button className="btn" onClick={() => zoom(0.5)} disabled={viewport.end - viewport.start <= MINUTE_MS}>Zoom in</button>
            <button className="btn" onClick={() => zoom(2)} disabled={viewport.end - viewport.start >= days * 24 * 60 * MINUTE_MS}>Zoom out</button>
            <button className="btn" onClick={() => pan(-1)} disabled={viewport.start <= initialViewport(days).start}>Pan earlier</button>
            <button className="btn" onClick={() => pan(1)} disabled={viewport.end >= initialViewport(days).end}>Pan later</button>
            <button className="btn" onClick={() => resetViewport()} aria-label="Reset chart zoom and pan">Reset</button>
          </div>
        </div>
        <p className="muted chart-range">Viewport: {new Date(viewport.start).toISOString().replace("T", " ").slice(0, 16)} – {new Date(viewport.end).toISOString().replace("T", " ").slice(0, 16)} UTC</p>
        {!modelsReady ? <p role="status" className="muted">Waiting for usage model options.</p>
          : <AsyncView state={{ ...seriesState, data: seriesState.data?.key === seriesKey ? seriesState.data.data : undefined }}>
            {(series) => <UsageCharts series={series} start={viewport.start} end={viewport.end} />}
          </AsyncView>}
      </section>
      {modelsReady && <AsyncView state={{ ...state, data: state.data?.key === filterKey ? state.data.data : undefined }}>
        {(d) => <UsageBody data={d} offset={offset} onPage={setOffset} showOrgNote={admin} detailsOpen={detailsOpen} onDetailsToggle={setDetailsOpen} />}
      </AsyncView>}
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
    : { value: v, note: "Estimated from configured list prices." };
}

function UsageBody({ data, offset, onPage, showOrgNote, detailsOpen, onDetailsToggle }: {
  data: UsageData;
  offset: number;
  onPage: (o: number) => void;
  showOrgNote: boolean;
  detailsOpen: boolean;
  onDetailsToggle: (open: boolean) => void;
}) {
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
        <Stat label="End-to-end p95" value={fmtSecondsFromMs(s.e2e_p95_ms)} note={s.e2e_p95_ms === null ? "Not available" : "Gateway end-to-end latency"} />
        <Stat label="Time to first token" value={s.ttft_supported ? "Supported" : "Unavailable"} note={s.ttft_supported ? undefined : "Not natively measurable for all callers"} />
        <Stat label="Cache tokens" value={s.cache_tokens_supported ? "Supported" : "Unavailable"} note={s.cache_tokens_supported ? undefined : "Not natively reported for all callers"} />
        <Stat label="Last ingested" value={fmtDate(s.last_ingested_at)} note={s.last_ingested_at ? "Data may lag the latest requests" : "No telemetry ingested yet"} />
      </dl>
      <details open={detailsOpen} onToggle={(e) => onDetailsToggle(e.currentTarget.open)}>
        <summary>Transaction details</summary>
        {data.items.length === 0 ? (
          <EmptyState title="No requests in this period" hint="Usage appears here after requests are made through the gateway and telemetry is ingested." />
        ) : (
          <>
            {showOrgNote && <p className="muted">Showing requests across organizations.</p>}
            <Table caption="Request usage" head={["Time", "Model", "Region", "Status", "Input", "Output", ...(s.cache_tokens_supported ? ["Cached in", "Cache write"] : []), "Cost", "E2E (s)", ...(s.ttft_supported ? ["TTFT (s)"] : []), "Completeness"]}>
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
                  <td className="num">{fmtSecondsFromMs(r.e2e_ms)}</td>
                  {s.ttft_supported && <td className="num">{r.ttft_ms === null ? NA : fmtSecondsFromMs(r.ttft_ms)}</td>}
                  <td>{r.completeness === "complete" ? <Badge tone="ok">complete</Badge> : <Badge tone="warn">{r.completeness}</Badge>}</td>
                </tr>
              ))}
            </Table>
            <Pager offset={offset} limit={LIMIT} total={data.total} onChange={onPage} />
          </>
        )}
      </details>
    </>
  );
}