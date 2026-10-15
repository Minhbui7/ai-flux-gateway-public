import { useCallback, useEffect, useRef, useState, type DependencyList, type ReactNode } from "react";
import { ApiError } from "../client";

export function BrandMark() {
  return (
    <div className="brand" aria-label="Singtel IDS AIFLUX">
      <svg width="28" height="28" viewBox="0 0 32 32" aria-hidden="true">
        <rect width="32" height="32" rx="8" fill="#14b8a6" />
        <path d="M7 21c4-9 8-9 12-3s5 3 6-6" fill="none" stroke="#06182f" strokeWidth="3" strokeLinecap="round" />
      </svg>
      <span><strong>AIFLUX</strong><small>Singtel IDS</small></span>
    </div>
  );
}

export function useAsync<T>(fn: () => Promise<T>, deps: DependencyList) {
  const [state, setState] = useState<{ data?: T; error?: string; loading: boolean }>({ loading: true });
  const run = useRef(0);
  const load = useCallback(() => {
    const id = ++run.current;
    setState((s) => ({ data: s.data, loading: true }));
    fn().then(
      (data) => id === run.current && setState({ data, loading: false }),
      (e: unknown) => id === run.current && setState({ error: e instanceof ApiError ? e.detail : "Something went wrong.", loading: false }),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => {
    load();
    return () => {
      run.current++;
    };
  }, [load]);
  return { ...state, reload: load };
}

export function AsyncView<T>({ state, children, emptyTitle, emptyHint, isEmpty }: {
  state: { data?: T; error?: string; loading: boolean; reload: () => void };
  children: (data: T) => ReactNode;
  emptyTitle?: string;
  emptyHint?: string;
  isEmpty?: (d: T) => boolean;
}) {
  if (state.error) return <ErrorState message={state.error} onRetry={state.reload} />;
  if (state.data === undefined) return <p role="status" className="muted">Loading…</p>;
  if (isEmpty?.(state.data)) return <EmptyState title={emptyTitle ?? "Nothing here yet"} hint={emptyHint} />;
  return <div aria-busy={state.loading}>{children(state.data)}</div>;
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="state error" role="alert">
      <strong>Something needs attention</strong>
      <p>{message}</p>
      {onRetry && <button className="btn" onClick={onRetry}>Try again</button>}
    </div>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="state empty">
      <strong>{title}</strong>
      {hint && <p>{hint}</p>}
    </div>
  );
}

export function Badge({ tone = "neutral", children }: { tone?: "ok" | "warn" | "bad" | "neutral" | "info"; children: ReactNode }) {
  return <span className={`badge ${tone}`}>{children}</span>;
}

const STATE_TONE = { active: "ok", pending: "warn", suspended: "neutral", failed: "bad" } as const;
export function StateBadge({ state }: { state: keyof typeof STATE_TONE }) {
  return <Badge tone={STATE_TONE[state] ?? "neutral"}>{state}</Badge>;
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <header className="page-head">
      <div>
        <h1 tabIndex={-1}>{title}</h1>
        {subtitle && <p className="muted">{subtitle}</p>}
      </div>
      {actions && <div className="actions">{actions}</div>}
    </header>
  );
}

export function Pager({ offset, limit, total, onChange }: { offset: number; limit: number; total: number; onChange: (offset: number) => void }) {
  if (total <= limit) return null;
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + limit, total);
  return (
    <nav className="pager" aria-label="Pagination">
      <button className="btn" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}>Previous</button>
      <span>{from}–{to} of {total}</span>
      <button className="btn" disabled={offset + limit >= total} onClick={() => onChange(offset + limit)}>Next</button>
    </nav>
  );
}

export function Field({ label, hint, error, children }: { label: string; hint?: string; error?: string; children: (id: string, describedBy: string | undefined) => ReactNode }) {
  const id = useRef(`f-${Math.random().toString(36).slice(2, 9)}`).current;
  const desc = hint || error ? `${id}-d` : undefined;
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {children(id, desc)}
      {(hint || error) && <small id={desc} className={error ? "field-error" : "muted"}>{error ?? hint}</small>}
    </div>
  );
}

export function Table({ caption, head, children }: { caption: string; head: string[]; children: ReactNode }) {
  return (
    <div className="table-wrap" tabIndex={0} role="region" aria-label={caption}>
      <table>
        <caption className="sr-only">{caption}</caption>
        <thead><tr>{head.map((h) => <th key={h} scope="col">{h}</th>)}</tr></thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

export const NA = "—";
export const fmtInt = (n: number | null | undefined) => (n === null || n === undefined ? NA : n.toLocaleString("en-US"));
export const fmtMs = (n: number | null | undefined) => (n === null || n === undefined ? NA : `${Math.round(n).toLocaleString("en-US")} ms`);
export const fmtSecondsFromMs = (n: number | null | undefined) =>
  n === null || n === undefined ? NA : `${(n / 1000).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 3 })} s`;
export const fmtDate = (s: string | null | undefined) => {
  if (!s) return NA;
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? s : d.toLocaleString();
};

export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}