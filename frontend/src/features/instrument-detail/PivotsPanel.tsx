/** CPR + classic pivots — daily / weekly / monthly (docs/05 §10.13).
 *
 * Forward-looking support / resistance from the last completed period's H/L/C:
 * the CPR band (TC / pivot / BC) and classic floor R1-R3 / S1-S3, per period,
 * with the developing (in-progress) period and ~3 months of history. Computed
 * on read from D1 bars. Descriptive — no bias, no BUY/SELL, no target / stop. */
import { useState } from "react";
import { usePivots } from "@/api/queries";
import { Panel, ProblemError, Skeleton, StatGrid } from "@/components/primitives";
import type { PivotPeriod, PivotTimeframe } from "@/api/generated/schema";
import { DASH, num, price } from "@/lib/format";

const TF_LABEL: Record<string, string> = { DAILY: "Daily", WEEKLY: "Weekly", MONTHLY: "Monthly" };
const TF_ORDER = ["DAILY", "WEEKLY", "MONTHLY"];

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const pad2 = (n: number) => String(n).padStart(2, "0");

const signed = (v: number, dp = 1) => `${v >= 0 ? "+" : ""}${num(v, dp)}`;

const tierCls: Record<string, string> = {
  AT: "bg-rose-100 text-rose-800 font-medium",
  NEAR: "bg-amber-100 text-amber-800",
  FAR: "text-slate-400",
};
const widthCls: Record<string, string> = {
  NARROW: "bg-sky-100 text-sky-800",
  AVERAGE: "bg-slate-100 text-slate-600",
  WIDE: "bg-violet-100 text-violet-800",
};
const relCls: Record<string, string> = {
  HIGHER_VALUE: "text-emerald-700",
  LOWER_VALUE: "text-rose-700",
  OVERLAPPING: "text-slate-500",
  INSIDE_VALUE: "text-sky-700",
  OUTSIDE_VALUE: "text-violet-700",
  UNCHANGED: "text-slate-400",
};
const relText = (r: string | null) => (r ? r.replace(/_/g, " ").toLowerCase() : "");

const LADDER: { key: keyof PivotPeriod; label: string; band?: boolean }[] = [
  { key: "r3", label: "R3" },
  { key: "r2", label: "R2" },
  { key: "r1", label: "R1" },
  { key: "cpr_top", label: "TC", band: true },
  { key: "pivot", label: "P", band: true },
  { key: "cpr_bottom", label: "BC", band: true },
  { key: "s1", label: "S1" },
  { key: "s2", label: "S2" },
  { key: "s3", label: "S3" },
];

