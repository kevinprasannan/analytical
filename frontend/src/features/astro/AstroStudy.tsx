/** Astro × market cross-check (docs/08 §4.9, docs/13 §5).
 *
 * Two views over every NIFTY/BANKNIFTY/SENSEX trading day since 2000, read
 * against the sky at 09:00 IST over Mumbai (sidereal, Lahiri):
 *   • Patterns — descriptive stats grouped by weekday / nakshatra / tithi / …
 *   • Day log  — the individual days, filterable by a weekday + tithi + nakshatra
 *                combination, sorted by return, paginated, with a summary strip.
 * Exploratory — no forecast, no execution language. Tables only. */
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useAstroAlmanac, useAstroDasha, useAstroDays, useAstroStudy } from "@/api/queries";
import { Badge, Panel, ProblemError, Skeleton, StatGrid } from "@/components/primitives";
import type { Col } from "@/components/primitives";
import { DataTable } from "@/components/primitives";
import { LastUpdated } from "@/components/LastUpdated";
import type {
  AlmanacRow,
  AstroStudyResponse,
  DayLogParams,
  DayLogRow,
  StudyBucket,
} from "@/api/generated/schema";
import { DASH, num } from "@/lib/format";

const signed = (v: number, dp = 2) => (v >= 0 ? "+" : "") + num(v, dp);

const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"];
const RASHIS = [
  "Mesha", "Vrishabha", "Mithuna", "Karka", "Simha", "Kanya",
  "Tula", "Vrischika", "Dhanu", "Makara", "Kumbha", "Meena",
];
const NAKSHATRAS = [
  "Ashwini", "Bharani", "Krittika", "Rohini", "Mrigashira", "Ardra", "Punarvasu",
  "Pushya", "Ashlesha", "Magha", "Purva Phalguni", "Uttara Phalguni", "Hasta",
  "Chitra", "Swati", "Vishakha", "Anuradha", "Jyeshtha", "Mula", "Purva Ashadha",
  "Uttara Ashadha", "Shravana", "Dhanishta", "Shatabhisha", "Purva Bhadrapada",
  "Uttara Bhadrapada", "Revati",
];

type DayFilters = Pick<
  DayLogParams,
  | "start"
  | "end"
  | "weekday"
  | "weekday_lord"
  | "month"
  | "day"
  | "tithi"
  | "paksha"
  | "moon_nakshatra"
  | "moon_nakshatra_lord"
  | "moon_rashi"
  | "moon_pada"
  | "lagna_rashi"
>;

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

/** diverging bar around a zero centre; width ∝ |v| / max. */
function MeanBar({ v, max }: { v: number; max: number }) {
  const w = Math.min(Math.abs(v) / max, 1) * 50;
  const up = v >= 0;
  return (
    <span className="inline-flex items-center gap-2">
      <span className="relative inline-block h-3 w-[72px] bg-[linear-gradient(theme(colors.slate.300),theme(colors.slate.300))] bg-[length:1px_100%] bg-center bg-no-repeat">
        <span
          className={`absolute top-0.5 bottom-0.5 ${up ? "left-1/2 bg-emerald-500/70" : "right-1/2 bg-rose-500/70"}`}
          style={{ width: `${w}%` }}
        />
      </span>
      <span className={`tabular-nums ${up ? "text-emerald-600" : "text-rose-600"}`}>
        {signed(v)}
      </span>
    </span>
  );
}

type SortKey = "key" | "n" | "mean_ret" | "pct_up" | "median_ret" | "std_ret" | "mean_range";

