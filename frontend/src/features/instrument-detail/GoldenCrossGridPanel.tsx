/** Golden Cross per timeframe (docs/05 §7, docs/07 §4.19).
 *
 * The 50 / 200 SMA cross state + the last golden / death cross for 5m / 15m /
 * 1h / 1D side by side. Column tinted emerald / rose when a cross is recent.
 * Computed on read; descriptive — not a signal, no BUY/SELL. */
import { useGoldenCrossGrid } from "@/api/queries";
import { Panel, ProblemError, Skeleton } from "@/components/primitives";
import type { GoldenCrossColumn } from "@/api/generated/schema";
import { DASH, num, pct, price } from "@/lib/format";

const xTypeLabel = (t: string | null) =>
  t === "GOLDEN" ? "golden" : t === "DEATH" ? "death" : t ? "none in window" : DASH;

const maLabel = (ma: string | null) => (ma === "FAST" ? "50" : ma === "SLOW" ? "200" : DASH);

function Head({ c }: { c: GoldenCrossColumn }) {
  const alertBull = c.recent && c.cross_type === "GOLDEN";
  const alertBear = c.recent && c.cross_type === "DEATH";
  const nearAlert = !alertBull && !alertBear && c.nearest_ma != null;
  const tint = alertBull
    ? "bg-emerald-50 border-emerald-300"
    : alertBear
      ? "bg-rose-50 border-rose-300"
      : nearAlert
        ? "bg-amber-50 border-amber-300"
        : "border-slate-200";
  return (
    <th className={`border-b-2 px-2 py-1.5 text-left align-bottom ${tint}`}>
      <div className="font-semibold text-slate-700">{c.timeframe}</div>
      {c.status === "OK" ? (
        <div
          className={`font-normal text-[11px] ${
            c.state === "ABOVE" ? "text-emerald-600" : c.state === "BELOW" ? "text-rose-600" : "text-slate-500"
          }`}
        >
          {c.state === "ABOVE" ? "50 › 200" : c.state === "BELOW" ? "50 ‹ 200" : "—"}
          {c.recent && (c.cross_type === "GOLDEN" || c.cross_type === "DEATH") ? (
            <span className="ml-1 font-semibold">
              ● {xTypeLabel(c.cross_type)}
              {c.bars_since_cross != null ? ` ${c.bars_since_cross}b` : ""}
            </span>
          ) : null}
          {c.nearest_ma && (
            <div
              className={`mt-0.5 font-semibold ${
                c.nearest_ma_side === "SUPPORT" ? "text-emerald-700" : "text-amber-700"
              }`}
              title={`price within the near-MA band of the ${maLabel(c.nearest_ma)}-period MA`}
            >
              ● near {maLabel(c.nearest_ma)} ({c.nearest_ma_side === "SUPPORT" ? "support" : "resistance"})
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

const dPct = (v: number | null) => (v == null ? DASH : `${v >= 0 ? "+" : ""}${pct(v, 2)}`);

const ROWS: { label: string; get: (c: GoldenCrossColumn) => string }[] = [
  { label: "Regime", get: (c) => (c.state === "ABOVE" ? "bullish (50 above 200)" : c.state === "BELOW" ? "bearish (50 below 200)" : DASH) },
  { label: "Last price", get: (c) => (c.last_price == null ? DASH : price(c.last_price)) },
  { label: "Fast (50)", get: (c) => (c.fast == null ? DASH : `${price(c.fast)} (${dPct(c.dist_to_fast_pct)})`) },
  { label: "Slow (200)", get: (c) => (c.slow == null ? DASH : `${price(c.slow)} (${dPct(c.dist_to_slow_pct)})`) },
  {
    label: "EMA (50/200)",
    get: (c) =>
      c.ema_fast == null && c.ema_slow == null
        ? DASH
        : `${c.ema_fast == null ? DASH : price(c.ema_fast)} / ${c.ema_slow == null ? DASH : price(c.ema_slow)}`,
  },
  { label: "Separation", get: (c) => (c.separation == null ? DASH : pct(c.separation, 2)) },
  { label: "Last cross", get: (c) => xTypeLabel(c.cross_type) },
  { label: "Bars since", get: (c) => (c.bars_since_cross == null ? DASH : num(c.bars_since_cross, 0)) },
  { label: "Cross date", get: (c) => (c.cross_ts ? c.cross_ts.slice(0, 10) : DASH) },
];

export function GoldenCrossGridPanel({ instrumentId }: { instrumentId: number }) {
  const q = useGoldenCrossGrid(instrumentId);
  const d = q.data;
  const applicable = d?.columns.some((c) => c.status !== "NOT_APPLICABLE");

  return (
    <Panel
      title="Golden Cross — 5m / 15m / 1h / 1D"
      right={
        d && (
          <span className="font-mono text-xs text-slate-500">
            {d.fast_period}/{d.slow_period} {d.ma_type} · module {d.golden_cross_grid_version}
          </span>
        )
      }
    >
      {q.isLoading && !d && <Skeleton rows={6} />}
      {q.error && <ProblemError error={q.error} onRetry={() => q.refetch()} />}

      {d && !applicable && (
        <p className="text-sm text-slate-500">
          {DASH} Golden Cross runs on the INDEX series — a dated contract's history is shorter than
          the {d.slow_period}-bar slow average (docs/05 §7).
        </p>
      )}

      {d && applicable && (
        <div className="space-y-2">
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
                {ROWS.map((r) => (
                  <tr key={r.label} className="border-b border-slate-50 last:border-0">
                    <td className="px-2 py-0.5 text-slate-500">{r.label}</td>
                    {d.columns.map((c) => (
                      <td
                        key={c.timeframe}
                        className={`px-2 py-0.5 ${
                          r.label === "Regime" && c.state === "ABOVE"
                            ? "text-emerald-600"
                            : r.label === "Regime" && c.state === "BELOW"
                              ? "text-rose-600"
                              : r.label === "Last cross" && c.cross_type === "GOLDEN"
                                ? "text-emerald-600"
                                : r.label === "Last cross" && c.cross_type === "DEATH"
                                  ? "text-rose-600"
                                  : r.label === "Fast (50)" && c.near_fast
                                    ? "font-semibold text-amber-700"
                                    : r.label === "Slow (200)" && c.near_slow
                                      ? "font-semibold text-amber-700"
                                      : ""
                        }`}
                      >
                        {c.status === "OK" ? r.get(c) : DASH}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-[11px] text-slate-400">
            {d.fast_period}/{d.slow_period}-{d.ma_type} on each timeframe's own bars — the cross
            state above is read off this pair. <b>EMA ({d.fast_period}/{d.slow_period})</b> is the
            same two periods computed as an exponential average instead, shown alongside for
            reference — it doesn't drive the regime/cross/near-MA reads, which stay {d.ma_type}
            -based. A column is
            tinted <span className="text-emerald-600">green</span> /{" "}
            <span className="text-rose-600">rose</span> when a cross printed within the recent
            window, or <span className="text-amber-700">amber</span> — "near {"{"}50/200{"}"}" —
            when the last price sits within {pct(d.near_ma_pct, 2)} of a moving average,
            reading that MA as dynamic support (price above it) or resistance (below). Descriptive
            — not a signal.
          </p>
        </div>
      )}
    </Panel>
  );
}
