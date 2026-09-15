/** Key levels from the last two sessions' profiles (docs/05 §10.12).
 *
 * POC / VAH / VAL / IB / session high-low from the previous two completed
 * sessions, price-sorted, each tagged with signed distance from the latest
 * price and a proximity tier (AT / NEAR / APPROACHING / FAR — bands default per
 * instrument). An acceptance / rejection read on the levels price is testing.
 * Descriptive — no bias, no BUY/SELL. */
import { useKeyLevels } from "@/api/queries";
import { Panel, ProblemError, Skeleton, StatGrid } from "@/components/primitives";
import type { KeyLevel } from "@/api/generated/schema";
import { DASH, num, price } from "@/lib/format";

const tierCls: Record<string, string> = {
  AT: "bg-rose-100 text-rose-800 font-medium",
  NEAR: "bg-amber-100 text-amber-800",
  APPROACHING: "bg-yellow-50 text-yellow-700",
  FAR: "text-slate-400",
};

const signed = (v: number, dp = 1) => `${v >= 0 ? "+" : ""}${num(v, dp)}`;
const acc = (a: string | null) =>
  a ? a.replace(/_/g, " ").toLowerCase() : "";

function NearestLine({ dir, lvl }: { dir: "up" | "down"; lvl: KeyLevel | null }) {
  if (!lvl) return <span className="text-slate-400">{DASH}</span>;
  return (
    <span className="whitespace-nowrap">
      {dir === "up" ? "↑ " : "↓ "}
      <b className="font-mono">{price(lvl.price)}</b>{" "}
      <span className="text-slate-500">
        {lvl.session} {lvl.kind.replace(/_/g, " ").toLowerCase()}
      </span>{" "}
      <span className={`rounded px-1 ${tierCls[lvl.tier] ?? ""}`}>
        {signed(lvl.distance, 0)} · {lvl.tier.toLowerCase()}
      </span>
    </span>
  );
}

export function KeyLevelsPanel({ instrumentId }: { instrumentId: number }) {
  const q = useKeyLevels(instrumentId);
  const d = q.data;

  return (
    <Panel
      title="Key levels — last 2 sessions"
      right={
        d && (
          <span className="font-mono text-xs text-slate-500">
            last {price(d.last_price)} · bands {d.bands.at}/{d.bands.near}/{d.bands.approaching} pt
          </span>
        )
      }
    >
      {q.isLoading && !d && <Skeleton rows={8} />}
      {q.error && (
        <p className="text-sm text-slate-500">
          {DASH} no completed market-profile session yet for this instrument.
        </p>
      )}

      {d && (
        <div className="space-y-4">
          <p className="max-w-3xl text-sm text-slate-500">
            The last two completed sessions' profile levels, sorted by price. Each shows the
            signed distance from the latest print and a <b>proximity tier</b> —{" "}
            <span className={`rounded px-1 ${tierCls.AT}`}>at</span>{" "}
            <span className={`rounded px-1 ${tierCls.NEAR}`}>near</span>{" "}
            <span className={`rounded px-1 ${tierCls.APPROACHING}`}>approaching</span>. Acceptance
            is read from the recent M5 bars. Descriptive — not a signal.
          </p>

          <StatGrid
            rows={[
              ["Next level up", <NearestLine key="u" dir="up" lvl={d.nearest_above} />],
              ["Next level down", <NearestLine key="d" dir="down" lvl={d.nearest_below} />],
              ...d.sessions.map(
                (s) =>
                  [
                    `${s.label} (${s.date})`,
                    `${s.shape ?? "—"} · ${s.day_type ?? "—"} · POC ${price(s.poc)} · VA ${price(
                      s.val,
                    )}–${price(s.vah)} · close ${s.close_vs_value?.toLowerCase() ?? "—"} value`,
                  ] as [string, string],
              ),
            ]}
          />

          <div className="overflow-x-auto">
            <table className="w-full text-xs tabular-nums">
              <thead className="text-slate-400">
                <tr className="border-b border-slate-200">
                  <th className="px-2 py-1 text-left">level</th>
                  <th className="px-2 py-1 text-left">from</th>
                  <th className="px-2 py-1 text-right">price</th>
                  <th className="px-2 py-1 text-right">dist</th>
                  <th className="px-2 py-1 text-left">tier</th>
                  <th className="px-2 py-1 text-left">acceptance</th>
                </tr>
              </thead>
              <tbody>
                {d.levels.map((l, i) => (
                  <tr key={i} className="border-b border-slate-100">
                    <td className="px-2 py-1 font-medium">{l.kind.replace(/_/g, " ")}</td>
                    <td className="px-2 py-1 text-slate-500">
                      {l.session} · {l.session_date.slice(5)}
                    </td>
                    <td className="px-2 py-1 text-right font-mono">{price(l.price)}</td>
                    <td
                      className={`px-2 py-1 text-right font-mono ${
                        l.side === "ABOVE"
                          ? "text-emerald-600"
                          : l.side === "BELOW"
                            ? "text-rose-600"
                            : "text-slate-500"
                      }`}
                    >
                      {signed(l.distance, 1)}
                    </td>
                    <td className="px-2 py-1">
                      <span className={`rounded px-1 py-0.5 ${tierCls[l.tier] ?? ""}`}>
                        {l.tier.toLowerCase()}
                      </span>
                    </td>
                    <td className="px-2 py-1 text-slate-500">{acc(l.acceptance)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p className="text-[11px] text-slate-400">module {d.key_levels_version}</p>
        </div>
      )}
    </Panel>
  );
}
