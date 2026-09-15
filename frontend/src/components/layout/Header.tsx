import { Link, NavLink } from "react-router-dom";
import { useCalendarStatus, useHealthReady, useMetaVersions } from "@/api/queries";
import { useTimeframe, TIMEFRAMES } from "@/lib/timeframe";
import { Badge } from "@/components/primitives";
import { relTime } from "@/lib/format";
import { istSessionWindow } from "@/lib/marketClock";
import { SHARE_MODE, lock } from "@/lib/share";

const NAV = [
  { to: "/dashboard", label: "Dashboard" },
  { to: "/instruments", label: "Instruments" },
  { to: "/runs", label: "Runs" },
  { to: "/config", label: "Config" },
  { to: "/calendar", label: "Calendar" },
  { to: "/astro", label: "Astro" },
];

export function Header() {
  const [tf, setTf] = useTimeframe();
  // stop polling after the bell — status is static off-hours, one fetch is enough
  const inSession = istSessionWindow();
  const health = useHealthReady(inSession ? 30_000 : false);
  const cal = useCalendarStatus(inSession ? 60_000 : 300_000);
  const meta = useMetaVersions();

  const h = health.data;
  const seededSoon =
    h?.calendar_seeded_until &&
    (new Date(h.calendar_seeded_until).getTime() - Date.now()) / 86_400_000 < 30;

  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-x-6 gap-y-2 px-4 py-2">
        <Link to="/dashboard" className="text-sm font-bold tracking-tight text-slate-900">
          Analytical
        </Link>
        <nav className="flex gap-1 text-sm">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              className={({ isActive }) =>
                `rounded px-2 py-1 ${isActive ? "bg-slate-100 font-semibold text-slate-900" : "text-slate-600 hover:text-slate-900"}`
              }
            >
              {n.label}
            </NavLink>
          ))}
        </nav>

        <div className="ml-auto flex flex-wrap items-center gap-2 text-xs">
          <label className="flex items-center gap-1 text-slate-500">
            TF
            <select
              value={tf}
              onChange={(e) => setTf(e.target.value as (typeof TIMEFRAMES)[number])}
              className="rounded border border-slate-300 px-1 py-0.5 text-slate-800"
            >
              {TIMEFRAMES.map((t) => (
                <option key={t}>{t}</option>
              ))}
            </select>
          </label>

          {cal.data && (
            <Badge tone={cal.data.is_open ? "ok" : "muted"}>
              {cal.data.is_open ? "market open" : "market closed"}
            </Badge>
          )}
          {h && (
            <Badge tone={h.worker_running ? "ok" : "warn"} title="single-flight advisory lock probe">
              {h.worker_running ? "worker running" : "worker idle"}
            </Badge>
          )}
          {h?.last_successful_cycle_age_seconds != null && (
            <span className="text-slate-500">
              last ok {Math.round(h.last_successful_cycle_age_seconds)}s ago
            </span>
          )}
          {seededSoon && (
            <Link to="/calendar">
              <Badge tone="warn">calendar seeded &lt; 30d</Badge>
            </Link>
          )}
          {meta.data?.stale_results && (
            <Link to="/runs">
              <Badge tone="warn">stale results</Badge>
            </Link>
          )}
          {SHARE_MODE && (
            <button
              type="button"
              onClick={() => {
                lock();
                window.location.reload();
              }}
              className="rounded border border-slate-300 px-1.5 py-0.5 text-slate-500 hover:bg-slate-50"
            >
              lock
            </button>
          )}
          {meta.data && (
            <span className="font-mono text-slate-400">
              algo {meta.data.algo_version} · scoring {meta.data.scoring_version}
            </span>
          )}
          {h?.provider_auth && h.provider_auth !== "OK" && (
            <Badge tone="bad">provider {h.provider_auth}</Badge>
          )}
          {health.dataUpdatedAt > 0 && (
            <span className="text-slate-400">health {relTime(new Date(health.dataUpdatedAt).toISOString())}</span>
          )}
        </div>
      </div>
    </header>
  );
}
