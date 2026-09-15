import type { ReactNode } from "react";
import { useState } from "react";
import { useParams } from "react-router-dom";
import { useInstrument, useOiPulse } from "@/api/queries";
import { Badge, Panel, ProblemError, Skeleton, StatGrid } from "@/components/primitives";
import { LastUpdated } from "@/components/LastUpdated";
import { StrategyBook } from "@/features/option-strategy/StrategyBook";
import type { OiPulseLeg } from "@/api/generated/schema";
import { DASH, int, num, price } from "@/lib/format";

const BUILDUP_TONE: Record<string, string> = {
  LONG_BUILDUP: "text-emerald-500",
  SHORT_COVERING: "text-sky-500",
  SHORT_BUILDUP: "text-rose-500",
  LONG_UNWINDING: "text-amber-500",
  INDETERMINATE: "text-neutral-500",
  NO_DATA: "text-neutral-600",
};

const BIAS_TONE: Record<string, "ok" | "warn" | "muted"> = {
  CALL_WRITING: "warn",
  PUT_UNWINDING: "warn",
  PUT_WRITING: "ok",
  CALL_UNWINDING: "ok",
  BALANCED: "muted",
};

const dOI = (v: number | null | undefined) =>
  v == null ? DASH : `${v > 0 ? "+" : ""}${int(v)}`;
const oiTone = (v: number | null | undefined) =>
  v == null || v === 0 ? "" : v > 0 ? "text-emerald-500" : "text-rose-500";
const short = (s: string) => s.replace(/_/g, " ").toLowerCase();
// API timestamps are UTC — show them in IST (the trading day's clock)
const hhmm = (iso: string) =>
  new Date(iso).toLocaleTimeString("en-GB", {
    timeZone: "Asia/Kolkata",
    hour: "2-digit",
    minute: "2-digit",
  });

function Cell({ children, cls }: { children: ReactNode; cls?: string }) {
  return <td className={`px-2 py-1 text-right tabular-nums ${cls ?? ""}`}>{children}</td>;
}

function Buildup({ leg }: { leg: OiPulseLeg | null }) {
  if (!leg) return <Cell>{DASH}</Cell>;
  return (
    <td className={`px-2 py-1 text-right text-[11px] ${BUILDUP_TONE[leg.buildup] ?? ""}`}>
      {leg.crowded && <span title="crowded — biggest OI build on this side">🔥 </span>}
      {short(leg.buildup)}
    </td>
  );
}

