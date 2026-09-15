import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useAnalysisRuns, useInstrument } from "@/api/queries";
import { ANALYSIS_ORDER } from "@/lib/scope";
import { DataTable, Panel, ProblemError, Skeleton, StatusPill, Badge } from "@/components/primitives";
import { LastUpdated } from "@/components/LastUpdated";
import { dt, num } from "@/lib/format";

export function InstrumentRunsView() {
  const id = Number(useParams().id);
  const inst = useInstrument(id);
  const [key, setKey] = useState("rsi");
  const q = useAnalysisRuns(id, key);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-lg font-bold">
          <Link className="text-blue-700 hover:underline" to={`/instruments/${id}`}>
            {inst.data?.contract_key ?? `#${id}`}
          </Link>{" "}
          — per-run audit trail
          <LastUpdated q={q} className="ml-2 align-middle font-normal" />
        </h1>
        <select value={key} onChange={(e) => setKey(e.target.value)} className="rounded border border-slate-300 px-2 py-1 text-sm">
          {ANALYSIS_ORDER.map((k) => (
            <option key={k}>{k}</option>
          ))}
        </select>
      </div>

      <Panel title={`${key} — recompute log (per cycle, not per bar)`}>
        {q.isLoading && <Skeleton rows={8} />}
        {q.isError && <ProblemError error={q.error} onRetry={() => q.refetch()} />}
        {q.data && (
          <DataTable
            cols={[
              { key: "run", header: "Run", cell: (r) => <Link className="text-blue-700 hover:underline" to={`/runs/${r.run_id}`}>#{r.run_id}</Link> },
              { key: "scope", header: "Scope key", cell: (r) => <span className="font-mono text-xs">{r.scope_key}</span> },
              { key: "status", header: "Status", cell: (r) => <StatusPill status={r.status} /> },
              { key: "carried", header: "Carried", cell: (r) => (r.carried ? <Badge tone="muted" title={`from #${r.carried_from_result_id}`}>carried</Badge> : "—") },
              { key: "asof", header: "As of", cell: (r) => dt(r.as_of_ts) },
              { key: "bars", header: "Bars", align: "right", cell: (r) => num(r.bars_used, 0) },
              { key: "cov", header: "Coverage", align: "right", cell: (r) => num(r.coverage_ratio, 3) },
              { key: "hash", header: "params_hash", cell: (r) => <span className="font-mono text-xs">{r.params_hash}</span> },
            ]}
            rows={q.data.runs}
            rowKey={(r) => r.run_id + r.scope_key}
          />
        )}
      </Panel>
    </div>
  );
}
