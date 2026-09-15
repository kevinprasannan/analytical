/** Opening-range breakout backtest (docs/16).
 *
 * Configurable range / breakout windows + target multiples, run over stored
 * M1 / M15 index bars. Per-day + aggregate hit-rates. Descriptive research —
 * no signal, no label, no BUY/SELL. Table only. */
import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { useInstrument, useOrbBacktest } from "@/api/queries";
import { Badge, Panel, ProblemError, Skeleton, StatGrid } from "@/components/primitives";
import { LastUpdated } from "@/components/LastUpdated";
import type { OrbBacktestParams, OrbDayResult } from "@/api/generated/schema";
import { DASH, num } from "@/lib/format";

const WD = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const pct = (v: number) => `${(v * 100).toFixed(0)}%`;
const clk = (min: number | null) =>
  min == null ? DASH : `${String(Math.floor(min / 60)).padStart(2, "0")}:${String(min % 60).padStart(2, "0")}`;
const DIR_TONE: Record<string, string> = {
  LONG: "text-emerald-600 font-medium",
  SHORT: "text-rose-600 font-medium",
  NONE: "text-slate-400",
};

function Field({
  label,
  value,
  onChange,
  type = "text",
  w = "w-24",
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  w?: string;
}) {
  return (
    <label className="flex flex-col gap-0.5 text-xs text-slate-500">
      {label}
      <input
        type={type}
        className={`${w} rounded border border-slate-300 bg-white px-2 py-1 text-sm text-slate-800`}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}

const today = () => new Date().toISOString().slice(0, 10);
const daysAgo = (n: number) => new Date(Date.now() - n * 864e5).toISOString().slice(0, 10);

export function Backtest() {
  const id = Number(useParams().id);
  const inst = useInstrument(id);

  const [form, setForm] = useState({
    start: daysAgo(365),
    end: today(),
    range_start: "09:40",
    range_end: "09:55",
    break_start: "09:55",
    break_end: "10:15",
    measure_until: "15:15",
    targets: "0.5,1.0",
    timeframe: "M1" as "M1" | "M15",
  });
  const [submitted, setSubmitted] = useState<typeof form | null>(null);
  const set = (k: keyof typeof form, v: string) =>
    setForm((f) => ({ ...f, [k]: v }) as typeof form);

  const q = useOrbBacktest(id, (submitted ?? form) as OrbBacktestParams, submitted != null);
  const d = q.data;

  const dayRows = useMemo(() => d?.days ?? [], [d]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Link to={`/instruments/${id}`} className="text-sm text-blue-700 hover:underline">
          ← {inst.data?.symbol ?? `#${id}`}
        </Link>
        <h1 className="text-lg font-bold">Opening-range breakout — backtest</h1>
        <Badge tone="muted">descriptive · not a signal</Badge>
        {submitted != null && <LastUpdated q={q} />}
      </div>

      <Panel title="Parameters">
        <div className="flex flex-wrap items-end gap-3">
          <Field label="from" type="date" w="w-36" value={form.start} onChange={(v) => set("start", v)} />
          <Field label="to" type="date" w="w-36" value={form.end} onChange={(v) => set("end", v)} />
          <Field label="range from" value={form.range_start} onChange={(v) => set("range_start", v)} />
          <Field label="range to" value={form.range_end} onChange={(v) => set("range_end", v)} />
          <Field label="breakout from" value={form.break_start} onChange={(v) => set("break_start", v)} />
          <Field label="breakout to" value={form.break_end} onChange={(v) => set("break_end", v)} />
          <Field
            label="measure until"
            value={form.measure_until}
            onChange={(v) => set("measure_until", v)}
          />
          <Field label="targets (×range)" value={form.targets} onChange={(v) => set("targets", v)} />
          <label className="flex flex-col gap-0.5 text-xs text-slate-500">
            bars
            <select
              className="rounded border border-slate-300 bg-white px-2 py-1 text-sm text-slate-800"
              value={form.timeframe}
              onChange={(e) => set("timeframe", e.target.value)}
            >
              <option value="M1">1 min</option>
              <option value="M15">15 min</option>
            </select>
          </label>
          <button
            type="button"
            onClick={() => setSubmitted({ ...form })}
            className="rounded bg-slate-800 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700"
          >
            Run
          </button>
        </div>
        <p className="mt-2 max-w-3xl text-xs text-slate-400">
          Range window → its high/low. First cross of an edge in the breakout window → LONG / SHORT
          (or an immediate breakout if price is already outside at the window start). Stop = the
          opposite edge; a bar touching both target and stop counts as stopped. Outcome measured to{" "}
          <b>measure until</b>. M1 gives minute-precise windows; M15 is faster but coarse.
        </p>
      </Panel>

      {q.isLoading && <Skeleton rows={10} />}
      {q.error && <ProblemError error={q.error} onRetry={() => q.refetch()} />}

      {d && (
        <>
          <Panel
            title="Result"
            right={
              <span className="font-mono text-xs text-slate-400">
                {d.underlying_symbol} · {d.timeframe} · {d.start} → {d.end}
              </span>
            }
          >
            <StatGrid
              rows={[
                ["Days sampled", `${d.aggregate.n_days} (range on ${d.aggregate.n_with_range})`],
                [
                  "Breakouts",
                  `${d.aggregate.n_breakout} (${pct(d.aggregate.breakout_rate)}) · ${d.aggregate.n_long} long / ${d.aggregate.n_short} short · ${d.aggregate.n_immediate} immediate`,
                ],
                ...d.aggregate.per_target.map(
                  (t) =>
                    [
                      `Target ${t.mult}× hit`,
                      <span key={t.mult}>
                        <b>{pct(t.hit_rate)}</b> of breakouts ({t.hits})
                        {t.avg_minutes_to_hit != null && (
                          <span className="text-slate-400"> · avg {t.avg_minutes_to_hit} min</span>
                        )}
                      </span>,
                    ] as [string, ReactNode],
                ),
                ["Stop hit", `${pct(d.aggregate.stop_rate)} of breakouts`],
                [
                  "Avg range / MFE / MAE",
                  `${d.aggregate.avg_range_size ?? DASH} pts · ${d.aggregate.avg_mfe_r ?? DASH}R fav · ${d.aggregate.avg_mae_r ?? DASH}R adv`,
                ],
              ]}
            />
          </Panel>

          <Panel title="By weekday">
            <div className="overflow-x-auto">
              <table className="w-full text-xs tabular-nums">
                <thead className="text-slate-400">
                  <tr className="border-b border-slate-200">
                    <th className="px-2 py-1 text-left">day</th>
                    <th className="px-2 py-1 text-right">n</th>
                    <th className="px-2 py-1 text-right">breakouts</th>
                    {d.config.target_mults.map((m) => (
                      <th key={m} className="px-2 py-1 text-right">
                        {m}× hit
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {d.aggregate.by_weekday.map((w) => (
                    <tr key={w.weekday} className="border-b border-slate-100">
                      <td className="px-2 py-1">{WD[w.weekday]}</td>
                      <td className="px-2 py-1 text-right text-slate-400">{w.n}</td>
                      <td className="px-2 py-1 text-right">{w.n_breakout}</td>
                      {w.per_target_hit_rate.map(([m, r]) => (
                        <td key={m} className="px-2 py-1 text-right">
                          {pct(r)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>

          <Panel title={`${dayRows.length} days`}>
            <div className="overflow-x-auto">
              <table className="w-full text-xs tabular-nums">
                <thead className="text-slate-400">
                  <tr className="border-b border-slate-200">
                    <th className="px-2 py-1 text-left">date</th>
                    <th className="px-2 py-1 text-left">day</th>
                    <th className="px-2 py-1 text-right">range</th>
                    <th className="px-2 py-1 text-right">size</th>
                    <th className="px-2 py-1 text-left">dir</th>
                    <th className="px-2 py-1 text-right">break</th>
                    {d.config.target_mults.map((m) => (
                      <th key={m} className="px-2 py-1 text-right">
                        {m}× (min)
                      </th>
                    ))}
                    <th className="px-2 py-1 text-right">stop</th>
                    <th className="px-2 py-1 text-right">MFE</th>
                    <th className="px-2 py-1 text-right">MAE</th>
                  </tr>
                </thead>
                <tbody>
                  {dayRows.map((r: OrbDayResult) => (
                    <tr key={r.date} className="border-b border-slate-100">
                      <td className="px-2 py-1 font-mono">{r.date}</td>
                      <td className="px-2 py-1 text-slate-500">{WD[r.weekday]}</td>
                      <td className="px-2 py-1 text-right text-slate-500">
                        {r.range_low == null ? DASH : `${num(r.range_low, 1)}–${num(r.range_high, 1)}`}
                      </td>
                      <td className="px-2 py-1 text-right">{r.range_size == null ? DASH : num(r.range_size, 1)}</td>
                      <td className={`px-2 py-1 ${DIR_TONE[r.direction]}`}>
                        {r.direction === "NONE" ? "—" : r.direction}
                        {r.break_immediate && <span className="ml-1 text-[10px] text-amber-600">imm</span>}
                      </td>
                      <td className="px-2 py-1 text-right font-mono">{clk(r.break_minute)}</td>
                      {r.targets.map((t, i) => (
                        <td
                          key={i}
                          className={`px-2 py-1 text-right ${
                            t.hit ? "text-emerald-600" : t.stopped_first ? "text-rose-500" : "text-slate-400"
                          }`}
                        >
                          {t.hit ? (t.minutes_to_hit ?? 0) : t.stopped_first ? "stop" : DASH}
                        </td>
                      ))}
                      <td className={`px-2 py-1 text-right ${r.stop_hit ? "text-rose-500" : "text-slate-300"}`}>
                        {r.stop_hit ? clk(r.stop_minute) : DASH}
                      </td>
                      <td className="px-2 py-1 text-right text-slate-500">{r.mfe_r ?? DASH}</td>
                      <td className="px-2 py-1 text-right text-slate-500">{r.mae_r ?? DASH}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {r_note(dayRows)}
          </Panel>

          <p className="text-[11px] text-slate-400">
            engine {d.algo_version} · module {d.index_orb_version} · descriptive backtest, not advice
          </p>
        </>
      )}
    </div>
  );
}

function r_note(rows: OrbDayResult[]) {
  const notes = new Set(rows.map((r) => r.note).filter(Boolean) as string[]);
  if (!notes.size) return null;
  return (
    <p className="mt-2 text-[11px] text-slate-400">
      no-breakout reasons: {[...notes].join(" · ")}
    </p>
  );
}
