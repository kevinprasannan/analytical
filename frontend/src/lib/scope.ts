/** Analysis scope helpers (docs/07 §3 — every analysis item carries scope + one of tf/date/ts). */
import type { AnalysisItem } from "@/api/generated/schema";

export function scopeRef(a: Pick<AnalysisItem, "scope" | "timeframe" | "session_date" | "snapshot_ts">): string {
  if (a.scope === "PER_TIMEFRAME") return `PER_TIMEFRAME:${a.timeframe ?? "?"}`;
  if (a.scope === "SESSION") return `SESSION:${a.session_date ?? "?"}`;
  return `SNAPSHOT:${a.snapshot_ts ?? "?"}`;
}

export const ANALYSIS_ORDER = [
  "rsi",
  "bollinger",
  "ema7",
  "golden_cross",
  "volume",
  "open_interest",
  "market_profile",
];
