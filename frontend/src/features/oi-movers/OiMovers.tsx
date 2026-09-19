/** Big OI movement — options only (docs/05 §11.4, docs/07 §4.22).
 *
 * The near-expiry option strikes that ADDED / REDUCED the most open interest
 * today, side by side. Each row: session ΔOI, last-15-min ΔOI, and a
 * positioning (buildup) label. Positioning vocabulary only — no BUY/SELL. */
import { useState } from "react";
import { useParams } from "react-router-dom";
import { useInstrument, useOiMovers, useOiMoverLtpTrace, useOiLadder } from "@/api/queries";
import { Badge, Panel, ProblemError, Skeleton, StatGrid } from "@/components/primitives";
import { LastUpdated } from "@/components/LastUpdated";
import type { OiMover, OiLadderRow } from "@/api/generated/schema";
import { DASH, int, num, price } from "@/lib/format";

const sInt = (v: number) => `${v > 0 ? "+" : ""}${int(v)}`;
const sPrice = (v: number) => `${v > 0 ? "+" : ""}${price(v)}`;
// API timestamps are UTC — show them in IST (the trading day's clock)
const hhmm = (iso: string) =>
  new Date(iso).toLocaleTimeString("en-GB", {
    timeZone: "Asia/Kolkata",
    hour: "2-digit",
    minute: "2-digit",
  });
type Selected = { strike: number; option_type: "CE" | "PE" };
const buildupCls: Record<string, string> = {
  LONG_BUILDUP: "bg-emerald-100 text-emerald-800",
  SHORT_BUILDUP: "bg-rose-100 text-rose-800",
  LONG_UNWINDING: "bg-amber-100 text-amber-800",
  SHORT_COVERING: "bg-sky-100 text-sky-800",
  INDETERMINATE: "bg-slate-100 text-slate-500",
  NO_DATA: "bg-slate-100 text-slate-400",
};
const TIME_BANDS = [1, 3, 5, 10, 15];
const MONEYNESS = [
  { id: "DEEP_ITM", label: "deep ITM" },
  { id: "ITM", label: "ITM" },
  { id: "ATM", label: "ATM" },
  { id: "OTM", label: "OTM" },
  { id: "DEEP_OTM", label: "deep OTM" },
];
const mnyShort: Record<string, string> = {
  DEEP_ITM: "d.ITM",
  ITM: "ITM",
  ATM: "ATM",
  OTM: "OTM",
  DEEP_OTM: "d.OTM",
};

