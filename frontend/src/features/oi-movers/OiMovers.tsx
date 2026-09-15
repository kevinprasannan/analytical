/** Big OI movement — options only (docs/05 §11.4, docs/07 §4.22).
 *
 * The near-expiry option strikes that ADDED / REDUCED the most open interest
 * today, side by side. Each row: session ΔOI, last-15-min ΔOI, and a
 * positioning (buildup) label. Positioning vocabulary only — no BUY/SELL. */
import { useState } from "react";
import { useParams } from "react-router-dom";
import { useInstrument, useOiMovers } from "@/api/queries";
import { Badge, Panel, ProblemError, Skeleton, StatGrid } from "@/components/primitives";
import { LastUpdated } from "@/components/LastUpdated";
import type { OiMover } from "@/api/generated/schema";
import { DASH, int, num, price } from "@/lib/format";

const sInt = (v: number) => `${v > 0 ? "+" : ""}${int(v)}`;
const buildupCls: Record<string, string> = {
  LONG_BUILDUP: "bg-emerald-100 text-emerald-800",
  SHORT_BUILDUP: "bg-rose-100 text-rose-800",
  LONG_UNWINDING: "bg-amber-100 text-amber-800",
  SHORT_COVERING: "bg-sky-100 text-sky-800",
  INDETERMINATE: "bg-slate-100 text-slate-500",
  NO_DATA: "bg-slate-100 text-slate-400",
};
const otCls = (t: string) => (t === "CE" ? "text-emerald-600" : "text-rose-600");

const TIME_BANDS = [3, 5, 10, 15];
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

function MoversTable({ rows, recentMin }: { rows: OiMover[]; recentMin: number }) {
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
            <th className="px-2 py-1 text-left">type</th>
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
              <td className="px-2 py-1 font-mono">
                {int(r.strike)}
                <span className="ml-1 text-[10px] text-slate-400">{mnyShort[r.moneyness] ?? r.moneyness}</span>
              </td>
              <td className={`px-2 py-1 font-medium ${otCls(r.option_type)}`}>
                {r.option_type}
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

export function OiMovers() {
  const { id } = useParams();
  const uid = Number(id);
  const inst = useInstrument(uid);
  const [band, setBand] = useState(15);
  const [mny, setMny] = useState<string[]>([]);
  const q = useOiMovers(uid, { top: 15, timeBand: band, moneyness: mny });
  const d = q.data;

  const toggleMny = (m: string) =>
    setMny((s) => (s.includes(m) ? s.filter((x) => x !== m) : [...s, m]));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-lg font-bold">
          Big OI movers — {inst.data?.symbol ?? inst.data?.contract_key ?? `#${uid}`}
          <span className="ml-2 text-xs font-normal text-slate-500">options only</span>
          <LastUpdated q={q} asOf={d?.as_of} className="ml-2 align-middle font-normal" />
        </h1>
        <div className="flex flex-wrap items-center gap-3 text-xs">
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
        </div>
      </div>

      {q.isLoading && !d && <Skeleton rows={10} />}
      {q.error && <ProblemError error={q.error} onRetry={() => q.refetch()} />}

      {d && (
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

          <div className="grid gap-4 lg:grid-cols-2">
            <Panel title={`OI added — top ${d.top}`}>
              <MoversTable rows={d.added} recentMin={d.recent_window_min} />
            </Panel>
            <Panel title={`OI reduced — top ${d.top}`}>
              <MoversTable rows={d.reduced} recentMin={d.recent_window_min} />
            </Panel>
          </div>
          <p className="text-[11px] text-slate-500">
            Split by <b>session</b> ΔOI (from today's open); click the <b>Δ session</b> / <b>Δ
            {d.recent_window_min}m</b> headers to re-rank. <b>LTP Δ%</b> is the premium change
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
    </div>
  );
}
