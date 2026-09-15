import type { ReactNode } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { useInstrument } from "@/api/queries";
import { useOptionChain } from "@/api/queries";
import { Panel, ProblemError, Skeleton, StatGrid, Badge } from "@/components/primitives";
import { LastUpdated } from "@/components/LastUpdated";
import { StrategyBook } from "@/features/option-strategy/StrategyBook";
import type { ChainLeg } from "@/api/generated/schema";
import { DASH, int, num, price } from "@/lib/format";

const ivPct = (v: number | null) => (v == null ? DASH : `${(v * 100).toFixed(1)}`);
const greek = (v: number | null, dp = 3) => (v == null ? DASH : num(v, dp));
const dOI = (v: number | null) =>
  v == null ? DASH : `${v > 0 ? "+" : ""}${int(v)}`;

function Cell({
  children,
  tone,
  hl,
}: {
  children: ReactNode;
  tone?: "up" | "down";
  hl?: "high" | "low";
}) {
  const c = tone === "up" ? "text-emerald-500" : tone === "down" ? "text-rose-500" : "";
  // open == session high → premium topped at the bell and faded (amber)
  // open == session low  → premium bottomed at the bell and rose (sky)
  const bg = hl === "high" ? "bg-amber-500/20" : hl === "low" ? "bg-sky-500/20" : "";
  return <td className={`px-2 py-1 text-right tabular-nums ${c} ${bg}`}>{children}</td>;
}

/** O / H / L cells for one leg, with the open tinted when it == session high/low. */
function OhlCells({ leg }: { leg: ChainLeg | null }) {
  const oHl = leg?.open_at_high ? "high" : leg?.open_at_low ? "low" : undefined;
  return (
    <>
      <Cell hl={oHl}>{price(leg?.day_open ?? null)}</Cell>
      <Cell hl={leg?.open_at_high ? "high" : undefined}>{price(leg?.day_high ?? null)}</Cell>
      <Cell hl={leg?.open_at_low ? "low" : undefined}>{price(leg?.day_low ?? null)}</Cell>
    </>
  );
}

const dPct = (v: number | null) =>
  v == null ? "" : ` ${v > 0 ? "+" : ""}${(v * 100).toFixed(0)}%`;

function LegCells({ leg, side }: { leg: ChainLeg | null; side: "call" | "put" }) {
  if (!leg) return <>{Array.from({ length: 9 }).map((_, i) => <Cell key={i}>{DASH}</Cell>)}</>;
  return (
    <>
      <td
        className={`px-2 py-1 text-right tabular-nums ${
          leg.crowded
            ? "bg-fuchsia-500/20 font-semibold"
            : leg.oi_change && leg.oi_change > 0
              ? "text-emerald-500"
              : leg.oi_change && leg.oi_change < 0
                ? "text-rose-500"
                : ""
        }`}
        title={leg.crowded ? "crowded — biggest OI build on this side" : undefined}
      >
        {leg.crowded && "🔥"}
        {dOI(leg.oi_change)}
        <span className="text-[10px] text-neutral-400">{dPct(leg.oi_change_pct)}</span>
      </td>
      <Cell>{int(leg.oi)}</Cell>
      <Cell>{greek(leg.theta, 1)}</Cell>
      <Cell>{greek(leg.delta)}</Cell>
      <Cell>{ivPct(leg.iv)}</Cell>
      <OhlCells leg={leg} />
      <Cell tone={side === "call" ? "up" : "down"}>{price(leg.ltp)}</Cell>
    </>
  );
}

const WINDOWS = [
  { id: "8", label: "±8" },
  { id: "12", label: "±12" },
  { id: "20", label: "±20" },
  { id: "all", label: "all" },
] as const;
type WinId = (typeof WINDOWS)[number]["id"];

