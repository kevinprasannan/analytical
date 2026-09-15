/** OI-based option-strategy suggestions (docs/07 §4.13, docs/05 §11.5).
 *
 * Shows a positioning "view" read off open interest, then candidate option
 * structures with per-leg BUY/SELL + ratio. This is the one place in the UI
 * that renders BUY/SELL — a bounded, owner-authorised exception to decision 15
 * (2026-09-03). Every render carries the disclaimer: illustrative analytical
 * output, not advice, not an order. */
import { useOptionStrategies } from "@/api/queries";
import { Panel, ProblemError, Skeleton, StatGrid, Badge } from "@/components/primitives";
import type { StrategySuggestion } from "@/api/generated/schema";
import { DASH, int, num } from "@/lib/format";

const VIEW_LABEL: Record<string, string> = {
  RANGEBOUND: "Rangebound",
  LEAN_BULLISH: "Leaning up",
  LEAN_BEARISH: "Leaning down",
  TREND_BULLISH: "Trending up",
  TREND_BEARISH: "Trending down",
  VOL_EXPANSION: "Vol expansion",
};
const VIEW_TONE: Record<string, string> = {
  RANGEBOUND: "text-sky-400",
  LEAN_BULLISH: "text-emerald-400",
  LEAN_BEARISH: "text-rose-400",
  TREND_BULLISH: "text-emerald-300",
  TREND_BEARISH: "text-rose-300",
  VOL_EXPANSION: "text-amber-400",
};
const BIAS_TONE: Record<string, string> = {
  BULLISH: "text-emerald-400",
  BEARISH: "text-rose-400",
  NEUTRAL: "text-neutral-400",
};

const pts = (v: number | null) => (v == null ? DASH : num(v, 1));

function LegRow({ leg }: { leg: StrategySuggestion["legs"][number] }) {
  const buy = leg.action === "BUY";
  return (
    <tr className="border-b border-neutral-900">
      <td className="px-2 py-1">
        <span className={buy ? "font-semibold text-emerald-400" : "font-semibold text-rose-400"}>
          {leg.action}
        </span>
      </td>
      <td className="px-2 py-1 text-right tabular-nums">{leg.lots}</td>
      <td className="px-2 py-1">{leg.option_type}</td>
      <td className="px-2 py-1 text-right tabular-nums">{int(leg.strike)}</td>
      <td className="px-2 py-1 text-right tabular-nums">{leg.ltp == null ? DASH : num(leg.ltp, 2)}</td>
      <td className="px-2 py-1 text-right tabular-nums text-neutral-500">
        {leg.oi == null ? DASH : int(leg.oi)}
      </td>
      <td className="px-2 py-1 text-right tabular-nums text-neutral-500">
        {leg.oi_change == null ? DASH : `${leg.oi_change > 0 ? "+" : ""}${int(leg.oi_change)}`}
      </td>
      <td className="px-2 py-1 text-neutral-500">
        {leg.role.replace(/_/g, " ")}
        {leg.expiry && <span className="ml-1 text-amber-500">· {leg.expiry}</span>}
      </td>
    </tr>
  );
}

