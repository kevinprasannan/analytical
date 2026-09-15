/** Premium decay — theta vs. the session's actual move, options only (docs/05
 * §11.6, docs/07 §4.23).
 *
 * For one underlying's near expiry, per strike: the decay theta alone would
 * predict for the time elapsed since today's open, set against what the
 * premium actually did. Descriptive positioning only — no BUY/SELL. */
import { useState } from "react";
import { useParams } from "react-router-dom";
import { useInstrument, usePremiumDecay } from "@/api/queries";
import { Badge, Panel, ProblemError, Skeleton, StatGrid } from "@/components/primitives";
import { LastUpdated } from "@/components/LastUpdated";
import type { DecayLeg, DecayRow } from "@/api/generated/schema";
import { DASH, int, num, price } from "@/lib/format";

const stateCls: Record<string, string> = {
  AS_EXPECTED: "bg-slate-100 text-slate-600",
  DECAYING_FASTER: "bg-rose-100 text-rose-800",
  OFFSET_BY_MOVE: "bg-emerald-100 text-emerald-800",
  NO_DATA: "bg-slate-100 text-slate-400",
};
const stateLabel: Record<string, string> = {
  AS_EXPECTED: "as expected",
  DECAYING_FASTER: "decaying faster",
  OFFSET_BY_MOVE: "offset by move",
  NO_DATA: DASH,
};

const sgn = (v: number) => `${v > 0 ? "+" : ""}${num(v, 2)}`;

/** The 4 cells for one leg, in natural (LTP → θ → expected/actual → state) order.
 * Reversed for the put side so `state` sits next to the strike on both sides — the
 * same mirrored-ladder convention as the OI-pulse screen. */
function legCells(leg: DecayLeg | null, side: "call" | "put") {
  const cells = !leg
    ? [
        <td key="ltp" className="px-2 py-1 text-right text-slate-300">{DASH}</td>,
        <td key="th" className="px-2 py-1 text-right text-slate-300">{DASH}</td>,
        <td key="ea" className="px-2 py-1 text-right text-slate-300">{DASH}</td>,
        <td key="st" className="px-2 py-1 text-slate-300">{DASH}</td>,
      ]
    : [
        <td key="ltp" className="px-2 py-1 text-right font-mono tabular-nums">
          {leg.ltp == null ? DASH : price(leg.ltp)}
          {leg.iv != null && (
            <span className="ml-1 text-[10px] text-slate-400">IV {num(leg.iv * 100, 1)}%</span>
          )}
        </td>,
        <td key="th" className="px-2 py-1 text-right font-mono tabular-nums">
          {leg.theta_per_lot == null ? (
            DASH
          ) : (
            <span className={leg.theta_per_lot < 0 ? "text-rose-600" : "text-emerald-600"}>
              {sgn(leg.theta_per_lot)}
            </span>
          )}
          {leg.theta_pct_of_premium != null && (
            <span className="ml-1 text-[10px] text-slate-400">
              {num(leg.theta_pct_of_premium * 100, 2)}%/d
            </span>
          )}
        </td>,
        <td
          key="ea"
          className="px-2 py-1 text-right font-mono tabular-nums"
          title="theta-implied → actual, since the session open"
        >
          {leg.expected_decay == null ? DASH : <span className="text-slate-400">{sgn(leg.expected_decay)}</span>}
          {" → "}
          {leg.actual_change == null ? (
            DASH
          ) : (
            <span className={leg.actual_change >= 0 ? "text-emerald-600" : "text-rose-600"}>
              {sgn(leg.actual_change)}
            </span>
          )}
        </td>,
        <td key="st" className="px-2 py-1">
          <span
            className={`rounded px-1 py-0.5 text-[11px] ${stateCls[leg.decay_state] ?? ""}`}
            title={leg.decay_gap != null ? `gap vs theta: ${sgn(leg.decay_gap)}` : undefined}
          >
            {stateLabel[leg.decay_state] ?? leg.decay_state}
          </span>
        </td>,
      ];
  return side === "put" ? cells.slice().reverse() : cells;
}

