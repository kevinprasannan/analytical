import type { ReactNode } from "react";
import { useState } from "react";
import { useParams } from "react-router-dom";
import { useInstrument, useDailyDigest } from "@/api/queries";
import { Badge, Panel, ProblemError, Skeleton, StatGrid } from "@/components/primitives";
import { LastUpdated } from "@/components/LastUpdated";
import type { DigestRow } from "@/api/generated/schema";
import { DASH, num, price } from "@/lib/format";

const RANGE_TONE: Record<string, string> = {
  OUTSIDE: "bg-amber-500/15 text-amber-600",
  PDH_BREAK: "bg-emerald-500/15 text-emerald-600",
  PDL_BREAK: "bg-rose-500/15 text-rose-600",
  INSIDE: "bg-neutral-500/10 text-neutral-500",
};

const DAYTYPE_TONE: Record<string, string> = {
  TREND_UP: "text-emerald-600 font-semibold",
  TREND_DOWN: "text-rose-600 font-semibold",
  LARGE_RANGE: "text-amber-600",
  NEUTRAL_EXTREME: "text-amber-600",
  NEUTRAL: "text-neutral-500",
  RANGE: "text-sky-600",
};

const SORTS = [
  { value: "-d", label: "date ↓" },
  { value: "d", label: "date ↑" },
  { value: "-change", label: "change % ↓" },
  { value: "-range", label: "range % ↓" },
  { value: "-gap", label: "gap % ↓" },
];
const PAGE_SIZES = [50, 100, 250, 500];