function SuggestionCard({ s }: { s: StrategySuggestion }) {
  return (
    <div className="rounded border border-neutral-800 p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="font-semibold">{s.name.replace(/_/g, " ")}</span>
        <Badge tone="muted">{s.family.replace(/_/g, "/").toLowerCase()}</Badge>
        <span className={`text-xs ${BIAS_TONE[s.direction_bias] ?? ""}`}>{s.direction_bias.toLowerCase()}</span>
        <Badge tone={s.risk === "DEFINED" ? "ok" : "bad"}>
          {s.risk === "DEFINED" ? "defined risk" : "undefined risk"}
        </Badge>
        {s.reward_risk != null && (
          <span className="text-xs text-neutral-400">
            R:R <b className="text-neutral-200">1:{num(s.reward_risk, 2)}</b>
          </span>
        )}
        {s.pop != null && (
          <span className={`text-xs ${s.high_pop ? "text-emerald-400" : "text-neutral-400"}`}>
            PoP <b>{num(s.pop * 100, 0)}%</b>
          </span>
        )}
        {s.edge_score != null && (
          <Badge tone="muted" title="pop × reward:risk — the ranking key">
            edge {num(s.edge_score, 2)}
          </Badge>
        )}
        <span className="text-xs text-neutral-500">
          {s.net === "CREDIT" ? "net credit" : s.net === "DEBIT" ? "net debit" : "premium n/a"}
          {s.est_net_premium != null && ` ${s.est_net_premium > 0 ? "+" : ""}${num(s.est_net_premium, 1)}`}
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="text-neutral-500">
            <tr className="border-b border-neutral-800">
              {["action", "x", "opt", "strike", "ltp", "OI", "ΔOI", "role"].map((h, i) => (
                <th key={h} className={`px-2 py-1 ${i === 0 || i === 7 ? "text-left" : "text-right"}`}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {s.legs.map((leg, i) => (
              <LegRow key={i} leg={leg} />
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-neutral-400">
        <span>
          max profit <b className="text-neutral-200">{s.max_profit == null ? "unbounded" : pts(s.max_profit)}</b>
        </span>
        <span>
          max loss{" "}
          <b className="text-neutral-200">{s.max_loss == null ? "undefined" : pts(s.max_loss)}</b>
        </span>
        {s.lower_breakeven != null && (
          <span>
            {s.upper_breakeven != null ? "band" : "breakeven"}{" "}
            <b className="text-neutral-200">
              {int(s.lower_breakeven)}
              {s.upper_breakeven != null && ` – ${int(s.upper_breakeven)}`}
            </b>
            {s.spot_inside_breakevens != null && (
              <span
                className={`ml-1 ${s.spot_inside_breakevens ? "text-emerald-500" : "text-rose-500"}`}
              >
                (spot {s.spot_inside_breakevens ? "inside" : "outside"})
              </span>
            )}
          </span>
        )}
        <span className="text-neutral-500">points, 1 lot-set, pre-cost</span>
      </div>

      <p className="mt-2 text-xs text-neutral-400">{s.rationale}</p>
      {s.caveats.length > 0 && (
        <ul className="mt-1 list-disc pl-4 text-xs text-amber-500/90">
          {s.caveats.map((c, i) => (
            <li key={i}>{c}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function StrategyBook({ underlyingId, expiry }: { underlyingId: number; expiry?: string }) {
  const q = useOptionStrategies(underlyingId, expiry);
  const b = q.data;

  return (
    <Panel
      title="Strategy read — OI positioning"
      right={<Badge tone="bad">not advice · not an order</Badge>}
    >
      {q.isLoading && !b && <Skeleton rows={8} />}
      {q.error && <ProblemError error={q.error} onRetry={() => q.refetch()} />}

      {b && (
        <div className="space-y-3">
          <div className="rounded border border-amber-500/40 bg-amber-500/10 p-2 text-xs text-amber-300">
            {b.disclaimer}
          </div>

          <div className="flex flex-wrap items-baseline gap-3">
            <span className={`text-lg font-bold ${VIEW_TONE[b.view.label] ?? ""}`}>
              {VIEW_LABEL[b.view.label] ?? b.view.label}
            </span>
            <span className="text-xs text-neutral-500">
              confidence {(b.view.confidence * 100).toFixed(0)}% · {b.expiry} ({b.days_to_expiry}d)
              {b.atm_iv != null && ` · ATM IV ${num(b.atm_iv * 100, 1)}%`}
              {b.ranked_by === "EDGE" && " · ranked by edge (PoP × R:R)"}
              {b.far_expiry && ` · calendars vs ${b.far_expiry}`}
            </span>
          </div>

          <StatGrid
            rows={[
              ["Spot", int(b.spot)],
              ["ATM", int(b.view.atm_strike)],
              [
                "OI walls (support / resistance)",
                `${b.view.support_wall != null ? int(b.view.support_wall) : DASH} / ${
                  b.view.resistance_wall != null ? int(b.view.resistance_wall) : DASH
                }`,
              ],
              ["Max pain", b.view.max_pain != null ? int(b.view.max_pain) : DASH],
              ["PCR (OI)", b.view.pcr_oi != null ? num(b.view.pcr_oi, 2) : DASH],
              [
                "Net ΔOI (CE / PE)",
                `${b.view.net_ce_oi_change > 0 ? "+" : ""}${int(b.view.net_ce_oi_change)} / ${
                  b.view.net_pe_oi_change > 0 ? "+" : ""
                }${int(b.view.net_pe_oi_change)}`,
              ],
              ["Crowded side", b.view.crowded_side.toLowerCase()],
            ]}
          />

          {b.view.evidence.length > 0 && (
            <ul className="list-disc pl-4 text-xs text-neutral-400">
              {b.view.evidence.map((e, i) => (
                <li key={i}>{e}</li>
              ))}
            </ul>
          )}

          <div className="space-y-2">
            {b.suggestions.map((s, i) => (
              <SuggestionCard key={i} s={s} />
            ))}
            {b.suggestions.length === 0 && (
              <p className="text-xs text-neutral-500">{DASH} no structure fits this read.</p>
            )}
          </div>

          <p className="text-[11px] text-neutral-600">engine {b.algo_version}</p>
        </div>
      )}
    </Panel>
  );
}
