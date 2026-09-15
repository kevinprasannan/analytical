import { useMemo, useState } from "react";
import { useCalendar, useCalendarStatus } from "@/api/queries";
import { Panel, ProblemError, Skeleton, StatGrid, Badge } from "@/components/primitives";
import { LastUpdated } from "@/components/LastUpdated";
import { dt } from "@/lib/format";

function isoDate(d: Date) {
  return d.toISOString().slice(0, 10);
}

export function CalendarView() {
  const status = useCalendarStatus(60_000);
  const [start, setStart] = useState(isoDate(new Date()));
  const [end, setEnd] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() + 30);
    return isoDate(d);
  });
  const cal = useCalendar(start, end);

  const s = status.data;
  const rows = useMemo(() => cal.data?.days ?? [], [cal.data]);

  return (
    <div className="space-y-4">
      <h1 className="flex items-baseline gap-2 text-lg font-bold">
        Trading calendar
        <LastUpdated q={[status, cal]} className="font-normal" />
      </h1>

      <Panel title="Session status" right={s && <Badge tone={s.is_open ? "ok" : "muted"}>{s.is_open ? "open" : "closed"}</Badge>}>
        {status.isLoading && <Skeleton rows={3} />}
        {s && (
          <StatGrid
            rows={[
              ["Now (IST)", dt(s.as_of.ist)],
              ["Session type", s.session_type ?? "—"],
              ["Next open", s.next_open ? `${dt(s.next_open.ist)} IST` : "—"],
              ["Next close", s.next_close ? `${dt(s.next_close.ist)} IST` : "—"],
              ["Seeded until", s.seeded_until ?? "—"],
            ]}
          />
        )}
      </Panel>

      <Panel
        title="Days"
        right={
          <span className="flex items-center gap-1 text-xs">
            <input type="date" value={start} onChange={(e) => setStart(e.target.value)} className="rounded border border-slate-300 px-1" />
            →
            <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} className="rounded border border-slate-300 px-1" />
          </span>
        }
      >
        {cal.isLoading && <Skeleton rows={10} />}
        {cal.isError && <ProblemError error={cal.error} onRetry={() => cal.refetch()} />}
        {cal.data && (
          <div className="max-h-[60vh] overflow-auto rounded border border-slate-200">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-slate-50 text-left text-xs uppercase text-slate-500">
                <tr>
                  <th className="px-3 py-2">Date</th>
                  <th className="px-3 py-2">Trading</th>
                  <th className="px-3 py-2">Session (IST)</th>
                  <th className="px-3 py-2">Type</th>
                  <th className="px-3 py-2">Segment</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {rows.map((r) => (
                  <tr key={r.calendar_date} className={r.is_trading_day ? "" : "text-slate-400"}>
                    <td className="px-3 py-1.5 font-mono">{r.calendar_date}</td>
                    <td className="px-3 py-1.5">{r.is_trading_day ? "yes" : "—"}</td>
                    <td className="px-3 py-1.5 font-mono">
                      {r.is_trading_day ? `${r.session_open_ist}–${r.session_close_ist}` : "—"}
                    </td>
                    <td className="px-3 py-1.5">{r.session_type}</td>
                    <td className="px-3 py-1.5">{r.segment}</td>
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
