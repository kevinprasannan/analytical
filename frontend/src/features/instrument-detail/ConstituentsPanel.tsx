/** Index constituents ordered by weight (docs/15).
 *
 * Weight + running cumulative + sector + concentration always; day contribution
 * to the index + breadth when a quote is reachable per name; beta / correlation
 * behind a toggle. Descriptive — it explains which names carry the index, not a
 * signal. No BUY/SELL. */
import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useConstituentLevels, useIndexConstituents } from "@/api/queries";
import { Badge, Panel, ProblemError, Skeleton, StatGrid } from "@/components/primitives";
import type { Constituent, ConstituentLevels } from "@/api/generated/schema";
import { DASH, num } from "@/lib/format";

const pct = (v: number | null | undefined, dp = 2) =>
  v == null ? DASH : `${v >= 0 ? "+" : ""}${num(v, dp)}%`;
const signed = (v: number | null | undefined, dp = 2) =>
  v == null ? DASH : `${v >= 0 ? "+" : ""}${num(v, dp)}`;
const tone = (v: number | null | undefined) =>
  v == null ? "" : v > 0 ? "text-emerald-600" : v < 0 ? "text-rose-600" : "text-slate-500";

type SortKey =
  | "rank"
  | "symbol"
  | "sector"
  | "weight_pct"
  | "change_pct"
  | "contribution_points"
  | "contribution_pct"
  | "beta"
  | "correlation";

const SORT_VAL: Record<SortKey, (c: Constituent) => number | string | null> = {
  rank: (c) => c.rank,
  symbol: (c) => c.symbol,
  sector: (c) => c.sector,
  weight_pct: (c) => c.weight_pct,
  change_pct: (c) => c.change_pct,
  contribution_points: (c) => c.contribution_points,
  contribution_pct: (c) => c.contribution_pct,
  beta: (c) => c.beta,
  correlation: (c) => c.correlation,
};

const today = () => new Date().toISOString().slice(0, 10);

const posCls = (v: string | null | undefined) =>
  v === "ABOVE" ? "text-emerald-600" : v === "BELOW" ? "text-rose-600" : "text-slate-500";
const rsiCls = (s: string | null | undefined) =>
  s === "OVERBOUGHT" ? "text-rose-600" : s === "OVERSOLD" ? "text-emerald-600" : "text-slate-600";
const crossCls = (t: string | null | undefined) =>
  t === "GOLDEN" ? "text-emerald-600 font-medium" : t === "DEATH" ? "text-rose-600 font-medium" : "text-slate-500";