function DecayLadder({ rows, atmStrike }: { rows: DecayRow[]; atmStrike: number | null }) {
  if (rows.length === 0)
    return <p className="px-2 py-4 text-sm text-slate-400">{DASH} no strikes for this expiry.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead className="text-slate-400">
          <tr>
            <th colSpan={4} className="px-2 py-1 text-center font-semibold text-emerald-600">
              CALLS
            </th>
            <th className="px-2 py-1 text-center">STRIKE</th>
            <th colSpan={4} className="px-2 py-1 text-center font-semibold text-rose-600">
              PUTS
            </th>
          </tr>
          <tr className="border-b border-slate-200">
            {["LTP", "θ/lot", "expected → actual", "state"].map((h) => (
              <th key={`c-${h}`} className="px-2 py-1 text-right">
                {h}
              </th>
            ))}
            <th className="px-2 py-1" />
            {["state", "expected → actual", "θ/lot", "LTP"].map((h) => (
              <th key={`p-${h}`} className="px-2 py-1 text-right">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr
              key={r.strike}
              className={`border-b border-slate-50 ${r.strike === atmStrike ? "bg-amber-50" : ""}`}
            >
              {legCells(r.call, "call")}
              <td className="px-2 py-1 text-center font-mono font-semibold">
                {int(r.strike)}
                {r.strike === atmStrike && (
                  <span className="ml-1 rounded bg-amber-200 px-1 text-[10px] text-amber-800">
                    ATM
                  </span>
                )}
              </td>
              {legCells(r.put, "put")}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function PremiumDecay() {
  const { id } = useParams();
  const uid = Number(id);
  const inst = useInstrument(uid);
  const [expiry, setExpiry] = useState<string | undefined>(undefined);
  const q = usePremiumDecay(uid, { expiry });
  const d = q.data;

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-bold">
        Premium decay — {inst.data?.symbol ?? inst.data?.contract_key ?? `#${uid}`}
        <span className="ml-2 text-xs font-normal text-slate-500">options only</span>
        <LastUpdated q={q} asOf={d?.as_of} className="ml-2 align-middle font-normal" />
      </h1>

      {q.isLoading && !d && <Skeleton rows={12} />}
      {q.error && <ProblemError error={q.error} onRetry={() => q.refetch()} />}

      {d && (
        <>
          <Panel
            title="Context"
            right={
              <div className="flex items-center gap-2">
                {d.fast_decay_zone && (
                  <Badge tone="warn" title="≤5 days to expiry — theta accelerates here">
                    fast decay zone
                  </Badge>
                )}
                <Badge tone="muted">positioning labels — no BUY/SELL</Badge>
                <select
                  className="rounded border border-slate-300 bg-white px-2 py-1 text-xs text-slate-700"
                  value={d.expiry}
                  onChange={(e) => setExpiry(e.target.value)}
                >
                  {d.expiries.map((e) => (
                    <option key={e} value={e}>
                      {e}
                    </option>
                  ))}
                </select>
              </div>
            }
          >
            <StatGrid
              rows={[
                ["Spot / expiry", `${price(d.spot)} · ${d.expiry} (${d.days_to_expiry}d)`],
                [
                  "ATM straddle θ/lot",
                  d.atm_straddle_theta_per_lot == null ? (
                    DASH
                  ) : (
                    <span
                      className={d.atm_straddle_theta_per_lot < 0 ? "text-rose-600" : "text-emerald-600"}
                    >
                      {sgn(d.atm_straddle_theta_per_lot)} / day
                    </span>
                  ),
                ],
                [
                  "ATM call / put θ/lot",
                  `${d.atm_call_theta_per_lot == null ? DASH : sgn(d.atm_call_theta_per_lot)} / ${
                    d.atm_put_theta_per_lot == null ? DASH : sgn(d.atm_put_theta_per_lot)
                  }`,
                ],
                [
                  "Session elapsed",
                  `${Math.round(d.elapsed_session_minutes)} min (${num(d.elapsed_calendar_days, 3)} calendar days)`,
                ],
                ["As of", d.as_of.slice(11, 16)],
              ]}
            />
          </Panel>

          <Panel title={`${d.rows.length} strikes`} right={<Badge tone="muted">table only</Badge>}>
            <DecayLadder rows={d.rows} atmStrike={d.atm_strike} />
          </Panel>

          <p className="text-[11px] text-slate-500">
            <b>θ/lot</b> is the option's current theta (Black-Scholes, from the live chain) scaled
            to one lot — the ₹ this contract would lose per calendar day from time alone, holding
            spot and IV fixed. <b>expected → actual</b> compares that theta-implied move since
            today's session open (a linear estimate, not a re-pricing) against what the premium
            actually did. <b>as expected</b> = the move is within a small band of theta alone;{" "}
            <b>decaying faster</b> = it lost more than theta alone predicts (IV/price working
            against it too); <b>offset by move</b> = a price/IV move outweighed the theta bleed
            (premium flat or up despite decay). On all but the quietest sessions the actual move
            usually dwarfs theta — that gap is the point of this screen. Positioning only, no
            BUY/SELL.
          </p>
        </>
      )}
    </div>
  );
}
