/** Economic event calendar (docs/05 §9g, docs/07 §4.27).
 *
 * Not live news — a small set of recurring-date event types (US jobs report,
 * India GST collection, monthly F&O/gold/silver expiry, Fed rate decisions)
 * with a before/after price read on the instrument being viewed, shown on
 * an actual calendar grid. Most occurrences pass without a large move; the
 * notable-move rate below is the real historical frequency, not an
 * assumption. Computed on read; descriptive — no signal, no
 * entry/target/stop. */
import { useMemo, useState } from "react";
import { useEventCalendar } from "@/api/queries";
import { Panel, ProblemError, Skeleton } from "@/components/primitives";
import type { EventOccurrence } from "@/api/generated/schema";
import { DASH, num, pct } from "@/lib/format";

const EVENT_LABEL: Record<string, string> = {
  US_JOBS_REPORT: "Jobs",
  US_JOBLESS_CLAIMS: "Claims",
  INDIA_GST_COLLECTION: "GST",
  FNO_EXPIRY: "F&O Exp",
  MCX_GOLD_EXPIRY: "MCX Gold",
  MCX_SILVER_EXPIRY: "MCX Silver",
  COMEX_GOLD_EXPIRY: "COMEX Gold",
  COMEX_SILVER_EXPIRY: "COMEX Silver",
  FED_RATE_DECISION: "Fed",
  ECB_RATE_DECISION: "ECB",
  RBI_RATE_DECISION: "RBI",
};
const EVENT_TONE: Record<string, string> = {
  US_JOBS_REPORT: "bg-sky-100 text-sky-800",
  US_JOBLESS_CLAIMS: "bg-cyan-100 text-cyan-800",
  INDIA_GST_COLLECTION: "bg-violet-100 text-violet-800",
  FNO_EXPIRY: "bg-amber-100 text-amber-800",
  MCX_GOLD_EXPIRY: "bg-yellow-100 text-yellow-800",
  MCX_SILVER_EXPIRY: "bg-slate-200 text-slate-700",
  COMEX_GOLD_EXPIRY: "bg-orange-100 text-orange-800",
  COMEX_SILVER_EXPIRY: "bg-stone-200 text-stone-700",
  FED_RATE_DECISION: "bg-rose-100 text-rose-800",
  ECB_RATE_DECISION: "bg-indigo-100 text-indigo-800",
  RBI_RATE_DECISION: "bg-fuchsia-100 text-fuchsia-800",
};
const EVENT_ORDER = [
  "US_JOBS_REPORT",
  "US_JOBLESS_CLAIMS",
  "INDIA_GST_COLLECTION",
  "FED_RATE_DECISION",
  "ECB_RATE_DECISION",
  "RBI_RATE_DECISION",
  "FNO_EXPIRY",
  "MCX_GOLD_EXPIRY",
  "MCX_SILVER_EXPIRY",
  "COMEX_GOLD_EXPIRY",
  "COMEX_SILVER_EXPIRY",
];

const monthKey = (iso: string) => iso.slice(0, 7); // "YYYY-MM"
const addMonths = (ym: string, n: number) => {
  const [y, m] = ym.split("-").map(Number);
  const d = new Date(Date.UTC(y, m - 1 + n, 1));
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
};
const monthLabel = (ym: string) => {
  const [y, m] = ym.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, 1)).toLocaleDateString("en-GB", {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
};

/** weeks -> 7 day-cells each; nulls pad the first/last week. Monday-first. */
function buildMonthGrid(ym: string): (string | null)[][] {
  const [y, m] = ym.split("-").map(Number);
  const daysInMonth = new Date(Date.UTC(y, m, 0)).getUTCDate();
  const firstWeekday = (new Date(Date.UTC(y, m - 1, 1)).getUTCDay() + 6) % 7; // Mon=0
  const cells: (string | null)[] = [
    ...Array(firstWeekday).fill(null),
    ...Array.from({ length: daysInMonth }, (_, i) => `${ym}-${String(i + 1).padStart(2, "0")}`),
  ];
  while (cells.length % 7 !== 0) cells.push(null);
  const weeks: (string | null)[][] = [];
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));
  return weeks;
}

