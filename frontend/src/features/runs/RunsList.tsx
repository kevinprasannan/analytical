import { useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "@/api/client";
import { useRuns, useTriggerRun } from "@/api/queries";
import type { RunSummary } from "@/api/generated/schema";
import { DataTable, ProblemError, Skeleton, StatusPill } from "@/components/primitives";
import { LastUpdated } from "@/components/LastUpdated";
import { dt } from "@/lib/format";

const ALL_PHASES = ["INGEST", "ANALYZE", "SCORE"];

export function RunsList() {
  const q = useRuns();
  const trigger = useTriggerRun();
  const [open, setOpen] = useState(false);
  const [phases, setPhases] = useState<string[]>(ALL_PHASES);
  const [note, setNote] = useState<string | null>(null);

  function run() {
    setNote(null);
    trigger.mutate(
      { phases },
      {
        onSuccess: () => setOpen(false),
        onError: (e) => {
          if (e instanceof ApiError && e.status === 409) {
            const ra = e.problem.detail;
            setNote(`A cycle is already running. ${ra}`);
          } else {
            setNote(e instanceof Error ? e.message : String(e));
          }
        },
      },
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="flex items-baseline gap-2 text-lg font-bold">
          Runs
          <LastUpdated q={q} className="font-normal" />
        </h1>
        <button
          onClick={() => setOpen(true)}
          className="rounded bg-slate-800 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700"
        >
          Trigger run
        </button>
      </div>

      {open && (
        <div className="rounded-lg border border-slate-300 bg-white p-4">
          <p className="mb-2 text-sm font-semibold">Trigger a manual cycle</p>
          <div className="flex flex-wrap gap-3 text-sm">
            {ALL_PHASES.map((p) => (
              <label key={p} className="flex items-center gap-1">
                <input
                  type="checkbox"
                  checked={phases.includes(p)}
                  onChange={(e) =>
                    setPhases((cur) => (e.target.checked ? [...cur, p] : cur.filter((x) => x !== p)))
                  }
                />
                {p}
              </label>
            ))}
          </div>
          <div className="mt-3 flex gap-2">
            <button
              disabled={trigger.isPending || phases.length === 0}
              onClick={run}
              className="rounded bg-slate-800 px-3 py-1.5 text-sm text-white disabled:opacity-50"
            >
              {trigger.isPending ? "running…" : "Run"}
            </button>
            <button onClick={() => setOpen(false)} className="rounded border border-slate-300 px-3 py-1.5 text-sm">
              Cancel
            </button>
          </div>
          {note && <p className="mt-2 text-sm text-amber-700">{note}</p>}
        </div>
      )}

      {q.isLoading && <Skeleton rows={10} />}
      {q.isError && <ProblemError error={q.error} onRetry={() => q.refetch()} />}
      {q.data && (
        <DataTable<RunSummary>
          cols={[
            { key: "seq", header: "Cycle", cell: (r) => <Link className="text-blue-700 hover:underline" to={`/runs/${r.id}`}>#{r.cycle_seq}</Link> },
            { key: "trigger", header: "Trigger", cell: (r) => r.trigger },
            { key: "status", header: "Status", cell: (r) => <StatusPill status={r.status} /> },
            { key: "started", header: "Started", cell: (r) => dt(r.started_at) },
            { key: "finished", header: "Finished", cell: (r) => dt(r.finished_at) },
            { key: "algo", header: "Versions", cell: (r) => <span className="font-mono text-xs">{r.algo_version} / {r.scoring_version}</span> },
          ]}
          rows={q.data.items}
          rowKey={(r) => r.id}
        />
      )}
    </div>
  );
}
