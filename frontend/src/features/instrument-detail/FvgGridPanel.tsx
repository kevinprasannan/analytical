/** ICT swing Fair Value Gaps per timeframe (docs/05 §9c, docs/07 §4.21).
 *
 * The 'left-side' FVGs that form into a swing high / low and then act as
 * inversion arrays — 5m / 15m / 30m / 1h. Each column shows the nearest active
 * gap above and below price, its CE, and its test / inversion state. Column
 * header tints when price is inside a primed gap. Computed on read; descriptive
 * — not a signal, no BUY/SELL. */
import { useFvgGrid } from "@/api/queries";
import { Panel, ProblemError, Skeleton } from "@/components/primitives";
import type { FvgColumn, SwingFvg } from "@/api/generated/schema";
import { DASH, num, price } from "@/lib/format";

const invCls = (k: string | null | undefined) =>
  k === "BULLISH" ? "text-emerald-600" : k === "BEARISH" ? "text-rose-600" : "text-slate-500";

const stateCls: Record<string, string> = {
  PRIMED: "bg-slate-100 text-slate-600",
  TESTED: "bg-amber-100 text-amber-800",
  RESPECTED: "bg-emerald-100 text-emerald-800",
  BREACHED: "bg-rose-100 text-rose-800 line-through",
};

function GapCell({ f }: { f: SwingFvg | null }) {
  if (!f) return <td className="px-2 py-1 text-slate-300">{DASH}</td>;
  return (
    <td className="px-2 py-1 align-top">
      <div className={`font-medium ${invCls(f.inversion_kind)}`}>
        {price(f.bottom)}–{price(f.top)}
      </div>
      <div className="text-[11px] text-slate-400">
        CE {price(f.ce)} · <span className={`rounded px-1 ${stateCls[f.state] ?? ""}`}>{f.state.toLowerCase()}</span> ·{" "}
        {f.distance_pct >= 0 ? "+" : ""}
        {num(f.distance_pct, 2)}%{f.reached_ce ? " · hit CE" : ""}
        {f.wick_violated && f.body_respected ? " · wick-only" : ""}
      </div>
    </td>
  );
}

function Head({ c }: { c: FvgColumn }) {
  const inGap =
    c.status === "OK" &&
    ((c.nearest_above && c.nearest_above.distance_pct === 0) ||
      (c.nearest_below && c.nearest_below.distance_pct === 0));
  const tint =
    inGap && c.bias === "BULLISH"
      ? "bg-emerald-50 border-emerald-300"
      : inGap && c.bias === "BEARISH"
        ? "bg-rose-50 border-rose-300"
        : "border-slate-200";
  return (
    <th className={`border-b-2 px-2 py-1.5 text-left align-bottom ${tint}`}>
      <div className="font-semibold text-slate-700">{c.timeframe}</div>
      {c.status === "OK" ? (
        <div className={`font-normal text-[11px] ${invCls(c.bias)}`}>
          {c.bias === "NEUTRAL" ? `${c.n_active} active` : `${c.bias.toLowerCase()} lean · ${c.n_active} active`}
        </div>
      ) : (
        <div className="font-normal text-[11px] text-slate-400">
          {c.status === "NOT_APPLICABLE" ? "n/a" : "insufficient"}
        </div>
      )}
    </th>
  );
}

export function FvgGridPanel({ instrumentId }: { instrumentId: number }) {
  const q = useFvgGrid(instrumentId);
  const d = q.data;
  const applicable = d?.columns.some((c) => c.status !== "NOT_APPLICABLE");

  return (
    <Panel
      title="ICT Fair Value Gaps — 5m / 15m / 30m / 1h"
      right={d && <span className="font-mono text-xs text-slate-500">module {d.fvg_grid_version}</span>}
    >
      {q.isLoading && !d && <Skeleton rows={5} />}
      {q.error && <ProblemError error={q.error} onRetry={() => q.refetch()} />}

      {d && !applicable && (
        <p className="text-sm text-slate-500">{DASH} swing FVGs run on the INDEX / FUTURE series.</p>
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
                <tr className="border-b border-slate-50">
                  <td className="px-2 py-1 text-slate-500">nearest above</td>
                  {d.columns.map((c) => (
                    <GapCell key={c.timeframe} f={c.status === "OK" ? c.nearest_above : null} />
                  ))}
                </tr>
                <tr className="border-b border-slate-50">
                  <td className="px-2 py-1 text-slate-500">nearest below</td>
                  {d.columns.map((c) => (
                    <GapCell key={c.timeframe} f={c.status === "OK" ? c.nearest_below : null} />
                  ))}
                </tr>
                <tr>
                  <td className="px-2 py-1 text-slate-500">last</td>
                  {d.columns.map((c) => (
                    <td key={c.timeframe} className="px-2 py-1 font-mono text-slate-500">
                      {c.last_price != null ? price(c.last_price) : DASH}
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
          <p className="text-[11px] text-slate-400">
            Left-side FVGs formed into a swing high / low, shown as their <b>inversion</b> polarity
            (a bullish gap into a swing high acts as resistance after price rotates). CE = 50 %.
            <span className="text-rose-600"> rose</span> = bearish array overhead,
            <span className="text-emerald-600"> green</span> = bullish array below. 30m folded from
            5m. Descriptive — not a signal.
          </p>
        </div>
      )}
    </Panel>
  );
}