function BucketTable({
  buckets,
  naturalOrder,
  extra,
  drillTo,
  onDrill,
}: {
  buckets: StudyBucket[];
  naturalOrder?: boolean;
  extra?: (b: StudyBucket) => string | undefined;
  drillTo?: (b: StudyBucket) => DayFilters;
  onDrill?: (f: DayFilters) => void;
}) {
  const [sort, setSort] = useState<string>(naturalOrder ? "" : "-mean_ret");
  const max = useMemo(
    () => Math.max(0.01, ...buckets.map((b) => Math.abs(b.mean_ret))) * 1.05,
    [buckets],
  );

  const rows = useMemo(() => {
    if (!sort) return buckets;
    const desc = sort.startsWith("-");
    const key = (desc ? sort.slice(1) : sort) as SortKey;
    return [...buckets].sort((a, b) => {
      const av = a[key];
      const bv = b[key];
      const cmp =
        typeof av === "string" ? av.localeCompare(bv as string) : (av as number) - (bv as number);
      return desc ? -cmp : cmp;
    });
  }, [buckets, sort]);

  const onSort = (key: string) => setSort((s) => (s === `-${key}` ? key : s === key ? "" : `-${key}`));

  const cols: Col<StudyBucket>[] = [
    {
      key: "key",
      header: "bucket",
      sortKey: "key",
      cell: (b) => (
        <span>
          {drillTo && onDrill ? (
            <button
              type="button"
              onClick={() => onDrill(drillTo(b))}
              className="text-blue-700 hover:underline"
              title="show the days behind this bucket"
            >
              {b.key}
            </button>
          ) : (
            b.key
          )}
          {extra?.(b) && <span className="ml-1.5 text-xs text-slate-400">· {extra(b)}</span>}
        </span>
      ),
    },
    { key: "n", header: "n", sortKey: "n", align: "right", cell: (b) => b.n },
    {
      key: "mean_ret",
      header: "mean %",
      sortKey: "mean_ret",
      align: "right",
      cell: (b) => <MeanBar v={b.mean_ret} max={max} />,
    },
    { key: "pct_up", header: "up %", sortKey: "pct_up", align: "right", cell: (b) => num(b.pct_up, 1) },
    {
      key: "median_ret",
      header: "med %",
      sortKey: "median_ret",
      align: "right",
      cell: (b) => (
        <span className={b.median_ret >= 0 ? "text-emerald-600" : "text-rose-600"}>
          {signed(b.median_ret)}
        </span>
      ),
    },
    { key: "std_ret", header: "vol", sortKey: "std_ret", align: "right", cell: (b) => num(b.std_ret, 2) },
    {
      key: "mean_range",
      header: "range %",
      sortKey: "mean_range",
      align: "right",
      cell: (b) => num(b.mean_range, 2),
    },
  ];

  return <DataTable cols={cols} rows={rows} rowKey={(b) => b.key} onSort={onSort} sort={sort} />;
}

