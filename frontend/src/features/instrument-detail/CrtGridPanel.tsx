/** Candle Range Theory per timeframe (docs/05 §9d, docs/07 §4.24).
 *
 * A reference candle's High-Low range, and how price has behaved around it
 * since: accepted (holds beyond a break), rejected (breaks then closes back
 * inside), or expanded (keeps travelling past the break) — plus a separate
 * flag for a reference candle that sat fully inside its own prior ("mother")
 * bar (compression). 5m / 15m / 30m / 1h, 30m folded from 5m. Computed on
 * read; descriptive — not a signal, no BUY/SELL. */
import { useCrtGrid } from "@/api/queries";
import { Panel, ProblemError, Skeleton } from "@/components/primitives";
import type { CrtColumn, CrtRead } from "@/api/generated/schema";
import { DASH, num, price } from "@/lib/format";

const SIGNAL_TONE: Record<string, string> = {
  BULLISH_CONTINUATION: "text-emerald-600",
  RANGE_EXPANSION_UP: "text-emerald-600",
  BEARISH_CONTINUATION: "text-rose-600",
  RANGE_EXPANSION_DOWN: "text-rose-600",
  HIGH_REJECTION: "text-amber-600",
  LOW_REJECTION: "text-amber-600",
  COMPRESSION: "text-sky-600",
  NEUTRAL: "text-slate-400",
};

const SIGNAL_LABEL: Record<string, string> = {
  BULLISH_CONTINUATION: "bullish continuation",
  RANGE_EXPANSION_UP: "range expansion ↑",
  BEARISH_CONTINUATION: "bearish continuation",
  RANGE_EXPANSION_DOWN: "range expansion ↓",
  HIGH_REJECTION: "high rejection",
  LOW_REJECTION: "low rejection",
  COMPRESSION: "compression",
  NEUTRAL: "neutral",
};

const HEAD_TINT: Record<string, string> = {
  BULLISH_CONTINUATION: "bg-emerald-50 border-emerald-300",
  RANGE_EXPANSION_UP: "bg-emerald-50 border-emerald-300",
  BEARISH_CONTINUATION: "bg-rose-50 border-rose-300",
  RANGE_EXPANSION_DOWN: "bg-rose-50 border-rose-300",
  HIGH_REJECTION: "bg-amber-50 border-amber-300",
  LOW_REJECTION: "bg-amber-50 border-amber-300",
  COMPRESSION: "bg-sky-50 border-sky-300",
};

const POSITION_LABEL: Record<string, string> = {
  ABOVE_HIGH: "above high",
  BELOW_LOW: "below low",
  AT_MIDPOINT: "at midpoint",
  INSIDE: "inside",
};

function Head({ c }: { c: CrtColumn }) {
  const r = c.read;
  const tint = (r && HEAD_TINT[r.signal]) || "border-slate-200";
  return (
    <th className={`border-b-2 px-2 py-1.5 text-left align-bottom ${tint}`}>
      <div className="font-semibold text-slate-700">{c.timeframe}</div>
      {c.status === "OK" && r ? (
        <div className={`font-normal text-[11px] ${SIGNAL_TONE[r.signal] ?? "text-slate-400"}`}>
          {SIGNAL_LABEL[r.signal] ?? r.signal.toLowerCase()}
        </div>
      ) : (
        <div className="font-normal text-[11px] text-slate-400">
          {c.status === "NOT_APPLICABLE" ? "n/a" : "insufficient"}
        </div>
      )}
    </th>
  );
}

function RangeCell({ r }: { r: CrtRead | null }) {
  if (!r) return <td className="px-2 py-1 text-slate-300">{DASH}</td>;
  return (
    <td className="px-2 py-1 align-top">
      <div className="font-medium text-slate-700">
        {price(r.ref_low)}–{price(r.ref_high)}
      </div>
      <div className="text-[11px] text-slate-400">
        mid {price(r.ref_midpoint)} · rng {num(r.ref_range, 1)}
        {r.is_inside_candle && (
          <span className="ml-1 rounded bg-sky-50 px-1 text-sky-700">inside (mother)</span>
        )}
      </div>
    </td>
  );
}

