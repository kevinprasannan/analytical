/** Market board (docs/08 §4.1) — the data-first landing view.
 *
 * One row per tracked INDEX / FUTURE: latest price, today's move, range, OI,
 * history coverage and the 5m / H1 / D1 labels. A health strip on top says at a
 * glance whether the data is fresh and complete. Options live in the option
 * chain, not here. */
import { Link } from "react-router-dom";
import { useBoard, useCalendarStatus, useConfig, useHealthReady } from "@/api/queries";
import { istSessionWindow } from "@/lib/marketClock";
import type { BoardRow, SignalLabel } from "@/api/generated/schema";
import { Badge, DataTable, Empty, LabelChip, ProblemError, Skeleton } from "@/components/primitives";
import { LastUpdated } from "@/components/LastUpdated";
import { DASH, num, relTime } from "@/lib/format";

const fmtPrice = (v: number | null) =>
  v == null ? DASH : v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const fmtOi = (v: number | null) => (v == null ? DASH : v.toLocaleString("en-IN"));

function Move({ pct }: { pct: number | null }) {
  if (pct == null) return <span className="text-slate-400">{DASH}</span>;
  const up = pct > 0;
  const flat = Math.abs(pct) < 0.005;
  const cls = flat ? "text-slate-500" : up ? "text-emerald-600" : "text-rose-600";
  const arrow = flat ? "" : up ? "▲" : "▼";
  return (
    <span className={`font-mono tabular-nums ${cls}`}>
      {arrow} {up && !flat ? "+" : ""}
      {num(pct, 2)}%
    </span>
  );
}

function Dot({ tone, title }: { tone: "ok" | "warn" | "bad" | "off"; title: string }) {
  const c = { ok: "bg-emerald-500", warn: "bg-amber-500", bad: "bg-rose-500", off: "bg-slate-300" }[
    tone
  ];
  return <span title={title} className={`inline-block h-2 w-2 shrink-0 rounded-full ${c}`} />;
}