function DayBadge({ o }: { o: EventOccurrence }) {
  const resolved = o.change_pct != null;
  return (
    <div
      className={`rounded px-1 py-0.5 text-[10px] leading-tight ${EVENT_TONE[o.event_type] ?? "bg-slate-100 text-slate-600"}`}
      title={`${EVENT_LABEL[o.event_type] ?? o.event_type} — ${o.event_date}`}
    >
      <div className="font-medium">{EVENT_LABEL[o.event_type] ?? o.event_type}</div>
      {resolved ? (
        <div className={o.change_pct! >= 0 ? "text-emerald-700" : "text-rose-700"}>
          {o.change_pct! >= 0 ? "+" : ""}
          {num(o.change_pct, 2)}%
        </div>
      ) : (
        <div className="text-slate-400">{DASH}</div>
      )}
    </div>
  );
}

function SummaryCard({ eventType, s }: { eventType: string; s: EventOccurrenceSummaryLike }) {
  return (
    <div className="rounded border border-slate-200 px-3 py-2">
      <div className={`mb-1 inline-block rounded px-1.5 py-0.5 text-[11px] font-medium ${EVENT_TONE[eventType] ?? ""}`}>
        {EVENT_LABEL[eventType] ?? eventType}
      </div>
      {s ? (
        <>
          <div className="text-xs text-slate-500">
            {s.n_resolved} of {s.n_occurrences} with data
          </div>
          {s.n_resolved > 0 ? (
            <>
              <div className="font-mono text-sm text-slate-700">
                median move {s.median_abs_change_pct != null ? `${num(s.median_abs_change_pct, 2)}%` : DASH}
              </div>
              <div className="text-xs text-slate-500">
                {s.pct_notable_move != null ? pct(s.pct_notable_move / 100, 0) : DASH} of occurrences moved
                notably ·{" "}
                <span className="text-emerald-600">{s.up_count}↑</span>/
                <span className="text-rose-600">{s.down_count}↓</span>
              </div>
            </>
          ) : (
            <div className="text-xs text-slate-400">no historical data available for this event</div>
          )}
        </>
      ) : (
        <div className="text-xs text-slate-400">{DASH}</div>
      )}
    </div>
  );
}

type EventOccurrenceSummaryLike = {
  n_occurrences: number;
  n_resolved: number;
  median_abs_change_pct: number | null;
  pct_notable_move: number | null;
  up_count: number;
  down_count: number;
} | undefined;

