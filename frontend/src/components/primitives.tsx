/** Small hand-built UI primitives (docs/08 §1 — no component library). */
import { useState } from "react";
import type { ReactNode } from "react";
import { ApiError } from "@/api/client";
import { labelStyle } from "@/lib/scoreBands";
import type { SignalLabel } from "@/api/generated/schema";

export function Badge({
  children,
  tone = "default",
  title,
}: {
  children: ReactNode;
  tone?: "default" | "ok" | "warn" | "bad" | "muted";
  title?: string;
}) {
  const cls = {
    default: "bg-slate-100 text-slate-700 ring-slate-300",
    ok: "bg-emerald-50 text-emerald-700 ring-emerald-300",
    warn: "bg-amber-50 text-amber-700 ring-amber-300",
    bad: "bg-rose-50 text-rose-700 ring-rose-300",
    muted: "bg-slate-50 text-slate-500 ring-slate-200",
  }[tone];
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-medium ring-1 ${cls}`}
    >
      {children}
    </span>
  );
}

export function LabelChip({ label, clamped }: { label: SignalLabel; clamped?: boolean }) {
  const s = labelStyle(label);
  return (
    <span className={`inline-flex items-center gap-1.5 rounded px-2 py-0.5 text-sm font-semibold ${s.className}`}>
      <span aria-hidden className="font-mono text-[10px] leading-none">
        {s.icon}
      </span>
      {s.text}
      {clamped && (
        <span title="clamped toward neutral (low confidence)" className="ml-1 text-[10px] font-normal opacity-70">
          clamped
        </span>
      )}
    </span>
  );
}

type Tone = "default" | "ok" | "warn" | "bad" | "muted";

export function StatusPill({ status }: { status: string }) {
  const tone: Tone =
    status === "OK" || status === "SUCCEEDED"
      ? "ok"
      : status === "NOT_APPLICABLE" || status === "SKIPPED"
        ? "muted"
        : status === "INSUFFICIENT_DATA" || status === "PARTIAL" || status === "DEGRADED"
          ? "warn"
          : "bad";
  return <Badge tone={tone}>{status.replace(/_/g, " ").toLowerCase()}</Badge>;
}

export function Panel({
  title,
  right,
  children,
  muted,
  collapsible,
  defaultCollapsed,
  accent,
}: {
  title: ReactNode;
  right?: ReactNode;
  children: ReactNode;
  muted?: boolean;
  collapsible?: boolean;
  defaultCollapsed?: boolean;
  accent?: "bull" | "bear";
}) {
  const [collapsed, setCollapsed] = useState(!!defaultCollapsed);
  const open = !collapsible || !collapsed;
  const accentClass =
    accent === "bull"
      ? "border-emerald-400 ring-1 ring-emerald-300"
      : accent === "bear"
        ? "border-rose-400 ring-1 ring-rose-300"
        : "border-slate-200";
  return (
    <section className={`rounded-lg border bg-white ${accentClass} ${muted ? "opacity-70" : ""}`}>
      <header className="flex items-center justify-between border-b border-slate-100 px-3 py-2">
        <h3
          className={`flex items-center gap-1.5 text-sm font-semibold text-slate-800 ${
            collapsible ? "cursor-pointer select-none" : ""
          }`}
          onClick={collapsible ? () => setCollapsed((c) => !c) : undefined}
          aria-expanded={collapsible ? open : undefined}
        >
          {collapsible && (
            <span
              className={`inline-block text-xs text-slate-400 transition-transform ${open ? "rotate-90" : ""}`}
              aria-hidden
            >
              ▶
            </span>
          )}
          {title}
        </h3>
        <div className="flex items-center gap-2">{right}</div>
      </header>
      {open && <div className="p-3">{children}</div>}
    </section>
  );
}

export function StatGrid({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm">
      {rows.map(([label, value]) => (
        <div key={label} className="contents">
          <dt className="text-slate-500">{label}</dt>
          <dd className="font-mono text-slate-900 tabular-nums">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Skeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div className="space-y-2" aria-busy>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-6 animate-pulse rounded bg-slate-100" />
      ))}
    </div>
  );
}

export function Spinner({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-4 text-sm text-slate-500" role="status">
      <span className="h-3 w-3 animate-spin rounded-full border-2 border-slate-300 border-t-slate-600" />
      {label}
    </div>
  );
}

export function Empty({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-8 text-center text-sm text-slate-500">
      <p>{children}</p>
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}

export function ProblemError({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const p =
    error instanceof ApiError
      ? error.problem
      : { title: "Something went wrong", status: 0, detail: String(error), type: "about:blank" };
  return (
    <div role="alert" className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm">
      <p className="font-semibold text-rose-800">
        {p.title}
        {p.status ? ` (${p.status})` : ""}
      </p>
      {p.detail && <p className="mt-1 text-rose-700">{p.detail}</p>}
      {p.errors && (
        <ul className="mt-2 list-disc pl-5 text-rose-700">
          {Object.entries(p.errors).map(([field, msg]) => (
            <li key={field}>
              <span className="font-mono">{field}</span>: {msg}
            </li>
          ))}
        </ul>
      )}
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-3 rounded border border-rose-300 bg-white px-2 py-1 text-rose-700 hover:bg-rose-100"
        >
          Retry
        </button>
      )}
    </div>
  );
}

export interface Col<T> {
  key: string;
  header: ReactNode;
  cell: (row: T) => ReactNode;
  sortKey?: string;
  align?: "left" | "right";
}

export function DataTable<T>({
  cols,
  rows,
  rowKey,
  onSort,
  sort,
  rowClass,
}: {
  cols: Col<T>[];
  rows: T[];
  rowKey: (r: T) => string | number;
  onSort?: (key: string) => void;
  sort?: string;
  rowClass?: (r: T) => string;
}) {
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200">
      <table className="w-full border-collapse text-sm">
        <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
          <tr>
            {cols.map((c) => {
              const active = sort === c.sortKey || sort === `-${c.sortKey}`;
              const dir = sort === `-${c.sortKey}` ? " ▼" : sort === c.sortKey ? " ▲" : "";
              return (
                <th
                  key={c.key}
                  className={`px-3 py-2 font-semibold ${c.align === "right" ? "text-right" : ""} ${
                    c.sortKey && onSort ? "cursor-pointer select-none hover:text-slate-800" : ""
                  }`}
                  onClick={c.sortKey && onSort ? () => onSort(c.sortKey!) : undefined}
                >
                  {c.header}
                  {active ? dir : ""}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((r) => (
            <tr key={rowKey(r)} className={`hover:bg-slate-50 ${rowClass ? rowClass(r) : ""}`}>
              {cols.map((c) => (
                <td
                  key={c.key}
                  className={`px-3 py-2 ${c.align === "right" ? "text-right font-mono tabular-nums" : ""}`}
                >
                  {c.cell(r)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