export function Dashboard() {
  const cfg = useConfig();
  // heartbeat: 1 min during session hours, 5 min off-hours (enough to resume at
  // the next open / react to a holiday) — it drives `live` below.
  const cal = useCalendarStatus(istSessionWindow() ? 60_000 : 300_000);
  const marketOpen = cal.data?.is_open === true;
  // poll fast only while the session is actually live (both the server calendar
  // and the IST clock agree); after ~15:40 the board is static — one fetch is enough.
  const live = marketOpen && istSessionWindow();
  const pollSecs = Number(cfg.data?.effective?.["cycle_interval_seconds"] ?? 180);
  const health = useHealthReady(live ? 30_000 : false);
  const q = useBoard(live ? pollSecs * 1000 : false);
  const rows = q.data?.rows ?? [];
  const now = Date.now();

  const h = health.data;
  const idle = h?.worker_running === false;
  const streamOn = h?.stream_enabled === true;

  // stale = last bar older than ~3 cycles; only meaningful while the market is open
  const staleCut = Math.max(pollSecs * 3, 600);
  const isStale = (r: BoardRow) =>
    marketOpen && r.staleness_seconds != null && r.staleness_seconds > staleCut;
  const nStale = rows.filter(isStale).length;
  const nGap = rows.filter((r) => r.history_ok === false).length;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-baseline gap-3">
          <h1 className="text-lg font-bold">Market</h1>
          {h?.last_successful_cycle_age_seconds != null && (
            <span className="text-xs text-slate-500">
              cycle {Math.round(h.last_successful_cycle_age_seconds)}s old · #
              {h.last_cycle_seq ?? "?"}
            </span>
          )}
          <LastUpdated q={q} />
        </div>
        <div className="flex items-center gap-2 text-xs">
          {streamOn && <Badge tone="ok">streaming</Badge>}
          <Badge tone={idle ? "warn" : "ok"}>{idle ? "worker idle" : "worker running"}</Badge>
          <Link to="/instruments" className="text-slate-500 hover:text-slate-900">
            instruments →
          </Link>
        </div>
      </div>

      {rows.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs">
          <span className="font-semibold text-slate-700">{rows.length} instruments</span>
          <span className="flex items-center gap-1">
            <Dot tone={cal.data ? (marketOpen ? "ok" : "off") : "off"} title="NSE session" />
            market {marketOpen ? "open" : "closed"}
          </span>
          <span className="flex items-center gap-1">
            <Dot tone={nStale ? "warn" : "ok"} title={`stale > ${staleCut}s`} />
            {nStale ? `${nStale} stale` : "all fresh"}
          </span>
          <span className="flex items-center gap-1">
            <Dot tone={nGap ? "warn" : "ok"} title="D1 history not through the last trading day" />
            {nGap ? `${nGap} behind on D1` : "D1 current"}
          </span>
        </div>
      )}

      {h?.provider_auth && h.provider_auth !== "OK" && (
        <div className="rounded border border-rose-300 bg-rose-50 px-3 py-2 text-sm text-rose-800">
          Provider auth is <b>{h.provider_auth}</b> — market data will stop updating until the
          Upstox token is refreshed (<code>python -m app.providers.upstox.cli login</code>).
        </div>
      )}
      {idle && (
        <div className="rounded border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-800">
          Worker not running — prices are static (last cycle #{h?.last_cycle_seq ?? "?"}).
        </div>
      )}

      {q.isLoading && <Skeleton rows={6} />}
      {q.isError && <ProblemError error={q.error} onRetry={() => q.refetch()} />}
      {q.data && rows.length === 0 && (
        <Empty
          action={
            <Link className="text-blue-700 underline" to="/instruments">
              Open Instrument Manager
            </Link>
          }
        >
          No tracked INDEX or FUTURE instruments yet.
        </Empty>
      )}

      {rows.length > 0 && (
        <DataTable<BoardRow>
          cols={[
            {
              key: "inst",
              header: "Instrument",
              cell: (r) => (
                <Link
                  className="font-medium text-slate-900 hover:text-blue-700 hover:underline"
                  to={`/instruments/${r.instrument_id}`}
                >
                  {r.contract_key}
                </Link>
              ),
            },
            {
              key: "last",
              header: "Last",
              align: "right",
              cell: (r) => <span className="font-mono tabular-nums">{fmtPrice(r.last_price)}</span>,
            },
            { key: "chg", header: "Chg", align: "right", cell: (r) => <Move pct={r.day_change_pct} /> },
            {
              key: "rng",
              header: "Range",
              align: "right",
              cell: (r) => (
                <span className="text-slate-500">{r.day_range_pct == null ? DASH : `${num(r.day_range_pct, 2)}%`}</span>
              ),
            },
            {
              key: "oi",
              header: "OI",
              align: "right",
              cell: (r) => <span className="text-slate-500">{fmtOi(r.oi)}</span>,
            },
            {
              key: "hist",
              header: "History",
              cell: (r) => {
                if (r.d1_through == null) return <span className="text-slate-300">{DASH}</span>;
                const tone = r.history_ok ? "ok" : "warn";
                return (
                  <span
                    className="flex items-center gap-1.5 text-xs text-slate-500"
                    title={`D1 ${r.d1_from} → ${r.d1_through} (${r.d1_bars?.toLocaleString("en-IN")} bars)${
                      r.m1_through ? ` · M1 ${r.m1_from} → ${r.m1_through}` : " · no M1"
                    }`}
                  >
                    <Dot tone={tone} title={r.history_ok ? "D1 current" : "D1 behind"} />
                    <span className="font-mono">→{r.d1_through}</span>
                  </span>
                );
              },
            },
            {
              key: "m5",
              header: "5m",
              cell: (r) =>
                r.label_m5 ? <LabelChip label={r.label_m5 as SignalLabel} /> : <span className="text-slate-300">{DASH}</span>,
            },
            {
              key: "h1",
              header: "H1",
              cell: (r) =>
                r.label_h1 ? <LabelChip label={r.label_h1 as SignalLabel} /> : <span className="text-slate-300">{DASH}</span>,
            },
            {
              key: "d1",
              header: "D1",
              cell: (r) =>
                r.label_d1 ? <LabelChip label={r.label_d1 as SignalLabel} /> : <span className="text-slate-300">{DASH}</span>,
            },
            {
              key: "upd",
              header: "Updated",
              cell: (r) => (
                <span
                  className={`text-xs ${isStale(r) ? "text-amber-600" : "text-slate-400"}`}
                  title={r.last_ts ?? undefined}
                >
                  {relTime(r.last_ts, now)}
                </span>
              ),
            },
            {
              key: "links",
              header: "",
              cell: (r) => (
                <span className="whitespace-nowrap text-xs text-slate-400">
                  {r.instrument_type === "INDEX" && (
                    <>
                      <Link
                        className="hover:text-blue-700 hover:underline"
                        to={`/instruments/${r.instrument_id}/option-chain`}
                      >
                        chain
                      </Link>
                      {" · "}
                    </>
                  )}
                  <Link
                    className="hover:text-blue-700 hover:underline"
                    to={`/instruments/${r.instrument_id}/series`}
                  >
                    series
                  </Link>
                </span>
              ),
            },
          ]}
          rows={rows}
          rowKey={(r) => r.instrument_id}
        />
      )}

      <p className="text-xs text-slate-400">
        Last price = newest 1‑min bar. Change vs the previous daily close; range = today's
        high−low. History = span of stored D1 bars (hover for M1). Labels are analytical only —
        not trade signals.
      </p>
    </div>
  );
}
