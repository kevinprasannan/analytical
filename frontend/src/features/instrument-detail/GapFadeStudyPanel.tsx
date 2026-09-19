/** Gap-fade streak study (docs/05 §9f, docs/07 §4.26).
 *
 * Not a backtest — a descriptive historical study covering BOTH reversal
 * directions: a day that gaps up but still closes down (bearish reversal),
 * and its mirror — a day that gaps down but still closes up (bullish
 * reversal). For each, this counts the streak that follows (continuing in
 * the reversal's own direction), the price box set once the streak ends,
 * how long price stayed inside it, and which way it eventually broke out.
 * Aggregated across the full available history, per direction. Computed on
 * read; descriptive — no entry/target/stop, no BUY/SELL. */
import { useState } from "react";
import { useGapFadeStudy } from "@/api/queries";
import { Panel, ProblemError, Skeleton } from "@/components/primitives";
import type { GapFadeOccurrence, GapFadeSummary } from "@/api/generated/schema";
import { DASH, num, pct, price } from "@/lib/format";

const STATUS_LABEL: Record<string, string> = {
  STREAK_ONGOING: "streak still running",
  INSUFFICIENT_BOX_DATA: "too recent",
  CONSOLIDATING: "still consolidating",
  BREAKOUT_UP: "broke up",
  BREAKOUT_DOWN: "broke down",
};

const STATUS_TONE: Record<string, string> = {
  STREAK_ONGOING: "text-slate-400",
  INSUFFICIENT_BOX_DATA: "text-slate-400",
  CONSOLIDATING: "text-amber-600",
  BREAKOUT_UP: "text-emerald-600",
  BREAKOUT_DOWN: "text-rose-600",
};

const DIRECTION_META: Record<string, { title: string; streakLabel: string; tone: string }> = {
  UP: {
    title: "Gap-up fade — bearish reversal",
    streakLabel: "down-streak",
    tone: "border-rose-200",
  },
  DOWN: {
    title: "Gap-down fade — bullish reversal",
    streakLabel: "up-streak",
    tone: "border-emerald-200",
  },
};

function OccurrenceRow({ o }: { o: GapFadeOccurrence }) {
  return (
    <tr className="border-b border-slate-50">
      <td className="px-2 py-1 font-mono">{o.event_date}</td>
      <td className="px-2 py-1 text-right">
        {o.gap_pct >= 0 ? "+" : ""}
        {num(o.gap_pct, 2)}% / {o.change_pct >= 0 ? "+" : ""}
        {num(o.change_pct, 2)}%
      </td>
      <td className="px-2 py-1 text-right">{o.streak_days}d</td>
      <td className="px-2 py-1">
        {o.box_high != null && o.box_low != null ? (
          <span className="font-mono text-slate-600">
            {price(o.box_low)}–{price(o.box_high)}
          </span>
        ) : (
          <span className="text-slate-300">{DASH}</span>
        )}
      </td>
      <td className="px-2 py-1 text-right">
        {o.consolidation_days != null ? `${o.consolidation_days}d` : DASH}
      </td>
      <td className={`px-2 py-1 ${STATUS_TONE[o.status] ?? "text-slate-500"}`}>
        {STATUS_LABEL[o.status] ?? o.status}
        {o.breakout_date && <span className="ml-1 text-[11px] text-slate-400">{o.breakout_date}</span>}
      </td>
    </tr>
  );
}

