/** Gann time cycles (docs/05 §9e, docs/07 §4.25).
 *
 * Classic W.D. Gann day-count projections (45/90/120/144/180/270/360 calendar
 * days by default) from the previous swing low and swing high over a ~1y
 * daily lookback. A date where several projections land close together is a
 * confluence cluster — a stronger "time turn" candidate by this method.
 * Computed on read; descriptive — a calendar-date study, not a signal, no
 * entry/target/stop. */
import { useGannCycles } from "@/api/queries";
import { Panel, ProblemError, Skeleton } from "@/components/primitives";
import type { GannCluster, GannProjection } from "@/api/generated/schema";
import { DASH, price } from "@/lib/format";

const kindTone = (k: string) => (k === "LOW" ? "text-emerald-600" : "text-rose-600");

const dayLabel = (d: number) => (d === 0 ? "today" : d > 0 ? `in ${d}d` : `${-d}d ago`);

function ActualCell({ p }: { p: GannProjection }) {
  if (p.actual_close == null) return <td className="px-2 py-1 text-slate-300">{DASH}</td>;
  const shifted = p.resolved_date != null && p.resolved_date !== p.target_date;
  return (
    <td className="px-2 py-1">
      <div className="font-mono text-slate-700">{price(p.actual_close)}</div>
      {p.actual_low != null && p.actual_high != null && (
        <div className="text-[11px] text-slate-400">
          {price(p.actual_low)}–{price(p.actual_high)}
          {shifted && ` · as of ${p.resolved_date}`}
        </div>
      )}
    </td>
  );
}

function ProjectionRow({ p }: { p: GannProjection }) {
  const upcoming = p.days_from_today >= 0;
  return (
    <tr className={`border-b border-slate-50 ${upcoming ? "" : "text-slate-400"}`}>
      <td className="px-2 py-1 font-mono">{p.target_date}</td>
      <td className={`px-2 py-1 ${kindTone(p.anchor_kind)}`}>
        {p.anchor_kind === "LOW" ? "low" : "high"} + {p.cycle_days}d
      </td>
      <td className="px-2 py-1 text-slate-500">
        from {p.anchor_date} ({price(p.anchor_price)})
      </td>
      <ActualCell p={p} />
      <td className="px-2 py-1 text-right">{dayLabel(p.days_from_today)}</td>
    </tr>
  );
}

function ClusterCard({ c }: { c: GannCluster }) {
  const upcoming = c.days_from_today >= 0;
  return (
    <div
      className={`rounded border px-3 py-2 ${
        upcoming ? "border-amber-300 bg-amber-50" : "border-slate-200 bg-slate-50"
      }`}
    >
      <div className="flex items-center justify-between">
        <span className="font-mono font-semibold text-slate-800">{c.cluster_date}</span>
        <span className={`text-xs ${upcoming ? "font-semibold text-amber-700" : "text-slate-400"}`}>
          {dayLabel(c.days_from_today)} · {c.strength} cycles converge
        </span>
      </div>
      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-slate-500">
        {c.projections.map((p, i) => (
          <span key={i} className={kindTone(p.anchor_kind)}>
            {p.anchor_kind === "LOW" ? "low" : "high"}+{p.cycle_days}d
          </span>
        ))}
      </div>
    </div>
  );
}

export function GannCyclesPanel({ instrumentId }: { instrumentId: number }) {
  const q = useGannCycles(instrumentId);
  const d = q.data;

  return (
    <Panel
      title="Gann time cycles"
      right={
        d && <span className="font-mono text-xs text-slate-500">module {d.gann_cycles_version}</span>
      }
    >
      <p className="mb-2 max-w-3xl text-sm text-slate-500">
        Classic Gann day-count cycles (45 / 90 / 120 / 144 / 180 / 270 / 360 calendar days) counted
        forward from the <span className="text-emerald-600">previous swing low</span> and{" "}
        <span className="text-rose-600">previous swing high</span> over roughly the last year of
        daily bars. A date where several projections land within a couple of days of each other is
        a <b>confluence cluster</b> — a stronger "time turn" candidate by this method. Once a
        projected date has passed, the <b>actual</b> column below fills in with what really
        happened there (close + day's range) so you can judge the date against real price action.
        A calendar-date study, not a signal — no entry, no target, no stop.
      </p>

      {q.isLoading && !d && <Skeleton rows={5} />}
      {q.error && <ProblemError error={q.error} onRetry={() => q.refetch()} />}

      {d && d.status === "NOT_APPLICABLE" && (
        <p className="text-sm text-slate-500">{DASH} Gann time cycles run on the INDEX / FUTURE series.</p>
      )}
      {d && d.status === "INSUFFICIENT_DATA" && (
        <p className="text-sm text-slate-500">{DASH} {d.reason ?? "not enough daily history yet."}</p>
      )}

      {d && d.status === "OK" && (
        <div className="space-y-3">
          {d.swing_low && d.swing_high && (
            <div className="grid gap-2 sm:grid-cols-2">
              <div className="rounded border border-emerald-200 bg-emerald-50 px-3 py-2">
                <div className="text-xs font-medium text-emerald-700">previous swing low</div>
                <div className="font-mono text-emerald-800">
                  {price(d.swing_low.price)} · {d.swing_low.anchor_date}
                </div>
              </div>
              <div className="rounded border border-rose-200 bg-rose-50 px-3 py-2">
                <div className="text-xs font-medium text-rose-700">previous swing high</div>
                <div className="font-mono text-rose-800">
                  {price(d.swing_high.price)} · {d.swing_high.anchor_date}
                </div>
              </div>
            </div>
          )}

          {d.clusters.length > 0 && (
            <div>
              <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                Confluence clusters
              </div>
              <div className="space-y-1.5">
                {d.clusters.map((c, i) => (
                  <ClusterCard key={i} c={c} />
                ))}
              </div>
            </div>
          )}

          <div>
            <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
              All projections ({d.projections.length})
            </div>
            {d.projections.length === 0 ? (
              <p className="text-sm text-slate-400">{DASH} nothing within the projection horizon.</p>
            ) : (
              <div className="max-h-64 overflow-auto rounded border border-slate-200">
                <table className="w-full text-xs tabular-nums">
                  <thead className="sticky top-0 bg-slate-50 text-slate-500">
                    <tr>
                      <th className="px-2 py-1 text-left">date</th>
                      <th className="px-2 py-1 text-left">cycle</th>
                      <th className="px-2 py-1 text-left">anchor</th>
                      <th className="px-2 py-1 text-left">actual</th>
                      <th className="px-2 py-1 text-right">when</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.projections.map((p, i) => (
                      <ProjectionRow key={i} p={p} />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}
    </Panel>
  );
}
