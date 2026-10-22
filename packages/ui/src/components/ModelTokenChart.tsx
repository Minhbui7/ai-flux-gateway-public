import { useId, useMemo, useState, type CSSProperties, type KeyboardEvent } from "react";
import type { ModelTokenBucket, ModelTokenSeries } from "../types";
import { fmtInt, NA } from "./ui";

const COLORS = ["accent", "link", "success", "warning", "danger", "text-soft"];
const EPOCH = Date.UTC(2000, 0, 1);
const WIDTH = 920, HEIGHT = 240, LEFT = 64, RIGHT = 16, TOP = 16, BOTTOM = 34;
const timeLabel = (time: number) => `${new Date(time).toISOString().slice(0, 16).replace("T", " ")} UTC`;
const modelLabel = (model: string) => model.trim() || "Unknown model";
const tokenLabel = (item: ModelTokenBucket | undefined) => item
  ? `${item.total_tokens === null ? NA : fmtInt(item.total_tokens)}${item.missing_token_requests ? " (partial)" : ""}`
  : "0";

export function ModelTokenChart({ series }: { series: ModelTokenSeries }) {
  const id = useId().replace(/:/g, "");
  const [selected, setSelected] = useState(0);
  const { models, buckets } = useMemo(() => {
    const models = [...new Set(series.items.map(item => item.model))].sort();
    const start = Date.parse(series.start), end = Date.parse(series.end);
    const interval = series.interval_seconds * 1000;
    const first = EPOCH + Math.floor((start - EPOCH) / interval) * interval;
    const rows = new Map<number, Map<string, ModelTokenBucket>>();
    for (const item of series.items) {
      const time = Date.parse(item.start);
      if (!rows.has(time)) rows.set(time, new Map());
      rows.get(time)!.set(item.model, item);
    }
    const buckets = Array.from({ length: Math.ceil((end - first) / interval) }, (_, index) => {
      const from = Math.max(start, first + index * interval);
      const items = rows.get(from) ?? new Map<string, ModelTokenBucket>();
      return {
        start: from, end: Math.min(end, first + (index + 1) * interval), items,
        total: [...items.values()].reduce((sum, item) => sum + (item.total_tokens ?? 0), 0),
        missing: [...items.values()].reduce((sum, item) => sum + item.missing_token_requests, 0),
      };
    });
    return { models, buckets };
  }, [series]);
  const cursor = Math.min(selected, buckets.length - 1);
  const bucket = buckets[cursor];
  const max = Math.max(1, ...buckets.map(item => item.total));
  const plotHeight = HEIGHT - TOP - BOTTOM, plotWidth = WIDTH - LEFT - RIGHT;
  const step = plotWidth / buckets.length;
  const styleFor = (index: number): CSSProperties => ({ color: `var(--cp-${COLORS[index % COLORS.length]})` });
  const fillFor = (index: number) => `url(#${id}-model-${index})`;
  const onKeyDown = (event: KeyboardEvent<SVGSVGElement>) => {
    const next = event.key === "Home" ? 0 : event.key === "End" ? buckets.length - 1
      : ["ArrowLeft", "ArrowDown"].includes(event.key) ? cursor - 1
        : ["ArrowRight", "ArrowUp"].includes(event.key) ? cursor + 1 : undefined;
    if (next !== undefined) { event.preventDefault(); setSelected(Math.max(0, Math.min(buckets.length - 1, next))); }
  };
  const intervalUnit = series.interval_seconds < 3600 ? "minute" : series.interval_seconds < 86400 ? "hour" : "day";
  const intervalCount = series.interval_seconds / (intervalUnit === "minute" ? 60 : intervalUnit === "hour" ? 3600 : 86400);
  const intervalText = `${intervalCount} ${intervalUnit}${intervalCount === 1 ? "" : "s"}`;
  const selectedText = bucket ? `${timeLabel(bucket.start)} to ${timeLabel(bucket.end)}: ${fmtInt(bucket.total)} known tokens${bucket.missing ? " (partial)" : ""}; ${models.map(model => `${modelLabel(model)}: ${tokenLabel(bucket.items.get(model))}`).join("; ")}` : "";
  const missing = series.items.reduce((sum, item) => sum + item.missing_token_requests, 0);

  return <section className="chart-panel model-token-chart" aria-labelledby={`${id}-title`}>
    <h2 id={`${id}-title`}>Token consumption by model</h2>
    <p className="muted">Input + output tokens per bucket · {intervalText} · UTC</p>
    {missing > 0 && <p role="status" className="notice">Partial data: {fmtInt(missing)} request(s) lack complete token usage. Bars show known totals only, not zero usage for missing measurements.</p>}
    {!series.items.length ? <p>No token usage in this viewport.</p> : <>
      <ul className="model-token-legend" aria-label="Model legend">{models.map((model, index) =>
        <li key={model}><svg width="16" height="16" aria-hidden="true" style={styleFor(index)}><rect width="16" height="16" fill={fillFor(index)} /></svg>{modelLabel(model)}</li>)}</ul>
      <svg className="usage-chart" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="slider" tabIndex={0}
        aria-label="Token consumption by model chart. Use arrow keys to select a time bucket, Home for the first and End for the last."
        aria-valuemin={0} aria-valuemax={buckets.length - 1} aria-valuenow={cursor} aria-valuetext={selectedText}
        onKeyDown={onKeyDown}
        onMouseMove={event => {
          const bounds = event.currentTarget.getBoundingClientRect();
          if (bounds.width) setSelected(Math.max(0, Math.min(buckets.length - 1, Math.floor(((event.clientX - bounds.left) / bounds.width * WIDTH - LEFT) / step))));
        }}>
        <title>Known total tokens over time, stacked by model. Exact values are available below.</title>
        <defs>{models.map((model, index) => <pattern key={model} id={`${id}-model-${index}`} width="8" height="8" patternUnits="userSpaceOnUse">
          <rect width="8" height="8" fill="currentColor" style={styleFor(index)} />
          {Math.floor(index / COLORS.length) % 3 === 1 && <path d="M0 8L8 0" className="model-token-pattern" />}
          {Math.floor(index / COLORS.length) % 3 === 2 && <circle cx="4" cy="4" r="1.5" className="model-token-pattern" />}
        </pattern>)}</defs>
        {[0, .5, 1].map(fraction => <g key={fraction}>
          <line className="chart-grid" x1={LEFT} x2={WIDTH - RIGHT} y1={TOP + plotHeight * fraction} y2={TOP + plotHeight * fraction} />
          <text className="chart-axis-label" x={LEFT - 6} y={TOP + plotHeight * fraction + 4} textAnchor="end">{new Intl.NumberFormat("en", { notation: "compact" }).format(max * (1 - fraction))}</text>
        </g>)}
        {buckets.map((item, bucketIndex) => {
          let accumulated = 0;
          return <g key={item.start} data-bucket-total={item.total}>{models.map((model, modelIndex) => {
            const tokens = item.items.get(model)?.total_tokens ?? 0;
            accumulated += tokens;
            return tokens > 0 && <rect key={model} data-model={model} data-tokens={tokens}
              x={LEFT + bucketIndex * step + step * .1} y={TOP + plotHeight * (1 - accumulated / max)}
              width={step * .8} height={plotHeight * tokens / max} fill={fillFor(modelIndex)}>
              <title>{modelLabel(model)}: {fmtInt(tokens)} tokens{item.items.get(model)?.missing_token_requests ? " (partial)" : ""}</title>
            </rect>;
          })}</g>;
        })}
        <rect className="model-token-cursor" x={LEFT + cursor * step} y={TOP} width={step} height={plotHeight} />
        <text className="chart-axis-label" x={LEFT} y={HEIGHT - 8}>{timeLabel(Date.parse(series.start))}</text>
        <text className="chart-axis-label" x={WIDTH - RIGHT} y={HEIGHT - 8} textAnchor="end">{timeLabel(Date.parse(series.end))}</text>
      </svg>
      <p className="chart-tooltip" role="status" aria-live="polite">{selectedText}</p>
      <details className="chart-data">
        <summary>View exact model token data</summary>
        <div className="table-wrap"><table>
          <caption className="sr-only">Known token consumption by model and UTC bucket</caption>
          <thead><tr><th scope="col">UTC bucket</th>{models.map(model => <th scope="col" key={model}>{modelLabel(model)}</th>)}<th scope="col">Known total</th><th scope="col">Missing usage</th></tr></thead>
          <tbody>{buckets.map(item => <tr key={item.start}><th scope="row">{timeLabel(item.start)} – {timeLabel(item.end)}</th>
            {models.map(model => <td className="num" key={model}>{tokenLabel(item.items.get(model))}</td>)}
            <td className="num">{fmtInt(item.total)}{item.missing ? " (partial)" : ""}</td><td>{fmtInt(item.missing)} request(s)</td>
          </tr>)}</tbody>
        </table></div>
      </details>
    </>}
  </section>;
}
