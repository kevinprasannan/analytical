/** Share mode — a passcode gate over the whole app.
 *
 *  **Default: on for everyone, on every URL.** The gate (`ShareGate`) wraps the
 *  whole router, so any path shows the passcode screen first; once unlocked the
 *  full app is available. Opt out entirely with `VITE_SHARE_MODE=0 npm run dev`.
 *
 *  The passcode is never in the bundle — only its SHA-256. A client-side gate is
 *  inherently weak (anyone can read the bundle); this just keeps casual eyes out
 *  and avoids shipping the number as plain text. */

import { sha256hex } from "./sha256";

export const SHARE_MODE = import.meta.env.VITE_SHARE_MODE !== "0";

// sha256("<passcode>")
const PASS_HASH = "462820e8a92787f67f40b0d5777764b6413ff8c2b0b8e1c436d3f7ad38e584eb";
const KEY = "analytical.share.unlocked";

export function isUnlocked(): boolean {
  if (!SHARE_MODE) return true;
  try {
    return sessionStorage.getItem(KEY) === PASS_HASH;
  } catch {
    return false;
  }
}

export function tryUnlock(input: string): boolean {
  const ok = sha256hex(input.trim()) === PASS_HASH;
  if (ok) {
    try {
      sessionStorage.setItem(KEY, PASS_HASH);
    } catch {
      /* private-mode storage disabled — stay unlocked for this view only */
    }
  }
  return ok;
}

export function lock(): void {
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
}