function MoversTable({
  rows,
  recentMin,
  onSelect,
}: {
  rows: OiMover[];
  recentMin: number;
  onSelect?: (r: OiMover) => void;
}) {
  const [sortRecent, setSortRecent] = useState(false);
  const sorted = [...rows].sort((a, b) =>
    sortRecent
      ? Math.abs(b.oi_change_recent) - Math.abs(a.oi_change_recent)
      : Math.abs(b.oi_change_session) - Math.abs(a.oi_change_session),
  );
  if (rows.length === 0)
    return <p className="px-2 py-4 text-sm text-slate-400">{DASH} nothing yet this session.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs tabular-nums">
        <thead className="text-slate-400">
          <tr className="border-b border-slate-200">
            <th className="px-2 py-1 text-left">strike</th>
            <th className="px-2 py-1 text-right">OI</th>
            <th
              className={`cursor-pointer px-2 py-1 text-right ${sortRecent ? "" : "font-semibold text-slate-700"}`}
              onClick={() => setSortRecent(false)}
            >
              Δ session
            </th>
            <th className="px-2 py-1 text-right">Δ %</th>
            <th
              className={`cursor-pointer px-2 py-1 text-right ${sortRecent ? "font-semibold text-slate-700" : ""}`}
              onClick={() => setSortRecent(true)}
            >
              Δ {recentMin}m
            </th>
            <th className="px-2 py-1 text-right">LTP</th>
            <th className="px-2 py-1 text-right" title="premium change vs today's open (recent-band change shown small when it diverges)">
              LTP Δ%
            </th>
            <th className="px-2 py-1 text-left">buildup</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => (
            <tr key={`${r.strike}-${r.option_type}`} className="border-b border-slate-50">
              <td
                className={`px-2 py-1 font-mono ${onSelect ? "cursor-pointer hover:text-sky-600 hover:underline" : ""}`}
                title={onSelect ? "view this strike's LTP trace" : undefined}
                onClick={onSelect ? () => onSelect(r) : undefined}
              >
                {int(r.strike)}
                <span className="ml-1 text-[10px] text-slate-400">{mnyShort[r.moneyness] ?? r.moneyness}</span>
                {r.crowded && <span title="crowded — outsized share of fresh OI"> 🔥</span>}
              </td>
              <td className="px-2 py-1 text-right text-slate-500">{int(r.oi)}</td>
              <td
                className={`px-2 py-1 text-right font-medium ${
                  r.oi_change_session >= 0 ? "text-emerald-600" : "text-rose-600"
                }`}
              >
                {sInt(r.oi_change_session)}
              </td>
              <td className="px-2 py-1 text-right text-slate-400">
                {r.oi_change_session_pct == null ? DASH : `${num(r.oi_change_session_pct * 100, 1)}%`}
              </td>
              <td
                className={`px-2 py-1 text-right ${
                  r.oi_change_recent > 0
                    ? "text-emerald-600"
                    : r.oi_change_recent < 0
                      ? "text-rose-600"
                      : "text-slate-400"
                }`}
              >
                {sInt(r.oi_change_recent)}
              </td>
              <td className="px-2 py-1 text-right font-mono">
                {r.ltp == null ? DASH : price(r.ltp)}
              </td>
              <td className="px-2 py-1 text-right font-mono">
                {r.price_change_session_pct == null ? (
                  <span className="text-slate-400">{DASH}</span>
                ) : (
                  <span
                    className={
                      r.price_change_session_pct >= 0 ? "text-emerald-600" : "text-rose-600"
                    }
                  >
                    {r.price_change_session_pct >= 0 ? "+" : ""}
                    {num(r.price_change_session_pct * 100, 1)}%
                  </span>
                )}
                {r.price_change_recent_pct != null &&
                  Math.abs((r.price_change_recent_pct ?? 0) - (r.price_change_session_pct ?? 0)) >=
                    0.002 && (
                    <span
                      className={`ml-1 text-[10px] ${r.price_change_recent_pct >= 0 ? "text-emerald-500" : "text-rose-500"}`}
                      title={`premium change over just the last ${recentMin} min`}
                    >
                      {recentMin}m {r.price_change_recent_pct >= 0 ? "+" : ""}
                      {num(r.price_change_recent_pct * 100, 1)}%
                    </span>
                  )}
              </td>
              <td className="px-2 py-1">
                <span className={`rounded px-1 py-0.5 text-[11px] ${buildupCls[r.buildup] ?? ""}`}>
                  {r.buildup.replace(/_/g, " ").toLowerCase()}
                </span>
                {r.buildup_now !== r.buildup &&
                  !["INDETERMINATE", "NO_DATA"].includes(r.buildup_now) && (
                    <span className="ml-1 text-[10px] text-slate-400" title="positioning over just the recent band">
                      now: {r.buildup_now.replace(/_/g, " ").toLowerCase()}
                    </span>
                  )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CePeBoxes({
  rows,
  recentMin,
  onSelect,
}: {
  rows: OiMover[];
  recentMin: number;
  onSelect?: (r: OiMover) => void;
}) {
  const ce = rows.filter((r) => r.option_type === "CE");
  const pe = rows.filter((r) => r.option_type === "PE");
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <div>
        <div className="mb-1 text-xs font-semibold text-emerald-700">Calls (CE)</div>
        <MoversTable rows={ce} recentMin={recentMin} onSelect={onSelect} />
      </div>
      <div>
        <div className="mb-1 text-xs font-semibold text-rose-700">Puts (PE)</div>
        <MoversTable rows={pe} recentMin={recentMin} onSelect={onSelect} />
      </div>
    </div>
  );
}

type TraceBucketRow = {
  key: string;
  tsStart: string;
  tsEnd: string;
  nTicks: number;
  oi: number | null;
  oiChange: number | null;
  optLow: number;
  optHigh: number;
  optClose: number; // last raw tick in the bucket — drives the up/down colour, not the band
  undLow: number | null;
  undHigh: number | null;
  undClose: number | null;
};

/** Group consecutive 1-min ticks into `bucketMin`-wide windows (session-open
 * anchored, same convention as the app's other M5/M15 aggregation), reporting
 * each window's LTP low/high band instead of every raw tick — owner: "i NEED
 * FILTRATION IN ltp TRACE IF LTP LOW HIGH BAND LIKE IF 5 MIN MULTIPLE PRICE
 * MEANS". OI/OI Δ are read from the bucket's last tick (a running value, not
 * something to band). `bucketMin=1` is a 1:1 passthrough of the raw ticks. */
function bucketTrace(series: LtpTracePoint[], bucketMin: number): TraceBucketRow[] {
  const size = Math.max(1, bucketMin);
  const out: TraceBucketRow[] = [];
  for (let i = 0; i < series.length; i += size) {
    const chunk = series.slice(i, i + size);
    const optVals = chunk.map((p) => p.option_ltp);
    const undVals = chunk
      .map((p) => p.underlying_ltp)
      .filter((v): v is number => v != null);
    const last = chunk[chunk.length - 1];
    out.push({
      key: chunk[0].ts,
      tsStart: chunk[0].ts,
      tsEnd: last.ts,
      nTicks: chunk.length,
      oi: last.oi,
      oiChange: last.oi_change,
      optLow: Math.min(...optVals),
      optHigh: Math.max(...optVals),
      optClose: last.option_ltp,
      undLow: undVals.length ? Math.min(...undVals) : null,
      undHigh: undVals.length ? Math.max(...undVals) : null,
      undClose: last.underlying_ltp,
    });
  }
  return out;
}

/** "163.45" when a bucket saw one price, "162.10–165.80" when it saw a range. */
const band = (lo: number, hi: number, fmt: (v: number) => string) =>
  lo === hi ? fmt(lo) : `${fmt(lo)}–${fmt(hi)}`;

function LtpTracePanel({
  underlyingId,
  candidates,
  sel,
  onSelectChange,
}: {
  underlyingId: number;
  candidates: OiMover[];
  sel: Selected | null;
  onSelectChange: (s: Selected) => void;
}) {
  const t = useOiMoverLtpTrace(underlyingId, sel?.strike ?? null, sel?.option_type ?? null);
  const td = t.data;
  const [bucketMin, setBucketMin] = useState(1);
  const rows = td ? bucketTrace(td.series, bucketMin) : [];

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3 text-xs">
        <div className="flex items-center gap-1">
          <span className="text-slate-500">strike</span>
          <select
            className="rounded border border-slate-300 px-1.5 py-0.5"
            value={sel ? `${sel.strike}-${sel.option_type}` : ""}
            onChange={(e) => {
              const [strike, option_type] = e.target.value.split("-");
              onSelectChange({ strike: Number(strike), option_type: option_type as "CE" | "PE" });
            }}
          >
            {candidates.length === 0 && <option value="">{DASH}</option>}
            {candidates.map((c) => (
              <option key={`${c.strike}-${c.option_type}`} value={`${c.strike}-${c.option_type}`}>
                {int(c.strike)} {c.option_type} ({c.oi_change_session >= 0 ? "added" : "reduced"})
              </option>
            ))}
          </select>
        </div>
        <div className="flex items-center gap-1">
          <span className="text-slate-500">group</span>
          <div className="inline-flex overflow-hidden rounded border border-slate-300">
            {TIME_BANDS.map((b) => (
              <button
                key={b}
                type="button"
                onClick={() => setBucketMin(b)}
                className={`px-2 py-0.5 ${bucketMin === b ? "bg-slate-800 text-white" : "text-slate-600 hover:bg-slate-100"}`}
              >
                {b}m
              </button>
            ))}
          </div>
        </div>
        {td && (
          <span className="text-slate-400">
            expiry {td.expiry} · {td.series.length} ticks this session
            {bucketMin > 1 && ` · ${rows.length} rows grouped ${bucketMin}m`}
          </span>
        )}
      </div>

      {t.isLoading && !td && <Skeleton rows={8} />}
      {t.error && <ProblemError error={t.error} onRetry={() => t.refetch()} />}
      {!sel && !t.isLoading && (
        <p className="text-sm text-slate-400">{DASH} pick a strike above, or click one in the Movers tab.</p>
      )}

      {td && rows.length > 0 && (
        <div className="max-h-[32rem] overflow-y-auto overflow-x-auto">
          <table className="w-full text-xs tabular-nums">
            <thead className="sticky top-0 bg-white text-slate-400">
              <tr className="border-b border-slate-200">
                <th className="px-2 py-1 text-left">time (IST)</th>
                <th className="px-2 py-1 text-right">
                  {td.strike} {td.option_type} OI
                </th>
                <th className="px-2 py-1 text-right" title="OI change vs. the previous row (tick to tick, or bucket to bucket when grouped)">
                  OI Δ (prev)
                </th>
                <th className="px-2 py-1 text-right" title="OI change vs. this trace's first tick (cumulative)">
                  OI Δ (session)
                </th>
                <th className="px-2 py-1 text-right">
                  {td.strike} {td.option_type} LTP{bucketMin > 1 ? " (low–high)" : ""}
                </th>
                <th className="px-2 py-1 text-right" title="LTP change vs. the previous row (close to close)">
                  LTP Δ
                </th>
                <th className="px-2 py-1 text-right">
                  {td.underlying_symbol} LTP{bucketMin > 1 ? " (low–high)" : ""}
                </th>
                <th className="px-2 py-1 text-right" title={`${td.underlying_symbol} LTP change vs. the previous row (close to close)`}>
                  {td.underlying_symbol} Δ
                </th>
              </tr>
            </thead>
            <tbody>
              {[...rows]
                .reverse()
                .map((r, i, arr) => {
                  const prev = arr[i + 1];
                  const oiTickDelta =
                    prev && r.oi != null && prev.oi != null ? r.oi - prev.oi : null;
                  const oiUp = oiTickDelta ?? 0;
                  const optDelta = prev ? r.optClose - prev.optClose : null;
                  const optUp = optDelta ?? 0;
                  const undDelta =
                    prev && r.undClose != null && prev.undClose != null
                      ? r.undClose - prev.undClose
                      : null;
                  const undUp = undDelta ?? 0;
                  const timeLabel =
                    r.tsStart === r.tsEnd ? hhmm(r.tsStart) : `${hhmm(r.tsStart)}–${hhmm(r.tsEnd)}`;
                  return (
                    <tr key={r.key} className="border-b border-slate-50">
                      <td className="px-2 py-1 text-slate-500">{timeLabel}</td>
                      <td
                        className={`px-2 py-1 text-right font-mono ${
                          oiUp > 0 ? "text-emerald-600" : oiUp < 0 ? "text-rose-600" : "text-slate-500"
                        }`}
                      >
                        {r.oi == null ? DASH : int(r.oi)}
                      </td>
                      <td
                        className={`px-2 py-1 text-right font-mono ${
                          oiTickDelta == null
                            ? "text-slate-400"
                            : oiTickDelta > 0
                              ? "text-emerald-600"
                              : oiTickDelta < 0
                                ? "text-rose-600"
                                : "text-slate-400"
                        }`}
                      >
                        {oiTickDelta == null ? DASH : sInt(oiTickDelta)}
                      </td>
                      <td
                        className={`px-2 py-1 text-right font-mono ${
                          r.oiChange == null
                            ? "text-slate-400"
                            : r.oiChange > 0
                              ? "text-emerald-600"
                              : r.oiChange < 0
                                ? "text-rose-600"
                                : "text-slate-400"
                        }`}
                      >
                        {r.oiChange == null ? DASH : sInt(r.oiChange)}
                      </td>
                      <td
                        className={`px-2 py-1 text-right font-mono ${
                          optUp > 0 ? "text-emerald-600" : optUp < 0 ? "text-rose-600" : ""
                        }`}
                      >
                        {band(r.optLow, r.optHigh, price)}
                      </td>
                      <td
                        className={`px-2 py-1 text-right font-mono ${
                          optDelta == null
                            ? "text-slate-400"
                            : optDelta > 0
                              ? "text-emerald-600"
                              : optDelta < 0
                                ? "text-rose-600"
                                : "text-slate-400"
                        }`}
                      >
                        {optDelta == null ? DASH : sPrice(optDelta)}
                      </td>
                      <td
                        className={`px-2 py-1 text-right font-mono ${
                          undUp > 0 ? "text-emerald-600" : undUp < 0 ? "text-rose-600" : "text-slate-500"
                        }`}
                      >
                        {r.undLow == null || r.undHigh == null ? DASH : band(r.undLow, r.undHigh, price)}
                      </td>
                      <td
                        className={`px-2 py-1 text-right font-mono ${
                          undDelta == null
                            ? "text-slate-400"
                            : undDelta > 0
                              ? "text-emerald-600"
                              : undDelta < 0
                                ? "text-rose-600"
                                : "text-slate-400"
                        }`}
                      >
                        {undDelta == null ? DASH : sPrice(undDelta)}
                      </td>
                    </tr>
                  );
                })}
            </tbody>
          </table>
        </div>
      )}
      {td && rows.length === 0 && (
        <p className="text-sm text-slate-400">{DASH} no ticks yet this session for this strike.</p>
      )}
      <p className="text-[11px] text-slate-500">
        Raw time / OI / OI Δ (prev) / OI Δ (session) / price / price Δ / price / price Δ, newest
        first — no indicator, no label. <b>group</b> buckets consecutive 1-min ticks into N-min
        windows and shows each window's LTP as a <b>low–high band</b> when it saw more than one
        price (a single value when it didn't) — <b>OI Δ (prev)</b> is the change versus the row
        right above it (tick to tick, or bucket to bucket when grouped); <b>OI Δ (session)</b> is
        the cumulative change versus this trace's first tick (≈ today's session open). Each{" "}
        <b>LTP Δ</b> / <b>{td?.underlying_symbol ?? "underlying"} Δ</b> is that row's own close
        (its last tick, even when grouped) versus the previous row's close — the plain price
        difference next to each low–high band. Watching where the strike's OI build tracks its own
        premium and {td?.underlying_symbol ?? "the underlying"}'s move, to read where the build-up
        might find liquidity.
      </p>
    </div>
  );
}

const LADDER_STEPS = [1, 3, 5, 10, 15];
const LADDER_COLUMNS = [3, 4, 5, 6];

/** For each time column, which strike carries that column's single biggest
 * |OI Δ| on this side — owner: "each maximum no oI change back ground color
 * elevate". Returns one strike (or null) per column, so the cell can be
 * given an elevated background instead of just the usual text colour. */
function maxAbsDeltaStrikePerColumn(
  rows: OiLadderRow[],
  side: "call" | "put",
  nCols: number,
): (number | null)[] {
  const out: (number | null)[] = new Array(nCols).fill(null);
  const best: number[] = new Array(nCols).fill(-1);
  for (const r of rows) {
    r[side].forEach((c, col) => {
      if (c.oi_delta != null && Math.abs(c.oi_delta) > best[col]) {
        best[col] = Math.abs(c.oi_delta);
        out[col] = r.strike;
      }
    });
  }
  return out;
}

/** Text colour always; an elevated background too when this cell is its
 * column's biggest |Δ| on this side. */
function ladderCellCls(delta: number | null, elevated: boolean): string {
  if (delta == null) return "text-slate-300";
  if (delta === 0) return "text-slate-400";
  const tone = delta > 0 ? "text-emerald-600" : "text-rose-600";
  if (!elevated) return tone;
  return `${tone} font-semibold ${delta > 0 ? "bg-emerald-100" : "bg-rose-100"}`;
}

type LadderCellData = { oi: number | null; oi_delta: number | null; ltp: number | null };

/** A ladder OI-Δ cell with a hover tooltip (owner: "tool tip is a good idea
 * if possible add option price also" — the earlier native `title` on the
 * header only showed the underlying's price and relied on the browser's own
 * tooltip, which is what rendered as a bare "?" `cursor-help` icon with no
 * visible text for the owner; this is a real, always-rendering CSS tooltip
 * instead, per-cell, carrying the option's own LTP too). */
function LadderCell({
  cell,
  elevated,
  mark,
  strike,
  side,
  underlyingSymbol,
  underlyingPx,
  openUpward,
}: {
  cell: LadderCellData;
  elevated: boolean;
  mark: string;
  strike: number;
  side: "CE" | "PE";
  underlyingSymbol: string;
  underlyingPx: number | null;
  openUpward?: boolean;
}) {
  // anchored to the cell's own edge rather than centred — a centred tooltip
  // clips against the table's scroll container at the far left/right columns
  // (owner: "tool tip ... not working showing symbol '?'" — the earlier
  // native `title` attempt clipped the same way at the table edges). CE
  // (left half of the ladder) grows rightward from the cell's left edge; PE
  // (right half) grows leftward from the cell's right edge. `openUpward` (the
  // last row) avoids the same clipping vertically, against the table's own
  // scroll container bottom edge.
  const align = side === "CE" ? "left-0" : "right-0";
  const vAlign = openUpward ? "bottom-full mb-1" : "top-full mt-1";
  return (
    <td
      className={`group relative px-2 py-1 text-right font-mono ${ladderCellCls(cell.oi_delta, elevated)}`}
    >
      {cell.oi_delta == null ? DASH : sInt(cell.oi_delta)}
      <div
        className={`pointer-events-none absolute ${align} ${vAlign} z-20 hidden w-max rounded bg-slate-900 px-2 py-1.5 text-left text-[11px] font-normal normal-case text-white shadow-lg group-hover:block`}
      >
        <div className="font-semibold">
          {int(strike)} {side} · {hhmm(mark)}
        </div>
        <div>
          OI {cell.oi == null ? DASH : int(cell.oi)}
          {cell.oi_delta != null && ` (${sInt(cell.oi_delta)})`}
        </div>
        <div>LTP {cell.ltp == null ? DASH : price(cell.ltp)}</div>
        <div className="text-slate-300">
          {underlyingSymbol} {underlyingPx == null ? DASH : price(underlyingPx)}
        </div>
      </div>
    </td>
  );
}

/** Classic CE | strike | PE option-chain layout, but each column is a recent
 * time mark and each cell is that strike/side's OI **change since the column
 * beside it** — owner: "OI Delta only that time change only ... like this
 * one more display option in LTP Trace [/ OI] movers", confirmed via a
 * follow-up as a CE/PE-mirrored ladder (calls read oldest→newest toward the
 * strike column, puts newest→oldest away from it). */
function OiLadderPanel({ underlyingId }: { underlyingId: number }) {
  const [stepMin, setStepMin] = useState(3);
  const [marks, setMarks] = useState(6);
  const q = useOiLadder(underlyingId, { marks, stepMin, windowUp: 10, windowDown: 10 });
  const d = q.data;
  const ceMaxStrike = d ? maxAbsDeltaStrikePerColumn(d.rows, "call", d.marks.length) : [];
  const peMaxStrike = d ? maxAbsDeltaStrikePerColumn(d.rows, "put", d.marks.length) : [];

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3 text-xs">
        <div className="flex items-center gap-1">
          <span className="text-slate-500">step</span>
          <div className="inline-flex overflow-hidden rounded border border-slate-300">
            {LADDER_STEPS.map((b) => (
              <button
                key={b}
                type="button"
                onClick={() => setStepMin(b)}
                className={`px-2 py-0.5 ${stepMin === b ? "bg-slate-800 text-white" : "text-slate-600 hover:bg-slate-100"}`}
              >
                {b}m
              </button>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-1">
          <span className="text-slate-500">columns</span>
          <div className="inline-flex overflow-hidden rounded border border-slate-300">
            {LADDER_COLUMNS.map((n) => (
              <button
                key={n}
                type="button"
                onClick={() => setMarks(n)}
                className={`px-2 py-0.5 ${marks === n ? "bg-slate-800 text-white" : "text-slate-600 hover:bg-slate-100"}`}
              >
                {n}
              </button>
            ))}
          </div>
        </div>
        {d && (
          <span className="text-slate-400">
            expiry {d.expiry} · ATM {d.atm_strike != null ? int(d.atm_strike) : DASH}
          </span>
        )}
      </div>

      {q.isLoading && !d && <Skeleton rows={10} />}
      {q.error && <ProblemError error={q.error} onRetry={() => q.refetch()} />}

      {d && d.rows.length > 0 && (
        <div className="overflow-x-auto rounded border border-slate-200">
          <table className="w-full text-xs tabular-nums">
            <thead className="bg-slate-50 text-slate-400">
              <tr>
                <th
                  colSpan={d.marks.length}
                  className="border-b border-slate-200 px-2 py-1 text-center font-semibold text-emerald-700"
                >
                  Calls (CE) OI Δ
                </th>
                <th className="border-b border-slate-200 px-2 py-1" />
                <th
                  colSpan={d.marks.length}
                  className="border-b border-slate-200 px-2 py-1 text-center font-semibold text-rose-700"
                >
                  Puts (PE) OI Δ
                </th>
              </tr>
              <tr>
                {d.marks.map((mk) => (
                  <th key={`ce-${mk}`} className="px-2 py-1 text-right font-normal">
                    {hhmm(mk)}
                  </th>
                ))}
                <th className="px-2 py-1 text-center font-semibold text-slate-500">strike</th>
                {[...d.marks].reverse().map((mk) => (
                  <th key={`pe-${mk}`} className="px-2 py-1 text-right font-normal">
                    {hhmm(mk)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {[...d.rows]
                .reverse()
                .map((r, rowIdx, rowsArr) => {
                  const isAtm = d.atm_strike != null && r.strike === d.atm_strike;
                  const openUpward = rowIdx === rowsArr.length - 1; // last row -> avoid clipping below
                  return (
                    <tr key={r.strike} className={isAtm ? "bg-amber-50" : ""}>
                      {r.call.map((c, i) => (
                        <LadderCell
                          key={i}
                          cell={c}
                          elevated={ceMaxStrike[i] === r.strike}
                          mark={d.marks[i]}
                          strike={r.strike}
                          side="CE"
                          underlyingSymbol={d.underlying_symbol}
                          underlyingPx={d.underlying_at_marks[i]}
                          openUpward={openUpward}
                        />
                      ))}
                      <td
                        className={`px-2 py-1 text-center font-semibold ${isAtm ? "text-amber-800" : "text-slate-700"}`}
                      >
                        {int(r.strike)}
                      </td>
                      {[...r.put]
                        .reverse()
                        .map((c, i) => {
                          const origCol = r.put.length - 1 - i;
                          return (
                            <LadderCell
                              key={i}
                              cell={c}
                              elevated={peMaxStrike[origCol] === r.strike}
                              mark={d.marks[origCol]}
                              strike={r.strike}
                              side="PE"
                              underlyingSymbol={d.underlying_symbol}
                              underlyingPx={d.underlying_at_marks[origCol]}
                              openUpward={openUpward}
                            />
                          );
                        })}
                    </tr>
                  );
                })}
            </tbody>
          </table>
        </div>
      )}
      {d && d.rows.length === 0 && (
        <p className="text-sm text-slate-400">{DASH} no strikes in range.</p>
      )}
      <p className="text-[11px] text-slate-500">
        Each cell is <b>OI Δ</b> — the change from the column beside it, not a running total —
        read left→right on the Calls side (oldest → newest) and right→left on the Puts side
        (mirrored, newest closest to the strike column), the classic CE | strike | PE chain
        layout. Highlighted row = ATM; each column's single biggest |Δ| on its side gets an
        elevated background so it stands out at a glance. Hover any cell for its raw OI, that
        option's own LTP, and {d?.underlying_symbol ?? "the underlying"}'s LTP at that instant.{" "}
        <b>step</b> sets the minutes between columns; <b>columns</b> sets how many. Positioning
        only, no BUY/SELL.
      </p>
    </div>
  );
}

export function OiMovers() {
  const { id } = useParams();
  const uid = Number(id);
  const inst = useInstrument(uid);
  const [band, setBand] = useState(15);
  const [mny, setMny] = useState<string[]>([]);
  const [tab, setTab] = useState<"movers" | "trace" | "ladder">("movers");
  const [sel, setSel] = useState<Selected | null>(null);
  const q = useOiMovers(uid, { top: 15, timeBand: band, moneyness: mny });
  const d = q.data;

  const toggleMny = (m: string) =>
    setMny((s) => (s.includes(m) ? s.filter((x) => x !== m) : [...s, m]));

  const candidates: OiMover[] = d
    ? [...d.added, ...d.reduced].filter(
        (r, i, arr) =>
          arr.findIndex((x) => x.strike === r.strike && x.option_type === r.option_type) === i,
      )
    : [];
  // default the trace tab to today's top OI add until the user picks one explicitly
  const effectiveSel: Selected | null =
    sel ?? (d && d.added.length > 0 ? { strike: d.added[0].strike, option_type: d.added[0].option_type as "CE" | "PE" } : null);
  const selectMover = (r: OiMover) => {
    setSel({ strike: r.strike, option_type: r.option_type as "CE" | "PE" });
    setTab("trace");
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-lg font-bold">
          Big OI movers — {inst.data?.symbol ?? inst.data?.contract_key ?? `#${uid}`}
          <span className="ml-2 text-xs font-normal text-slate-500">options only</span>
          <LastUpdated q={q} asOf={d?.as_of} className="ml-2 align-middle font-normal" />
        </h1>
        <div className="flex flex-wrap items-center gap-3 text-xs">
          <div className="inline-flex overflow-hidden rounded border border-slate-300">
            {(["movers", "trace", "ladder"] as const).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setTab(t)}
                className={`px-2 py-0.5 ${tab === t ? "bg-slate-800 text-white" : "text-slate-600 hover:bg-slate-100"}`}
              >
                {t === "movers" ? "Movers" : t === "trace" ? "LTP trace" : "OI ladder"}
              </button>
            ))}
          </div>
          {tab === "movers" && (
            <>
              <div className="flex items-center gap-1">
                <span className="text-slate-500">recent band</span>
                <div className="inline-flex overflow-hidden rounded border border-slate-300">
                  {TIME_BANDS.map((b) => (
                    <button
                      key={b}
                      type="button"
                      onClick={() => setBand(b)}
                      className={`px-2 py-0.5 ${band === b ? "bg-slate-800 text-white" : "text-slate-600 hover:bg-slate-100"}`}
                    >
                      {b}m
                    </button>
                  ))}
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-1">
                <span className="text-slate-500">moneyness</span>
                {MONEYNESS.map((o) => (
                  <button
                    key={o.id}
                    type="button"
                    onClick={() => toggleMny(o.id)}
                    className={`rounded border px-1.5 py-0.5 ${
                      mny.includes(o.id)
                        ? "border-slate-800 bg-slate-800 text-white"
                        : "border-slate-300 text-slate-600 hover:bg-slate-100"
                    }`}
                  >
                    {o.label}
                  </button>
                ))}
                {mny.length > 0 && (
                  <button type="button" className="text-slate-400 underline" onClick={() => setMny([])}>
                    all
                  </button>
                )}
              </div>
            </>
          )}
        </div>
      </div>

      {q.isLoading && !d && <Skeleton rows={10} />}
      {q.error && <ProblemError error={q.error} onRetry={() => q.refetch()} />}

      {d && tab === "movers" && (
        <>
          <Panel title="Context" right={<Badge tone="muted">positioning labels — no BUY/SELL</Badge>}>
            <StatGrid
              rows={[
                ["Spot / expiry", `${price(d.spot)} · ${d.expiry}`],
                ["PCR (OI) / max-pain", `${d.pcr_oi_now == null ? DASH : num(d.pcr_oi_now, 2)} · ${d.max_pain_now == null ? DASH : int(d.max_pain_now)}`],
                [
                  "Support / resistance strike",
                  `${d.support_strike == null ? DASH : int(d.support_strike)} · ${d.resistance_strike == null ? DASH : int(d.resistance_strike)}`,
                ],
                [
                  "Net ΔOI (CE / PE)",
                  <span key="n">
                    <span className={d.net_ce_oi_change >= 0 ? "text-emerald-600" : "text-rose-600"}>
                      {sInt(d.net_ce_oi_change)}
                    </span>{" "}
                    /{" "}
                    <span className={d.net_pe_oi_change >= 0 ? "text-emerald-600" : "text-rose-600"}>
                      {sInt(d.net_pe_oi_change)}
                    </span>{" "}
                    <span className="text-slate-400">
                      · fresh OI on {d.crowded_side.toLowerCase()}
                    </span>
                  </span>,
                ],
                ["As of", `${d.as_of.slice(11, 16)} · Δ${d.recent_window_min}m = last ${d.recent_window_min} min`],
              ]}
            />
          </Panel>

          <div className="space-y-4">
            <Panel title={`OI added — top ${d.top}`}>
              <CePeBoxes rows={d.added} recentMin={d.recent_window_min} onSelect={selectMover} />
            </Panel>
            <Panel title={`OI reduced — top ${d.top}`}>
              <CePeBoxes rows={d.reduced} recentMin={d.recent_window_min} onSelect={selectMover} />
            </Panel>
          </div>
          <p className="text-[11px] text-slate-500">
            Split by <b>session</b> ΔOI (from today's open); click the <b>Δ session</b> / <b>Δ
            {d.recent_window_min}m</b> headers to re-rank, or a <b>strike</b> to open its LTP trace.
            <b> LTP Δ%</b> is the premium change
            versus today's open, with the last-{d.recent_window_min}-min change shown small when
            it diverges. The <b>buildup</b> chip is the
            <i> session</i> read (so "added" rows are always a *buildup*, "reduced" a
            *unwinding / covering*): long/short buildup = OI rising with premium up/down;
            long unwinding / short covering = OI falling with premium down/up. A <b>now:</b> tag
            appears when the last {d.recent_window_min} min diverges — the day's build
            accelerating or reversing. Positioning only, no BUY/SELL.
          </p>
        </>
      )}

      {tab === "trace" && (
        <Panel title="Strike LTP trace" right={<Badge tone="muted">raw time/price — no signal</Badge>}>
          <LtpTracePanel
            underlyingId={uid}
            candidates={candidates}
            sel={effectiveSel}
            onSelectChange={setSel}
          />
        </Panel>
      )}

      {tab === "ladder" && (
        <Panel title="OI ladder — CE / PE by time" right={<Badge tone="muted">OI change only — no signal</Badge>}>
          <OiLadderPanel underlyingId={uid} />
        </Panel>
      )}
    </div>
  );
}