export function OptionChain() {
  const { id } = useParams();
  const uid = Number(id);
  const inst = useInstrument(uid);
  const [expiry, setExpiry] = useState<string | undefined>(undefined);
  const [win, setWin] = useState<WinId>("12");
  const [follow, setFollow] = useState(true);
  const q = useOptionChain(uid, expiry);
  const ch = q.data;

  // the row nearest the ATM strike (fallback: nearest to spot)
  const atmIdx = useMemo(() => {
    if (!ch || ch.rows.length === 0) return -1;
    if (ch.atm_strike != null) {
      const exact = ch.rows.findIndex((r) => r.strike === ch.atm_strike);
      if (exact >= 0) return exact;
    }
    let best = 0;
    let bestD = Infinity;
    ch.rows.forEach((r, i) => {
      const d = Math.abs(r.strike - ch.spot);
      if (d < bestD) {
        bestD = d;
        best = i;
      }
    });
    return best;
  }, [ch]);

  const visibleRows = useMemo(() => {
    if (!ch) return [];
    const indexed = ch.rows.map((r, i) => ({ r, i }));
    if (win === "all" || atmIdx < 0) return indexed;
    // keep 2k+1 strikes centred on ATM; if ATM is near an edge, slide the window
    // so you still get a full band (the "intelligence")
    const total = 2 * Number(win) + 1;
    const start = Math.max(0, Math.min(atmIdx - Number(win), ch.rows.length - total));
    return indexed.slice(start, start + total);
  }, [ch, win, atmIdx]);

  const scrollBox = useRef<HTMLDivElement>(null);
  const atmRow = useRef<HTMLTableRowElement>(null);
  // re-centre on the ATM row whenever it changes (spot moved) — the "auto adjust".
  // scroll only the table box, never the page.
  useEffect(() => {
    if (!follow) return;
    const box = scrollBox.current;
    const row = atmRow.current;
    if (!box || !row) return;
    const boxR = box.getBoundingClientRect();
    const rowR = row.getBoundingClientRect();
    const delta = rowR.top - boxR.top - (box.clientHeight / 2 - rowR.height / 2);
    box.scrollTo({ top: Math.max(0, box.scrollTop + delta), behavior: "smooth" });
  }, [ch?.atm_strike, win, follow, visibleRows.length]);

  const atmRowData = atmIdx >= 0 ? ch?.rows[atmIdx] : undefined;

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-bold">
        Option chain — {inst.data?.symbol ?? inst.data?.contract_key ?? `#${uid}`}
        <LastUpdated q={q} className="ml-2 align-middle font-normal" />
      </h1>

      {q.isLoading && <Skeleton rows={10} />}
      {q.error && <ProblemError error={q.error} onRetry={() => q.refetch()} />}

      {ch && (
        <>
          <Panel
            title="Summary"
            right={
              <select
                className="rounded border border-neutral-700 bg-transparent px-2 py-1 text-xs"
                value={ch.expiry}
                onChange={(e) => setExpiry(e.target.value)}
              >
                {ch.expiries.map((e) => (
                  <option key={e} value={e}>{e}</option>
                ))}
              </select>
            }
          >
            <StatGrid
              rows={[
                ["Spot", price(ch.spot)],
                ["Expiry", `${ch.expiry} (${ch.days_to_expiry}d)`],
                ["ATM strike", ch.atm_strike != null ? int(ch.atm_strike) : DASH],
                ["PCR (OI)", ch.pcr_oi != null ? num(ch.pcr_oi, 2) : DASH],
                ["Max pain", ch.max_pain_strike != null ? int(ch.max_pain_strike) : DASH],
                [
                  "Crowded (OI build)",
                  <span key="cr">
                    <span
                      className={
                        ch.crowded_side === "CALLS"
                          ? "font-semibold text-rose-600"
                          : ch.crowded_side === "PUTS"
                            ? "font-semibold text-emerald-600"
                            : "text-slate-500"
                      }
                    >
                      🔥 {ch.crowded_side.toLowerCase()}
                    </span>
                    {ch.crowded_side === "CALLS" && ch.crowded_call_strike != null
                      ? ` @ ${int(ch.crowded_call_strike)}${
                          ch.crowded_call_frac != null
                            ? ` (${(ch.crowded_call_frac * 100).toFixed(0)}%)`
                            : ""
                        }`
                      : ch.crowded_side === "PUTS" && ch.crowded_put_strike != null
                        ? ` @ ${int(ch.crowded_put_strike)}${
                            ch.crowded_put_frac != null
                              ? ` (${(ch.crowded_put_frac * 100).toFixed(0)}%)`
                              : ""
                          }`
                        : ""}
                  </span>,
                ],
                ["Total CE / PE OI", `${int(ch.total_call_oi)} / ${int(ch.total_put_oi)}`],
                ["Risk-free rate", `${(ch.risk_free_rate * 100).toFixed(2)}%`],
                ["Engine", ch.algo_version],
              ]}
            />
          </Panel>

          <Panel
            title={
              win === "all"
                ? `${ch.rows.length} strikes`
                : `ATM ±${win} — ${visibleRows.length} of ${ch.rows.length} strikes`
            }
            right={
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <div className="inline-flex overflow-hidden rounded border border-slate-300">
                  {WINDOWS.map((w) => (
                    <button
                      key={w.id}
                      type="button"
                      onClick={() => setWin(w.id)}
                      className={`px-2 py-0.5 ${win === w.id ? "bg-slate-800 text-white" : "text-slate-600 hover:bg-slate-100"}`}
                    >
                      {w.label}
                    </button>
                  ))}
                </div>
                <label className="flex items-center gap-1 text-slate-500">
                  <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} />
                  follow ATM
                </label>
                <Badge tone="muted">table only</Badge>
              </div>
            }
          >
            {/* pinned ATM read — stays visible as spot moves and the chain re-centres */}
            {atmRowData && (
              <div className="sticky top-0 z-20 mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 rounded border border-amber-300 bg-amber-50 px-3 py-1.5 text-xs">
                <span className="font-semibold text-amber-800">ATM {int(atmRowData.strike)}</span>
                <span className="text-slate-600">spot {price(ch.spot)}</span>
                <span className="text-emerald-700">
                  CE {price(atmRowData.call?.ltp ?? null)}{" "}
                  <span className="text-slate-400">ΔOI {dOI(atmRowData.call?.oi_change ?? null)}</span>
                </span>
                <span className="text-rose-700">
                  PE {price(atmRowData.put?.ltp ?? null)}{" "}
                  <span className="text-slate-400">ΔOI {dOI(atmRowData.put?.oi_change ?? null)}</span>
                </span>
                <span className="text-slate-500">
                  PCR {ch.pcr_oi != null ? num(ch.pcr_oi, 2) : DASH} · max-pain{" "}
                  {ch.max_pain_strike != null ? int(ch.max_pain_strike) : DASH}
                </span>
                {q.isFetching && <span className="text-slate-400">updating…</span>}
              </div>
            )}
            <div ref={scrollBox} className="max-h-[70vh] overflow-auto">
              <table className="w-full text-xs">
                <thead className="sticky top-0 z-10 bg-white text-neutral-400 [&_th]:bg-white">
                  <tr>
                    <th colSpan={9} className="px-2 py-1 text-center font-semibold text-emerald-500">
                      CALLS
                    </th>
                    <th className="px-2 py-1 text-center">STRIKE</th>
                    <th colSpan={9} className="px-2 py-1 text-center font-semibold text-rose-500">
                      PUTS
                    </th>
                  </tr>
                  <tr className="border-b border-neutral-800">
                    {["ΔOI", "OI", "θ/d", "Δ", "IV%", "O", "H", "L", "LTP"].map((h, i) => (
                      <th key={`c-${i}`} className="px-2 py-1 text-right">{h}</th>
                    ))}
                    <th className="px-2 py-1"></th>
                    {["LTP", "O", "H", "L", "IV%", "Δ", "θ/d", "OI", "ΔOI"].map((h, i) => (
                      <th key={`p-${i}`} className="px-2 py-1 text-right">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {visibleRows.map(({ r: row, i }) => {
                    const atm = i === atmIdx;
                    const near = Math.abs(i - atmIdx) === 1;
                    return (
                      <tr
                        key={row.strike}
                        ref={atm ? atmRow : undefined}
                        className={`border-b border-neutral-900 ${
                          atm
                            ? "bg-amber-100/70 font-semibold ring-1 ring-amber-400"
                            : near
                              ? "bg-amber-50/50"
                              : ""
                        }`}
                      >
                        <LegCells leg={row.call} side="call" />
                        <td className="px-2 py-1 text-center font-mono">
                          {int(row.strike)}
                          {atm && <span className="ml-1 text-[10px] text-amber-400">ATM</span>}
                        </td>
                        {/* puts, mirrored order: LTP, O, H, L, IV, Δ, θ, OI, ΔOI */}
                        <Cell tone="down">{price(row.put?.ltp ?? null)}</Cell>
                        <OhlCells leg={row.put} />
                        <Cell>{ivPct(row.put?.iv ?? null)}</Cell>
                        <Cell>{greek(row.put?.delta ?? null)}</Cell>
                        <Cell>{greek(row.put?.theta ?? null, 1)}</Cell>
                        <Cell>{int(row.put?.oi ?? null)}</Cell>
                        <td
                          className={`px-2 py-1 text-right tabular-nums ${
                            row.put?.crowded
                              ? "bg-fuchsia-500/20 font-semibold"
                              : row.put?.oi_change && row.put.oi_change > 0
                                ? "text-emerald-500"
                                : row.put?.oi_change && row.put.oi_change < 0
                                  ? "text-rose-500"
                                  : ""
                          }`}
                          title={row.put?.crowded ? "crowded — biggest OI build on this side" : undefined}
                        >
                          {row.put?.crowded && "🔥"}
                          {dOI(row.put?.oi_change ?? null)}
                          <span className="text-[10px] text-neutral-400">
                            {dPct(row.put?.oi_change_pct ?? null)}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-neutral-500">
              <span>O / H / L / LTP = this contract&rsquo;s session range from the M1 bars.</span>
              <span className="inline-flex items-center gap-1">
                <span className="inline-block h-3 w-3 rounded-sm bg-amber-500/40" /> open = high
                (topped at the bell, faded)
              </span>
              <span className="inline-flex items-center gap-1">
                <span className="inline-block h-3 w-3 rounded-sm bg-sky-500/40" /> open = low
                (bottomed at the bell, rose)
              </span>
              <span>IV / greeks / PCR / max-pain computed on read.</span>
            </p>
          </Panel>

          <StrategyBook underlyingId={uid} expiry={ch.expiry} />
        </>
      )}
    </div>
  );
}
