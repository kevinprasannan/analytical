import { useParams, Link } from "react-router-dom";
import { useRun } from "@/api/queries";
import { Panel, ProblemError, Skeleton, StatusPill, Badge } from "@/components/primitives";
import { LastUpdated } from "@/components/LastUpdated";
import { dt } from "@/lib/format";

export function RunDetailView() {
  const id = Number(useParams().id);
  const q = useRun(id);

  if (q.isLoading) return <Skeleton rows={8} />;
  if (q.isError) return <ProblemError error={q.error} onRetry={() => q.refetch()} />;
  const r = q.data!;

  const byInst = new Map<number, Record<string, string>>();
  for (const s of r.instrument_status) {
    const row = byInst.get(s.instrument_id) ?? {};
    row[s.phase] = s.outcome;
    byInst.set(s.instrument_id, row);
  }

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-bold">
        Run #{r.cycle_seq} <StatusPill status={r.status} />
        <LastUpdated q={q} className="ml-2 align-middle font-normal" />
      </h1>
      <p className="text-sm text-slate-500">
        {r.trigger} · {dt(r.started_at)} → {dt(r.finished_at)} · params_hash{" "}
        <span className="font-mono">{r.params_hash}</span>
      </p>

      <div className="grid gap-3 md:grid-cols-3">
        {r.phase_status.map((p) => (
          <Panel key={p.phase} title={p.phase} right={<StatusPill status={p.status} />}>
            <ul className="text-sm">
              {Object.entries(p.counts).map(([k, v]) => (
                <li key={k} className="flex justify-between">
                  <span className="text-slate-500">{k}</span>
                  <span className="font-mono">{v}</span>
                </li>
              ))}
              {Object.keys(p.counts).length === 0 && <li className="text-slate-400">no counts</li>}
            </ul>
          </Panel>
        ))}
      </div>

      <Panel title="Per-instrument outcomes">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="px-3 py-2">Instrument</th>
                <th className="px-3 py-2">INGEST</th>
                <th className="px-3 py-2">ANALYZE</th>
                <th className="px-3 py-2">SCORE</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {[...byInst.entries()].map(([iid, row]) => (
                <tr key={iid}>
                  <td className="px-3 py-2">
                    <Link className="text-blue-700 hover:underline" to={`/instruments/${iid}`}>#{iid}</Link>
                  </td>
                  {["INGEST", "ANALYZE", "SCORE"].map((ph) => (
                    <td key={ph} className="px-3 py-2">
                      {row[ph] ? <StatusPill status={row[ph]!} /> : "—"}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel title="config_snapshot" right={<Badge tone="muted">read-only</Badge>}>
        <pre className="max-h-96 overflow-auto rounded bg-slate-50 p-2 text-xs">
          {JSON.stringify(r.config_snapshot, null, 2)}
        </pre>
      </Panel>
    </div>
  );
}
