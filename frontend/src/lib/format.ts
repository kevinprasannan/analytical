/** Number / time formatting (docs/08 §5). Nulls render as an em dash. */

const EN_IN = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 20 });

export const DASH = "—";

export function num(v: number | string | null | undefined, dp: number): string {
  if (v === null || v === undefined || v === "") return DASH;
  const n = typeof v === "string" ? Number(v) : v;
  if (!Number.isFinite(n)) return DASH;
  return new Intl.NumberFormat("en-IN", {
    minimumFractionDigits: dp,
    maximumFractionDigits: dp,
  }).format(n);
}

export const price = (v: number | string | null | undefined) => num(v, 2);
export const rsi = (v: number | string | null | undefined) => num(v, 1);
export const ratio = (v: number | string | null | undefined) => num(v, 2);
export const score = (v: number | string | null | undefined) => num(v, 1);
export const pct = (v: number | string | null | undefined, dp = 2) =>
  v === null || v === undefined ? DASH : `${num(Number(v) * 100, dp)}%`;

export function int(v: number | null | undefined): string {
  if (v === null || v === undefined) return DASH;
  return EN_IN.format(v);
}

export function bool(v: boolean | null | undefined): string {
  return v === null || v === undefined ? DASH : v ? "yes" : "no";
}

export function relTime(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return DASH;
  const secs = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.round(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.round(secs / 3600)}h ago`;
  return `${Math.round(secs / 86400)}d ago`;
}

export function ageSeconds(iso: string | null | undefined, now = Date.now()): number | null {
  if (!iso) return null;
  return Math.round((now - new Date(iso).getTime()) / 1000);
}

export function dt(iso: string | null | undefined): string {
  if (!iso) return DASH;
  return new Date(iso).toLocaleString("en-IN", { hour12: false });
}

export function titleCase(s: string): string {
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