export function ConstituentsPanel({ indexId }: { indexId: number }) {
  const [beta, setBeta] = useState(false);
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "rank", dir: 1 });
  const [asOfDate, setAsOfDate] = useState(""); // "" = live
  const [showLevels, setShowLevels] = useState(false);
  const q = useIndexConstituents(indexId, { includeBeta: beta, asOfDate: asOfDate || undefined });
  const d = q.data;
  const lvl = useConstituentLevels(indexId, 10, showLevels);
  const lvlBySymbol = useMemo(() => {
    const m = new Map<string, ConstituentLevels>();
    lvl.data?.stocks.forEach((s) => m.set(s.symbol, s));
    return m;
  }, [lvl.data]);

  const onSort = (key: SortKey) =>
    setSort((s) =>
      s.key === key ? { key, dir: (s.dir * -1) as 1 | -1 } : { key, dir: key === "symbol" || key === "sector" ? 1 : -1 },
    );

  const rows: Constituent[] = d
    ? [...d.items].sort((a, b) => {
        const av = SORT_VAL[sort.key](a);
        const bv = SORT_VAL[sort.key](b);
        if (av == null && bv == null) return a.rank - b.rank;
        if (av == null) return 1; // nulls last, regardless of dir
        if (bv == null) return -1;
        const cmp = typeof av === "string" ? av.localeCompare(bv as string) : av - (bv as number);
        return cmp * sort.dir;
      })
    : [];

  const arrow = (key: SortKey) => (sort.key === key ? (sort.dir === 1 ? " ↑" : " ↓") : "");
  const th = (key: SortKey, label: string, align = "text-right") => (
    <th
      className={`cursor-pointer select-none px-2 py-1 hover:text-slate-700 ${align}`}
      onClick={() => onSort(key)}
    >
      {label}
      {arrow(key)}
    </th>
  );

  return (
    <Panel
      title="Constituents — by weight"
      right={
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
          {d && (
            <span className="font-mono">
              {d.n_constituents} names · Σ {num(d.total_weight_pct, 1)}%
              {d.weights_effective_date ? ` · as of ${d.weights_effective_date}` : ""}
            </span>
          )}
          {d && (
            <Badge tone={d.historical ? "warn" : "muted"}>
              {d.historical ? `historical: ${d.as_of ?? asOfDate}` : d.source === "seed" ? "weights only" : d.source}
            </Badge>
          )}
          <label className="flex items-center gap-1">
            date
            <input
              type="date"
              className="rounded border border-slate-300 px-1 py-0.5"
              max={today()}
              value={asOfDate}
              onChange={(e) => setAsOfDate(e.target.value)}
            />
          </label>
          {asOfDate && (
            <button
              type="button"
              className="text-slate-400 underline hover:text-slate-600"
              onClick={() => setAsOfDate("")}
            >
              back to live
            </button>
          )}
          <label className="flex items-center gap-1">
            <input type="checkbox" checked={beta} onChange={(e) => setBeta(e.target.checked)} />
            beta / corr
          </label>
        </div>
      }
    >
      {q.isLoading && !d && <Skeleton rows={10} />}
      {q.error && <ProblemError error={q.error} onRetry={() => q.refetch()} />}

      {d && (
        <div className="space-y-4">
          <p className="max-w-3xl text-sm text-slate-500">
            Free-float index weights (seeded, owner-maintained). <b>Contribution</b> = a name's day
            move × its weight → approximate index points it added; <b>rank</b> is by that. Breadth
            says whether the move is broad or carried by a few names. Descriptive — not a signal.
          </p>

          <StatGrid
            rows={[
              [
                "Index change (approx)",
                <span key="c" className={tone(d.index_change_pct)}>
                  {pct(d.index_change_pct)}
                  {d.index_ltp != null ? ` · ${num(d.index_ltp, 1)}` : ""}
                </span>,
              ],
              ["Top 5 / 10 weight", `${num(d.concentration.top5_pct, 1)}% / ${num(d.concentration.top10_pct, 1)}%`],
              ["Concentration (HHI)", num(d.concentration.hhi, 4)],
              ...(d.breadth
                ? [
                    [
                      "Total contribution",
                      d.breadth.net_contribution_points == null ? (
                        DASH
                      ) : (
                        <span key="tot" className={tone(d.breadth.net_contribution_points)}>
                          {signed(d.breadth.net_contribution_points, 1)} pts
                          {d.index_ltp != null && d.index_prev_close != null
                            ? ` (index moved ${signed(d.index_ltp - d.index_prev_close, 1)})`
                            : ""}
                        </span>
                      ),
                    ] as [string, ReactNode],
                    [
                      "Advances / declines",
                      `${d.breadth.advances} up · ${d.breadth.declines} dn · ${d.breadth.unchanged} flat (of ${d.breadth.covered})`,
                    ] as [string, string],
                    [
                      "Weighted A/D",
                      <span key="ad" className={tone(d.breadth.advance_decline_weight)}>
                        {signed(d.breadth.advance_decline_weight, 1)} pts weight
                        {` (${num(d.breadth.up_weight_pct, 1)}% up vs ${num(d.breadth.down_weight_pct, 1)}% dn)`}
                      </span>,
                    ] as [string, ReactNode],
                    [
                      "Move carried by top 5",
                      d.breadth.top5_move_share == null
                        ? DASH
                        : `${num(d.breadth.top5_move_share * 100, 0)}%`,
                    ] as [string, string],
                  ]
                : []),
            ]}
          />

          {d.sectors.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-xs tabular-nums">
                <thead className="text-slate-400">
                  <tr className="border-b border-slate-200">
                    <th className="px-2 py-1 text-left">sector</th>
                    <th className="px-2 py-1 text-right">weight %</th>
                    <th className="px-2 py-1 text-right">names</th>
                    <th className="px-2 py-1 text-right">contrib pts</th>
                    <th className="px-2 py-1 text-right">contrib %</th>
                  </tr>
                </thead>
                <tbody>
                  {d.sectors.map((s) => (
                    <tr key={s.sector} className="border-b border-slate-100">
                      <td className="px-2 py-1">{s.sector}</td>
                      <td className="px-2 py-1 text-right">{num(s.weight_pct, 2)}</td>
                      <td className="px-2 py-1 text-right text-slate-400">{s.count}</td>
                      <td className={`px-2 py-1 text-right ${tone(s.contribution_points)}`}>
                        {s.contribution_points == null ? DASH : signed(s.contribution_points, 1)}
                      </td>
                      <td className={`px-2 py-1 text-right ${tone(s.contribution_pct)}`}>
                        {s.contribution_pct == null ? DASH : signed(s.contribution_pct, 3)}
                      </td>
                    </tr>
                  ))}
                </tbody>
                {d.breadth?.net_contribution_points != null && (
                  <tfoot>
                    <tr className="border-t-2 border-slate-300 font-medium">
                      <td className="px-2 py-1">Total</td>
                      <td className="px-2 py-1 text-right">{num(d.total_weight_pct, 2)}</td>
                      <td className="px-2 py-1 text-right text-slate-400">{d.n_constituents}</td>
                      <td
                        className={`px-2 py-1 text-right ${tone(d.breadth.net_contribution_points)}`}
                      >
                        {signed(d.breadth.net_contribution_points, 1)}
                      </td>
                      <td className={`px-2 py-1 text-right ${tone(d.breadth.net_contribution_pct)}`}>
                        {d.breadth.net_contribution_pct == null
                          ? DASH
                          : signed(d.breadth.net_contribution_pct, 3)}
                      </td>
                    </tr>
                  </tfoot>
                )}
              </table>
            </div>
          )}

          {/* Top 10 by weight — the "what carries the index" hint, all columns */}
          <div>
            <div className="mb-1 flex flex-wrap items-center gap-2">
              <span className="text-xs font-semibold text-slate-600">
                Top 10 by weight — what carries the index
              </span>
              <label className="flex items-center gap-1 text-xs text-slate-500">
                <input
                  type="checkbox"
                  checked={showLevels}
                  onChange={(e) => setShowLevels(e.target.checked)}
                />
                + levels &amp; indicators
              </label>
              {showLevels && lvl.isFetching && <span className="text-xs text-slate-400">loading… (live fetch)</span>}
              {showLevels && lvl.error && (
                <span className="text-xs text-rose-600">levels unavailable</span>
              )}
              {showLevels && (lvl.data?.errors.length ?? 0) > 0 && (
                <span className="text-xs text-amber-600">
                  {lvl.data?.errors.length} name(s) failed
                </span>
              )}
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs tabular-nums">
                <thead className="text-slate-400">
                  <tr className="border-b border-slate-200">
                    <th className="px-2 py-1 text-right">#</th>
                    <th className="px-2 py-1 text-left">symbol</th>
                    <th className="px-2 py-1 text-left">sector</th>
                    <th className="px-2 py-1 text-right">weight %</th>
                    <th className="px-2 py-1 text-right">cum %</th>
                    <th className="px-2 py-1 text-right">chg %</th>
                    <th className="px-2 py-1 text-right">contrib pts</th>
                    <th className="px-2 py-1 text-right">contrib %</th>
                    <th className="px-2 py-1 text-right">c-rank</th>
                    {beta && <th className="px-2 py-1 text-right">beta</th>}
                    {beta && <th className="px-2 py-1 text-right">corr</th>}
                    {showLevels && (
                      <>
                        <th className="border-l border-slate-200 px-2 py-1 text-right">last</th>
                        <th className="px-2 py-1 text-right">P</th>
                        <th className="px-2 py-1 text-left">vs P</th>
                        <th className="px-2 py-1 text-right">R1 / S1</th>
                        <th className="px-2 py-1 text-right">52w</th>
                        <th className="px-2 py-1 text-right">RSI d/h</th>
                        <th className="px-2 py-1 text-right">%B</th>
                        <th className="px-2 py-1 text-left">50/200</th>
                        <th className="px-2 py-1 text-left">read</th>
                      </>
                    )}
                  </tr>
                </thead>
                <tbody>
                  {[...d.items]
                    .sort((a, b) => b.weight_pct - a.weight_pct)
                    .slice(0, 10)
                    .map((c: Constituent) => {
                      const L = lvlBySymbol.get(c.symbol);
                      return (
                        <tr key={c.symbol} className="border-b border-slate-100">
                          <td className="px-2 py-0.5 text-right text-slate-400">{c.rank}</td>
                          <td className="px-2 py-0.5 font-medium" title={c.name}>
                            {c.symbol}
                          </td>
                          <td className="px-2 py-0.5 text-slate-500">{c.sector}</td>
                          <td className="px-2 py-0.5 text-right font-medium">{num(c.weight_pct, 3)}</td>
                          <td className="px-2 py-0.5 text-right text-slate-400">
                            {num(c.cumulative_weight_pct, 1)}
                          </td>
                          <td className={`px-2 py-0.5 text-right ${tone(c.change_pct)}`}>
                            {c.change_pct == null ? DASH : signed(c.change_pct, 2)}
                          </td>
                          <td className={`px-2 py-0.5 text-right ${tone(c.contribution_points)}`}>
                            {c.contribution_points == null ? DASH : signed(c.contribution_points, 1)}
                          </td>
                          <td className={`px-2 py-0.5 text-right ${tone(c.contribution_pct)}`}>
                            {c.contribution_pct == null ? DASH : signed(c.contribution_pct, 3)}
                          </td>
                          <td className="px-2 py-0.5 text-right text-slate-400">
                            {c.contribution_rank ?? DASH}
                          </td>
                          {beta && (
                            <td className="px-2 py-0.5 text-right">
                              {c.beta == null ? DASH : num(c.beta, 2)}
                            </td>
                          )}
                          {beta && (
                            <td className="px-2 py-0.5 text-right text-slate-400">
                              {c.correlation == null ? DASH : num(c.correlation, 2)}
                            </td>
                          )}
                          {showLevels && (
                            <>
                              <td className="border-l border-slate-200 px-2 py-0.5 text-right font-mono">
                                {L ? num(L.last_price, 1) : DASH}
                              </td>
                              <td className="px-2 py-0.5 text-right font-mono text-slate-500">
                                {L ? num(L.pivot.p, 1) : DASH}
                              </td>
                              <td className={`px-2 py-0.5 ${posCls(L?.pivot.close_vs_pivot)}`}>
                                {L ? L.pivot.close_vs_pivot.toLowerCase() : DASH}
                              </td>
                              <td className="px-2 py-0.5 text-right font-mono text-slate-500">
                                {L ? `${num(L.pivot.r1, 1)} / ${num(L.pivot.s1, 1)}` : DASH}
                              </td>
                              <td className="px-2 py-0.5 text-right">
                                {L?.range52.position == null
                                  ? DASH
                                  : `${num(L.range52.position * 100, 0)}%`}
                              </td>
                              <td className="px-2 py-0.5 text-right">
                                {L?.rsi_d1 ? (
                                  <span className={rsiCls(L.rsi_d1.state)}>{num(L.rsi_d1.value, 0)}</span>
                                ) : (
                                  DASH
                                )}
                                <span className="text-slate-300">/</span>
                                {L?.rsi_h1 ? (
                                  <span className={rsiCls(L.rsi_h1.state)}>{num(L.rsi_h1.value, 0)}</span>
                                ) : (
                                  DASH
                                )}
                              </td>
                              <td className="px-2 py-0.5 text-right">
                                {L?.bollinger_d1?.pct_b == null ? DASH : num(L.bollinger_d1.pct_b, 2)}
                              </td>
                              <td className={`px-2 py-0.5 ${crossCls(L?.ma.cross_type)}`}>
                                {L?.ma.cross_state == null
                                  ? DASH
                                  : L.ma.cross_state === "ABOVE"
                                    ? "50›200"
                                    : "50‹200"}
                                {L?.ma.recent_cross ? " ●" : ""}
                              </td>
                              <td className="px-2 py-0.5 text-slate-500" title={L?.hint}>
                                {L?.hint ?? (lvl.isFetching ? "…" : DASH)}
                              </td>
                            </>
                          )}
                        </tr>
                      );
                    })}
                </tbody>
              </table>
            </div>
          </div>

          <div className="max-h-[65vh] overflow-auto">
            <table className="w-full text-xs tabular-nums">
              <thead className="sticky top-0 z-10 bg-white text-slate-400 [&_th]:bg-white">
                <tr className="border-b border-slate-200">
                  {th("rank", "#")}
                  {th("symbol", "symbol", "text-left")}
                  {th("sector", "sector", "text-left")}
                  {th("weight_pct", "weight %")}
                  <th className="px-2 py-1 text-right">cum %</th>
                  {th("change_pct", "chg %")}
                  {th("contribution_points", "contrib pts")}
                  {th("contribution_pct", "contrib %")}
                  <th className="px-2 py-1 text-right">rank</th>
                  {beta && th("beta", "beta")}
                  {beta && th("correlation", "corr")}
                </tr>
              </thead>
              <tbody>
                {rows.map((c: Constituent) => (
                  <tr key={c.symbol} className="border-b border-slate-100">
                    <td className="px-2 py-1 text-right text-slate-400">{c.rank}</td>
                    <td className="px-2 py-1 font-medium" title={c.name}>
                      {c.symbol}
                    </td>
                    <td className="px-2 py-1 text-slate-500">{c.sector}</td>
                    <td className="px-2 py-1 text-right font-medium">{num(c.weight_pct, 3)}</td>
                    <td className="px-2 py-1 text-right text-slate-400">
                      {num(c.cumulative_weight_pct, 1)}
                    </td>
                    <td className={`px-2 py-1 text-right ${tone(c.change_pct)}`}>
                      {c.change_pct == null ? DASH : signed(c.change_pct, 2)}
                    </td>
                    <td className={`px-2 py-1 text-right ${tone(c.contribution_points)}`}>
                      {c.contribution_points == null ? DASH : signed(c.contribution_points, 1)}
                    </td>
                    <td className={`px-2 py-1 text-right ${tone(c.contribution_pct)}`}>
                      {c.contribution_pct == null ? DASH : signed(c.contribution_pct, 3)}
                    </td>
                    <td className="px-2 py-1 text-right text-slate-400">
                      {c.contribution_rank ?? DASH}
                    </td>
                    {beta && (
                      <td className="px-2 py-1 text-right">
                        {c.beta == null ? DASH : num(c.beta, 2)}
                      </td>
                    )}
                    {beta && (
                      <td className="px-2 py-1 text-right text-slate-400">
                        {c.correlation == null ? DASH : num(c.correlation, 2)}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t-2 border-slate-300 font-medium">
                  <td className="px-2 py-1" colSpan={3}>
                    Total ({d.n_constituents})
                  </td>
                  <td className="px-2 py-1 text-right">{num(d.total_weight_pct, 2)}</td>
                  <td className="px-2 py-1 text-right text-slate-400">
                    {num(d.total_weight_pct, 1)}
                  </td>
                  <td className="px-2 py-1" />
                  <td
                    className={`px-2 py-1 text-right ${tone(
                      d.breadth?.net_contribution_points ?? null,
                    )}`}
                  >
                    {d.breadth?.net_contribution_points == null
                      ? DASH
                      : signed(d.breadth.net_contribution_points, 1)}
                  </td>
                  <td
                    className={`px-2 py-1 text-right ${tone(
                      d.breadth?.net_contribution_pct ?? null,
                    )}`}
                  >
                    {d.breadth?.net_contribution_pct == null
                      ? DASH
                      : signed(d.breadth.net_contribution_pct, 3)}
                  </td>
                  <td className="px-2 py-1" />
                  {beta && <td className="px-2 py-1" />}
                  {beta && <td className="px-2 py-1" />}
                </tr>
              </tfoot>
            </table>
          </div>

          <p className="text-[11px] text-slate-400">
            engine {d.algo_version} · module {d.index_constituents_version}
            {d.beta_lookback ? ` · beta over ${d.beta_lookback} D1 sessions` : ""}
          </p>
        </div>
      )}
    </Panel>
  );
}