function LevelLadder({ p, lastPrice, at, near }: { p: PivotPeriod; lastPrice: number | null; at: number; near: number }) {
  return (
    <table className="w-full text-xs tabular-nums">
      <tbody>
        {LADDER.map(({ key, label, band }) => {
          const v = p[key] as number;
          const dist = lastPrice != null ? v - lastPrice : null;
          const tier = dist == null ? "FAR" : Math.abs(dist) <= at ? "AT" : Math.abs(dist) <= near ? "NEAR" : "FAR";
          return (
            <tr key={label} className={`border-b border-slate-50 last:border-0 ${band ? "bg-slate-50" : ""}`}>
              <td className={`px-2 py-0.5 ${band ? "font-semibold text-slate-700" : "text-slate-500"}`}>{label}</td>
              <td className="px-2 py-0.5 text-right font-mono">{price(v)}</td>
              <td
                className={`px-2 py-0.5 text-right font-mono ${
                  dist == null ? "text-slate-400" : dist > 0 ? "text-emerald-600" : "text-rose-600"
                }`}
              >
                {dist == null ? DASH : signed(dist, 1)}
              </td>
              <td className="px-2 py-0.5">
                {tier !== "FAR" && (
                  <span className={`rounded px-1 ${tierCls[tier]}`}>{tier.toLowerCase()}</span>
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

const pivotCls: Record<string, string> = {
  ABOVE: "text-emerald-700",
  BELOW: "text-rose-700",
  AT: "text-slate-500",
};

function CalendarDateHistory({ rows }: { rows: PivotPeriod[] }) {
  return (
    <div className="mt-1 max-h-72 overflow-auto">
      <table className="w-full tabular-nums">
        <thead className="sticky top-0 bg-white text-slate-400">
          <tr className="border-b border-slate-200">
            <th className="px-2 py-1 text-left">year</th>
            <th className="px-2 py-1 text-left">session</th>
            <th className="px-2 py-1 text-right">P</th>
            <th className="px-2 py-1 text-right">R1 / S1</th>
            <th className="px-2 py-1 text-right">close</th>
            <th className="px-2 py-1 text-right">ret %</th>
            <th className="px-2 py-1 text-left">close vs P</th>
            <th className="px-2 py-1 text-center">R1·S1 hit</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((h) => {
            const rl = h.realized;
            return (
              <tr key={h.year ?? h.for_date} className="border-b border-slate-50">
                <td className="px-2 py-0.5 font-medium">{h.year}</td>
                <td className="px-2 py-0.5 text-slate-500">{h.for_date?.slice(5)}</td>
                <td className="px-2 py-0.5 text-right font-mono">{price(h.pivot)}</td>
                <td className="px-2 py-0.5 text-right font-mono text-slate-500">
                  {price(h.r1)} / {price(h.s1)}
                </td>
                <td className="px-2 py-0.5 text-right font-mono">{rl ? price(rl.close) : DASH}</td>
                <td
                  className={`px-2 py-0.5 text-right font-mono ${
                    rl && rl.ret_pct != null ? (rl.ret_pct >= 0 ? "text-emerald-600" : "text-rose-600") : ""
                  }`}
                >
                  {rl && rl.ret_pct != null ? signed(rl.ret_pct, 2) : DASH}
                </td>
                <td className={`px-2 py-0.5 ${rl ? pivotCls[rl.close_vs_pivot] ?? "" : ""}`}>
                  {rl ? rl.close_vs_pivot.toLowerCase() : DASH}
                </td>
                <td className="px-2 py-0.5 text-center">
                  <span className={rl?.touched_r1 ? "text-emerald-600" : "text-slate-300"}>R1</span>
                  {" · "}
                  <span className={rl?.touched_s1 ? "text-rose-600" : "text-slate-300"}>S1</span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function TimeframeBlock({
  tf,
  block,
  lastPrice,
  at,
  near,
  calendarMode,
}: {
  tf: string;
  block: PivotTimeframe;
  lastPrice: number | null;
  at: number;
  near: number;
  calendarMode: boolean;
}) {
  const c = block.current;
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-baseline gap-2">
        <h4 className="text-sm font-semibold text-slate-800">{TF_LABEL[tf] ?? tf}</h4>
        {c && (
          <>
            <span className="font-mono text-[11px] text-slate-500">
              from {c.from_period.start === c.from_period.end
                ? c.from_period.start
                : `${c.from_period.start} → ${c.from_period.end}`}{" "}
              (H {price(c.from_period.high)} · L {price(c.from_period.low)} · C {price(c.from_period.close)})
            </span>
            <span className={`rounded px-1 text-[11px] ${widthCls[c.width_band] ?? ""}`}>
              CPR {c.width_band.toLowerCase()} · {num(c.cpr_width_pct, 2)}%
            </span>
            {c.vs_prev && (
              <span className={`text-[11px] ${relCls[c.vs_prev] ?? "text-slate-500"}`}>
                {relText(c.vs_prev)} vs prev
              </span>
            )}
          </>
        )}
      </div>

      {c ? (
        <div>
          <div className="mb-0.5 text-[11px] font-medium uppercase tracking-wide text-slate-400">Now</div>
          <LevelLadder p={c} lastPrice={lastPrice} at={at} near={near} />
        </div>
      ) : (
        <p className="text-xs text-slate-400">{DASH} no completed {TF_LABEL[tf]?.toLowerCase()} period yet.</p>
      )}

      {block.next && (
        <div className="rounded border border-dashed border-slate-300 p-1.5">
          <div className="mb-0.5 flex flex-wrap items-baseline gap-1.5 text-[11px]">
            <span className="font-medium uppercase tracking-wide text-slate-500">
              {block.next.for_label ?? "Next"}
            </span>
            {block.next.provisional && (
              <span className="rounded bg-amber-100 px-1 text-amber-800">provisional</span>
            )}
            <span className={`rounded px-1 ${widthCls[block.next.width_band] ?? ""}`}>
              CPR {block.next.width_band.toLowerCase()} · {num(block.next.cpr_width_pct, 2)}%
            </span>
            {block.next.vs_prev && (
              <span className={relCls[block.next.vs_prev] ?? "text-slate-500"}>
                {relText(block.next.vs_prev)} vs prev
              </span>
            )}
            <span className="font-mono text-slate-400">
              from {block.next.from_period.start === block.next.from_period.end
                ? block.next.from_period.start
                : `${block.next.from_period.start}→${block.next.from_period.end}`}
            </span>
          </div>
          <LevelLadder p={block.next} lastPrice={lastPrice} at={at} near={near} />
        </div>
      )}

      {block.history.length > 0 && calendarMode && tf === "DAILY" && (
        <details className="text-xs" open>
          <summary className="cursor-pointer select-none font-medium text-slate-600">
            same date — {block.history.length} years
          </summary>
          <CalendarDateHistory rows={block.history} />
        </details>
      )}

      {block.history.length > 0 && !(calendarMode && tf === "DAILY") && (
        <details className="text-xs">
          <summary className="cursor-pointer select-none text-slate-500">
            history — {block.history.length} periods
          </summary>
          <div className="mt-1 max-h-56 overflow-auto">
            <table className="w-full tabular-nums">
              <thead className="sticky top-0 bg-white text-slate-400">
                <tr className="border-b border-slate-200">
                  <th className="px-2 py-1 text-left">from</th>
                  <th className="px-2 py-1 text-right">P</th>
                  <th className="px-2 py-1 text-right">TC / BC</th>
                  <th className="px-2 py-1 text-right">CPR %</th>
                  <th className="px-2 py-1 text-right">R1 / S1</th>
                  <th className="px-2 py-1 text-left">vs prev</th>
                </tr>
              </thead>
              <tbody>
                {block.history.map((h, i) => (
                  <tr key={i} className="border-b border-slate-50">
                    <td className="px-2 py-0.5 text-slate-500">
                      {h.from_period.start === h.from_period.end
                        ? h.from_period.start.slice(5)
                        : `${h.from_period.start.slice(5)}→${h.from_period.end.slice(5)}`}
                    </td>
                    <td className="px-2 py-0.5 text-right font-mono">{price(h.pivot)}</td>
                    <td className="px-2 py-0.5 text-right font-mono text-slate-500">
                      {price(h.cpr_top)} / {price(h.cpr_bottom)}
                    </td>
                    <td className="px-2 py-0.5 text-right">
                      <span className={`rounded px-1 ${widthCls[h.width_band] ?? ""}`}>{num(h.cpr_width_pct, 2)}</span>
                    </td>
                    <td className="px-2 py-0.5 text-right font-mono text-slate-500">
                      {price(h.r1)} / {price(h.s1)}
                    </td>
                    <td className={`px-2 py-0.5 ${relCls[h.vs_prev ?? ""] ?? "text-slate-400"}`}>
                      {relText(h.vs_prev)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </div>
  );
}

export function PivotsPanel({ instrumentId }: { instrumentId: number }) {
  const [mon, setMon] = useState<number | "">("");
  const [day, setDay] = useState(1);
  const [years, setYears] = useState(20);
  const dailyOn = mon === "" ? undefined : `${pad2(Number(mon))}-${pad2(day)}`;

  // no month picked → same query key as the page header's usePivots(id): one shared fetch
  const q = usePivots(instrumentId, dailyOn ? { dailyOn, dailyYears: years } : {});
  const d = q.data;
  const at = d?.bands.at ?? 15;
  const near = d?.bands.near ?? 30;
  const calendarMode = d?.daily_history_mode === "CALENDAR_DATE";

  const sel = "rounded border border-slate-300 bg-white px-1 py-0.5 text-xs";

  return (
    <Panel
      title="CPR & pivots — daily / weekly / monthly"
      right={
        d && (
          <span className="font-mono text-xs text-slate-500">
            {d.last_price != null ? `last ${price(d.last_price)}` : "no price"} · {d.d1_bars_used} D1 bars ·
            module {d.pivots_version}
          </span>
        )
      }
    >
      {q.isLoading && !d && <Skeleton rows={10} />}
      {q.error && <ProblemError error={q.error} onRetry={() => q.refetch()} />}

      {d && (
        <div className="space-y-4">
          <p className="max-w-3xl text-sm text-slate-500">
            Classic floor pivots (R1-R3 / S1-S3) and the Central Pivot Range (TC / pivot / BC) from
            a completed period's high / low / close. <b>Now</b> = the lines in force this period;
            <b> Next</b> = the upcoming period ("tomorrow" for daily), from the in-progress period's
            data — <i>provisional</i> until it closes. A <b>narrow</b> CPR flags an expansion day,
            <b>wide</b> a rotational one. Descriptive — not a signal.
          </p>

          <div className="flex flex-wrap items-center gap-2 text-xs text-slate-600">
            <span className="font-medium">Daily history:</span>
            <label className="flex items-center gap-1">
              on
              <select
                className={sel}
                value={mon}
                onChange={(e) => setMon(e.target.value === "" ? "" : Number(e.target.value))}
              >
                <option value="">recent 3 mo</option>
                {MONTHS.map((mName, i) => (
                  <option key={mName} value={i + 1}>
                    {mName}
                  </option>
                ))}
              </select>
            </label>
            {mon !== "" && (
              <>
                <select
                  className={sel}
                  value={day}
                  onChange={(e) => setDay(Number(e.target.value))}
                  aria-label="day of month"
                >
                  {Array.from({ length: 31 }, (_, i) => i + 1).map((dn) => (
                    <option key={dn} value={dn}>
                      {dn}
                    </option>
                  ))}
                </select>
                <label className="flex items-center gap-1">
                  ·
                  <select
                    className={sel}
                    value={years}
                    onChange={(e) => setYears(Number(e.target.value))}
                    aria-label="years back"
                  >
                    {[5, 10, 15, 20, 25, 30].map((y) => (
                      <option key={y} value={y}>
                        {y} yr
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  type="button"
                  className="text-slate-400 hover:text-slate-700"
                  onClick={() => setMon("")}
                >
                  clear
                </button>
              </>
            )}
            {calendarMode && d.daily_on && (
              <span className="text-slate-400">
                — {d.timeframes.DAILY?.history.length ?? 0} sessions on/after {d.daily_on}, one per year
              </span>
            )}
          </div>

          {(d.nearest_above || d.nearest_below) && (
            <StatGrid
              rows={[
                [
                  "Next level up",
                  d.nearest_above
                    ? `${price(d.nearest_above.price)} · ${d.nearest_above.timeframe.toLowerCase()} ${d.nearest_above.name} (${signed(d.nearest_above.distance, 0)})`
                    : DASH,
                ],
                [
                  "Next level down",
                  d.nearest_below
                    ? `${price(d.nearest_below.price)} · ${d.nearest_below.timeframe.toLowerCase()} ${d.nearest_below.name} (${signed(d.nearest_below.distance, 0)})`
                    : DASH,
                ],
              ]}
            />
          )}

          <div className="grid gap-5 lg:grid-cols-3">
            {TF_ORDER.filter((tf) => d.timeframes[tf]).map((tf) => (
              <TimeframeBlock
                key={tf}
                tf={tf}
                block={d.timeframes[tf] as PivotTimeframe}
                lastPrice={d.last_price}
                at={at}
                near={near}
                calendarMode={calendarMode}
              />
            ))}
          </div>
        </div>
      )}
    </Panel>
  );
}