function DirectionSection({
  direction,
  summary,
  occurrences,
}: {
  direction: string;
  summary: GapFadeSummary | undefined;
  occurrences: GapFadeOccurrence[];
}) {
  const meta = DIRECTION_META[direction] ?? { title: direction, streakLabel: "streak", tone: "" };
  if (!summary || summary.n_occurrences === 0) {
    return (
      <div className={`rounded border ${meta.tone} px-3 py-2`}>
        <div className="mb-1 text-sm font-semibold text-slate-700">{meta.title}</div>
        <p className="text-sm text-slate-400">
          {DASH} no days matched these thresholds in the available history.
        </p>
      </div>
    );
  }
  return (
    <div className={`space-y-3 rounded border ${meta.tone} p-3`}>
      <div className="text-sm font-semibold text-slate-700">{meta.title}</div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <div className="rounded border border-slate-200 px-3 py-2">
          <div className="text-xs text-slate-500">occurrences</div>
          <div className="font-mono text-lg text-slate-800">{summary.n_occurrences}</div>
        </div>
        <div className="rounded border border-slate-200 px-3 py-2">
          <div className="text-xs text-slate-500">median {meta.streakLabel}</div>
          <div className="font-mono text-lg text-slate-800">
            {summary.median_streak_days ?? DASH}d
          </div>
        </div>
        <div className="rounded border border-slate-200 px-3 py-2">
          <div className="text-xs text-slate-500">median consolidation</div>
          <div className="font-mono text-lg text-slate-800">
            {summary.median_consolidation_days ?? DASH}d
          </div>
        </div>
        <div className="rounded border border-slate-200 px-3 py-2">
          <div className="text-xs text-slate-500">breakout split (of {summary.n_breakout_resolved})</div>
          <div className="font-mono text-lg">
            <span className="text-emerald-600">{summary.breakout_up_count}↑</span>
            {" / "}
            <span className="text-rose-600">{summary.breakout_down_count}↓</span>
            {summary.breakout_up_pct != null && (
              <span className="ml-1 text-xs text-slate-400">({pct(summary.breakout_up_pct / 100, 0)} up)</span>
            )}
          </div>
        </div>
      </div>

      <div>
        <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
          {meta.streakLabel} length — how often
        </div>
        <div className="flex flex-wrap gap-1.5">
          {Object.entries(summary.streak_day_histogram).map(([len, count]) => (
            <span
              key={len}
              className="rounded bg-slate-100 px-2 py-1 text-xs text-slate-600"
              title={`${count} occurrence${count === 1 ? "" : "s"} with a ${len}-day ${meta.streakLabel}`}
            >
              {len}d × {count}
            </span>
          ))}
        </div>
      </div>

      <div>
        <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
          every occurrence ({occurrences.length})
        </div>
        <div className="max-h-72 overflow-auto rounded border border-slate-200">
          <table className="w-full text-xs tabular-nums">
            <thead className="sticky top-0 bg-slate-50 text-slate-500">
              <tr>
                <th className="px-2 py-1 text-left">event</th>
                <th className="px-2 py-1 text-right">gap / close</th>
                <th className="px-2 py-1 text-right">streak</th>
                <th className="px-2 py-1 text-left">box</th>
                <th className="px-2 py-1 text-right">in box</th>
                <th className="px-2 py-1 text-left">outcome</th>
              </tr>
            </thead>
            <tbody>
              {occurrences.map((o, i) => (
                <OccurrenceRow key={i} o={o} />
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

export function GapFadeStudyPanel({ instrumentId }: { instrumentId: number }) {
  const [gapMag, setGapMag] = useState(0.5);
  const [chgMag, setChgMag] = useState(0.5);
  const q = useGapFadeStudy(instrumentId, {
    gap_up_min_pct: gapMag,
    chg_down_max_pct: -chgMag,
    gap_down_max_pct: -gapMag,
    chg_up_min_pct: chgMag,
  });
  const d = q.data;

  return (
    <Panel
      title="Gap-fade streak study"
      right={
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
          <label className="flex items-center gap-1">
            gap ≥
            <input
              type="number"
              step={0.1}
              min={0}
              value={gapMag}
              onChange={(e) => setGapMag(Math.max(0, Number(e.target.value)))}
              className="w-14 rounded border border-slate-300 px-1 py-0.5"
            />
            %
          </label>
          <label className="flex items-center gap-1">
            close ≥
            <input
              type="number"
              step={0.1}
              min={0}
              value={chgMag}
              onChange={(e) => setChgMag(Math.max(0, Number(e.target.value)))}
              className="w-14 rounded border border-slate-300 px-1 py-0.5"
            />
            % (either way)
          </label>
          {d && <span className="font-mono">module {d.gap_fade_study_version}</span>}
        </div>
      }
    >
      <p className="mb-2 max-w-3xl text-sm text-slate-500">
        Not a backtest — a historical study, covering <b>both</b> reversal directions: a day that
        gaps up but still closes down (bearish), and its mirror — a day that gaps down but still
        closes up (bullish). Each qualifying day (by the ± thresholds above) gets its own
        <b> streak</b> (continuing in the reversal's own direction), a price <b>box</b> once the
        streak ends, and however it eventually <b>broke out</b>. Descriptive — no entry, no target,
        no stop.
      </p>

      {q.isLoading && !d && <Skeleton rows={8} />}
      {q.error && <ProblemError error={q.error} onRetry={() => q.refetch()} />}

      {d && d.status === "NOT_APPLICABLE" && (
        <p className="text-sm text-slate-500">{DASH} the gap-fade study runs on the INDEX / FUTURE series.</p>
      )}
      {d && d.status === "INSUFFICIENT_DATA" && (
        <p className="text-sm text-slate-500">{DASH} {d.reason ?? "not enough daily history yet."}</p>
      )}

      {d && d.status === "OK" && (
        <div className="grid gap-3 lg:grid-cols-2">
          <DirectionSection
            direction="UP"
            summary={d.summaries.find((s) => s.direction === "UP")}
            occurrences={d.occurrences.filter((o) => o.direction === "UP")}
          />
          <DirectionSection
            direction="DOWN"
            summary={d.summaries.find((s) => s.direction === "DOWN")}
            occurrences={d.occurrences.filter((o) => o.direction === "DOWN")}
          />
        </div>
      )}
    </Panel>
  );
}
