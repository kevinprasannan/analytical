import { Outlet } from "react-router-dom";
import { Header } from "./Header";

export function Shell() {
  return (
    <div className="min-h-full">
      <Header />
      <main className="mx-auto max-w-[1400px] px-4 py-5">
        <Outlet />
      </main>
      <footer className="mx-auto max-w-[1400px] px-4 pb-8 pt-4 text-xs text-slate-400">
        Analytical decision-support. Numbers &amp; tables only — no charts, no BUY/SELL/execution
        output (docs/01 §1, docs/08 §2).
      </footer>
    </div>
  );
}
