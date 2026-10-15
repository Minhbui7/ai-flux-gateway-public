import { useEffect, useMemo, useState, type KeyboardEvent, type MouseEvent } from "react";
import type { UsageMinute, UsageSeries } from "../types";
import { fmtInt, NA } from "./ui";

const MINUTE_MS = 60_000;
const CHART_WIDTH = 920;
const CHART_HEIGHT = 190;
const PADDING = { left: 48, right: 16, top: 16, bottom: 30 };
const TABLE_PAGE_SIZE = 25;
type Metric = "requests" | "tokens" | "latency";

interface Props {
  series: UsageSeries;
  start: number;
  end: number;
}

interface ChartDataProps extends Props {
  points: Map<number, UsageMinute>;
}

function minuteKey(value: string): number {
  return Math.floor(new Date(value).getTime() / MINUTE_MS) * MINUTE_MS;
}

function valueFor(point: UsageMinute | undefined, metric: Metric): number | null {
  if (!point) return metric === "latency" ? null : 0;
  if (metric === "requests") return point.requests;
  if (metric === "tokens") return point.total_tokens;
  return point.avg_e2e_seconds;
}

function formatMetric(value: number | null, metric: Metric, point?: UsageMinute): string {
  if (metric === "requests") return fmtInt(value);
  if (metric === "tokens") {
    if (value === null) return point?.requests ? `Missing (${fmtInt(point.missing_token_requests)} request(s))` : NA;
    return `${fmtInt(value)}${point?.missing_token_requests ? " (partial)" : ""}`;
  }
  return value === null ? "No latency samples" : `${value.toFixed(3)} s`;
}

function metricTitle(metric: Metric): string {
  if (metric === "requests") return "Requests per minute";
  if (metric === "tokens") return "Tokens per minute";
  return "Average end-to-end latency per minute (seconds)";
}

function buildEnvelope(series: UsageSeries, metric: Metric, start: number, end: number) {
  const range = Math.max(MINUTE_MS, end - start);
  const minuteCount = Math.max(1, Math.ceil(range / MINUTE_MS));
  const bucketCount = Math.min(900, minuteCount);
  const buckets = Array.from({ length: bucketCount }, () => ({ values: [] as number[], rows: 0 }));
  for (const point of series.items) {
    const time = minuteKey(point.minute);
    if (time < start || time >= end) continue;
    const index = Math.min(bucketCount - 1, Math.max(0, Math.floor(((time - start) / range) * bucketCount)));
    const bucket = buckets[index]!;
    bucket.rows++;
    const value = valueFor(point, metric);
    if (value !== null && Number.isFinite(value)) bucket.values.push(value);
  }
  if (metric !== "latency") {
    buckets.forEach((bucket, index) => {
      const from = Math.floor((index / bucketCount) * minuteCount);
      const to = Math.min(minuteCount, Math.ceil(((index + 1) / bucketCount) * minuteCount));
      if (bucket.rows < to - from) bucket.values.push(0);
    });
  }
  return buckets;
}

function timeLabel(epoch: number): string {
  return `${new Date(epoch).toISOString().slice(0, 16).replace("T", " ")} UTC`;
}

