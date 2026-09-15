/** One trading day, everything on one screen (docs/13 §5.2):
 *   • Market — D1 open/high/low/close + intraday bars for the session (5m/15m/1h toggle)
 *   • Panchang — weekday / tithi / nakshatra / lagna at 09:00 IST
 *   • Planets — sidereal (Lahiri) positions
 *   • Shadbala — Parashari six-fold strength
 * Descriptive; no forecast, no execution language. Tables only. */
import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useAstroDayDetail, useAstroKpTimeline, useAstroMoonDasha } from "@/api/queries";
import { Badge, Panel, ProblemError, Skeleton, StatGrid } from "@/components/primitives";
import type { Col } from "@/components/primitives";
import { DataTable } from "@/components/primitives";
import { LastUpdated } from "@/components/LastUpdated";
import type {
  DayBadhaka,
  DayHouseGroup,
  DayHourBar,
  DayPlanet,
  DayShadbala,
  DayTithiShoonya,
  KpChain,
  KpTimelineRow,
  MoonDasha,
  MoonDashaPeriod,
} from "@/api/generated/schema";
import { DASH, int, num } from "@/lib/format";

/** the four purushartha trikonas: 1·5·9 / 2·6·10 / 3·7·11 / 4·8·12 */
const GROUP_META: Record<string, { triad: string; hint: string; cls: string }> = {
  Dharma: { triad: "1·5·9", hint: "trines — purpose", cls: "text-amber-700 bg-amber-50" },
  Artha: { triad: "2·6·10", hint: "upachaya — resources", cls: "text-emerald-700 bg-emerald-50" },
  Kama: { triad: "3·7·11", hint: "desire — drive", cls: "text-sky-700 bg-sky-50" },
  Moksha: { triad: "4·8·12", hint: "release — endings", cls: "text-violet-700 bg-violet-50" },
};
const groupTag = (g: string | null) =>
  g ? `${g} (${GROUP_META[g]?.triad ?? "?"})` : DASH;

const TF_LABEL: Record<"H1" | "M15" | "M5", string> = {
  H1: "hourly",
  M15: "15-min",
  M5: "5-min",
};

type Frame = "lagna" | "lagna_deg" | "naklord_deg" | "moon" | "sun";
const FRAMES: { id: Frame; label: string }[] = [
  { id: "lagna", label: "Lagna (whole-sign)" },
  { id: "lagna_deg", label: "Lagna (by degree)" },
  { id: "naklord_deg", label: "Moon's nakshatra-lord (by degree)" },
  { id: "moon", label: "from Moon" },
  { id: "sun", label: "from Sun" },
];
const houseOf = (p: DayPlanet, f: Frame): { h: number | null; g: string | null } =>
  f === "moon"
    ? { h: p.house_from_moon, g: p.house_group_moon }
    : f === "sun"
      ? { h: p.house_from_sun, g: p.house_group_sun }
      : f === "lagna_deg"
        ? { h: p.house_from_lagna_deg, g: p.house_group_lagna_deg }
        : f === "naklord_deg"
          ? { h: p.house_from_naklord_deg, g: p.house_group_naklord_deg }
          : { h: p.house_from_lagna, g: p.house_group_lagna };

const signed = (v: number | null | undefined, dp = 2) =>
  v === null || v === undefined ? DASH : (v >= 0 ? "+" : "") + num(v, dp);

const istTime = (iso: string | null) =>
  iso
    ? new Date(iso).toLocaleTimeString("en-IN", {
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
        timeZone: "Asia/Kolkata",
      })
    : DASH;

const longDate = (d: string) =>
  new Date(`${d}T00:00:00`).toLocaleDateString("en-IN", {
    weekday: "long",
    day: "2-digit",
    month: "long",
    year: "numeric",
  });

function Move({ v }: { v: number | null | undefined }) {
  if (v === null || v === undefined) return <span>{DASH}</span>;
  return (
    <span className={v >= 0 ? "text-emerald-600" : "text-rose-600"}>
      {v >= 0 ? "▲" : "▼"} {signed(v)} %
    </span>
  );
}

/** stable key for one period node (level + start are unique within the tree) */
const periodKey = (p: MoonDashaPeriod) => `${p.level}-${p.start_min}`;

/** one KP lord chain (sign ⊃ star ⊃ sub ⊃ sub-sub) as an inline strip. */
function KpChainStrip({ chain }: { chain: KpChain }) {
  const links: [string, string, string][] = [
    ["sign", chain.sign_lord, chain.sign_lord_abbr],
    ["star", chain.star_lord, chain.star_lord_abbr],
    ["sub", chain.sub_lord, chain.sub_lord_abbr],
    ["sub-sub", chain.sub_sub_lord, chain.sub_sub_lord_abbr],
  ];
  return (
    <div className="flex flex-wrap items-center gap-1 text-sm">
      {links.map(([label, lord, abbr], i) => (
        <span key={label} className="flex items-center gap-1">
          {i > 0 && <span className="text-slate-300">→</span>}
          <span className="rounded bg-white px-1.5 py-0.5 ring-1 ring-slate-200">
            <span className="text-[10px] uppercase text-slate-400">{label}</span>{" "}
            <b className="text-slate-800">{lord}</b>
            <span className="ml-0.5 text-xs text-slate-400">({abbr})</span>
          </span>
        </span>
      ))}
    </div>
  );
}

/** the dasha lord's house from the lagna, both conventions */
type LordHouse = { deg: number | null; dg: string | null; whole: number | null; wg: string | null };

/** one session-length basis (390 or 400 min) of the Moon-anchored dasha —
 *  MD rows fold open to AD, AD rows fold open to PD; per-row triangles plus
 *  three bulk shortcuts (collapse all / MD+AD / MD+AD+PD). */
const CUTOFF_OPTS = ["15:30", "15:40", "full"] as const;

