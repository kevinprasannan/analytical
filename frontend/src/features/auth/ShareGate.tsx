import type { FormEvent, ReactNode } from "react";
import { useState } from "react";
import { SHARE_MODE, isUnlocked, tryUnlock } from "@/lib/share";

/** Wraps the app. In share mode, blocks everything behind a passcode until it
 *  matches; otherwise renders children straight through. */
export function ShareGate({ children }: { children: ReactNode }) {
  const [ok, setOk] = useState(() => isUnlocked());
  const [pw, setPw] = useState("");
  const [err, setErr] = useState(false);

  if (!SHARE_MODE || ok) return <>{children}</>;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (tryUnlock(pw)) {
      setOk(true);
    } else {
      setErr(true);
      setPw("");
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
      <form
        onSubmit={submit}
        className="w-72 space-y-3 rounded-lg border border-slate-200 bg-white p-6 shadow-sm"
      >
        <div className="text-sm font-bold text-slate-900">Analytical</div>
        <p className="text-xs text-slate-500">Enter the passcode to view the dashboard.</p>
        <input
          type="password"
          inputMode="numeric"
          autoFocus
          value={pw}
          onChange={(e) => {
            setPw(e.target.value);
            setErr(false);
          }}
          placeholder="Passcode"
          className="w-full rounded border border-slate-300 px-2 py-1.5 text-sm outline-none focus:border-slate-500"
        />
        {err && <p className="text-xs text-rose-600">Incorrect passcode.</p>}
        <button
          type="submit"
          className="w-full rounded bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700"
        >
          Unlock
        </button>
      </form>
    </div>
  );
}