const sgn = (v: number) => (v > 0 ? "text-emerald-600" : v < 0 ? "text-rose-600" : "");
const pct = (v: number) => `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;

function Num({ children, cls }: { children: ReactNode; cls?: string }) {
  return <td className={`px-2 py-1 text-right tabular-nums ${cls ?? ""}`}>{children}</td>;
}

function Row({ r }: { r: DigestRow }) {
  return (
    <tr className="border-b border-neutral-900">
      <td className="px-2 py-1 font-mono whitespace-nowrap">{r.d}</td>
      <td className="px-2 py-1 text-neutral-500">{r.weekday.slice(0, 3)}</td>
      <Num>{price(r.open)}</Num>
      <Num>{price(r.high)}</Num>
      <Num>{price(r.low)}</Num>
      <Num>{price(r.close)}</Num>
      <Num cls={sgn(r.change_pct)}>{pct(r.change_pct)}</Num>
      <Num cls={sgn(r.gap_pct)}>{pct(r.gap_pct)}</Num>
      <Num>{r.range_pct.toFixed(2)}%</Num>
      <Num cls={r.pdh_broken ? "text-emerald-600 font-semibold" : "text-neutral-500"}>
        {price(r.pdh)}
      </Num>
      <Num cls={r.pdl_broken ? "text-rose-600 font-semibold" : "text-neutral-500"}>
        {price(r.pdl)}
      </Num>
      <td className="px-2 py-1 text-center">
        <span className={`rounded px-1.5 py-0.5 text-[11px] ${RANGE_TONE[r.range_type] ?? ""}`}>
          {r.range_type.replace("_", " ").toLowerCase()}
          {r.pdh_close_above ? " · c>PDH" : r.pdl_close_below ? " · c<PDL" : ""}
        </span>
      </td>
      <Num>
        {r.close_range_pos != null ? `${(r.close_range_pos * 100).toFixed(0)}%` : DASH}
      </Num>
      <td className={`px-2 py-1 text-[11px] ${DAYTYPE_TONE[r.d1_day_type] ?? "text-neutral-500"}`}>
        {r.d1_day_type.replace(/_/g, " ").toLowerCase()}
        {r.day_type && r.day_type !== r.d1_day_type && (
          <span className="ml-1 text-neutral-400">· tpo {r.day_type.toLowerCase()}</span>
        )}
      </td>
      <td className="px-2 py-1 text-neutral-400">
        {r.profile_shape
          ? `${r.profile_shape}${r.poc != null ? ` · POC ${price(r.poc)}` : ""}${
              r.close_vs_value ? ` · c ${r.close_vs_value.toLowerCase()} VA` : ""
            }`
          : DASH}
      </td>
    </tr>
  );
}

export function DailyDigest() {
  const { id } = useParams();
  const iid = Number(id);
  const inst = useInstrument(iid);
  const [start, setStart] = useState<string>();
  const [end, setEnd] = useState<string>();
  const [sort, setSort] = useState("-d");
  const [pageSize, setPageSize] = useState(100);
  const [offset, setOffset] = useState(0);
  const [gapMin, setGapMin] = useState<string>("");
  const [gapMax, setGapMax] = useState<string>("");
  const [chgMin, setChgMin] = useState<string>("");
  const [chgMax, setChgMax] = useState<string>("");
  const num_ = (s: string) => (s.trim() === "" ? undefined : Number(s));

  const q = useDailyDigest(iid, {
    start,
    end,
    sort,
    limit: pageSize,
    offset,
    gap_min_pct: num_(gapMin),
    gap_max_pct: num_(gapMax),
    chg_min_pct: num_(chgMin),
    chg_max_pct: num_(chgMax),
  });
  const hasGapChgFilter = gapMin || gapMax || chgMin || chgMax;
  const clearGapChgFilter = () => {
    setGapMin("");
    setGapMax("");
    setChgMin("");
    setChgMax("");
    setOffset(0);
  };
  const applyGapFadePreset = () => {
    setGapMin("0.5");
    setGapMax("");
    setChgMin("");
    setChgMax("-0.5");
    setOffset(0);
  };
  const d = q.data;
  const s = d?.summary;
  const pctOf = (n: number) => (s && s.days ? ` (${((n / s.days) * 100).toFixed(0)}%)` : "");

  const reset = () => setOffset(0);

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-bold">
        Daily digest — {inst.data?.symbol ?? inst.data?.contract_key ?? `#${iid}`}
        <LastUpdated q={q} className="ml-2 align-middle font-normal" />
      </h1>

      <Panel title="Filter">
        <div className="flex flex-wrap items-end gap-3 text-xs">
          <label className="flex flex-col gap-0.5 text-slate-500">
            from
            <input
              type="date"
              className="rounded border border-slate-300 bg-white px-2 py-1 text-sm text-slate-800"
              value={start ?? ""}
              onChange={(e) => {
                setStart(e.target.value || undefined);
                reset();
              }}
            />
          </label>
          <label className="flex flex-col gap-0.5 text-slate-500">
            to
            <input
              type="date"
              className="rounded border border-slate-300 bg-white px-2 py-1 text-sm text-slate-800"
              value={end ?? ""}
              onChange={(e) => {
                setEnd(e.target.value || undefined);
                reset();
              }}
            />
          </label>
          <label className="flex flex-col gap-0.5 text-slate-500">
            sort
            <select
              className="rounded border border-slate-300 bg-white px-2 py-1 text-sm text-slate-800"
              value={sort}
              onChange={(e) => {
                setSort(e.target.value);
                reset();
              }}
            >
              {SORTS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-0.5 text-slate-500">
            rows
            <select
              className="rounded border border-slate-300 bg-white px-2 py-1 text-sm text-slate-800"
              value={pageSize}
              onChange={(e) => {
                setPageSize(Number(e.target.value));
                reset();
              }}
            >
              {PAGE_SIZES.map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </select>
          </label>
        </div>

        <div className="mt-3 flex flex-wrap items-end gap-3 border-t border-slate-100 pt-3 text-xs">
          <label className="flex flex-col gap-0.5 text-slate-500">
            gap % ≥
            <input
              type="number"
              step="0.1"
              placeholder="e.g. 0.5"
              className="w-20 rounded border border-slate-300 bg-white px-2 py-1 text-sm text-slate-800"
              value={gapMin}
              onChange={(e) => {
                setGapMin(e.target.value);
                reset();
              }}
            />
          </label>
          <label className="flex flex-col gap-0.5 text-slate-500">
            gap % ≤
            <input
              type="number"
              step="0.1"
              className="w-20 rounded border border-slate-300 bg-white px-2 py-1 text-sm text-slate-800"
              value={gapMax}
              onChange={(e) => {
                setGapMax(e.target.value);
                reset();
              }}
            />
          </label>
          <label className="flex flex-col gap-0.5 text-slate-500">
            close % ≥
            <input
              type="number"
              step="0.1"
              className="w-20 rounded border border-slate-300 bg-white px-2 py-1 text-sm text-slate-800"
              value={chgMin}
              onChange={(e) => {
                setChgMin(e.target.value);
                reset();
              }}
            />
          </label>
          <label className="flex flex-col gap-0.5 text-slate-500">
            close % ≤
            <input
              type="number"
              step="0.1"
              placeholder="e.g. -0.5"
              className="w-20 rounded border border-slate-300 bg-white px-2 py-1 text-sm text-slate-800"
              value={chgMax}
              onChange={(e) => {
                setChgMax(e.target.value);
                reset();
              }}
            />
          </label>
          <button
            type="button"
            onClick={applyGapFadePreset}
            className="rounded border border-slate-300 px-2 py-1 text-slate-600 hover:bg-slate-100"
            title="gap % ≥ 0.5 and close % ≤ -0.5 — gapped up, faded to close down"
          >
            gap-up fade preset
          </button>
          {hasGapChgFilter && (
            <button type="button" onClick={clearGapChgFilter} className="text-blue-700 underline">
              clear
            </button>
          )}
          <span className="text-slate-400">
            gap % = open vs prior close; close % = close vs prior close (both signed)
          </span>
        </div>
      </Panel>

      {q.isLoading && !d && <Skeleton rows={10} />}
      {q.error && <ProblemError error={q.error} onRetry={() => q.refetch()} />}

      {d && s && (
        <>
          <Panel
            title="Summary"
            right={
              <div className="flex items-center gap-2">
                {(d.gap_min_pct != null ||
                  d.gap_max_pct != null ||
                  d.chg_min_pct != null ||
                  d.chg_max_pct != null) && (
                  <Badge tone="warn">
                    filtered: gap [{d.gap_min_pct ?? "−∞"}, {d.gap_max_pct ?? "+∞"}] · close [
                    {d.chg_min_pct ?? "−∞"}, {d.chg_max_pct ?? "+∞"}]
                  </Badge>
                )}
                {d.first && (
                  <span className="font-mono text-xs text-neutral-400">
                    {d.first} → {d.last} · {d.total} days
                  </span>
                )}
              </div>
            }
          >
            <StatGrid
              rows={[
                ["PDH broken", `${s.pdh_breaks}${pctOf(s.pdh_breaks)}`],
                ["PDL broken", `${s.pdl_breaks}${pctOf(s.pdl_breaks)}`],
                ["Close > PDH", `${s.pdh_close_above}${pctOf(s.pdh_close_above)}`],
                ["Close < PDL", `${s.pdl_close_below}${pctOf(s.pdl_close_below)}`],
                ["Inside days", `${s.inside_days}${pctOf(s.inside_days)}`],
                ["Outside days", `${s.outside_days}${pctOf(s.outside_days)}`],
                ["Mean range", `${num(s.mean_range_pct, 2)} %`],
                ["Mean gap", `${num(s.mean_gap_pct, 2)} %`],
                ["Mean close chg", `${num(s.mean_change_pct, 2)} %`],
                ["Days with TPO profile", String(s.days_with_profile)],
              ]}
            />
            <div className="mt-3 flex flex-wrap gap-1.5 text-[11px]">
              {Object.entries(s.d1_day_type_counts).map(([k, v]) => (
                <span
                  key={k}
                  className={`rounded bg-neutral-500/10 px-1.5 py-0.5 ${
                    DAYTYPE_TONE[k] ?? "text-neutral-500"
                  }`}
                >
                  {k.replace(/_/g, " ").toLowerCase()} {v}
                  {pctOf(v)}
                </span>
              ))}
            </div>
          </Panel>

          <Panel
            title={`${d.items.length} of ${d.total}`}
            right={
              <div className="flex items-center gap-2 text-xs">
                <button
                  className="rounded border border-neutral-700 px-2 py-1 disabled:opacity-40"
                  disabled={offset === 0}
                  onClick={() => setOffset(Math.max(0, offset - pageSize))}
                >
                  ← prev
                </button>
                <button
                  className="rounded border border-neutral-700 px-2 py-1 disabled:opacity-40"
                  disabled={offset + pageSize >= d.total}
                  onClick={() => setOffset(offset + pageSize)}
                >
                  next →
                </button>
                <Badge tone="muted">table only</Badge>
              </div>
            }
          >
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="text-neutral-400">
                  <tr className="border-b border-neutral-800">
                    {["date", "day", "O", "H", "L", "C", "chg", "gap", "rng"].map((h) => (
                      <th key={h} className={`px-2 py-1 ${h === "date" || h === "day" ? "text-left" : "text-right"}`}>
                        {h}
                      </th>
                    ))}
                    <th className="px-2 py-1 text-right">PDH</th>
                    <th className="px-2 py-1 text-right">PDL</th>
                    <th className="px-2 py-1 text-center">range</th>
                    <th className="px-2 py-1 text-right">c-loc</th>
                    <th className="px-2 py-1 text-left">day type</th>
                    <th className="px-2 py-1 text-left">TPO profile</th>
                  </tr>
                </thead>
                <tbody>
                  {d.items.map((r) => (
                    <Row key={r.d} r={r} />
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-2 text-[11px] text-neutral-500">
              PDH / PDL = previous day&rsquo;s high / low; <b>broken</b> = today&rsquo;s high above /
              low below it. <b>c-loc</b> = where the close finished in the day&rsquo;s range (0 % low,
              100 % high). <b>day type</b> is classified from the D1 candle (range vs. trailing-14,
              close location, PDH/PDL breaks); <b>TPO profile</b> comes from the market-profile
              session for that day, blank where none was built. Descriptive — no execution language.
            </p>
          </Panel>
        </>
      )}
    </div>
  );
}