function MinuteTable({ start, end, metric, points }: ChartDataProps & { metric: Metric }) {
  const [page, setPage] = useState(0);
  const count = Math.max(1, Math.ceil((end - start) / MINUTE_MS));
  const pageCount = Math.ceil(count / TABLE_PAGE_SIZE);
  useEffect(() => setPage(0), [start, end, metric]);
  const rows = useMemo(() => {
    const first = page * TABLE_PAGE_SIZE;
    return Array.from({ length: Math.min(TABLE_PAGE_SIZE, count - first) }, (_, index) => {
      const time = start + (first + index) * MINUTE_MS;
      const point = points.get(time);
      return { time, point, value: valueFor(point, metric) };
    });
  }, [points, start, count, page, metric]);
  return (
    <details className="chart-data">
      <summary>View exact minute data</summary>
      <div className="table-wrap">
        <table>
          <caption className="sr-only">{metricTitle(metric)} minute data</caption>
          <thead><tr><th scope="col">UTC minute</th><th scope="col">Value</th><th scope="col">Data quality</th></tr></thead>
          <tbody>{rows.map((row) => (
            <tr key={row.time}>
              <td>{timeLabel(row.time)}</td>
              <td className="num">{formatMetric(row.value, metric, row.point)}</td>
              <td>{metric === "tokens" && row.point?.missing_token_requests
                ? `${fmtInt(row.point.missing_token_requests)} request(s) missing token usage`
                : metric === "latency" && row.value === null
                  ? "No latency samples"
                  : row.point ? "Measured" : "No requests"}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      <div className="chart-table-pager">
        <button className="btn" disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>Earlier minutes</button>
        <span>{page + 1} of {pageCount}</span>
        <button className="btn" disabled={page + 1 >= pageCount} onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}>Later minutes</button>
      </div>
    </details>
  );
}

function ChartPanel({ series, start, end, metric, points }: ChartDataProps & { metric: Metric }) {
  const [cursor, setCursor] = useState(start);
  const buckets = useMemo(() => buildEnvelope(series, metric, start, end), [series, metric, start, end]);
  useEffect(() => setCursor(start), [start, end]);
  const point = points.get(Math.floor(cursor / MINUTE_MS) * MINUTE_MS);
  const selected = valueFor(point, metric);
  const values = buckets.flatMap((bucket) => bucket.values);
  const maxValue = values.reduce((max, value) => Math.max(max, value), 1);
  const minValue = metric === "latency" && values.length ? values.reduce((min, value) => Math.min(min, value), Infinity) : 0;
  const y = (value: number) => PADDING.top + ((maxValue - value) / (maxValue - minValue || 1)) * (CHART_HEIGHT - PADDING.top - PADDING.bottom);
  const plotWidth = CHART_WIDTH - PADDING.left - PADDING.right;
  const x = (index: number) => PADDING.left + ((index + 0.5) / buckets.length) * plotWidth;
  const ticks = [0, 0.25, 0.5, 0.75, 1];
  const setCursorFromPosition = (event: MouseEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const svgX = rect.width > 0 ? ((event.clientX - rect.left) / rect.width) * CHART_WIDTH : PADDING.left;
    const fraction = (svgX - PADDING.left) / plotWidth;
    const clamped = Math.max(0, Math.min(1, fraction));
    const time = start + clamped * (end - start);
    setCursor(Math.min(end - MINUTE_MS, Math.max(start, Math.floor(time / MINUTE_MS) * MINUTE_MS)));
  };
  const onKeyDown = (event: KeyboardEvent<SVGSVGElement>) => {
    const count = Math.max(0, Math.ceil((end - start) / MINUTE_MS) - 1);
    let next: number | undefined;
    if (event.key === "ArrowLeft" || event.key === "ArrowDown") next = cursor - MINUTE_MS;
    if (event.key === "ArrowRight" || event.key === "ArrowUp") next = cursor + MINUTE_MS;
    if (event.key === "Home") next = start;
    if (event.key === "End") next = start + count * MINUTE_MS;
    if (next !== undefined) {
      event.preventDefault();
      setCursor(Math.max(start, Math.min(end - MINUTE_MS, next)));
    }
  };
  const metricText = formatMetric(selected, metric, point);

  return (
    <section className="chart-panel" aria-labelledby={`${metric}-chart-title`}>
      <h2 id={`${metric}-chart-title`}>{metricTitle(metric)}</h2>
      <svg
        className="usage-chart"
        viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
        role="slider"
        aria-label={`${metricTitle(metric)} chart. Use arrow keys for the previous or next minute, Home for the start, and End for the latest minute.`}
        aria-valuemin={start}
        aria-valuemax={end - MINUTE_MS}
        aria-valuenow={cursor}
        aria-valuetext={`${timeLabel(cursor)}: ${metricText}`}
        tabIndex={0}
        onMouseMove={setCursorFromPosition}
        onFocus={() => setCursor(start)}
        onKeyDown={onKeyDown}
      >
        <title>{metricTitle(metric)}. Downsampled for display; minute values remain exact in the tooltip and data table.</title>
        {ticks.map((fraction) => {
          const gridY = PADDING.top + fraction * (CHART_HEIGHT - PADDING.top - PADDING.bottom);
          const value = maxValue - fraction * (maxValue - minValue);
          return <g key={fraction}><line className="chart-grid" x1={PADDING.left} x2={CHART_WIDTH - PADDING.right} y1={gridY} y2={gridY} /><text className="chart-axis-label" x={PADDING.left - 7} y={gridY + 4} textAnchor="end">{metric === "latency" ? `${value.toFixed(2)}s` : fmtInt(Math.round(value))}</text></g>;
        })}
        {buckets.map((bucket, index) => {
          if (!bucket.values.length) return null;
          const high = bucket.values.reduce((max, value) => Math.max(max, value), -Infinity);
          const low = bucket.values.reduce((min, value) => Math.min(min, value), Infinity);
          return <line key={index} className={`chart-mark ${metric}`} x1={x(index)} x2={x(index)} y1={y(high) - 1} y2={y(low) + 1} />;
        })}
        <line className="chart-cursor" x1={PADDING.left + ((cursor - start) / Math.max(1, end - start)) * plotWidth} x2={PADDING.left + ((cursor - start) / Math.max(1, end - start)) * plotWidth} y1={PADDING.top} y2={CHART_HEIGHT - PADDING.bottom} />
        <text className="chart-axis-label" x={PADDING.left} y={CHART_HEIGHT - 7}>{timeLabel(start)}</text>
        <text className="chart-axis-label" x={CHART_WIDTH - PADDING.right} y={CHART_HEIGHT - 7} textAnchor="end">{timeLabel(end)}</text>
      </svg>
      <p className="chart-tooltip" role="status" aria-live="polite"><strong>{timeLabel(cursor)}</strong>: {metricText}{metric === "tokens" && point?.missing_token_requests ? `; partial, ${fmtInt(point.missing_token_requests)} request(s) missing token usage` : ""}{metric === "latency" && point ? `; ${fmtInt(point.latency_samples)} latency sample(s)` : ""}</p>
      <p className="sr-only">The plot is visually downsampled to preserve peaks over long ranges; the selected minute and exact values are available by keyboard and in the exact minute data table.</p>
      <MinuteTable series={series} start={start} end={end} metric={metric} points={points} />
    </section>
  );
}

export function UsageCharts({ series, start, end }: Props) {
  const points = useMemo(() => new Map(series.items.map((item) => [minuteKey(item.minute), item])), [series.items]);
  return (
    <div className="usage-charts" aria-label="Synchronized usage charts">
      <ChartPanel series={series} start={start} end={end} metric="requests" points={points} />
      <ChartPanel series={series} start={start} end={end} metric="tokens" points={points} />
      <ChartPanel series={series} start={start} end={end} metric="latency" points={points} />
    </div>
  );
}