/** small segmented control */
function Seg({
  options,
  value,
  onChange,
}: {
  options: { id: string; label: string }[];
  value: string;
  onChange: (id: string) => void;
}) {
  return (
    <div className="inline-flex overflow-hidden rounded border border-slate-300 text-xs">
      {options.map((o, i) => (
        <button
          key={o.id}
          type="button"
          aria-pressed={value === o.id}
          onClick={() => onChange(o.id)}
          className={`px-2 py-1 ${i > 0 ? "border-l border-slate-200" : ""} ${
            value === o.id ? "bg-slate-800 text-white" : "text-slate-600 hover:text-slate-900"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

const WD_GRAHA: Record<string, string> = {
  Monday: "Moon",
  Tuesday: "Mars",
  Wednesday: "Mercury",
  Thursday: "Jupiter",
  Friday: "Venus",
};

function Patterns({ s, onDrill }: { s: AstroStudyResponse; onDrill: (f: DayFilters) => void }) {
  const b = s.baseline;
  const [nakCut, setNakCut] = useState("nak");
  const [signCut, setSignCut] = useState("lagna");
  const [tithiCut, setTithiCut] = useState("tithi");

  return (
    <div className="space-y-4">
      <Panel
        title="The reference line"
        right={
          <span className="font-mono text-xs text-slate-400">
            {s.first} → {s.last}
          </span>
        }
      >
        <p className="mb-3 max-w-2xl text-sm text-slate-500">
          All {s.n_days.toLocaleString("en-IN")} trading days pooled. Every table below is read
          against these numbers — a green bar beats an average day, a red bar lags it. Click any
          bucket name to open its days in the Day log.
        </p>
        <StatGrid
          rows={[
            ["Days", s.n_days.toLocaleString("en-IN")],
            ["Mean return", `${signed(b.mean_ret)} %`],
            ["Median", `${signed(b.median_ret)} %`],
            ["Up days", `${num(b.pct_up, 1)} %`],
            ["Avg range", `${num(b.mean_range, 2)} %`],
            ["Best / worst day", `${signed(b.best)} / ${signed(b.worst)} %`],
          ]}
        />
      </Panel>

      <Panel title="By weekday">
        <p className="mb-3 text-sm text-slate-500">
          The plain trading-week cut. The graha beside each day is its fixed lord.
        </p>
        <BucketTable
          buckets={s.by_weekday}
          naturalOrder
          extra={(x) => WD_GRAHA[x.key]}
          drillTo={(x) => ({ weekday: x.key })}
          onDrill={onDrill}
        />
      </Panel>

      <Panel
        title="By Moon nakshatra"
        right={
          <Seg
            value={nakCut}
            onChange={setNakCut}
            options={[
              { id: "nak", label: "27 nakshatras" },
              { id: "lord", label: "by dispositor" },
            ]}
          />
        }
      >
        <p className="mb-3 max-w-2xl text-sm text-slate-500">
          The lunar mansion the Moon held at 9:00&nbsp;AM IST. ~245 days per bucket — a mean-return
          gap of a few basis points is well inside the noise (daily σ ≈ 1.4%).
        </p>
        {nakCut === "nak" ? (
          <BucketTable
            buckets={s.by_moon_nakshatra}
            drillTo={(x) => ({ moon_nakshatra: x.key })}
            onDrill={onDrill}
          />
        ) : (
          <BucketTable
            buckets={s.by_moon_nakshatra_lord}
            drillTo={(x) => ({ moon_nakshatra_lord: x.key })}
            onDrill={onDrill}
          />
        )}
      </Panel>

      <Panel
        title="By rising sign"
        right={
          <Seg
            value={signCut}
            onChange={setSignCut}
            options={[
              { id: "lagna", label: "Lagna" },
              { id: "moon", label: "Moon sign" },
            ]}
          />
        }
      >
        <p className="mb-3 max-w-2xl text-sm text-slate-500">
          Lagna is the rashi on the eastern horizon at 9:00&nbsp;AM over Mumbai; it walks all twelve
          signs in a day, so a fixed clock time samples each for a bounded slice of the session.
        </p>
        {signCut === "lagna" ? (
          <BucketTable
            buckets={s.by_lagna_rashi}
            naturalOrder
            drillTo={(x) => ({ lagna_rashi: x.key })}
            onDrill={onDrill}
          />
        ) : (
          <BucketTable
            buckets={s.by_moon_rashi}
            naturalOrder
            drillTo={(x) => ({ moon_rashi: x.key })}
            onDrill={onDrill}
          />
        )}
      </Panel>

      <Panel
        title="By tithi"
        right={
          <Seg
            value={tithiCut}
            onChange={setTithiCut}
            options={[
              { id: "tithi", label: "30 tithis" },
              { id: "paksha", label: "paksha" },
            ]}
          />
        }
      >
        <p className="mb-3 text-sm text-slate-500">
          The lunar day — the Moon–Sun angle in 12° steps — and the fortnight it falls in.
        </p>
        {tithiCut === "tithi" ? (
          <BucketTable
            buckets={s.by_tithi}
            naturalOrder
            drillTo={(x) => ({ tithi: Number(x.key) })}
            onDrill={onDrill}
          />
        ) : (
          <BucketTable
            buckets={s.by_paksha}
            naturalOrder
            drillTo={(x) => ({ paksha: x.key })}
            onDrill={onDrill}
          />
        )}
      </Panel>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Day log
// ---------------------------------------------------------------------------

const FILTER_LABEL: Record<keyof DayFilters, string> = {
  start: "from",
  end: "to",
  weekday: "weekday",
  weekday_lord: "weekday lord",
  month: "month",
  day: "day",
  tithi: "tithi",
  paksha: "paksha",
  moon_nakshatra: "nakshatra",
  moon_nakshatra_lord: "nak. lord",
  moon_rashi: "Moon rashi",
  moon_pada: "pada",
  lagna_rashi: "lagna",
};

const chipValue = (k: keyof DayFilters, v: string | number): string =>
  k === "month" ? (MONTHS[Number(v) - 1] ?? String(v)) : String(v);

type FOpt = string | number | { value: string | number; label: string };

function FSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string | number | undefined;
  onChange: (v: string | undefined) => void;
  options: FOpt[];
}) {
  return (
    <label className="flex flex-col gap-0.5 text-xs text-slate-500">
      {label}
      <select
        className="rounded border border-slate-300 bg-white px-2 py-1 text-sm text-slate-800"
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || undefined)}
      >
        <option value="">any</option>
        {options.map((o) => {
          const v = typeof o === "object" ? o.value : o;
          const l = typeof o === "object" ? o.label : o;
          return (
            <option key={v} value={v}>
              {l}
            </option>
          );
        })}
      </select>
    </label>
  );
}

function FDate({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string | undefined;
  onChange: (v: string | undefined) => void;
}) {
  return (
    <label className="flex flex-col gap-0.5 text-xs text-slate-500">
      {label}
      <input
        type="date"
        className="rounded border border-slate-300 bg-white px-2 py-1 text-sm text-slate-800"
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || undefined)}
      />
    </label>
  );
}

function DayRetCell({ v }: { v: number }) {
  return (
    <span className={`font-mono tabular-nums ${v >= 0 ? "text-emerald-600" : "text-rose-600"}`}>
      {signed(v, 2)}
    </span>
  );
}

function DayLog({
  underlying,
  filters,
  setFilters,
  sort,
  setSort,
  offset,
  setOffset,
  pageSize,
  setPageSize,
}: {
  underlying: string;
  filters: DayFilters;
  setFilters: (f: DayFilters) => void;
  sort: string;
  setSort: (s: string) => void;
  offset: number;
  setOffset: (n: number) => void;
  pageSize: number;
  setPageSize: (n: number) => void;
}) {
  const params: DayLogParams = { underlying, sort, limit: pageSize, offset, ...filters };
  const q = useAstroDays(params);

  const setF = (patch: Partial<DayFilters>) => {
    setOffset(0);
    setFilters({ ...filters, ...patch });
  };
  const clearKey = (k: keyof DayFilters) => setF({ [k]: undefined });
  const clearAll = () => {
    setOffset(0);
    setFilters({});
  };

  // header sort → backend token (d | ret | range | tithi)
  const onSort = (k: string) => {
    setOffset(0);
    setSort(sort === `-${k}` ? k : `-${k}`);
  };

  const cols: Col<DayLogRow>[] = [
    {
      key: "d",
      header: "date",
      sortKey: "d",
      cell: (r) => (
        <Link
          to={`/astro/day/${r.d}?underlying=${underlying}`}
          className="font-mono text-blue-700 hover:underline"
        >
          {r.d}
        </Link>
      ),
    },
    { key: "day", header: "day", cell: (r) => r.day_name.slice(0, 3) },
    { key: "tithi", header: "tithi", sortKey: "tithi", align: "right", cell: (r) => r.tithi },
    { key: "paksha", header: "paksha", cell: (r) => r.paksha },
    {
      key: "nak",
      header: "nakshatra",
      cell: (r) => (
        <span>
          {r.moon_nakshatra}
          <span className="ml-1 text-xs text-slate-400">· {r.moon_nakshatra_lord}</span>
        </span>
      ),
    },
    { key: "moon", header: "Moon", cell: (r) => r.moon_rashi },
    { key: "lagna", header: "lagna", cell: (r) => r.lagna_rashi },
    {
      key: "dasha",
      header: "dasha @open",
      cell: (r) =>
        r.dasha_lord ? (
          <span
            className="whitespace-nowrap"
            title={`Moon-anchored (390 min): ${r.dasha_lord} mahadasha, ${r.dasha_sub_lord} antardasha at session open · balance ${r.dasha_balance_hms}`}
          >
            {r.dasha_lord}
            <span className="text-slate-400"> – {r.dasha_sub_lord}</span>
          </span>
        ) : (
          <span className="text-slate-300">{DASH}</span>
        ),
    },
    { key: "close", header: "close", sortKey: "close", align: "right", cell: (r) => num(r.close, 2) },
    { key: "ret", header: "chg %", sortKey: "ret", align: "right", cell: (r) => <DayRetCell v={r.ret_pct} /> },
    {
      key: "range",
      header: "range %",
      sortKey: "range",
      align: "right",
      cell: (r) => num(r.range_pct, 2),
    },
    {
      key: "gap",
      header: "gap %",
      sortKey: "gap",
      align: "right",
      cell: (r) => <DayRetCell v={r.gap_pct} />,
    },
  ];

  const activeChips = (Object.keys(filters) as (keyof DayFilters)[]).filter(
    (k) => filters[k] !== undefined && filters[k] !== "",
  );

  const d = q.data;
  const sm = d?.summary;
  const showTo = d ? Math.min(offset + d.items.length, d.total) : 0;

  return (
    <div className="space-y-4">
      <Panel title="Filter the days">
        <div className="flex flex-wrap items-end gap-3">
          <FDate label="from" value={filters.start} onChange={(v) => setF({ start: v })} />
          <FDate label="to" value={filters.end} onChange={(v) => setF({ end: v })} />
          <FSelect
            label="weekday"
            value={filters.weekday}
            onChange={(v) => setF({ weekday: v })}
            options={WEEKDAYS}
          />
          <FSelect
            label="month"
            value={filters.month}
            onChange={(v) => setF({ month: v ? Number(v) : undefined })}
            options={MONTHS.map((m, i) => ({ value: i + 1, label: m }))}
          />
          <FSelect
            label="day"
            value={filters.day}
            onChange={(v) => setF({ day: v ? Number(v) : undefined })}
            options={Array.from({ length: 31 }, (_, i) => i + 1)}
          />
          <FSelect
            label="tithi"
            value={filters.tithi}
            onChange={(v) => setF({ tithi: v ? Number(v) : undefined })}
            options={Array.from({ length: 30 }, (_, i) => i + 1)}
          />
          <FSelect
            label="paksha"
            value={filters.paksha}
            onChange={(v) => setF({ paksha: v })}
            options={["Shukla", "Krishna"]}
          />
          <FSelect
            label="Moon nakshatra"
            value={filters.moon_nakshatra}
            onChange={(v) => setF({ moon_nakshatra: v })}
            options={NAKSHATRAS}
          />
          <FSelect
            label="Moon rashi"
            value={filters.moon_rashi}
            onChange={(v) => setF({ moon_rashi: v })}
            options={RASHIS}
          />
          <FSelect
            label="lagna rashi"
            value={filters.lagna_rashi}
            onChange={(v) => setF({ lagna_rashi: v })}
            options={RASHIS}
          />
          {activeChips.length > 0 && (
            <button
              type="button"
              onClick={clearAll}
              className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50"
            >
              clear all
            </button>
          )}
        </div>
        {activeChips.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {activeChips.map((k) => (
              <button
                key={k}
                type="button"
                onClick={() => clearKey(k)}
                className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-200"
                title="remove this filter"
              >
                {FILTER_LABEL[k]}:{" "}
                <b className="font-semibold">{chipValue(k, filters[k] as string | number)}</b> ×
              </button>
            ))}
          </div>
        )}
      </Panel>

      <Panel
        title={activeChips.length ? "This combination" : "All days"}
        right={
          d && d.first ? (
            <span className="font-mono text-xs text-slate-400">
              {d.first} → {d.last}
            </span>
          ) : undefined
        }
      >
        {q.isLoading && !d ? (
          <Skeleton rows={4} />
        ) : sm && sm.n > 0 ? (
          <StatGrid
            rows={[
              ["Days", sm.n.toLocaleString("en-IN")],
              ["Mean return", `${signed(sm.mean_ret)} %`],
              ["Median", `${signed(sm.median_ret)} %`],
              ["Up days", `${num(sm.pct_up, 1)} %`],
              ["Avg range", `${num(sm.mean_range, 2)} %`],
              ["Volatility (σ)", `${num(sm.std_ret, 2)} %`],
              ["Best / worst day", `${signed(sm.best)} / ${signed(sm.worst)} %`],
            ]}
          />
        ) : (
          <p className="text-sm text-slate-500">{DASH} no day matches this combination.</p>
        )}
      </Panel>

      {q.error && <ProblemError error={q.error} onRetry={() => q.refetch()} />}

      {d && d.items.length > 0 && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-slate-500">
            <span>
              showing <b className="text-slate-700">{offset + 1}</b>–
              <b className="text-slate-700">{showTo}</b> of{" "}
              <b className="text-slate-700">{d.total.toLocaleString("en-IN")}</b> days
              <span className="ml-2 text-xs text-slate-400">
                sorted {sort.startsWith("-") ? "↓" : "↑"} {sort.replace("-", "")}
              </span>
            </span>
            <div className="flex items-center gap-2">
              <label className="flex items-center gap-1 text-xs">
                page size
                <select
                  className="rounded border border-slate-300 bg-white px-1 py-0.5"
                  value={pageSize}
                  onChange={(e) => {
                    setOffset(0);
                    setPageSize(Number(e.target.value));
                  }}
                >
                  {[25, 50, 100, 200].map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - pageSize))}
                className="rounded border border-slate-300 px-2 py-1 disabled:opacity-40"
              >
                ← prev
              </button>
              <button
                type="button"
                disabled={offset + pageSize >= d.total}
                onClick={() => setOffset(offset + pageSize)}
                className="rounded border border-slate-300 px-2 py-1 disabled:opacity-40"
              >
                next →
              </button>
            </div>
          </div>
          <DataTable cols={cols} rows={d.items} rowKey={(r) => r.d} onSort={onSort} sort={sort} />
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Almanac — the sky for the days ahead (candle or not)
// ---------------------------------------------------------------------------

function Almanac({ underlying }: { underlying: string }) {
  const [start, setStart] = useState<string>();
  const [end, setEnd] = useState<string>();
  const [offset, setOffset] = useState(0);
  const pageSize = 60;
  const q = useAstroAlmanac({ underlying, start, end, limit: pageSize, offset });
  const d = q.data;

  return (
    <div className="space-y-4">
      <Panel title="Almanac — the sky, day by day">
        <p className="mb-3 max-w-3xl text-sm text-slate-500">
          Every computed day (default: today onward), whether or not the market has traded it. Rows
          with no candle still carry the full panchang — click a date to open its planets, Shadbala
          and chart.
        </p>
        <div className="flex flex-wrap items-end gap-3 text-xs">
          <label className="flex flex-col gap-0.5 text-slate-500">
            from
            <input
              type="date"
              className="rounded border border-slate-300 bg-white px-2 py-1 text-sm text-slate-800"
              value={start ?? ""}
              onChange={(e) => {
                setStart(e.target.value || undefined);
                setOffset(0);
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
                setOffset(0);
              }}
            />
          </label>
        </div>
      </Panel>

      {q.isLoading && !d && <Skeleton rows={10} />}
      {q.error && <ProblemError error={q.error} onRetry={() => q.refetch()} />}

      {d && (
        <Panel
          title={`${d.items.length} of ${d.total} days · ${d.with_candle} with a candle`}
          right={
            <div className="flex items-center gap-2 text-xs">
              <button
                className="rounded border border-slate-300 px-2 py-1 disabled:opacity-40"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - pageSize))}
              >
                ← prev
              </button>
              <button
                className="rounded border border-slate-300 px-2 py-1 disabled:opacity-40"
                disabled={offset + pageSize >= d.total}
                onClick={() => setOffset(offset + pageSize)}
              >
                next →
              </button>
            </div>
          }
        >
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-slate-400">
                <tr className="border-b border-slate-200">
                  {["date", "day", "tithi", "paksha", "nakshatra", "Moon", "lagna", "Sun", "chg %"].map(
                    (h, i) => (
                      <th key={h} className={`px-2 py-1 ${i < 2 ? "text-left" : "text-right"}`}>
                        {h}
                      </th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody>
                {d.items.map((r: AlmanacRow) => (
                  <tr key={r.d} className="border-b border-slate-100">
                    <td className="px-2 py-1">
                      <Link
                        className="font-mono text-blue-700 underline"
                        to={`/astro/day/${r.d}?underlying=${underlying}`}
                      >
                        {r.d}
                      </Link>
                    </td>
                    <td className="px-2 py-1 text-slate-500">{r.day_name.slice(0, 3)}</td>
                    <td className="px-2 py-1 text-right tabular-nums">{r.tithi}</td>
                    <td className="px-2 py-1 text-right">{r.paksha}</td>
                    <td className="px-2 py-1 text-right">{r.moon_nakshatra}</td>
                    <td className="px-2 py-1 text-right">{r.moon_rashi}</td>
                    <td className="px-2 py-1 text-right">{r.lagna_rashi}</td>
                    <td className="px-2 py-1 text-right">{r.sun_rashi}</td>
                    <td className="px-2 py-1 text-right tabular-nums">
                      {r.has_candle && r.ret_pct != null ? (
                        <span className={r.ret_pct >= 0 ? "text-emerald-600" : "text-rose-600"}>
                          {signed(r.ret_pct, 2)}
                        </span>
                      ) : (
                        <span className="text-slate-300">no candle</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Vimshottari dasha — the 120-year lord cycle scaled to one session
// ---------------------------------------------------------------------------

const DASHA_LORDS = [
  "Ketu", "Venus", "Sun", "Moon", "Mars", "Rahu", "Jupiter", "Saturn", "Mercury",
];

function Dasha() {
  const [minutesText, setMinutesText] = useState("390");
  const [startLord, setStartLord] = useState("Ketu");
  const minutes = Number(minutesText);
  const validMinutes = Number.isFinite(minutes) && minutes > 0;
  const q = useAstroDasha({
    minutes: validMinutes ? minutes : undefined,
    start_lord: startLord,
  });
  const d = q.data;
  const cols = d ? d.rows[0].antardashas.map((c) => c.lord) : [];

  return (
    <div className="space-y-4">
      <Panel title="Vimshottari dasha — one session, the whole cycle">
        <p className="mb-3 max-w-3xl text-sm text-slate-500">
          The nine lords rule in fixed proportion — Ketu&nbsp;7 · Venus&nbsp;20 · Sun&nbsp;6 ·
          Moon&nbsp;10 · Mars&nbsp;7 · Rahu&nbsp;18 · Jupiter&nbsp;16 · Saturn&nbsp;19 ·
          Mercury&nbsp;17 = 120&nbsp;years. Every cell keeps that ratio, so the grid reads both as
          years and as <b>H:MM:SS of a {validMinutes ? minutes : "—"}-minute session</b>. Rows are
          the mahadasha (major period); columns the antardasha (sub-period) within it.
        </p>
        <div className="flex flex-wrap items-end gap-3 text-xs">
          <label className="flex flex-col gap-0.5 text-slate-500">
            session minutes
            <input
              type="number"
              min={1}
              step={5}
              className="w-28 rounded border border-slate-300 bg-white px-2 py-1 text-sm text-slate-800"
              value={minutesText}
              onChange={(e) => setMinutesText(e.target.value)}
            />
          </label>
          <div className="flex gap-1">
            {["390", "400", "375"].map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setMinutesText(m)}
                className={`rounded border px-2 py-1 ${
                  minutesText === m
                    ? "border-slate-800 bg-slate-800 text-white"
                    : "border-slate-300 text-slate-600 hover:bg-slate-50"
                }`}
              >
                {m}
              </button>
            ))}
          </div>
          <label className="flex flex-col gap-0.5 text-slate-500">
            start lord (mahadasha at t=0)
            <select
              className="rounded border border-slate-300 bg-white px-2 py-1 text-sm text-slate-800"
              value={startLord}
              onChange={(e) => setStartLord(e.target.value)}
            >
              {DASHA_LORDS.map((l) => (
                <option key={l} value={l}>
                  {l}
                </option>
              ))}
            </select>
          </label>
        </div>
        {!validMinutes && (
          <p className="mt-2 text-xs text-rose-600">enter a session length greater than 0</p>
        )}
      </Panel>

      {q.isLoading && !d && <Skeleton rows={10} />}
      {q.error && <ProblemError error={q.error} onRetry={() => q.refetch()} />}

      {d && (
        <Panel
          title="Mahadasha × antardasha"
          right={
            <span className="font-mono text-xs text-slate-400">
              120y {d.total_hms ? `· ${d.total_hms}` : ""} · from {d.start_lord}
            </span>
          }
        >
          <div className="overflow-x-auto">
            <table className="w-full text-xs tabular-nums">
              <thead className="text-slate-400">
                <tr className="border-b border-slate-200">
                  <th className="px-2 py-1 text-left">mahadasha</th>
                  <th className="px-2 py-1 text-right">period total</th>
                  {cols.map((l) => (
                    <th key={l} className="px-2 py-1 text-right">
                      {d.abbr[l] ?? l.slice(0, 2)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {d.rows.map((r) => (
                  <tr key={r.lord} className="border-b border-slate-100">
                    <td className="whitespace-nowrap px-2 py-1 font-medium text-slate-700">
                      {r.lord}{" "}
                      <span className="text-slate-400">({r.abbr})</span>
                    </td>
                    <td className="px-2 py-1 text-right">
                      <div className="font-medium text-slate-800">{r.years_label}</div>
                      {r.hms && <div className="text-[10px] text-slate-400">{r.hms}</div>}
                    </td>
                    {r.antardashas.map((c) => {
                      const isMd = c.lord === r.lord;
                      return (
                        <td
                          key={c.lord}
                          className={`px-2 py-1 text-right ${isMd ? "bg-amber-50" : ""}`}
                          title={`${r.lord} → ${c.lord}: ${c.years_label}${c.hms ? ` · ${c.hms}` : ""}`}
                        >
                          <div className="text-slate-700">{c.hms ?? c.years_label}</div>
                          <div className="text-[10px] text-slate-400">
                            {c.hms ? c.years_label : num(c.years, 3) + "y"}
                          </div>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t-2 border-slate-300 font-medium text-slate-600">
                  <td className="px-2 py-1">Total</td>
                  <td className="px-2 py-1 text-right">
                    120y{d.total_hms ? ` · ${d.total_hms}` : ""}
                  </td>
                  {cols.map((l) => {
                    const yrs = d.years[l];
                    return (
                      <td key={l} className="px-2 py-1 text-right text-slate-400">
                        {yrs}y
                      </td>
                    );
                  })}
                </tr>
              </tfoot>
            </table>
          </div>
          <p className="mt-2 text-[11px] text-slate-400">
            Amber cell = the sub-period ruled by the mahadasha lord itself (where the chronological
            sequence begins). Column totals are the lord's base years; each mahadasha row also sums
            to its own period total.
          </p>
        </Panel>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------

type AstroView = "patterns" | "daylog" | "almanac" | "dasha";

export function AstroStudy() {
  const [underlying, setUnderlying] = useState("NIFTY-INDEX");
  const [view, setView] = useState<AstroView>("patterns");
  const [filters, setFilters] = useState<DayFilters>({});
  const [sort, setSort] = useState("-ret");
  const [offset, setOffset] = useState(0);
  const [pageSize, setPageSize] = useState(50);

  const q = useAstroStudy({ underlying });

  const drill = (f: DayFilters) => {
    setFilters(f);
    setOffset(0);
    setSort("-ret");
    setView("daylog");
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-bold">Astro × market</h1>
        <Badge tone="muted">descriptive, not predictive</Badge>
        <LastUpdated q={q} />
        <Seg
          value={view}
          onChange={(v) => setView(v as AstroView)}
          options={[
            { id: "patterns", label: "Patterns" },
            { id: "daylog", label: "Day log" },
            { id: "almanac", label: "Almanac" },
            { id: "dasha", label: "Dasha" },
          ]}
        />
        <select
          className="ml-auto rounded border border-slate-300 bg-white px-2 py-1 text-sm"
          value={underlying}
          onChange={(e) => setUnderlying(e.target.value)}
        >
          {["NIFTY-INDEX", "BANKNIFTY-INDEX", "SENSEX-INDEX"].map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </select>
      </div>

      {view !== "dasha" && (
        <p className="max-w-3xl text-sm text-slate-500">
          Every {underlying.replace("-INDEX", "")} trading day since 2000, read against the sky at
          9:00&nbsp;AM IST over Mumbai (sidereal, Lahiri). Return is close-to-close; buckets are
          small, so read rank order as texture, not signal.
        </p>
      )}

      {view === "patterns" && (
        <>
          {q.isLoading && <Skeleton rows={12} />}
          {q.error && <ProblemError error={q.error} onRetry={() => q.refetch()} />}
          {q.data &&
            (q.data.n_days > 0 ? (
              <Patterns s={q.data} onDrill={drill} />
            ) : (
              <p className="text-sm text-slate-500">{DASH} no data</p>
            ))}
        </>
      )}
      {view === "daylog" && (
        <DayLog
          underlying={underlying}
          filters={filters}
          setFilters={setFilters}
          sort={sort}
          setSort={setSort}
          offset={offset}
          setOffset={setOffset}
          pageSize={pageSize}
          setPageSize={setPageSize}
        />
      )}
      {view === "almanac" && <Almanac underlying={underlying} />}
      {view === "dasha" && <Dasha />}
    </div>
  );
}
