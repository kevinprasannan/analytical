import type { ReactNode } from "react";
import type { AnalysisItem } from "@/api/generated/schema";
import { Panel, StatGrid, StatusPill, Badge } from "@/components/primitives";
import { bool, num, pct, price, ratio, rsi, titleCase } from "@/lib/format";

const v = (a: AnalysisItem, key: string) => a.values[key] as number | string | boolean | null | undefined;

function Frame({
  a,
  children,
  accent,
}: {
  a: AnalysisItem;
  children?: ReactNode;
  accent?: "bull" | "bear";
}) {
  const na = a.status === "NOT_APPLICABLE";
  const insuf = a.status === "INSUFFICIENT_DATA";
  return (
    <Panel
      title={titleCase(a.analysis_key)}
      muted={na}
      accent={na || insuf ? undefined : accent}
      right={
        <>
          {a.carried && <Badge tone="muted" title="result carried, not recomputed">carried</Badge>}
          {a.provenance?.provisional && <Badge tone="warn">provisional</Badge>}
          <StatusPill status={a.status} />
        </>
      }
    >
      {na || insuf ? (
        <div className="text-sm text-slate-500">
          <p>{a.reason ?? (na ? "not applicable to this instrument type" : "insufficient data")}</p>
          {insuf && a.provenance && (
            <p className="mt-1 font-mono text-xs">
              coverage {num(a.provenance.coverage_ratio, 3)} · bars {a.provenance.bars_used ?? "—"}
            </p>
          )}
        </div>
      ) : (
        <div className="space-y-2">
          {children}
          <p className="font-mono text-[11px] text-slate-400">
            {a.scope} · as of {a.as_of_ts} · coverage {num(a.provenance?.coverage_ratio ?? null, 3)}
          </p>
        </div>
      )}
    </Panel>
  );
}

