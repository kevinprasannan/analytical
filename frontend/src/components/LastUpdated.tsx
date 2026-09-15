/** A small, shared "data freshness" line for every screen (docs/08 §3).
 *
 * Pass the screen's primary TanStack Query result (or several). It shows how
 * long ago that data was last fetched, ticking live, a manual ↻ refresh, and —
 * when given — the payload's own `as of` stamp in IST. Read-only chrome. */
import { useEffect, useState } from "react";

/** The minimal slice of a TanStack Query result this needs. */
export type QueryLike = {
  dataUpdatedAt: number;
  isFetching: boolean;
  refetch: () => unknown;
};

function useNow(active: boolean, everyMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => setNow(Date.now()), everyMs);
    return () => clearInterval(t);
  }, [active, everyMs]);
  return now;
}

function ago(ms: number, now: number): string {
  const s = Math.max(0, Math.round((now - ms) / 1000));
  if (s < 5) return "just now";
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86_400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86_400)}d ago`;
}

const istHhMm = (iso: string): string | null => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? null
    : d.toLocaleTimeString("en-GB", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit" });
};

export function LastUpdated({
  q,
  asOf,
  label = "updated",
  className = "",
}: {
  q: QueryLike | QueryLike[];
  /** the payload's own timestamp (ISO) — shown as `· data HH:MM IST` when present */
  asOf?: string | null;
  label?: string;
  className?: string;
}) {
  const list = Array.isArray(q) ? q : [q];
  const stamps = list.map((x) => x.dataUpdatedAt).filter((n) => n > 0);
  // the OLDEST fetch time — "everything on screen is at least this fresh"
  const updatedAt = stamps.length ? Math.min(...stamps) : 0;
  const fetching = list.some((x) => x.isFetching);
  const now = useNow(updatedAt > 0);
  const asOfIst = asOf ? istHhMm(asOf) : null;

  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1 text-[11px] text-slate-400 ${className}`}
      aria-live="polite"
    >
      <button
        type="button"
        onClick={() => list.forEach((x) => x.refetch())}
        title="Refresh now"
        aria-label="Refresh now"
        className="rounded px-1 leading-none hover:bg-slate-100 hover:text-slate-600"
      >
        ↻
      </button>
      {updatedAt > 0 ? (
        <span title={new Date(updatedAt).toLocaleString("en-IN", { hour12: false })}>
          {fetching ? "refreshing…" : `${label} ${ago(updatedAt, now)}`}
        </span>
      ) : (
        <span>{fetching ? "loading…" : "—"}</span>
      )}
      {asOfIst && <span className="text-slate-300">· data {asOfIst} IST</span>}
    </span>
  );
}