export function OiPulse() {
  const { id } = useParams();
  const uid = Number(id);
  const inst = useInstrument(uid);
  const [expiry, setExpiry] = useState<string | undefined>(undefined);
  const [traceUp, setTraceUp] = useState<number | undefined>(undefined); // strikes above ATM; undefined = all
  const [traceDown, setTraceDown] = useState<number | undefined>(undefined); // strikes below ATM
  const q = useOiPulse(uid, { expiry, traceUp, traceDown });
  const p = q.data;

  const arrow = (from: number | null, to: number | null, dp = 2) =>
    from == null || to == null ? DASH : `${num(from, dp)} → ${num(to, dp)}`;

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-bold">
        OI pulse — {inst.data?.symbol ?? inst.data?.contract_key ?? `#${uid}`}
        <LastUpdated q={q} asOf={p?.as_of} className="ml-2 align-middle font-normal" />
      </h1>

      {q.isLoading && <Skeleton rows={12} />}
      {q.error && <ProblemError error={q.error} onRetry={() => q.refetch()} />}

      {p && (
        <>
          <Panel
            title="Pulse"
            right={
              <div className="flex items-center gap-2">
                <Badge tone={BIAS_TONE[p.bias] ?? "muted"}>{short(p.bias)}</Badge>
                <select
                  className="rounded border border-neutral-700 bg-transparent px-2 py-1 text-xs"
                  value={p.expiry}
                  onChange={(e) => setExpiry(e.target.value)}
                >
                  {p.expiries.map((e) => (
                    <option key={e} value={e}>{e}</option>
                  ))}
                </select>
              </div>
            }
          >
            <StatGrid
              rows={[
                ["Spot", price(p.spot)],
                ["Expiry", p.expiry],
                ["PCR (OI) open → now", arrow(p.pcr_oi_open, p.pcr_oi_now)],
                [
                  "Max pain open → now",
                  p.max_pain_open == null || p.max_pain_now == null
                    ? DASH
                    : `${int(p.max_pain_open)} → ${int(p.max_pain_now)}` +
                      (p.max_pain_shift ? ` (${p.max_pain_shift > 0 ? "+" : ""}${int(p.max_pain_shift)})` : ""),
                ],
                ["OI support (max PE OI)", p.support_strike != null ? int(p.support_strike) : DASH],
                ["OI resistance (max CE OI)", p.resistance_strike != null ? int(p.resistance_strike) : DASH],
                ["Total CE / PE OI", `${int(p.total_ce_oi)} / ${int(p.total_pe_oi)}`],
                ["Net ΔOI CE / PE (session)", `${dOI(p.net_ce_oi_change)} / ${dOI(p.net_pe_oi_change)}`],
                [
                  "Crowded",
                  <span key="cr">
                    <span
                      className={
                        p.crowded_side === "CALLS"
                          ? "font-semibold text-rose-500"
                          : p.crowded_side === "PUTS"
                            ? "font-semibold text-emerald-500"
                            : "text-neutral-500"
                      }
                    >
                      🔥 {p.crowded_side.toLowerCase()}
                    </span>
                    {p.crowded_side === "CALLS" && p.crowded_ce_strike != null
                      ? ` @ ${int(p.crowded_ce_strike)}${
                          p.crowded_ce_frac != null
                            ? ` (${(p.crowded_ce_frac * 100).toFixed(0)}%)`
                            : ""
                        }`
                      : p.crowded_side === "PUTS" && p.crowded_pe_strike != null
                        ? ` @ ${int(p.crowded_pe_strike)}${
                            p.crowded_pe_frac != null
                              ? ` (${(p.crowded_pe_frac * 100).toFixed(0)}%)`
                              : ""
                          }`
                        : ""}
                  </span>,
                ],
                ["As of", hhmm(p.as_of)],
                ["Engine", `${p.algo_version} · pulse ${p.oi_pulse_version}`],
              ]}
            />
          </Panel>

          <Panel title={`${p.rows.length} strikes`} right={<Badge tone="muted">table only</Badge>}>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="text-neutral-400">
                  <tr>
                    <th colSpan={4} className="px-2 py-1 text-center font-semibold text-emerald-500">
                      CALLS
                    </th>
                    <th className="px-2 py-1 text-center">STRIKE</th>
                    <th colSpan={4} className="px-2 py-1 text-center font-semibold text-rose-500">
                      PUTS
                    </th>
                  </tr>
                  <tr className="border-b border-neutral-800">
                    {["OI", "Δ session", "Δ 15m", "buildup"].map((h) => (
                      <th key={`c-${h}`} className="px-2 py-1 text-right">{h}</th>
                    ))}
                    <th className="px-2 py-1" />
                    {["buildup", "Δ 15m", "Δ session", "OI"].map((h) => (
                      <th key={`p-${h}`} className="px-2 py-1 text-right">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {p.rows.map((row) => {
                    const isSup = row.strike === p.support_strike;
                    const isRes = row.strike === p.resistance_strike;
                    const mark = isRes ? "bg-rose-500/10" : isSup ? "bg-emerald-500/10" : "";
                    return (
                      <tr key={row.strike} className={`border-b border-neutral-900 ${mark}`}>
                        <Cell>{row.call ? int(row.call.oi) : DASH}</Cell>
                        <Cell cls={oiTone(row.call?.oi_change_session)}>
                          {dOI(row.call?.oi_change_session)}
                        </Cell>
                        <Cell cls={oiTone(row.call?.oi_change_recent)}>
                          {dOI(row.call?.oi_change_recent)}
                        </Cell>
                        <Buildup leg={row.call} />
                        <td className="px-2 py-1 text-center font-mono">
                          {int(row.strike)}
                          {isRes && <span className="ml-1 text-[10px] text-rose-400">R</span>}
                          {isSup && <span className="ml-1 text-[10px] text-emerald-400">S</span>}
                        </td>
                        <Buildup leg={row.put} />
                        <Cell cls={oiTone(row.put?.oi_change_recent)}>
                          {dOI(row.put?.oi_change_recent)}
                        </Cell>
                        <Cell cls={oiTone(row.put?.oi_change_session)}>
                          {dOI(row.put?.oi_change_session)}
                        </Cell>
                        <Cell>{row.put ? int(row.put.oi) : DASH}</Cell>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className="mt-2 text-[11px] text-neutral-500">
              Buildup describes positioning in that option contract (price × OI move),
              not the underlying. Analytical view only — no execution.
            </p>
          </Panel>

          {p.trace.length > 0 && (
            <Panel
              title="Session trace"
              right={
                <div className="flex flex-wrap items-center gap-2">
                  <label className="flex items-center gap-1 text-xs text-neutral-500">
                    ▲ up
                    <select
                      className="rounded border border-neutral-700 bg-transparent px-2 py-1 text-xs"
                      value={traceUp ?? ""}
                      onChange={(e) =>
                        setTraceUp(e.target.value === "" ? undefined : Number(e.target.value))
                      }
                    >
                      <option value="">all</option>
                      {[0, 1, 2, 3, 5, 7, 10, 15].map((n) => (
                        <option key={n} value={n}>
                          +{n}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="flex items-center gap-1 text-xs text-neutral-500">
                    ▼ down
                    <select
                      className="rounded border border-neutral-700 bg-transparent px-2 py-1 text-xs"
                      value={traceDown ?? ""}
                      onChange={(e) =>
                        setTraceDown(e.target.value === "" ? undefined : Number(e.target.value))
                      }
                    >
                      <option value="">all</option>
                      {[0, 1, 2, 3, 5, 7, 10, 15].map((n) => (
                        <option key={n} value={n}>
                          −{n}
                        </option>
                      ))}
                    </select>
                  </label>
                  <Badge tone="muted">
                    IST · newest first · stops 15:40
                    {p.trace_atm_strike != null &&
                    (p.trace_window_up != null || p.trace_window_down != null)
                      ? ` · ATM ${int(p.trace_atm_strike)} +${p.trace_window_up ?? "∞"}/−${
                          p.trace_window_down ?? "∞"
                        }`
                      : ""}
                  </Badge>
                </div>
              }
            >
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead className="text-neutral-400">
                    <tr className="border-b border-neutral-800">
                      {[
                        "time IST",
                        "spot",
                        "calls ΔOI",
                        "(Δ)",
                        "puts ΔOI",
                        "(Δ)",
                        "diff ΔOI",
                        "diff %",
                        "dir of chng",
                        "PCR",
                        "COI PCR",
                        "VOL PCR",
                        "sentiment",
                      ].map((h, i) => (
                        <th
                          key={h}
                          className={`px-2 py-1 ${i === 0 ? "text-left" : "text-right"}`}
                        >
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {[...p.trace].reverse().map((t) => (
                      <tr key={t.ts} className="border-b border-neutral-900">
                        <td className="px-2 py-1 font-mono">{hhmm(t.ts)}</td>
                        <Cell>{t.spot != null ? price(t.spot) : DASH}</Cell>
                        <Cell>{int(t.call_oi_change)}</Cell>
                        <Cell cls={oiTone(t.call_oi_change_delta)}>
                          {dOI(t.call_oi_change_delta)}
                        </Cell>
                        <Cell>{int(t.put_oi_change)}</Cell>
                        <Cell cls={oiTone(t.put_oi_change_delta)}>
                          {dOI(t.put_oi_change_delta)}
                        </Cell>
                        <Cell cls={oiTone(t.diff_oi)}>{dOI(t.diff_oi)}</Cell>
                        <Cell>{t.diff_pct != null ? `${(t.diff_pct * 100).toFixed(1)}%` : DASH}</Cell>
                        <Cell cls={oiTone(t.dir_of_change)}>{dOI(t.dir_of_change)}</Cell>
                        <Cell>{t.pcr_oi != null ? num(t.pcr_oi, 2) : DASH}</Cell>
                        <Cell>{t.coi_pcr != null ? num(t.coi_pcr, 2) : DASH}</Cell>
                        <Cell>{t.vol_pcr != null ? num(t.vol_pcr, 2) : DASH}</Cell>
                        <td
                          className={`px-2 py-1 text-right ${
                            t.sentiment === "Bullish"
                              ? "text-emerald-500"
                              : t.sentiment === "Bearish"
                                ? "text-rose-500"
                                : "text-neutral-500"
                          }`}
                        >
                          {t.sentiment}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="mt-2 text-[11px] text-neutral-500">
                ΔOI columns are cumulative since 09:15; the (Δ) columns are the move vs. the
                previous mark. diff = put ΔOI − call ΔOI (negative ⇒ resistance-heavy). Sentiment
                is a positioning read, not a trade signal.
              </p>
            </Panel>
          )}

          <StrategyBook underlyingId={uid} expiry={p.expiry} />
        </>
      )}
    </div>
  );
}
