import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useAnalysisSeries, useInstrument } from "@/api/queries";
import { useTimeframe } from "@/lib/timeframe";
import { ANALYSIS_ORDER } from "@/lib/scope";
import { Panel, ProblemError, Skeleton, StatusPill } from "@/components/primitives";
import { LastUpdated } from "@/components/LastUpdated";
import { dt, num } from "@/lib/format";

export function InstrumentSeries() {
  const id = Number(useParams().id);
  const [tf] = useTimeframe();
  const inst = useInstrument(id);
  const [key, setKey] = useState("rsi");
  const q = useAnalysisSeries(id, key, tf);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-lg font-bold">
          <Link className="text-blue-700 hover:underline" to={`/instruments/${id}?tf=${tf}`}>
            {inst.data?.contract_key ?? `#${id}`}
          </Link>{" "}
          — per-bar series ({tf})
          <LastUpdated q={q} className="ml-2 align-middle font-normal" />
        </h1>
        <select value={key} onChange={(e) => setKey(e.target.value)} className="rounded border border-slate-300 px-2 py-1 text-sm">
          {ANALYSIS_ORDER.filter((k) => k !== "market_profile").map((k) => (
            <option key={k}>{k}</option>
          ))}
        </select>
      </div>

      <Panel title={`${key} — one row per finalized bar`}>
        {q.isLoading && <Skeleton rows={10} />}
        {q.isError && <ProblemError error={q.error} onRetry={() => q.refetch()} />}
        {q.data && q.data.points.length === 0 && <p className="text-sm text-slate-500">No finalized results yet.</p>}
        {q.data && q.data.points.length > 0 && (
          <div className="max-h-[70vh] overflow-auto rounded border border-slate-200">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-slate-50 text-left text-slate-500">
                <tr>
                  <th className="px-2 py-1">Bar ts</th>
                  <th className="px-2 py-1">Status</th>
                  {Object.keys(q.data.points[0]!.values).map((c) => (
                    <th key={c} className="px-2 py-1 text-right">
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 font-mono tabular-nums">
                {q.data.points.map((p, i) => (
                  <tr key={i}>
                    <td className="whitespace-nowrap px-2 py-1">{dt(p.ts)}</td>
                    <td className="px-2 py-1">
                      <StatusPill status={p.status} />
                    </td>
                    {Object.keys(q.data!.points[0]!.values).map((c) => {
                      const val = p.values[c];
                      return (
                        <td key={c} className="px-2 py-1 text-right">
                          {typeof val === "number" ? num(val, 4) : String(val ?? "—")}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
