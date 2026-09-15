/** Multi-timeframe candlestick patterns (docs/05 §9b, docs/07 §4.17).
 *
 * Columns = 5m / 15m / 30m / 1h; rows = the last N major patterns per column,
 * newest first. M30 is folded on read from M5 (no M30 in the engine grid).
 * A column is tinted (the "alert") when its most recent pattern sits on the
 * just-closed bar, OR when a STRONG reversal-type pattern (engulfing, harami,
 * hammer/star family, piercing/dark-cloud, morning/evening star) shows up
 * anywhere in the scanned window, even a few bars back. Descriptive — not a
 * signal, no BUY/SELL. */
import { useCandlesGrid } from "@/api/queries";
import { Panel, ProblemError, Skeleton } from "@/components/primitives";
import type { CandleGridColumn, CandleGridHit } from "@/api/generated/schema";
import { DASH, titleCase } from "@/lib/format";

const patName = (p: string) => titleCase(p.toLowerCase());

const biasCls = (b: string | null | undefined) =>
  b === "BULLISH" ? "text-emerald-600" : b === "BEARISH" ? "text-rose-600" : "text-slate-500";

// API timestamps are UTC — show the bar's own clock time in IST (the trading day's clock)
const hhmm = (iso: string) =>
  new Date(iso).toLocaleTimeString("en-GB", {
    timeZone: "Asia/Kolkata",
    hour: "2-digit",
    minute: "2-digit",
  });

// classic reversal shapes — excludes DOJI / GRAVESTONE_DOJI / DRAGONFLY_DOJI /
// MARUBOZU (indecision / continuation reads, not named reversal patterns)
const REVERSAL_PATTERNS = new Set([
  "BULLISH_ENGULFING",
  "BEARISH_ENGULFING",
  "BULLISH_HARAMI",
  "BEARISH_HARAMI",
  "HAMMER",
  "HANGING_MAN",
  "SHOOTING_STAR",
  "INVERTED_HAMMER",
  "PIERCING_LINE",
  "DARK_CLOUD_COVER",
  "MORNING_STAR",
  "EVENING_STAR",
]);

function ColumnHead({ c }: { c: CandleGridColumn }) {
  const lastBarAlert = c.on_last_bar && (c.last_bias === "BULLISH" || c.last_bias === "BEARISH");
  // a STRONG reversal pattern anywhere in the scanned window alerts too, even
  // when it isn't the very latest bar
  const strongReversal = c.patterns.find(
    (p) => p.strength === "STRONG" && REVERSAL_PATTERNS.has(p.pattern),
  );
  const alert = lastBarAlert || strongReversal != null;
  const alertBias = lastBarAlert ? c.last_bias : strongReversal?.bias;
  const tint =
    alert && alertBias === "BULLISH"
      ? "bg-emerald-50 border-emerald-300"
      : alert && alertBias === "BEARISH"
        ? "bg-rose-50 border-rose-300"
        : "border-slate-200";
  // don't repeat the same hit twice when it's both the latest bar and the
  // strong-reversal hit
  const showReversalLine = strongReversal != null && !(lastBarAlert && strongReversal.bars_ago === 0);
  // patterns[] is newest-first, so the head entry lines up with last_pattern
  const lastHit = c.patterns[0];
  return (
    <th className={`border-b-2 px-2 py-1.5 text-left align-bottom ${tint}`}>
      <div className="font-semibold text-slate-700">{c.timeframe}</div>
      {c.status === "OK" ? (
        <div className="font-normal text-[11px] text-slate-500">
          {c.last_pattern ? (
            <span className={biasCls(c.last_bias)}>
              {lastBarAlert ? "● " : ""}
              {patName(c.last_pattern)}
              {c.on_last_bar ? " · now" : ` · ${c.last_bars_ago}b ago`}
              {lastHit && <span className="text-slate-400"> · {hhmm(lastHit.bar_ts)}</span>}
            </span>
          ) : (
            <span className="text-slate-400">no pattern</span>
          )}
          {showReversalLine && strongReversal && (
            <div className={`mt-0.5 font-semibold ${biasCls(strongReversal.bias)}`}>
              ● {patName(strongReversal.pattern)} (strong, {strongReversal.bars_ago}b ago ·{" "}
              {hhmm(strongReversal.bar_ts)})
            </div>
          )}
        </div>
      ) : (
        <div className="font-normal text-[11px] text-slate-400">
          {c.status === "NOT_APPLICABLE" ? "n/a" : "insufficient"}
        </div>
      )}
    </th>
  );
}

function HitCell({ h }: { h: CandleGridHit | undefined }) {
  if (!h) return <td className="px-2 py-1 text-slate-300">{DASH}</td>;
  const strongReversal = h.strength === "STRONG" && REVERSAL_PATTERNS.has(h.pattern);
  return (
    <td className={`px-2 py-1 align-top ${strongReversal ? "bg-amber-50" : ""}`}>
      <div className={`font-medium ${biasCls(h.bias)}`}>
        {strongReversal && "● "}
        {patName(h.pattern)}
      </div>
      <div className="text-[11px] text-slate-400">
        {h.strength.toLowerCase()} · {h.bars_ago === 0 ? "last bar" : `${h.bars_ago}b ago`} ·{" "}
        {h.trend_context.toLowerCase()} · {hhmm(h.bar_ts)}
      </div>
    </td>
  );
}

export function CandlesGridPanel({ instrumentId }: { instrumentId: number }) {
  const q = useCandlesGrid(instrumentId, 5);
  const d = q.data;
  const rows = d ? Math.max(0, ...d.columns.map((c) => c.patterns.length)) : 0;

  return (
    <Panel
      title="Candlestick patterns — 5m / 15m / 30m / 1h"
      right={
        d && (
          <span className="font-mono text-xs text-slate-500">
            last 5 · newest first · module {d.candles_grid_version}
          </span>
        )
      }
    >
      {q.isLoading && !d && <Skeleton rows={6} />}
      {q.error && <ProblemError error={q.error} onRetry={() => q.refetch()} />}

      {d && (
        <div className="space-y-2">
          <div className="overflow-x-auto">
            <table className="w-full text-xs tabular-nums">
              <thead>
                <tr>
                  {d.columns.map((c) => (
                    <ColumnHead key={c.timeframe} c={c} />
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows === 0 && (
                  <tr>
                    <td
                      colSpan={d.columns.length}
                      className="px-2 py-3 text-center text-slate-400"
                    >
                      no major patterns in the recent window on any timeframe
                    </td>
                  </tr>
                )}
                {Array.from({ length: rows }).map((_, i) => (
                  <tr key={i} className="border-b border-slate-100 last:border-0">
                    {d.columns.map((c) => (
                      <HitCell key={c.timeframe} h={c.patterns[i]} />
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-[11px] text-slate-400">
            30m is folded on read from 5m bars (session-anchored); it is not a scored engine
            timeframe. A column tints when its just-closed bar carries a pattern, or when a{" "}
            <span className="rounded bg-amber-50 px-1">● amber-marked</span> <b>strong</b>{" "}
            reversal pattern (engulfing, harami, hammer / star family, piercing / dark-cloud,
            morning / evening star) shows up anywhere in the last 5 bars — even a few bars back.
            Descriptive — not a signal, no entry / target / stop.
          </p>
        </div>
      )}
    </Panel>
  );
}