function MoonDashaBasis({ md, positions }: { md: MoonDasha; positions: DayPlanet[] }) {
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(md.periods.map(periodKey)));
  const [cutoff, setCutoff] = useState<(typeof CUTOFF_OPTS)[number]>("15:40");

  const toggle = (p: MoonDashaPeriod) =>
    setExpanded((s) => {
      const next = new Set(s);
      const k = periodKey(p);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });

  const setAll = (n: 1 | 2 | 3) => {
    if (n === 1) setExpanded(new Set());
    else if (n === 2) setExpanded(new Set(md.periods.map(periodKey)));
    else setExpanded(new Set(md.periods.flatMap((p) => [periodKey(p), ...p.children.map(periodKey)])));
  };

  // cutoff hides any period that *starts* on or after the chosen wall-clock time
  // (start_clock is "HH:MM" IST, same-day — lexical compare is safe here)
  const past = (p: MoonDashaPeriod) => cutoff !== "full" && p.start_clock >= cutoff;

  const rows: MoonDashaPeriod[] = [];
  const walk = (list: MoonDashaPeriod[]) => {
    for (const p of list) {
      if (past(p)) continue;
      rows.push(p);
      if (p.children.length && expanded.has(periodKey(p))) walk(p.children);
    }
  };
  walk(md.periods);
  const hidden = cutoff !== "full" && md.periods.some((p) => past(p));

  // dasha-lord grahas are Sun…Ketu — look each up in the day's positions to get
  // its place from the lagna, by exact degree (equal house) and whole-sign
  const houseOfLord = (lord: string): LordHouse => {
    const p = positions.find((x) => x.body === lord);
    return {
      deg: p?.house_from_lagna_deg ?? null,
      dg: p?.house_group_lagna_deg ?? null,
      whole: p?.house_from_lagna ?? null,
      wg: p?.house_group_lagna ?? null,
    };
  };
  const rulH = houseOfLord(md.dasha_lord);
  const lagnaCell = (lord: string) => {
    const h = houseOfLord(lord);
    if (h.deg == null && h.whole == null) return <span className="text-slate-300">{DASH}</span>;
    return (
      <span
        className="whitespace-nowrap"
        title={`from lagna — by degree: house ${h.deg ?? "?"} (${groupTag(h.dg)}) · whole-sign: house ${h.whole ?? "?"} (${groupTag(h.wg)})`}
      >
        <b className="font-mono">{h.deg ?? DASH}</b>
        <span className="text-slate-400">°</span>
        <span className="mx-1 text-slate-300">/</span>
        <b className="font-mono">{h.whole ?? DASH}</b>
        <span className="text-slate-400">w</span>
      </span>
    );
  };
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <span className="rounded bg-slate-800 px-2 py-0.5 text-xs font-medium text-white">
          {md.subdivision_minutes} min = 120 y
        </span>
        <span className="text-xs text-slate-500">session open {md.session_open} IST</span>
        <span className="text-xs text-slate-400">
          click ▸ on a row to open it, or jump to a depth:
        </span>
        <div className="inline-flex overflow-hidden rounded border border-slate-300 text-xs">
          {([1, 2, 3] as const).map((n) => (
            <button
              key={n}
              type="button"
              onClick={() => setAll(n)}
              className={`px-2 py-1 ${n > 1 ? "border-l border-slate-200" : ""} text-slate-600 hover:bg-slate-700 hover:text-white`}
            >
              {n === 1 ? "MD" : n === 2 ? "MD+AD" : "MD+AD+PD"}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-1 text-xs text-slate-500">
          show until
          <select
            className="rounded border border-slate-300 bg-white px-1.5 py-1 text-slate-800"
            value={cutoff}
            onChange={(e) => setCutoff(e.target.value as (typeof CUTOFF_OPTS)[number])}
          >
            {CUTOFF_OPTS.map((o) => (
              <option key={o} value={o}>
                {o === "full" ? "full session" : o + " IST"}
              </option>
            ))}
          </select>
        </label>
      </div>

      <StatGrid
        rows={[
          ["Moon", `${md.nakshatra} p${md.pada} · ${num(md.position_in_nakshatra_deg, 2)}° in`],
          ["Ruling mahadasha", `${md.dasha_lord} (${md.dasha_lord_abbr})`],
          [
            "Lord from lagna",
            rulH.deg == null && rulH.whole == null
              ? DASH
              : `house ${rulH.deg ?? "?"} by degree (${groupTag(rulH.dg)}) · house ${rulH.whole ?? "?"} whole-sign`,
          ],
          ["Elapsed of nakshatra", `${num(md.elapsed_fraction * 100, 1)} %`],
          ["Balance at open", `${md.balance_hms} · ${md.balance_years_label}`],
        ]}
      />

      <div className="overflow-x-auto">
        <table className="w-full text-xs tabular-nums">
          <thead className="text-slate-400">
            <tr className="border-b border-slate-200">
              <th className="px-2 py-1 text-left">clock IST</th>
              <th className="px-2 py-1 text-left">period</th>
              <th className="px-2 py-1 text-right" title="house from lagna: by exact degree / whole-sign">
                lagna °/w
              </th>
              <th className="px-2 py-1 text-right">duration</th>
              <th className="px-2 py-1 text-right">= years</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p, i) => (
              <tr
                key={i}
                className={`border-b border-slate-100 ${
                  p.level === 1 ? "font-medium text-slate-700" : "text-slate-500"
                }`}
              >
                <td className="whitespace-nowrap px-2 py-1 font-mono">
                  {p.start_clock}–{p.end_clock}
                </td>
                <td
                  className="px-2 py-1"
                  style={{ paddingLeft: `${8 + (p.level - 1) * 16}px` }}
                >
                  {p.children.length > 0 ? (
                    <button
                      type="button"
                      onClick={() => toggle(p)}
                      aria-expanded={expanded.has(periodKey(p))}
                      aria-label={expanded.has(periodKey(p)) ? "collapse" : "expand"}
                      className="mr-1 inline-block w-3 text-slate-400 hover:text-slate-800"
                    >
                      {expanded.has(periodKey(p)) ? "▾" : "▸"}
                    </button>
                  ) : (
                    p.level > 1 && <span className="mr-1 inline-block w-3 text-slate-300">└</span>
                  )}
                  {p.lord}
                  {p.partial && (
                    <span className="ml-1 rounded bg-amber-50 px-1 text-[10px] text-amber-700">
                      balance
                    </span>
                  )}
                </td>
                <td className="px-2 py-1 text-right">{lagnaCell(p.lord)}</td>
                <td className="px-2 py-1 text-right">{p.hms}</td>
                <td className="px-2 py-1 text-right text-slate-400">{p.years_label}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {hidden && (
        <p className="text-[11px] text-slate-400">
          periods starting at or after {cutoff} IST hidden — switch “show until” to see the rest.
        </p>
      )}

      {md.kp_chain && (
        <div className="rounded border border-slate-200 bg-slate-50 px-3 py-2">
          <div className="mb-1 text-xs font-medium text-slate-500">
            KP chain — the Moon at {num(md.moon_longitude, 4)}° sidereal
          </div>
          <KpChainStrip chain={md.kp_chain} />
          <p className="mt-1 text-[11px] text-slate-400">
            sign lord ⊃ star (nakshatra) lord ⊃ sub lord ⊃ sub-sub lord — each cut by the
            Vimshottari 7·20·6·10·7·18·16·19·17 proportions. Star lord = the ruling mahadasha
            ({md.dasha_lord_abbr}).
          </p>
        </div>
      )}
    </div>
  );
}

const KP_END_OPTS = ["15:30", "15:40"] as const;
const KP_LEVEL_OPTS = [
  { id: "sub", label: "sub-lord" },
  { id: "sub_sub", label: "sub-sub" },
] as const;

const relTone = (r: string) =>
  r === "friend" ? "text-emerald-600" : r === "enemy" ? "text-rose-600" : "text-slate-400";

const numTone = (v: number | null | undefined) =>
  v == null ? "" : v > 0 ? "text-emerald-600" : v < 0 ? "text-rose-600" : "text-slate-500";

const chainKey = (p: KpTimelineRow["lagna"], deep: boolean) =>
  `${p.sign_lord}·${p.star_lord}·${p.sub_lord}${deep ? "·" + p.sub_sub_lord : ""}`;

/** KP-chain **change brackets** for the Lagna + Moon across the session
 *  (09:00 → end) — a new row whenever either chain's lord changes at the chosen
 *  level — with the Parashari star↔sub relation within each and Lagna-sub ↔
 *  Moon-sub across, plus a collapsible session H1 bar table. Fetches its own data. */
function KpLordsPanel({
  date,
  underlying,
  hourly,
}: {
  date: string;
  underlying: string;
  hourly: DayHourBar[];
}) {
  const [end, setEnd] = useState<(typeof KP_END_OPTS)[number]>("15:40");
  const [level, setLevel] = useState<"sub" | "sub_sub">("sub");
  const [showBars, setShowBars] = useState(false);
  const q = useAstroKpTimeline(date, end, level, underlying);
  const rows = q.data?.rows ?? [];
  const deep = level === "sub_sub";
  const hasMkt = rows.some((r) => r.market);

  const chainCells = (p: KpTimelineRow["lagna"], unchanged: boolean) =>
    unchanged ? (
      <span className="text-slate-300">〃</span>
    ) : (
      <span className="whitespace-nowrap font-mono">
        {p.sign_lord_abbr}
        <span className="text-slate-300">·</span>
        {p.star_lord_abbr}
        <span className="text-slate-300">·</span>
        <b className="text-slate-800">{p.sub_lord_abbr}</b>
        {deep && (
          <>
            <span className="text-slate-300">·</span>
            {p.sub_sub_lord_abbr}
          </>
        )}
        <span className={`ml-1 ${relTone(p.star_sub_relation)}`}>
          ({p.star_sub_relation.slice(0, 3)})
        </span>
      </span>
    );

  const seg = `sign·star·sub${deep ? "·sub-sub" : ""}`;

  return (
    <Panel
      title="KP lords — Lagna & Moon"
      right={
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
          <label className="flex items-center gap-1">
            09:00 →
            <select
              className="rounded border border-slate-300 bg-white px-1.5 py-1 text-sm text-slate-800"
              value={end}
              onChange={(e) => setEnd(e.target.value as (typeof KP_END_OPTS)[number])}
            >
              {KP_END_OPTS.map((o) => (
                <option key={o} value={o}>
                  {o} IST
                </option>
              ))}
            </select>
          </label>
          <div className="inline-flex overflow-hidden rounded border border-slate-300">
            {KP_LEVEL_OPTS.map((o) => (
              <button
                key={o.id}
                type="button"
                onClick={() => setLevel(o.id)}
                className={`px-2 py-1 ${o.id !== "sub" ? "border-l border-slate-200" : ""} ${
                  level === o.id ? "bg-slate-700 text-white" : "text-slate-600 hover:text-slate-900"
                }`}
              >
                {o.label}
              </button>
            ))}
          </div>
        </div>
      }
    >
      <p className="mb-2 max-w-2xl text-sm text-slate-500">
        A <b>change bracket</b> — one row per stretch of the session — starts whenever the KP
        chain <b>{seg}</b> lord (abbreviations) of the <b>Lagna</b> or the <b>Moon</b> changes at
        the chosen level. The Lagna moves ~1° every 4 min so its sub lord turns over through the
        day; the Moon barely moves (〃 = unchanged from the row above).{" "}
        <span className={relTone("friend")}>friend</span> /{" "}
        <span className="text-slate-400">neut</span> /{" "}
        <span className={relTone("enemy")}>enemy</span> is the Parashari natural relation
        (star ↔ sub in each chain). <b>houses (sign·star·sub)</b> is the whole-sign house{" "}
        <b>from the Lagna</b> (ascendant = 1) of the Lagna chain's sign, star and sub lord
        grahas — e.g. <span className="font-mono">11-9-10</span>. <b>mkt O→C</b> is the index's
        open→close move over that bracket and <b>price</b> its close (when M1 bars exist).
        Descriptive — no signal.
      </p>

      {q.isLoading && !q.data && <Skeleton rows={8} />}
      {q.error && <ProblemError error={q.error} onRetry={() => q.refetch()} />}

      {rows.length > 0 && (
        <div className="max-h-[28rem] overflow-auto">
          <table className="w-full text-xs tabular-nums">
            <thead className="sticky top-0 bg-white text-slate-400">
              <tr className="border-b border-slate-200">
                <th className="px-2 py-1 text-left">IST bracket</th>
                <th className="px-2 py-1 text-left">Lagna — {seg} (star↔sub)</th>
                <th className="px-2 py-1 text-left">Moon — {seg} (star↔sub)</th>
                <th
                  className="px-2 py-1 text-left"
                  title="whole-sign house from the Lagna (asc = 1) of the sign / star / sub lord grahas"
                >
                  houses (sign·star·sub)
                </th>
                {hasMkt && <th className="px-2 py-1 text-right">mkt O→C</th>}
                {hasMkt && <th className="px-2 py-1 text-right">price</th>}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => {
                const prev = rows[i - 1];
                const lh = r.lagna_houses;
                return (
                  <tr key={r.start} className="border-b border-slate-100">
                    <td className="px-2 py-1 font-mono text-slate-600">
                      {r.start}–{r.end}
                    </td>
                    <td className="px-2 py-1">
                      {chainCells(
                        r.lagna,
                        !!prev && chainKey(prev.lagna, deep) === chainKey(r.lagna, deep),
                      )}
                    </td>
                    <td className="px-2 py-1">
                      {chainCells(
                        r.moon,
                        !!prev && chainKey(prev.moon, deep) === chainKey(r.moon, deep),
                      )}
                    </td>
                    <td className="whitespace-nowrap px-2 py-1 font-mono text-slate-700">
                      {lh.sign ?? DASH}-{lh.star ?? DASH}-{lh.sub ?? DASH}
                    </td>
                    {hasMkt && (
                      <td className={`px-2 py-1 text-right font-mono ${numTone(r.market?.change)}`}>
                        {r.market
                          ? `${signed(r.market.change, 1)}${
                              r.market.change_pct != null
                                ? ` (${signed(r.market.change_pct, 2)}%)`
                                : ""
                            }`
                          : DASH}
                      </td>
                    )}
                    {hasMkt && (
                      <td className="px-2 py-1 text-right font-mono text-slate-500">
                        {r.market ? num(r.market.close, 1) : DASH}
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {hourly.length > 0 && (
        <div className="mt-3">
          <button
            type="button"
            onClick={() => setShowBars((v) => !v)}
            className="flex items-center gap-1 text-xs font-medium text-slate-500 hover:text-slate-800"
            aria-expanded={showBars}
          >
            <span className={`inline-block text-[10px] text-slate-400 ${showBars ? "rotate-90" : ""}`}>
              ▶
            </span>
            market data — session H1 bars
          </button>
          {showBars && (
            <div className="mt-1 overflow-x-auto">
              <table className="w-full text-xs tabular-nums">
                <thead className="text-slate-400">
                  <tr className="border-b border-slate-200">
                    <th className="px-2 py-1 text-left">IST</th>
                    <th className="px-2 py-1 text-right">open</th>
                    <th className="px-2 py-1 text-right">high</th>
                    <th className="px-2 py-1 text-right">low</th>
                    <th className="px-2 py-1 text-right">close</th>
                  </tr>
                </thead>
                <tbody>
                  {hourly.map((b) => (
                    <tr key={b.ts} className="border-b border-slate-100">
                      <td className="px-2 py-1 font-mono text-slate-600">{istTime(b.ts)}</td>
                      <td className="px-2 py-1 text-right">{num(b.open, 2)}</td>
                      <td className="px-2 py-1 text-right">{num(b.high, 2)}</td>
                      <td className="px-2 py-1 text-right">{num(b.low, 2)}</td>
                      <td className="px-2 py-1 text-right">{num(b.close, 2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </Panel>
  );
}

const OPEN_OPTS = ["09:00", "09:15"] as const;
const MIN_OPTS = [390, 400] as const;

/** Moon-anchored dasha with a session-open + session-length picker (fetches
 *  its own data so the two selectors are live, not the two static bases). */
function MoonDashaPanel({
  date,
  underlying,
  positions,
}: {
  date: string;
  underlying: string;
  positions: DayPlanet[];
}) {
  const [open, setOpen] = useState<(typeof OPEN_OPTS)[number]>("09:15");
  const [minutes, setMinutes] = useState<(typeof MIN_OPTS)[number]>(390);
  const q = useAstroMoonDasha(
    date ? { d: date, minutes, levels: 3, session_open: open, underlying } : undefined,
  );
  const md = q.data;

  const pick = (
    label: string,
    value: string | number,
    opts: readonly (string | number)[],
    onChange: (v: string) => void,
  ) => (
    <label className="flex items-center gap-1 text-xs text-slate-500">
      {label}
      <select
        className="rounded border border-slate-300 bg-white px-2 py-1 text-sm text-slate-800"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        {opts.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </label>
  );

  return (
    <Panel
      title="Dasha — Moon-anchored (balance of dasha)"
      collapsible
      right={
        <div className="flex flex-wrap items-center gap-2">
          {pick("open", open, OPEN_OPTS, (v) => setOpen(v as (typeof OPEN_OPTS)[number]))}
          {pick("minutes", minutes, MIN_OPTS, (v) => setMinutes(Number(v) as (typeof MIN_OPTS)[number]))}
          <Badge tone="muted">not the 120-year cycle</Badge>
        </div>
      }
    >
      <p className="mb-3 max-w-3xl text-sm text-slate-500">
        Standard <b>balance-of-dasha</b> math on the day's exact Moon longitude — nakshatra → lord →
        un-elapsed fraction — with the <b>{minutes} minutes</b> of the session standing in for the
        120-year cycle, anchored at <b>{open} IST</b>. The first mahadasha is cut to its balance;
        full periods follow in Ketu→Venus→Sun→… order, wrapping to tile the session. The{" "}
        <b>lagna °/w</b> column is that period lord's house from the ascendant — by exact degree
        (equal 30° houses on the lagna point), then whole-sign. Not the abstract start-lord grid on
        the Astro screen, and not a different dasha school.
      </p>
      {q.isLoading && !md && <Skeleton rows={8} />}
      {q.error && !md && (
        <p className="text-sm text-slate-500">{DASH} no Moon position stored for this date.</p>
      )}
      {md && <MoonDashaBasis md={md} positions={positions} />}
    </Panel>
  );
}

// ---------------------------------------------------------------------------
// Session price path × dasha  — a deliberately rough inline SVG (decision #11
// lifted 2026-09-03, owner: this one approximate plot on the astro day screen
// only; no charting library; "no charts" still holds everywhere else).
// An open-price line (each bar's open, 5m/15m/1h) over the Moon-anchored dasha bands, plus a 09:00 IST
// planet-places lane (zodiac 0–360°, one snapshot — planets don't move here).
// ---------------------------------------------------------------------------

const GRAHA_ABBR: Record<string, string> = {
  Sun: "Su", Moon: "Mo", Mars: "Ma", Mercury: "Me", Jupiter: "Ju",
  Venus: "Ve", Saturn: "Sa", Rahu: "Ra", Ketu: "Ke", Lagna: "La",
};
const RASHI_SHORT = [
  "Mesh", "Vrsh", "Mith", "Kark", "Simh", "Kany",
  "Tula", "Vrsc", "Dhan", "Maka", "Kumb", "Meen",
];

/** minutes past 09:15 IST for an ISO timestamp (approx — DST-free zone). */
function istMinsFromOpen(iso: string): number {
  const p = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Kolkata",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(new Date(iso));
  const h = Number(p.find((x) => x.type === "hour")?.value ?? 0);
  const m = Number(p.find((x) => x.type === "minute")?.value ?? 0);
  return h * 60 + m - (9 * 60 + 15);
}

const clockAt = (minsFromOpen: number) => {
  const t = (9 * 60 + 15 + minsFromOpen) % 1440;
  const h = Math.floor(t / 60);
  const m = Math.round(t % 60);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
};

/** which mahadasha / antardasha / pratyantar was running at a given minute of
 * the session (the same Moon-anchored dasha the plot draws). Falls back to
 * the last period when a bar prints at/after the dasha's own session end
 * (a slightly-late final print). */
function dashaAt(
  minsFromOpen: number,
  dasha: MoonDasha | undefined,
): { md: string; ad: string; pd: string } {
  const at = (kids: MoonDashaPeriod[]): MoonDashaPeriod | undefined =>
    kids.find((p) => minsFromOpen >= p.start_min && minsFromOpen < p.end_min) ??
    kids[kids.length - 1];
  if (!dasha || dasha.periods.length === 0) return { md: DASH, ad: DASH, pd: DASH };
  const md = at(dasha.periods);
  const ad = md ? at(md.children) : undefined;
  const pd = ad ? at(ad.children) : undefined;
  return { md: md?.abbr ?? DASH, ad: ad?.abbr ?? DASH, pd: pd?.abbr ?? DASH };
}

function SessionDashaPlot({
  bars,
  dasha,
  positions,
}: {
  bars: DayHourBar[];
  dasha: MoonDasha;
  positions: DayPlanet[];
}) {
  const pts = bars
    .filter((b) => b.open != null)
    .map((b) => ({
      m: istMinsFromOpen(b.ts),
      o: b.open as number,
      c: (b.close ?? b.open) as number,
    }))
    .filter((p) => p.m >= -30 && p.m <= dasha.subdivision_minutes + 60)
    .sort((a, b) => a.m - b.m);
  if (pts.length < 2) return null;

  const W = 760;
  const plotH = 150;
  const laneH = 15;
  const pdH = 11;
  const padL = 46;
  const padR = 8;
  const padT = 8;
  const zGap = 24;
  const zH = 38;
  const laneTopMd = padT + plotH + 2;
  const laneTopAd = laneTopMd + laneH + 1;
  const laneTopPd = laneTopAd + laneH + 1;
  const clockY = laneTopPd + pdH + 11;
  const zTop = clockY + zGap;
  const H = zTop + zH + 12;

  const total = dasha.subdivision_minutes;
  const os = pts.map((p) => p.o);
  const rawLo = Math.min(...os);
  const rawHi = Math.max(...os);
  const pad = (rawHi - rawLo) * 0.15 || 1;
  const lo = rawLo - pad;
  const hi = rawHi + pad;
  const span = hi - lo || 1;
  const x = (m: number) => padL + (Math.max(0, Math.min(total, m)) / total) * (W - padL - padR);
  const y = (v: number) => padT + (1 - (v - lo) / span) * plotH;
  const zx = (lon: number) => padL + (((lon % 360) + 360) % 360) / 360 * (W - padL - padR);

  const md = dasha.periods.filter((p) => p.level === 1);
  const ad = dasha.periods.flatMap((p) => p.children.filter((c) => c.level === 2));
  const pd = dasha.periods.flatMap((p) =>
    p.children.flatMap((c) => c.children.filter((g) => g.level === 3)),
  );
  const firstM = pts[0].m;
  const lastM = pts[pts.length - 1].m;

  // each dasha lord's place from the lagna today — by exact degree / whole-sign
  const houseFromLagna = (lord: string): { d: number | null; w: number | null } | null => {
    const g = positions.find((p) => p.body === lord);
    return g ? { d: g.house_from_lagna_deg, w: g.house_from_lagna } : null;
  };

  const movePct = (a: number, b: number): number | null => {
    const seg = pts.filter((p) => p.m >= a - 1e-6 && p.m <= b + 1e-6);
    if (seg.length < 1) return null;
    const first = seg[0].o;
    const last = seg[seg.length - 1].c;
    return first ? ((last - first) / first) * 100 : null;
  };

  const band = (p: MoonDashaPeriod, i: number, yTop: number, h: number, withMove: boolean) => {
    const x1 = x(p.start_min);
    const w = x(p.end_min) - x1;
    const mv = withMove ? movePct(Math.max(p.start_min, firstM), Math.min(p.end_min, lastM)) : null;
    const hh = withMove ? houseFromLagna(p.lord) : null;
    return (
      <g key={`${yTop}-${i}`}>
        <rect
          x={x1}
          y={yTop}
          width={Math.max(0, w)}
          height={h}
          fill={i % 2 ? "rgba(100,116,139,0.10)" : "rgba(100,116,139,0.04)"}
          stroke="rgba(100,116,139,0.25)"
          strokeWidth={0.5}
        />
        {w > 20 && (
          <text x={x1 + 3} y={yTop + h - 4} fontSize={9} fill="#475569">
            {p.abbr}
            {hh && (hh.d != null || hh.w != null) && w > 34 && (
              <tspan fill="#b45309">
                {" "}
                H{hh.d ?? "?"}/{hh.w ?? "?"}
              </tspan>
            )}
            {mv != null && w > 76 && (
              <tspan fill={mv >= 0 ? "#059669" : "#e11d48"}>
                {" "}
                {mv >= 0 ? "+" : ""}
                {mv.toFixed(2)}%
              </tspan>
            )}
          </text>
        )}
      </g>
    );
  };

  const ticks = [0, 60, 120, 180, 240, 300, 360].filter((t) => t <= total);
  const line = pts.map((p) => `${x(p.m)},${y(p.o)}`).join(" ");

  // planets at 09:00 IST — sort by longitude, stagger labels that would collide
  const rowLast = [-999, -999];
  const placed = positions
    .filter((p) => p.longitude != null)
    .map((p) => ({ ...p, lon: p.longitude as number }))
    .sort((a, b) => a.lon - b.lon)
    .map((p) => {
      let row = p.lon - rowLast[0] < 14 ? 1 : 0;
      if (row === 1 && p.lon - rowLast[1] < 14) row = 0; // both crowded — accept overlap
      rowLast[row] = p.lon;
      return { ...p, row };
    });

  // the running mahadasha lord as a graha, and the Lagna, on the same lane
  const mdName = dasha.dasha_lord;
  const mdP = placed.find((p) => p.body === mdName);
  const lagP = placed.find((p) => p.body === "Lagna");

  return (
    <div className="overflow-x-auto">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full"
        role="img"
        aria-label="session open-price line over the Moon-anchored dasha periods, with 09:00 IST planet places"
      >
        {/* price gridlines + labels */}
        {[rawLo, (rawLo + rawHi) / 2, rawHi].map((v, i) => (
          <g key={i}>
            <line x1={padL} x2={W - padR} y1={y(v)} y2={y(v)} stroke="#e2e8f0" strokeWidth={0.5} />
            <text x={4} y={y(v) + 3} fontSize={9} fill="#94a3b8">
              {v.toFixed(0)}
            </text>
          </g>
        ))}
        {/* mahadasha bands behind the line */}
        {md.map((p, i) => band(p, i, padT, plotH, false))}
        {/* open-price line (each bar's open, at the selected timeframe) */}
        <polyline points={line} fill="none" stroke="#1e293b" strokeWidth={1.5} />
        {pts.map((p, i) => (
          <circle key={i} cx={x(p.m)} cy={y(p.o)} r={1.7} fill="#1e293b" />
        ))}
        {/* mahadasha lane (with per-period % move), antardasha lane, pratyantar lane */}
        {[
          { at: laneTopMd, label: "MD" },
          { at: laneTopAd, label: "AD" },
          { at: laneTopPd, label: "PD" },
        ].map((l) => (
          <text key={l.label} x={2} y={l.at + 9} fontSize={7} fill="#cbd5e1">
            {l.label}
          </text>
        ))}
        {md.map((p, i) => band(p, i, laneTopMd, laneH, true))}
        {ad.map((p, i) => band(p, i, laneTopAd, laneH, false))}
        {pd
          .filter((p) => x(p.end_min) - x(p.start_min) >= 1.2) // drop sub-pixel PDs
          .map((p, i) => band(p, i, laneTopPd, pdH, false))}
        {/* clock axis */}
        {ticks.map((t) => (
          <text key={t} x={x(t)} y={clockY} fontSize={9} fill="#94a3b8" textAnchor="middle">
            {clockAt(t)}
          </text>
        ))}
        {/* planet-places lane: zodiac 0–360°, one snapshot at 09:00 IST */}
        <text x={4} y={zTop - 3} fontSize={8} fill="#94a3b8">
          planets 09:00 IST
        </text>
        <rect
          x={padL}
          y={zTop}
          width={W - padL - padR}
          height={zH}
          fill="rgba(148,163,184,0.05)"
          stroke="#e2e8f0"
          strokeWidth={0.5}
        />
        {RASHI_SHORT.map((name, i) => (
          <g key={name}>
            <line
              x1={zx(i * 30)}
              x2={zx(i * 30)}
              y1={zTop}
              y2={zTop + zH}
              stroke="#e2e8f0"
              strokeWidth={0.5}
            />
            <text
              x={zx(i * 30 + 15)}
              y={zTop + zH - 3}
              fontSize={7}
              fill="#cbd5e1"
              textAnchor="middle"
            >
              {name}
            </text>
          </g>
        ))}
        {/* running mahadasha lord ↔ Lagna, drawn above the lane with the house count */}
        {mdP && lagP && (
          <g>
            <line
              x1={zx(lagP.lon)}
              x2={zx(mdP.lon)}
              y1={zTop - 7}
              y2={zTop - 7}
              stroke="#d97706"
              strokeWidth={1}
              strokeDasharray="3 2"
            />
            <circle cx={zx(lagP.lon)} cy={zTop - 7} r={1.6} fill="#7c3aed" />
            <circle cx={zx(mdP.lon)} cy={zTop - 7} r={1.6} fill="#d97706" />
            <text
              x={(zx(lagP.lon) + zx(mdP.lon)) / 2}
              y={zTop - 10}
              fontSize={8}
              fill="#b45309"
              textAnchor="middle"
            >
              La→{GRAHA_ABBR[mdName] ?? mdName.slice(0, 2)} (MD) · house{" "}
              {mdP.house_from_lagna_deg ?? "?"}° / {mdP.house_from_lagna ?? "?"}w
            </text>
          </g>
        )}
        {placed.map((p) => {
          const isLagna = p.body === "Lagna";
          const isMd = p.body === mdName;
          const col = isLagna
            ? "#7c3aed"
            : isMd
              ? "#d97706"
              : p.retrograde
                ? "#e11d48"
                : "#334155";
          const ly = zTop + (p.row === 1 ? 22 : 11);
          return (
            <g key={p.body}>
              <line
                x1={zx(p.lon)}
                x2={zx(p.lon)}
                y1={zTop}
                y2={zTop + zH - (isMd ? 0 : 8)}
                stroke={col}
                strokeWidth={isLagna || isMd ? 1.3 : 0.8}
              />
              <text
                x={zx(p.lon)}
                y={ly}
                fontSize={8}
                fill={col}
                fontWeight={isLagna || isMd ? 700 : 400}
                textAnchor="middle"
              >
                {GRAHA_ABBR[p.body] ?? p.body.slice(0, 2)}
                {p.retrograde ? "℞" : ""}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Planet matrix — pairwise angular separation (degrees) between every body,
// with the classical aspect angles tinted. Pure: reads the day's longitudes.
// ---------------------------------------------------------------------------

/** shortest angular separation of two longitudes, 0–180° */
const sepDeg = (a: number, b: number) => {
  const d = Math.abs(((a - b) % 360) + 360) % 360;
  return d > 180 ? 360 - d : d;
};

/** signed separation a−b wrapped to (−180, 180]: + = a is zodiacally *ahead of*
 *  (in front of) b, − = a is *behind* b. */
const signedSep = (a: number, b: number) => {
  const d = (((a - b) % 360) + 540) % 360; // 0..360 shifted so result is (−180,180]
  return d - 180;
};

// aspect angle -> {label, cell class}. Orb ±6°.
const ASPECTS: { at: number; label: string; cls: string }[] = [
  { at: 0, label: "conjunction", cls: "bg-amber-100 text-amber-800" },
  { at: 60, label: "sextile", cls: "bg-violet-100 text-violet-800" },
  { at: 90, label: "square", cls: "bg-sky-100 text-sky-800" },
  { at: 120, label: "trine", cls: "bg-emerald-100 text-emerald-800" },
  { at: 180, label: "opposition", cls: "bg-rose-100 text-rose-800" },
];
const ASPECT_ORB = 6;
const aspectOf = (deg: number) =>
  ASPECTS.find((a) => Math.abs(deg - a.at) <= ASPECT_ORB) ?? null;

function PlanetMatrix({ positions }: { positions: DayPlanet[] }) {
  const bodies = positions.filter((p) => p.longitude != null);
  if (bodies.length < 2) return null;

  return (
    <Panel
      title="Planet matrix — angular separation"
      right={
        <span className="flex flex-wrap gap-1 text-[10px]">
          {ASPECTS.map((a) => (
            <span key={a.at} className={`rounded px-1 ${a.cls}`}>
              {a.at}° {a.label}
            </span>
          ))}
        </span>
      }
    >
      <p className="mb-2 max-w-3xl text-xs text-slate-500">
        Shortest arc between each pair of grahas (and the Lagna) at 09:00 IST, in degrees. The mark
        shows the <b>row</b> body relative to the <b>column</b> body in zodiacal order:{" "}
        <span className="text-emerald-700">▲ ahead / in front</span>,{" "}
        <span className="text-rose-700">▼ behind</span>. Cells within {ASPECT_ORB}° of a classical
        aspect angle are tinted. Descriptive — no forecast.
      </p>
      <div className="overflow-x-auto">
        <table className="text-xs tabular-nums">
          <thead>
            <tr className="text-slate-400">
              <th className="px-2 py-1" />
              {bodies.map((c) => (
                <th
                  key={c.body}
                  className="px-2 py-1 text-right font-medium"
                  title={`${c.body} ${num(c.longitude, 2)}°`}
                >
                  {GRAHA_ABBR[c.body] ?? c.body.slice(0, 2)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {bodies.map((r) => (
              <tr key={r.body} className="border-t border-slate-100">
                <td
                  className="whitespace-nowrap px-2 py-1 font-medium text-slate-600"
                  title={`${r.body} ${num(r.longitude, 2)}°`}
                >
                  {GRAHA_ABBR[r.body] ?? r.body.slice(0, 2)}
                  <span className="ml-1 text-[10px] text-slate-400">{num(r.longitude, 1)}°</span>
                </td>
                {bodies.map((c) => {
                  if (c.body === r.body)
                    return (
                      <td key={c.body} className="px-2 py-1 text-center text-slate-300">
                        {DASH}
                      </td>
                    );
                  const s = sepDeg(r.longitude as number, c.longitude as number);
                  const sg = signedSep(r.longitude as number, c.longitude as number);
                  const ahead = sg > 0;
                  const asp = aspectOf(s);
                  const dir = `${r.body} is ${s.toFixed(1)}° ${ahead ? "ahead of" : "behind"} ${c.body}`;
                  return (
                    <td
                      key={c.body}
                      className={`px-2 py-1 text-right ${asp ? `rounded ${asp.cls}` : ""}`}
                      title={
                        asp
                          ? `${dir} — ${asp.label}, ${(s - asp.at).toFixed(1)}° orb`
                          : dir
                      }
                    >
                      <span className={ahead ? "text-emerald-600" : "text-rose-500"}>
                        {ahead ? "▲" : "▼"}
                      </span>{" "}
                      {s.toFixed(1)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

const ordinal = (n: number) => `${n}${["th", "st", "nd", "rd"][n % 10 > 3 || (n >= 11 && n <= 13) ? 0 : n % 10]}`;
const TITHI_NAME = [
  "Pratipada", "Dwitiya", "Tritiya", "Chaturthi", "Panchami", "Shashthi", "Saptami",
  "Ashtami", "Navami", "Dashami", "Ekadashi", "Dwadashi", "Trayodashi", "Chaturdashi",
  "Purnima/Amavasya",
];
const tithiName = (inPaksha: number) => TITHI_NAME[Math.min(Math.max(inPaksha, 1), 15) - 1];

function BadhakaShoonyaPanel({
  badhaka,
  shoonya,
}: {
  badhaka: DayBadhaka[];
  shoonya: DayTithiShoonya | null;
}) {
  return (
    <Panel title="Badhaka & Tithi Shoonyam">
      {badhaka.length > 0 && (
        <div className="mb-3 overflow-x-auto">
          <div className="mb-1 text-xs font-medium text-slate-500">
            Baadhagaadhipathi — badhaka house &amp; its lord
          </div>
          <table className="w-full text-xs tabular-nums">
            <thead className="text-slate-400">
              <tr className="border-b border-slate-200">
                <th className="px-2 py-1 text-left">from</th>
                <th className="px-2 py-1 text-left">sign</th>
                <th className="px-2 py-1 text-right">badhaka</th>
                <th className="px-2 py-1 text-left">badhaka sign</th>
                <th className="px-2 py-1 text-left">lord</th>
                <th className="px-2 py-1 text-right">lord now</th>
              </tr>
            </thead>
            <tbody>
              {badhaka.map((b) => (
                <tr key={b.frame} className="border-b border-slate-100 last:border-0">
                  <td className="px-2 py-1">{b.reference}</td>
                  <td className="px-2 py-1 text-slate-500">
                    {b.reference_sign} · {b.movability.toLowerCase()}
                  </td>
                  <td className="px-2 py-1 text-right font-medium">{ordinal(b.badhaka_house)}</td>
                  <td className="px-2 py-1">{b.badhaka_sign}</td>
                  <td className="px-2 py-1 font-medium text-rose-700">{b.badhaka_lord}</td>
                  <td className="px-2 py-1 text-right text-slate-500">
                    {b.badhaka_lord_house_from_ref != null
                      ? `${ordinal(b.badhaka_lord_house_from_ref)} from ref`
                      : DASH}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {shoonya && (
        <div className="space-y-1.5">
          <div className="text-xs font-medium text-slate-500">
            Tithi Shoonyam — {shoonya.tithi_name || tithiName(shoonya.tithi_in_paksha)}{" "}
            ({shoonya.paksha})
          </div>
          <StatGrid
            rows={[
              [
                "Today's tithi",
                `${shoonya.paksha} ${shoonya.tithi_name || tithiName(shoonya.tithi_in_paksha)} (${shoonya.tithi_in_paksha} / ${shoonya.tithi})`,
              ],
              [
                "Shoonya rashis (this tithi)",
                shoonya.shoonya_rashis.length
                  ? shoonya.shoonya_rashis.map((r) => r.name).join(", ")
                  : DASH,
              ],
              [
                "Bodies in a shoonya rashi",
                shoonya.bodies_in_shoonya.length ? (
                  <span key="b" className="rounded bg-rose-100 px-1.5 py-0.5 font-medium text-rose-800">
                    {shoonya.bodies_in_shoonya.map((b) => `${b.body} (${b.rashi})`).join(", ")}
                  </span>
                ) : (
                  <span key="b" className="text-emerald-700">none — all clear</span>
                ),
              ],
              [
                `Masa Shunya (${shoonya.chandra_masa ?? "n/a"}${
                  shoonya.chandra_masa_approx && shoonya.chandra_masa ? " ~" : ""
                })`,
                <span
                  key="v"
                  className={
                    shoonya.is_shoonya
                      ? "rounded bg-rose-100 px-1.5 py-0.5 font-semibold text-rose-800"
                      : "text-slate-600"
                  }
                >
                  {shoonya.is_shoonya
                    ? "SHOONYA — void tithi for this masa"
                    : shoonya.shoonya_tithis.length
                      ? `not a void tithi (masa voids: ${shoonya.shoonya_tithis
                          .map((t) => tithiName(t))
                          .join(", ")})`
                      : "not a void tithi"}
                </span>,
              ],
            ]}
          />
        </div>
      )}

      <p className="mt-2 text-[11px] text-slate-400">
        Badhaka: movable lagna → 11th, fixed → 9th, dual → 7th; its sign-lord is the
        Baadhagaadhipathi. Tithi Shoonyam: each tithi holds certain rashis "void" (owner table) —
        a graha or the lagna sitting in one is read as blunted; the "Masa Shunya" line is the
        separate classical per-lunar-month void-tithi check (month back-estimated from the
        Sun–Moon elongation, so a day off near a sankranti). Descriptive — not a forecast.
      </p>
    </Panel>
  );
}

function Seg({ value, onChange }: { value: Frame; onChange: (f: Frame) => void }) {
  return (
    <div className="inline-flex overflow-hidden rounded border border-slate-300 text-xs">
      {FRAMES.map((o, i) => (
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

export function AstroDay() {
  const { date = "" } = useParams();
  const [sp] = useSearchParams();
  const underlying = sp.get("underlying") || "NIFTY-INDEX";
  const q = useAstroDayDetail(date, underlying);
  const [frame, setFrame] = useState<Frame>("lagna");
  const [tf, setTf] = useState<"H1" | "M15" | "M5">("H1");


  const planetCols: Col<DayPlanet>[] = [
    { key: "b", header: "graha", cell: (p) => <span className="font-medium">{p.body}</span> },
    {
      key: "sign",
      header: "rashi",
      cell: (p) =>
        p.changed_rashi ? (
          <span className="rounded bg-amber-100 px-1 font-medium text-amber-800">
            {p.rashi}
            <span className="ml-1 text-xs font-normal text-amber-600">← {p.prev_rashi}</span>
          </span>
        ) : (
          p.rashi
        ),
    },
    {
      key: "deg",
      header: "° in sign",
      align: "right",
      cell: (p) => <span className="font-mono">{num(p.degree, 2)}</span>,
    },
    {
      key: "nak",
      header: "nakshatra",
      cell: (p) => (
        <span>
          <span
            className={
              p.changed_nakshatra
                ? "rounded bg-amber-100 px-1 font-medium text-amber-800"
                : ""
            }
          >
            {p.nakshatra}
          </span>{" "}
          <span
            className={
              p.changed_pada
                ? "rounded bg-amber-100 px-1 font-medium text-amber-800"
                : "text-slate-400"
            }
          >
            p{p.pada}
          </span>
          {(p.changed_nakshatra || p.changed_pada) && (
            <span className="ml-1 text-xs text-amber-600">
              ← {p.changed_nakshatra ? p.prev_nakshatra : ""}
              {p.changed_pada ? ` p${p.prev_pada}` : ""}
            </span>
          )}
          <span className="ml-1 text-xs text-slate-400">· {p.nakshatra_lord}</span>
        </span>
      ),
    },
    {
      key: "house",
      header: `house (${FRAMES.find((f) => f.id === frame)?.label})`,
      cell: (p) => {
        const { h, g } = houseOf(p, frame);
        return h == null ? (
          DASH
        ) : (
          <span className="whitespace-nowrap">
            <b className="font-mono">{h}</b>
            <span
              className={`ml-1.5 rounded px-1 py-0.5 text-xs ${GROUP_META[g ?? ""]?.cls ?? ""}`}
            >
              {groupTag(g)}
            </span>
          </span>
        );
      },
    },
    {
      key: "state",
      header: "state",
      cell: (p) => (
        <span className="flex flex-wrap gap-1">
          {p.retrograde && <Badge tone="warn">retro</Badge>}
          {p.dignity && <Badge tone="muted">{p.dignity}</Badge>}
          {p.changed_retrograde && (
            <Badge tone="bad">→ {p.retrograde ? "turned retro" : "turned direct"}</Badge>
          )}
        </span>
      ),
    },
    {
      key: "spd",
      header: "speed °/day",
      align: "right",
      cell: (p) => <span className="font-mono">{num(p.speed_longitude, 3)}</span>,
    },
  ];

  const shadCols: Col<DayShadbala>[] = [
    { key: "g", header: "graha", cell: (s) => <span className="font-medium">{s.graha}</span> },
    { key: "rank", header: "rank", align: "right", cell: (s) => s.rank },
    {
      key: "rupa",
      header: "total (rupa)",
      align: "right",
      cell: (s) => <span className="font-mono">{num(s.total_rupa, 2)}</span>,
    },
    { key: "req", header: "required", align: "right", cell: (s) => num(s.required_rupa, 2) },
    {
      key: "ratio",
      header: "×req",
      align: "right",
      cell: (s) => (
        <span className={s.strength_ratio >= 1 ? "text-emerald-600" : "text-rose-600"}>
          {num(s.strength_ratio, 2)}
        </span>
      ),
    },
    { key: "sth", header: "sthana", align: "right", cell: (s) => num(s.sthana_bala, 0) },
    { key: "dig", header: "dig", align: "right", cell: (s) => num(s.dig_bala, 0) },
    { key: "kala", header: "kala", align: "right", cell: (s) => num(s.kala_bala, 0) },
    { key: "che", header: "cheshta", align: "right", cell: (s) => num(s.cheshta_bala, 0) },
    { key: "nai", header: "naisargika", align: "right", cell: (s) => num(s.naisargika_bala, 0) },
    { key: "drik", header: "drik", align: "right", cell: (s) => num(s.drik_bala, 0) },
    {
      key: "ish",
      header: "ishta / kashta",
      align: "right",
      cell: (s) => `${num(s.ishta_phala, 1)} / ${num(s.kashta_phala, 1)}`,
    },
  ];

  const d = q.data;
  const bars = d ? (tf === "M15" ? d.market.m15 : tf === "M5" ? d.market.m5 : d.market.hourly) : [];
  const moon = d?.astro.positions.find((p) => p.body === "Moon");
  const sun = d?.astro.positions.find((p) => p.body === "Sun");
  const plotDasha =
    d?.astro.moon_dasha.find((x) => x.subdivision_minutes === 390) ?? d?.astro.moon_dasha[0];

  const hourCols: Col<DayHourBar>[] = [
    { key: "t", header: "IST", cell: (b) => <span className="font-mono">{istTime(b.ts)}</span> },
    { key: "o", header: "open", align: "right", cell: (b) => num(b.open, 2) },
    { key: "h", header: "high", align: "right", cell: (b) => num(b.high, 2) },
    { key: "l", header: "low", align: "right", cell: (b) => num(b.low, 2) },
    { key: "c", header: "close", align: "right", cell: (b) => num(b.close, 2) },
    {
      key: "chg",
      header: "bar %",
      align: "right",
      cell: (b) =>
        b.open && b.close ? <Move v={((b.close - b.open) / b.open) * 100} /> : DASH,
    },
    { key: "v", header: "vol", align: "right", cell: (b) => int(b.volume ?? null) },
    {
      key: "md",
      header: "MD",
      cell: (b) => dashaAt(istMinsFromOpen(b.ts), plotDasha).md,
    },
    {
      key: "ad",
      header: "AD",
      cell: (b) => dashaAt(istMinsFromOpen(b.ts), plotDasha).ad,
    },
    {
      key: "pd",
      header: "PD",
      cell: (b) => dashaAt(istMinsFromOpen(b.ts), plotDasha).pd,
    },
  ];

  const activeFrame = d?.astro.house_frames.find((f) => f.frame === frame);
  const refName = activeFrame?.reference ?? "Lagna";
  const naklordPos = d?.astro.positions.find(
    (p) => p.body === d.astro.day?.moon_nakshatra_lord,
  );
  const naklordDeg = naklordPos?.degree ?? null;
  const naklordSign = naklordPos?.rashi ?? null;
  // grahas whose whole-sign house (= rashi) shifted since the previous weekday
  const movedHouse = new Set(
    (d?.astro.positions ?? []).filter((p) => p.changed_rashi).map((p) => p.body),
  );

  const houseGroupCols: Col<DayHouseGroup>[] = [
    {
      key: "g",
      header: "group",
      cell: (r) => (
        <span className={`rounded px-1.5 py-0.5 font-medium ${GROUP_META[r.group]?.cls ?? ""}`}>
          {r.group}
        </span>
      ),
    },
    {
      key: "h",
      header: "houses",
      cell: (r) => <span className="font-mono">{r.houses.join(" · ")}</span>,
    },
    {
      key: "hint",
      header: "",
      cell: (r) => <span className="text-xs text-slate-400">{GROUP_META[r.group]?.hint}</span>,
    },
    {
      key: "bodies",
      header: `occupants (from ${refName})`,
      cell: (r) =>
        r.bodies.length ? (
          <span className="flex flex-wrap gap-1">
            {r.bodies.map((b) => (
              <Badge
                key={b}
                tone={
                  movedHouse.has(b) ? "warn" : b === refName || b === "Lagna" ? "ok" : "muted"
                }
                title={movedHouse.has(b) ? "changed sign since the previous weekday" : undefined}
              >
                {movedHouse.has(b) ? `${b} ▸` : b}
              </Badge>
            ))}
          </span>
        ) : (
          <span className="text-slate-300">{DASH}</span>
        ),
    },
  ];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Link to="/astro" className="text-sm text-blue-700 hover:underline">
          ← Astro
        </Link>
        <h1 className="text-lg font-bold">{date ? longDate(date) : "Day"}</h1>
        <Badge tone="muted">{underlying.replace("-INDEX", "")}</Badge>
        <Badge tone="muted">descriptive, not predictive</Badge>
        <LastUpdated q={q} />
      </div>

      {q.isLoading && <Skeleton rows={10} />}
      {q.error && <ProblemError error={q.error} onRetry={() => q.refetch()} />}

      {d && (
        <>
          <Panel title="Market — daily candle">
            {d.market.d1 ? (
              <StatGrid
                rows={[
                  ["Open", num(d.market.d1.open, 2)],
                  ["High", num(d.market.d1.high, 2)],
                  ["Low", num(d.market.d1.low, 2)],
                  ["Close", num(d.market.d1.close, 2)],
                  ["Prev close", num(d.market.d1.prev_close, 2)],
                  ["Gap (open vs prev close)", <Move key="gap" v={d.market.d1.gap_pct} />],
                  ["Change (close vs prev close)", <Move key="chg" v={d.market.d1.ret_pct} />],
                  [
                    "Day range (high−low, intraday only)",
                    `${num(d.market.d1.range_pct, 2)} %`,
                  ],
                  ["Volume", int(d.market.d1.volume ?? null)],
                ]}
              />
            ) : (
              <p className="text-sm text-slate-500">{DASH} no daily bar stored for this date.</p>
            )}
          </Panel>

          <Panel
            title="Market — intraday"
            right={
              <div className="flex items-center gap-2 text-xs text-slate-400">
                <select
                  className="rounded border border-slate-300 bg-white px-2 py-1 text-slate-700"
                  value={tf}
                  onChange={(e) => setTf(e.target.value as "H1" | "M15" | "M5")}
                >
                  <option value="H1">1 hour</option>
                  <option value="M15">15 min</option>
                  <option value="M5">5 min</option>
                </select>
                <span>{bars.length} bars · session-open anchored</span>
              </div>
            }
          >
            {bars.length > 0 ? (
              <>
                {plotDasha && (
                  <div className="mb-3">
                    <p className="mb-1 text-xs text-slate-400">
                      rough {TF_LABEL[tf]} open-price line (each bar's open) over
                      the Moon-anchored mahadasha bands ({plotDasha.subdivision_minutes}-min basis);
                      lower lane = each mahadasha tagged{" "}
                      <span className="text-amber-700">H{"<by-degree>"}/{"<whole-sign>"}</span> — that
                      lord's house from the lagna today — plus its approx % move, then the
                      antardasha (AD) and pratyantar (PD) lanes;
                      bottom strip = the 09:00 IST planet places on the zodiac (℞ = retrograde,{" "}
                      <span className="text-violet-600">La</span> = lagna,{" "}
                      <span className="text-amber-600">amber</span> = running mahadasha lord linked to
                      the lagna)
                    </p>
                    <SessionDashaPlot bars={bars} dasha={plotDasha} positions={d.astro.positions} />
                  </div>
                )}
                {plotDasha && (
                  <p className="mb-1 text-xs text-slate-400">
                    <b>MD / AD / PD</b> = the mahadasha / antardasha / pratyantar lord running at
                    each bar's own time (same {plotDasha.subdivision_minutes}-min basis as the
                    plot above).
                  </p>
                )}
                <DataTable cols={hourCols} rows={bars} rowKey={(b) => b.ts} />
              </>
            ) : (
              <p className="text-sm text-slate-500">
                {DASH} no {TF_LABEL[tf]} bars stored for this date (index intraday begins 2022).
              </p>
            )}
          </Panel>

          <Panel title="Panchang — 09:00 IST, Mumbai (sidereal, Lahiri)">
            {d.astro.day ? (
              <StatGrid
                rows={[
                  ["Weekday", `${d.astro.day.day_name} · ${d.astro.day.weekday_lord}`],
                  [
                    "Tithi",
                    `${d.astro.day.tithi} (${d.astro.day.paksha})`,
                  ],
                  ...(d.astro.day.chandra_masa
                    ? [
                        [
                          "Chandra masa",
                          `${d.astro.day.chandra_masa} (amanta, approx)`,
                        ] as [string, string],
                      ]
                    : []),
                  [
                    "Moon",
                    `${d.astro.day.moon_rashi} · ${d.astro.day.moon_nakshatra} p${d.astro.day.moon_pada} · ${d.astro.day.moon_nakshatra_lord}`,
                  ],
                  [
                    "Lagna",
                    `${d.astro.day.lagna_rashi} · ${d.astro.day.lagna_nakshatra} p${d.astro.day.lagna_pada}`,
                  ],
                  ...(moon?.house_from_lagna != null
                    ? [
                        [
                          "Moon from lagna",
                          `${moon.house_from_lagna}th · ${groupTag(moon.house_group_lagna)}`,
                        ] as [string, string],
                      ]
                    : []),
                  ["Sun", d.astro.day.sun_rashi],
                  ...(sun?.house_from_lagna != null
                    ? [
                        [
                          "Sun from lagna",
                          `${sun.house_from_lagna}th · ${groupTag(sun.house_group_lagna)}`,
                        ] as [string, string],
                      ]
                    : []),
                  ["Sunrise / sunset", `${istTime(d.astro.day.sunrise_ts)} / ${istTime(d.astro.day.sunset_ts)}`],
                  ["Ayanamsha", num(d.astro.day.ayanamsha, 4)],
                ]}
              />
            ) : (
              <p className="text-sm text-slate-500">{DASH} no chart stored for this date.</p>
            )}
          </Panel>

          {(d.astro.badhaka.length > 0 || d.astro.tithi_shoonya) && (
            <BadhakaShoonyaPanel
              badhaka={d.astro.badhaka}
              shoonya={d.astro.tithi_shoonya}
            />
          )}

          {date && (
            <KpLordsPanel date={date} underlying={underlying} hourly={d.market.hourly} />
          )}

          {date && (
            <MoonDashaPanel
              date={date}
              underlying={underlying}
              positions={d.astro.positions}
            />
          )}

          {d.astro.house_frames.length > 0 && activeFrame && (
            <Panel
              title={`Houses from ${refName} — trikona groups`}
              right={<Seg value={frame} onChange={setFrame} />}
            >
              <p className="mb-3 max-w-2xl text-sm text-slate-500">
                {frame === "lagna_deg" ? (
                  <>
                    Equal houses of 30° anchored on the <b>exact ascendant degree</b>
                    {d.astro.day?.lagna_longitude != null && (
                      <> ({num(d.astro.day.lagna_longitude % 30, 2)}° {d.astro.day.lagna_rashi})</>
                    )}{" "}
                    — house 1 runs from the lagna point to +30°, and so on, so a graha just{" "}
                    <i>before</i> the lagna degree sits in the 12th even if it shares the sign.
                  </>
                ) : frame === "naklord_deg" ? (
                  <>
                    Equal houses of 30° anchored on the <b>exact degree of the Moon's current
                    nakshatra-lord</b> — today that's{" "}
                    <b>{d.astro.day?.moon_nakshatra_lord ?? DASH}</b>
                    {naklordDeg != null && <> ({num(naklordDeg, 2)}° {naklordSign})</>}, since the
                    Moon is in <b>{d.astro.day?.moon_nakshatra}</b>. The reference graha itself
                    changes as the Moon moves nakshatra to nakshatra (Ashlesha/Ayilyam → Mercury,
                    Ardra → Rahu, Moola → Ketu, …) — same 30°-from-the-point math as lagna-by-degree.
                  </>
                ) : (
                  <>Whole-sign houses counted from the {refName.toLowerCase()}.</>
                )}{" "}
                The twelve fall into four groups 120° apart — 1·5·9, 2·6·10, 3·7·11, 4·8·12 — here
                showing where each graha sits relative to the {refName.toLowerCase()} today. The
                same toggle drives the “house” column below.
              </p>
              <DataTable
                cols={houseGroupCols}
                rows={activeFrame.groups}
                rowKey={(r) => r.group}
              />
            </Panel>
          )}

          {d.astro.positions.length > 0 && (
            <Panel
              title="Planets — sidereal positions"
              right={
                d.astro.prev_date ? (
                  <span className="text-xs text-slate-400">
                    <span className="rounded bg-amber-100 px-1 text-amber-800">amber</span> = changed
                    since {d.astro.prev_date}
                  </span>
                ) : undefined
              }
            >
              <DataTable cols={planetCols} rows={d.astro.positions} rowKey={(p) => p.body} />
            </Panel>
          )}

          {d.astro.positions.length > 1 && <PlanetMatrix positions={d.astro.positions} />}

          {d.astro.shadbala.length > 0 && (
            <Panel
              title="Shadbala — Parashari six-fold strength"
              right={<span className="text-xs text-slate-400">virupas; ×req ≥ 1 = adequate</span>}
            >
              <DataTable cols={shadCols} rows={d.astro.shadbala} rowKey={(s) => s.graha} />
            </Panel>
          )}
        </>
      )}
    </div>
  );
}
