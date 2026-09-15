/** Global user-facing timeframe selector state — URL param + localStorage. */
import { useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import type { Timeframe } from "@/api/generated/schema";

export const TIMEFRAMES: Timeframe[] = ["M5", "M15", "H1", "D1"];
const LS_KEY = "analytical.timeframe";
const DEFAULT: Timeframe = "M15";

export function isTimeframe(v: string | null): v is Timeframe {
  return v !== null && (TIMEFRAMES as string[]).includes(v);
}

export function useTimeframe(): [Timeframe, (tf: Timeframe) => void] {
  const [params, setParams] = useSearchParams();
  const fromUrl = params.get("tf");
  const stored = typeof localStorage !== "undefined" ? localStorage.getItem(LS_KEY) : null;
  const tf: Timeframe = isTimeframe(fromUrl) ? fromUrl : isTimeframe(stored) ? stored : DEFAULT;

  const set = useCallback(
    (next: Timeframe) => {
      try {
        localStorage.setItem(LS_KEY, next);
      } catch {
        /* private mode */
      }
      const p = new URLSearchParams(params);
      p.set("tf", next);
      setParams(p, { replace: true });
    },
    [params, setParams],
  );

  return [tf, set];
}