export function AnalysisPanel({ a }: { a: AnalysisItem }) {
  switch (a.analysis_key) {
    case "rsi":
      return (
        <Frame a={a}>
          <StatGrid
            rows={[
              ["RSI", rsi(v(a, "rsi") as number)],
              ["State", String(v(a, "state") ?? "—").toLowerCase()],
              ["Slope", num(v(a, "slope") as number, 2)],
              ["Divergence", String(v(a, "divergence") ?? "—").toLowerCase()],
            ]}
          />
        </Frame>
      );
    case "bollinger":
      return (
        <Frame a={a}>
          <StatGrid
            rows={[
              ["Basis", price(v(a, "basis") as number)],
              ["Upper / Lower", `${price(v(a, "upper") as number)} / ${price(v(a, "lower") as number)}`],
              ["%B", ratio(v(a, "percent_b") as number)],
              ["Bandwidth", ratio(v(a, "bandwidth") as number)],
              ["Bandwidth pctile", ratio(v(a, "bandwidth_percentile") as number)],
              ["Squeeze", bool(v(a, "squeeze") as boolean)],
              ["Position", String(v(a, "position") ?? "—").replace(/_/g, " ").toLowerCase()],
            ]}
          />
        </Frame>
      );
    case "ema7":
      return (
        <Frame a={a}>
          <StatGrid
            rows={[
              ["EMA", price(v(a, "ema") as number)],
              ["Price vs EMA", price(v(a, "price_vs_ema") as number)],
              ["Above", bool(v(a, "price_above") as boolean)],
              ["Slope state", String(v(a, "slope_state") ?? "—").toLowerCase()],
              ["ATR(14)", price((a.aux["atr14"] as number) ?? null)],
            ]}
          />
        </Frame>
      );
    case "golden_cross": {
      const xType = String(v(a, "cross_type") ?? "");
      const isRecent = v(a, "recent") === true;
      const state = String(v(a, "state") ?? "");
      const bars = v(a, "bars_since_cross") as number | null | undefined;
      const alertBull = isRecent && xType === "GOLDEN";
      const alertBear = isRecent && xType === "DEATH";
      const accent = alertBull ? "bull" : alertBear ? "bear" : undefined;
      return (
        <Frame a={a} accent={accent}>
          {(alertBull || alertBear) && (
            <p className={`text-xs font-semibold ${alertBull ? "text-emerald-600" : "text-rose-600"}`}>
              {alertBull ? "Golden cross" : "Death cross"} — 50 crossed{" "}
              {alertBull ? "above" : "below"} 200
              {bars != null ? `, ${bars} bar${bars === 1 ? "" : "s"} ago` : ""}.
            </p>
          )}
          <StatGrid
            rows={[
              ["Fast / Slow", `${price(v(a, "fast") as number)} / ${price(v(a, "slow") as number)}`],
              [
                "Regime",
                <span
                  key="rg"
                  className={
                    state === "ABOVE"
                      ? "text-emerald-600"
                      : state === "BELOW"
                        ? "text-rose-600"
                        : ""
                  }
                >
                  {state === "ABOVE"
                    ? "50 above 200 · bullish"
                    : state === "BELOW"
                      ? "50 below 200 · bearish"
                      : "—"}
                </span>,
              ],
              [
                "Cross type",
                <span
                  key="ct"
                  className={
                    xType === "GOLDEN"
                      ? "font-medium text-emerald-600"
                      : xType === "DEATH"
                        ? "font-medium text-rose-600"
                        : "text-slate-500"
                  }
                >
                  {xType === "GOLDEN"
                    ? "golden"
                    : xType === "DEATH"
                      ? "death"
                      : "none in window"}
                </span>,
              ],
              ["Bars since cross", bars != null ? num(bars, 0) : "—"],
              ["Separation", pct(v(a, "separation") as number, 3)],
              ["Recent", bool(isRecent)],
            ]}
          />
        </Frame>
      );
    }
    case "volume":
      return (
        <Frame a={a}>
          <StatGrid
            rows={[
              ["Volume", num(v(a, "volume") as number, 0)],
              ["Vol MA", num(v(a, "vol_ma") as number, 0)],
              ["RVOL", ratio(v(a, "rvol") as number)],
              ["Spike", bool(v(a, "spike") as boolean)],
              ["Up/Down ratio", ratio(v(a, "up_down_ratio") as number)],
              ["Up/Down state", String(v(a, "up_down_state") ?? "—").replace(/_/g, " ").toLowerCase()],
              ["Trend", String(v(a, "trend") ?? "—").toLowerCase()],
            ]}
          />
        </Frame>
      );
    case "open_interest":
      return (
        <Frame a={a}>
          <StatGrid
            rows={[
              ["OI", num(v(a, "oi") as number, 0)],
              ["Δ OI", num(v(a, "oi_change") as number, 0)],
              ["% Δ OI", pct(v(a, "oi_pct_change") as number)],
              ["Price Δ", price(v(a, "price_change") as number)],
              ["Price / OI dir", `${v(a, "price_direction")} / ${v(a, "oi_direction")}`],
              ["Behavior", String(v(a, "behavior") ?? "—").replace(/_/g, " ").toLowerCase()],
            ]}
          />
          {a.warnings.some((w) => w.includes("option contract")) && (
            <p className="mt-1 text-xs text-slate-500">
              Positioning describes this option contract, not the underlying (docs/05 §9.5).
            </p>
          )}
        </Frame>
      );
    case "order_block": {
      const zone = (z: Record<string, unknown> | null | undefined) =>
        z
          ? `${price(z.low as number)}–${price(z.high as number)}  (${z.age_bars} bars, ${
              z.mitigated ? "mitigated" : "unmitigated"
            }, ${pct(z.distance_pct as number, 2)})`
          : "—";
      const zones = (a.values.zones as Record<string, unknown>[] | undefined) ?? [];
      return (
        <Frame a={a}>
          <StatGrid
            rows={[
              ["Bias", String(v(a, "bias") ?? "—").toLowerCase()],
              ["Zone state", String(v(a, "zone_state") ?? "—").replace(/_/g, " ").toLowerCase()],
              ["Price", price(v(a, "price") as number)],
              ["ATR", price(v(a, "atr") as number)],
              [
                "Active blocks",
                `${num(v(a, "n_active_bullish") as number, 0)} bullish · ${num(
                  v(a, "n_active_bearish") as number,
                  0,
                )} bearish`,
              ],
              ["Nearest bullish (demand)", zone(a.values.nearest_bullish as Record<string, unknown>)],
              ["Nearest bearish (supply)", zone(a.values.nearest_bearish as Record<string, unknown>)],
            ]}
          />
          {zones.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-xs tabular-nums">
                <thead className="text-slate-400">
                  <tr className="border-b border-slate-200">
                    <th className="px-2 py-1 text-left">side</th>
                    <th className="px-2 py-1 text-right">zone</th>
                    <th className="px-2 py-1 text-right">age</th>
                    <th className="px-2 py-1 text-right">dist %</th>
                    <th className="px-2 py-1 text-left">state</th>
                  </tr>
                </thead>
                <tbody>
                  {zones.slice(0, 12).map((z, i) => (
                    <tr key={i} className="border-b border-slate-100">
                      <td
                        className={`px-2 py-1 ${
                          z.side === "BULLISH" ? "text-emerald-600" : "text-rose-600"
                        }`}
                      >
                        {String(z.side).toLowerCase()}
                      </td>
                      <td className="px-2 py-1 text-right font-mono">
                        {price(z.low as number)}–{price(z.high as number)}
                      </td>
                      <td className="px-2 py-1 text-right text-slate-400">{String(z.age_bars)}</td>
                      <td className="px-2 py-1 text-right">{pct(z.distance_pct as number, 2)}</td>
                      <td className="px-2 py-1 text-slate-500">
                        {z.mitigated ? "mitigated" : "active"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="text-[11px] text-slate-400">
            Last opposing candle before a Break of Structure. Descriptive — not a signal, no
            entry / target / stop.
          </p>
        </Frame>
      );
    }
    case "candles": {
      const onLast = v(a, "on_last_bar") === true;
      const lastBias = String(v(a, "last_bias") ?? "");
      const lastPattern = v(a, "last_pattern") as string | null;
      const accent = onLast && lastBias === "BULLISH" ? "bull" : onLast && lastBias === "BEARISH" ? "bear" : undefined;
      const hits = (a.values.patterns as Record<string, unknown>[] | undefined) ?? [];
      return (
        <Frame a={a} accent={accent}>
          <StatGrid
            rows={[
              ["Bias", String(v(a, "bias") ?? "—").toLowerCase()],
              [
                "Last pattern",
                lastPattern
                  ? `${titleCase(lastPattern.toLowerCase())} · ${lastBias.toLowerCase()} · ${String(
                      v(a, "last_strength") ?? "",
                    ).toLowerCase()}`
                  : "none in window",
              ],
              [
                "When",
                lastPattern
                  ? onLast
                    ? "on the last bar"
                    : `${num(v(a, "last_bars_ago") as number, 0)} bars ago`
                  : "—",
              ],
              [
                "Window",
                `${num(v(a, "n_bullish") as number, 0)} bullish · ${num(
                  v(a, "n_bearish") as number,
                  0,
                )} bearish · ${num(v(a, "bars_scanned") as number, 0)} bars`,
              ],
            ]}
          />
          {onLast && (
            <p className={`text-xs font-semibold ${lastBias === "BULLISH" ? "text-emerald-600" : "text-rose-600"}`}>
              {titleCase((lastPattern ?? "").toLowerCase())} on the just-closed bar.
            </p>
          )}
          {hits.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-xs tabular-nums">
                <thead className="text-slate-400">
                  <tr className="border-b border-slate-200">
                    <th className="px-2 py-1 text-left">pattern</th>
                    <th className="px-2 py-1 text-left">bias</th>
                    <th className="px-2 py-1 text-left">strength</th>
                    <th className="px-2 py-1 text-right">bars ago</th>
                    <th className="px-2 py-1 text-right">close</th>
                  </tr>
                </thead>
                <tbody>
                  {hits.slice(0, 12).map((h, i) => (
                    <tr key={i} className="border-b border-slate-100">
                      <td className="px-2 py-1">{titleCase(String(h.pattern).toLowerCase())}</td>
                      <td
                        className={`px-2 py-1 ${
                          h.bias === "BULLISH"
                            ? "text-emerald-600"
                            : h.bias === "BEARISH"
                              ? "text-rose-600"
                              : "text-slate-500"
                        }`}
                      >
                        {String(h.bias).toLowerCase()}
                      </td>
                      <td className="px-2 py-1 text-slate-500">{String(h.strength).toLowerCase()}</td>
                      <td className="px-2 py-1 text-right text-slate-400">{String(h.bars_ago)}</td>
                      <td className="px-2 py-1 text-right font-mono">{price(h.close as number)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="text-[11px] text-slate-400">
            Major candlestick patterns over the recent window. Descriptive — not a signal, no
            entry / target / stop.
          </p>
        </Frame>
      );
    }
    default:
      return (
        <Frame a={a}>
          <pre className="overflow-x-auto text-xs">{JSON.stringify(a.values, null, 2)}</pre>
        </Frame>
      );
  }
}