export function EventCalendarPanel({ instrumentId }: { instrumentId: number }) {
  const q = useEventCalendar(instrumentId);
  const d = q.data;
  const today = new Date().toISOString().slice(0, 7);
  const [month, setMonth] = useState(today);

  const byDay = useMemo(() => {
    const map = new Map<string, EventOccurrence[]>();
    for (const o of d?.occurrences ?? []) {
      if (monthKey(o.event_date) !== month) continue;
      const list = map.get(o.event_date) ?? [];
      list.push(o);
      map.set(o.event_date, list);
    }
    return map;
  }, [d, month]);

  const weeks = useMemo(() => buildMonthGrid(month), [month]);

  return (
    <Panel
      title="Economic event calendar"
      right={
        <div className="flex items-center gap-2 text-xs text-slate-500">
          <button
            type="button"
            onClick={() => setMonth((m) => addMonths(m, -1))}
            className="rounded border border-slate-300 px-1.5 py-0.5 hover:bg-slate-50"
          >
            ◀
          </button>
          <span className="min-w-[9rem] text-center font-medium text-slate-700">{monthLabel(month)}</span>
          <button
            type="button"
            onClick={() => setMonth((m) => addMonths(m, 1))}
            className="rounded border border-slate-300 px-1.5 py-0.5 hover:bg-slate-50"
          >
            ▶
          </button>
          {month !== today && (
            <button type="button" onClick={() => setMonth(today)} className="text-sky-600 hover:underline">
              today
            </button>
          )}
          {d && <span className="font-mono">module {d.event_calendar_version}</span>}
        </div>
      }
    >
      <p className="mb-2 max-w-3xl text-sm text-slate-500">
        Not breaking news — a small set of <b>recurring-date</b> events (US jobs report: 1st Friday
        of month; US jobless claims: every Thursday; India GST collection: ~1st of month; Fed/ECB/RBI
        rate decisions; monthly F&amp;O/MCX/COMEX gold+silver expiry) with the actual price move
        before → after each date, on the instrument you're viewing. Most occurrences pass quietly —
        the "notable move" rate below is the real historical frequency, not a guess.{" "}
        <b>Fed/ECB/RBI rate decisions</b> are manually maintained lists — 2023-2025 from training
        knowledge at moderate confidence, plus a few owner-confirmed 2026 Fed dates (never guessed
        for 2026+ — no formula exists for committee-set dates). <b>MCX gold/silver expiry</b> use
        MCX's 5th-of-month rule, approximated against NSE trading days (no MCX holiday calendar
        here, but MCX and NSE share Indian holidays so this stays close). <b>COMEX gold/silver
        expiry</b> use a rougher 27th-of-month rule-of-thumb — COMEX (US) and NSE (India) don't
        share a holiday calendar at all, so this can be off by more than the MCX approximation.
        Descriptive only — no signal, no entry, no target, no stop.
      </p>

      {q.isLoading && !d && <Skeleton rows={6} />}
      {q.error && <ProblemError error={q.error} onRetry={() => q.refetch()} />}

      {d && d.status === "NOT_APPLICABLE" && (
        <p className="text-sm text-slate-500">{DASH} the event calendar runs on the INDEX / FUTURE series.</p>
      )}
      {d && d.status === "INSUFFICIENT_DATA" && (
        <p className="text-sm text-slate-500">{DASH} {d.reason ?? "not enough daily history yet."}</p>
      )}

      {d && d.status === "OK" && (
        <div className="space-y-3">
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {EVENT_ORDER.map((et) => (
              <SummaryCard key={et} eventType={et} s={d.summaries.find((s) => s.event_type === et)} />
            ))}
          </div>

          <div className="overflow-x-auto">
            <table className="w-full table-fixed border-collapse text-xs">
              <thead>
                <tr>
                  {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((wd) => (
                    <th key={wd} className="border-b border-slate-200 px-1 py-1 text-left font-normal text-slate-400">
                      {wd}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {weeks.map((week, wi) => (
                  <tr key={wi}>
                    {week.map((day, di) => (
                      <td
                        key={di}
                        className={`h-16 max-w-0 align-top border border-slate-100 px-1 py-1 ${
                          day === today + "-" + String(new Date().getUTCDate()).padStart(2, "0")
                            ? "bg-sky-50"
                            : ""
                        }`}
                      >
                        {day && (
                          <>
                            <div className="text-[11px] text-slate-400">{Number(day.slice(-2))}</div>
                            <div className="space-y-0.5">
                              {(byDay.get(day) ?? []).map((o, i) => (
                                <DayBadge key={i} o={o} />
                              ))}
                            </div>
                          </>
                        )}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-[11px] text-slate-400">
            <span className="rounded bg-sky-100 px-1 text-sky-800">Jobs</span> = US jobs report ·{" "}
            <span className="rounded bg-cyan-100 px-1 text-cyan-800">Claims</span> = US initial
            jobless claims (every Thursday) ·{" "}
            <span className="rounded bg-violet-100 px-1 text-violet-800">GST</span> = India GST
            collection · <span className="rounded bg-rose-100 px-1 text-rose-800">Fed</span> = FOMC
            rate decision (manually maintained: 2023-2025 + owner-confirmed 2026 dates) ·{" "}
            <span className="rounded bg-indigo-100 px-1 text-indigo-800">ECB</span> = ECB rate
            decision (manually maintained: 2023-2025) ·{" "}
            <span className="rounded bg-fuchsia-100 px-1 text-fuchsia-800">RBI</span> = RBI MPC
            rate decision (manually maintained: 2023-2025) ·{" "}
            <span className="rounded bg-amber-100 px-1 text-amber-800">F&amp;O Exp</span> = monthly
            F&amp;O expiry (current/next contract only — no historical dates retained, so it never
            shows a % move here) ·{" "}
            <span className="rounded bg-yellow-100 px-1 text-yellow-800">MCX Gold</span> /{" "}
            <span className="rounded bg-slate-200 px-1 text-slate-700">MCX Silver</span> = MCX
            expiry (5th of month, approximated against NSE trading days) ·{" "}
            <span className="rounded bg-orange-100 px-1 text-orange-800">COMEX Gold</span> /{" "}
            <span className="rounded bg-stone-200 px-1 text-stone-700">COMEX Silver</span> = COMEX
            expiry (27th of month rule-of-thumb, cruder approximation — no shared holiday calendar
            with NSE).
          </p>
        </div>
      )}
    </Panel>
  );
}