function PositionCell({ r }: { r: CrtRead | null }) {
  if (!r) return <td className="px-2 py-1 text-slate-300">{DASH}</td>;
  return (
    <td className="px-2 py-1">
      <div className="text-slate-700">{POSITION_LABEL[r.current_position] ?? r.current_position}</div>
      <div className="text-[11px] text-slate-400">last {price(r.last_close)}</div>
    </td>
  );
}

function BreakoutCell({ r }: { r: CrtRead | null }) {
  if (!r || r.breakout_direction === "NONE") return <td className="px-2 py-1 text-slate-300">{DASH}</td>;
  const up = r.breakout_direction === "HIGH";
  const tone = up ? "text-emerald-600" : "text-rose-600";
  return (
    <td className="px-2 py-1 align-top">
      <div className={`font-medium ${tone}`}>{up ? "▲ high break" : "▼ low break"}</div>
      <div className="text-[11px] text-slate-400">
        {r.close_outside ? "close outside" : "closed back inside"}
        {r.retested && " · retested"}
        {r.holds_beyond && " · holds"}
        {r.volume_confirms === true && " · vol-confirmed"}
        {r.volume_confirms === false && " · vol light"}
      </div>
    </td>
  );
}

function ExpansionCell({ r }: { r: CrtRead | null }) {
  if (!r || r.expansion_points == null) return <td className="px-2 py-1 text-slate-300">{DASH}</td>;
  return (
    <td className="px-2 py-1 font-mono text-slate-600">
      {num(r.expansion_points, 1)} pts
      {r.expansion_multiple != null && (
        <span className="ml-1 text-[11px] text-slate-400">({num(r.expansion_multiple, 2)}×rng)</span>
      )}
    </td>
  );
}

export function CrtGridPanel({ instrumentId }: { instrumentId: number }) {
  const q = useCrtGrid(instrumentId);
  const d = q.data;
  const applicable = d?.columns.some((c) => c.status !== "NOT_APPLICABLE");

  return (
    <Panel
      title="Candle Range Theory — 5m / 15m / 30m / 1h"
      right={d && <span className="font-mono text-xs text-slate-500">module {d.crt_grid_version}</span>}
    >
      <p className="mb-2 max-w-3xl text-sm text-slate-500">
        Each column's <b>reference candle</b> is a few bars back from the latest (default 5); the
        bars since it are read against its High / Low / midpoint — a break that <b>holds</b> is
        continuation, a break that <b>closes back inside</b> is rejection, and a break that keeps
        travelling is <b>range expansion</b>. A reference candle sitting fully inside its own prior
        bar is flagged <b>compression</b> — the eventual break of that prior bar's own high/low
        then matters more. Not "green = bullish" — the boundaries and what happens after a break
        are the point. Descriptive — not a signal.
      </p>

      {q.isLoading && !d && <Skeleton rows={5} />}
      {q.error && <ProblemError error={q.error} onRetry={() => q.refetch()} />}

      {d && !applicable && (
        <p className="text-sm text-slate-500">{DASH} Candle Range Theory runs on the INDEX / FUTURE series.</p>
      )}

      {d && applicable && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs tabular-nums">
            <thead>
              <tr>
                <th className="border-b-2 border-slate-200 px-2 py-1.5 text-left" />
                {d.columns.map((c) => (
                  <Head key={c.timeframe} c={c} />
                ))}
              </tr>
            </thead>
            <tbody>
              <tr className="border-b border-slate-50">
                <td className="px-2 py-1 text-slate-500">reference range</td>
                {d.columns.map((c) => (
                  <RangeCell key={c.timeframe} r={c.status === "OK" ? c.read : null} />
                ))}
              </tr>
              <tr className="border-b border-slate-50">
                <td className="px-2 py-1 text-slate-500">current position</td>
                {d.columns.map((c) => (
                  <PositionCell key={c.timeframe} r={c.status === "OK" ? c.read : null} />
                ))}
              </tr>
              <tr className="border-b border-slate-50">
                <td className="px-2 py-1 text-slate-500">breakout</td>
                {d.columns.map((c) => (
                  <BreakoutCell key={c.timeframe} r={c.status === "OK" ? c.read : null} />
                ))}
              </tr>
              <tr>
                <td className="px-2 py-1 text-slate-500">expansion</td>
                {d.columns.map((c) => (
                  <ExpansionCell key={c.timeframe} r={c.status === "OK" ? c.read : null} />
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}
