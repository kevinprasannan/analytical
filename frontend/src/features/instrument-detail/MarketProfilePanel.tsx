import { useState } from "react";
import { useMarketProfile } from "@/api/queries";
import type { MarketProfile, MPEvent, MPEventsBlock } from "@/api/generated/schema";
import { Panel, StatGrid, Badge, Skeleton } from "@/components/primitives";
import { bool, num, price, titleCase } from "@/lib/format";

const isoDate = (d: Date) => d.toISOString().slice(0, 10);
const addDays = (iso: string, n: number) => {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return isoDate(d);
};
const weekday = (iso: string) =>
  new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-GB", { weekday: "short", timeZone: "UTC" });

const STRENGTH_TONE: Record<string, "ok" | "warn" | "muted" | "bad"> = {
  STRONG: "ok",
  MODERATE: "warn",
  WEAK: "muted",
  CONTEXT: "muted",
};
const STATE_TONE: Record<string, "ok" | "warn" | "muted" | "bad"> = {
  CONFIRMED: "ok",
  DEVELOPING: "warn",
  TRIGGERED: "warn",
  INVALIDATED: "bad",
  EXPIRED: "muted",
  NOT_TRIGGERED: "muted",
};
const STRENGTH_ORDER: Record<string, number> = { STRONG: 0, MODERATE: 1, WEAK: 2, CONTEXT: 3 };

/** analytical one-liner for an event — never a directive */
function describe(e: MPEvent): string {
  const m = e.meta ?? {};
  const s = (k: string) => (m[k] == null ? "" : String(m[k]));
  switch (e.id) {
    case "MP-001":
      return `Open ${s("location").replace(/_/g, " ").toLowerCase()}`;
    case "MP-002":
      return m.above_prev_high ? "Open above prior high" : m.below_prev_low ? "Open below prior low" : "Open inside prior range";
    case "MP-003":
      return `Gap ${s("gap_band").toLowerCase()}${m.gap_sign === 1 ? " up" : m.gap_sign === -1 ? " down" : ""}`;
    case "MP-010":
      return `Acceptance above prior VAH — ${e.state.toLowerCase()}`;
    case "MP-011":
      return `Acceptance below prior VAL — ${e.state.toLowerCase()}`;
    case "MP-012":
      return "Probe above prior VAH rejected back into value";
    case "MP-013":
      return "Probe below prior VAL rejected back into value";
    case "MP-015":
      return `Developing value building ${e.direction === "UP" ? "above" : "below"} prior value area`;
    case "MP-016":
      return `Acceptance above prior day high — ${e.state.toLowerCase()}`;
    case "MP-017":
      return `Acceptance below prior day low — ${e.state.toLowerCase()}`;
    case "MP-019":
      return `Acceptance above IB high — ${e.state.toLowerCase()}`;
    case "MP-020":
      return `Acceptance below IB low — ${e.state.toLowerCase()}`;
    case "MP-030":
      return `Value ${s("direction").toLowerCase().replace("_", " ")} · ${s("topology").toLowerCase().replace(/_/g, " ")}`;
    case "MP-040":
      return `POC ${s("migration").toLowerCase()} vs prior session`;
    case "MP-041":
      return `Developing POC drifting ${s("direction").toLowerCase()}`;
    case "MP-051":
      return `IB broken ${s("broken").toLowerCase()}`;
    case "MP-052":
      return `Range extension ${s("sidedness").toLowerCase().replace(/_/g, " ")}`;
    case "MP-053":
      return `Directional after IB — ${s("direction").toLowerCase()}`;
    case "MP-060":
      return `Upside auction: ${s("outcome").toLowerCase().replace(/_/g, " ")}`;
    case "MP-061":
      return `Downside auction: ${s("outcome").toLowerCase().replace(/_/g, " ")}`;
    case "MP-070":
      return `Extremes — high ${s("high").toLowerCase()}, low ${s("low").toLowerCase()}`;
    case "MP-072":
      return `Poor ${m.poor_high ? "high" : ""}${m.poor_high && m.poor_low ? " & " : ""}${m.poor_low ? "low" : ""}`;
    case "MP-075":
      return `${s("n_distributions")} distributions`;
    default:
      return e.id;
  }
}

function EventList({ ev }: { ev: MPEventsBlock }) {
  if (ev.status !== "OK") {
    return (
      <p className="text-xs text-slate-500">
        Auction events: {ev.status.toLowerCase()}
        {ev.reason ? ` — ${ev.reason}` : ""}
      </p>
    );
  }
  const rows = [...ev.events].sort(
    (a, b) =>
      (STRENGTH_ORDER[a.strength] ?? 9) - (STRENGTH_ORDER[b.strength] ?? 9) ||
      a.id.localeCompare(b.id),
  );
  const dt = ev.day_type;
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        {dt && (
          <>
            <Badge tone={dt.provisional ? "warn" : "ok"}>
              {titleCase(dt.day_type)}
              {dt.provisional ? " (provisional)" : ""}
            </Badge>
            <Badge tone="muted">{titleCase(dt.silhouette)}</Badge>
          </>
        )}
        <span className="text-slate-400">
          {rows.length} events · v{ev.version} · analytical only
        </span>
      </div>
      <div className="max-h-72 overflow-y-auto rounded border border-slate-200">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-slate-50 text-slate-500">
            <tr>
              <th className="px-2 py-1 text-left">Event</th>
              <th className="px-2 py-1 text-left">State</th>
              <th className="px-2 py-1 text-left">Read (not a signal)</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows.map((e) => (
              <tr key={e.id + e.state} className={e.strength === "CONTEXT" ? "text-slate-400" : ""}>
                <td className="whitespace-nowrap px-2 py-1">
                  <span className="font-mono">{e.id}</span>{" "}
                  <Badge tone={STRENGTH_TONE[e.strength] ?? "muted"}>{e.strength.toLowerCase()}</Badge>
                </td>
                <td className="px-2 py-1">
                  <Badge tone={STATE_TONE[e.state] ?? "muted"}>
                    {e.state.replace(/_/g, " ").toLowerCase()}
                  </Badge>
                  {e.last_bracket != null && (
                    <span className="ml-1 text-slate-400">@{e.last_bracket}</span>
                  )}
                </td>
                <td className="px-2 py-1">{describe(e)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {ev.tensions.length > 0 && (
        <p className="text-xs text-amber-700">
          {ev.tensions.length} conflicting-evidence note{ev.tensions.length > 1 ? "s" : ""} —{" "}
          {ev.tensions.map((t) => String((t as { label?: string }).label ?? "")).join(", ")}
        </p>
      )}
    </div>
  );
}

export function MarketProfilePanel({
  mp: latest,
  instrumentId,
}: {
  mp: MarketProfile;
  instrumentId: number;
}) {
  // null = viewing the latest/live session (the `latest` prop, already fetched
  // by the parent); a date = browsing a past session (owner: "like this last 3
  // day value or 7 days" — a way to page back through recent sessions' TPO grid)
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const histQ = useMarketProfile(instrumentId, selectedDate ?? undefined);
  const browsing = selectedDate !== null;
  const mp = browsing ? histQ.data : latest;
  const today = isoDate(new Date());

  // TPO and Volume Profile merged into one price-row table (owner: "VOLUME &
  // tpo TWO COLUMN MERGE IT ONE WITH SMALL BAR") — was two tab-switched
  // renderings of the same table; now both render together per price row,
  // joined on `price_low` (both share the session's bin grid, except a
  // borrowed-FUTURE volume profile — §11.4 — which can differ by a bin or two).
  const tpoBins = (mp?.profiles.TPO?.bins ?? []) as Record<string, number | string>[];
  const volBins = (mp?.profiles.VOLUME?.bins ?? []) as Record<string, number | string>[];
  // the traditional hand-drawn TPO chart: each price row lists just the periods
  // that traded there (already chronological — A<B<...<Z<a<b<...), packed left —
  // column position is a print slot, not a fixed period. maxPrints sizes the
  // widest row so every row's columns line up.
  const maxPrints = Math.max(
    0,
    ...tpoBins.map((b) => (typeof b.letters === "string" ? b.letters.length : 0)),
  );

  const tpoByPrice = new Map(tpoBins.map((b) => [Number(b.price_low), b]));
  const volByPrice = new Map(volBins.map((b) => [Number(b.price_low), Number(b.volume)]));
  const priceRows = Array.from(
    new Set([...tpoByPrice.keys(), ...volByPrice.keys()]),
  ).sort((a, b) => b - a);
  const maxVolume = Math.max(0, ...volByPrice.values());

  // Initial Balance band — every bin whose price range overlaps [ib_low, ib_high]
  // (a value-based overlap test, since ib_high/ib_low are the session's raw first-
  // periods extremes, not necessarily bin-aligned). Read against price, not
  // against specific period letters, since the API doesn't expose `ib_periods`.
  const ibHigh = mp?.ib_high ?? null;
  const ibLow = mp?.ib_low ?? null;
  const binSize = mp?.bin_size ?? 0;
  const ibPrices =
    ibHigh != null && ibLow != null
      ? priceRows.filter((p) => p + binSize > ibLow && p <= ibHigh)
      : [];
  const ibTop = ibPrices.length ? Math.max(...ibPrices) : null;
  const ibBottom = ibPrices.length ? Math.min(...ibPrices) : null;

  // the date the nav controls are anchored on — the picked date while browsing,
  // else the latest session (so the input always shows something meaningful)
  const anchor = selectedDate ?? latest.session_date;
  const atLatest = anchor >= latest.session_date;

  return (
    <Panel
      title="Market Profile (session)"
      right={
        <div className="flex flex-wrap items-center gap-2">
          {mp && !mp.is_session_complete && <Badge tone="warn">forming</Badge>}
          <div className="flex items-center gap-1 text-xs">
            <button
              type="button"
              title="previous session"
              onClick={() => setSelectedDate(addDays(anchor, -1))}
              className="rounded border border-slate-300 px-1.5 py-0.5 text-slate-600 hover:bg-slate-100"
            >
              ◀
            </button>
            <input
              type="date"
              value={anchor}
              max={today}
              onChange={(e) => setSelectedDate(e.target.value || null)}
              className="rounded border border-slate-300 px-1 py-0.5 text-slate-700"
            />
            <button
              type="button"
              title="next session"
              disabled={atLatest}
              onClick={() => setSelectedDate(addDays(anchor, 1))}
              className="rounded border border-slate-300 px-1.5 py-0.5 text-slate-600 hover:bg-slate-100 disabled:opacity-30"
            >
              ▶
            </button>
            {browsing && (
              <button
                type="button"
                onClick={() => setSelectedDate(null)}
                className="text-blue-700 underline"
              >
                latest
              </button>
            )}
          </div>
          <Badge tone="muted">
            {(mp?.session_date ?? anchor)} {weekday(mp?.session_date ?? anchor)}
          </Badge>
        </div>
      }
    >
      {browsing && histQ.isLoading && <Skeleton rows={4} />}
      {browsing && !histQ.isLoading && histQ.error && (
        <p className="py-3 text-sm text-slate-500">
          — no session on {selectedDate} ({weekday(selectedDate)}). Weekends and holidays have
          none — try ◀ / ▶ or pick another date.
        </p>
      )}
      {mp && (
        <>
      <div className="grid gap-4 md:grid-cols-2">
        <StatGrid
          rows={[
            ["POC", price(mp.poc)],
            ["VAH / VAL", `${price(mp.vah)} / ${price(mp.val)}`],
            ["IB high / low", `${price(mp.ib_high)} / ${price(mp.ib_low)}`],
            ["Session hi / lo", `${price(mp.session_high)} / ${price(mp.session_low)}`],
            ["Bin size", num(mp.bin_size, 2)],
            ["Shape", mp.profile_shape ? titleCase(mp.profile_shape) : "—"],
            ["Close", price(mp.close)],
            [
              "Close vs POC/VAH/VAL",
              `${mp.close_vs_poc ?? "—"} / ${mp.close_vs_vah ?? "—"} / ${mp.close_vs_val ?? "—"}`,
            ],
            ["In value area", bool(mp.close_in_value_area)],
            ["Session complete", bool(mp.is_session_complete)],
          ]}
        />

        <div>
          {mp.volume_source === "FUTURE" && volByPrice.size > 0 && (
            <div className="mb-2 flex items-center gap-1 text-xs">
              <span
                className="rounded bg-amber-100 px-1.5 py-0.5 text-[11px] text-amber-800"
                title={`${mp.session_date}'s index has no traded volume of its own (it's a calculated value, not something bought/sold) — the Volume bar below is the linked future contract's own Volume Profile for the same session, approximate against the index's own price grid.`}
              >
                Volume from {mp.volume_source_contract_key}
              </span>
            </div>
          )}
          <div className="max-h-72 overflow-auto rounded border border-slate-200">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-slate-50 text-slate-500">
                <tr>
                  <th className="px-2 py-1 text-left">Price</th>
                  <th className="w-8 px-0 py-1 text-center font-normal">IB</th>
                  {Array.from({ length: maxPrints }, (_, idx) => (
                    <th key={idx} className="w-5 px-0 py-1 text-center font-normal text-slate-300">
                      ·
                    </th>
                  ))}
                  <th className="px-2 py-1 text-right">TPO</th>
                  {volByPrice.size > 0 && (
                    <th className="px-2 py-1 text-left">Volume</th>
                  )}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 font-mono tabular-nums">
                {priceRows.map((priceLow) => {
                  const tb = tpoByPrice.get(priceLow);
                  const isPoc = mp.poc != null && priceLow === mp.poc;
                  const inIb = ibPrices.includes(priceLow);
                  const letters = typeof tb?.letters === "string" ? tb.letters : "";
                  const vol = volByPrice.get(priceLow);
                  const volPct = vol != null && maxVolume > 0 ? (vol / maxVolume) * 100 : 0;
                  const ibMark =
                    priceLow === ibTop && priceLow === ibBottom
                      ? "IB"
                      : priceLow === ibTop
                        ? "hi"
                        : priceLow === ibBottom
                          ? "lo"
                          : inIb
                            ? "│"
                            : "";
                  return (
                    <tr key={priceLow} className={isPoc ? "bg-amber-50" : ""}>
                      <td className={`px-2 py-0.5 ${isPoc ? "font-semibold text-amber-800" : ""}`}>
                        {price(priceLow)}
                        {isPoc && <span className="ml-1 text-[10px] text-amber-600">POC</span>}
                      </td>
                      <td
                        className={`w-8 px-0 py-0.5 text-center text-[10px] ${
                          inIb ? "bg-sky-50 font-semibold text-sky-700" : ""
                        }`}
                      >
                        {ibMark}
                      </td>
                      {Array.from({ length: maxPrints }, (_, idx) => (
                        <td key={idx} className="w-5 px-0 py-0.5 text-center text-slate-700">
                          {letters[idx] ?? ""}
                        </td>
                      ))}
                      <td className="px-2 py-0.5 text-right">
                        {tb ? num(tb.tpo_count, 0) : ""}
                      </td>
                      {volByPrice.size > 0 && (
                        <td className="px-2 py-0.5">
                          {vol != null && (
                            <div className="flex items-center gap-1.5">
                              <div className="h-2.5 w-16 overflow-hidden rounded-sm bg-slate-100">
                                <div
                                  className="h-full rounded-sm bg-indigo-300"
                                  style={{ width: `${Math.max(volPct, vol > 0 ? 3 : 0)}%` }}
                                />
                              </div>
                              <span className="text-[10px] text-slate-500">{num(vol, 0)}</span>
                            </div>
                          )}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="mt-1 text-[11px] text-slate-400">
            Columns left to right: <b>Price</b>, <b>IB</b>, then each row's own periods packed
            left (the traditional hand-drawn TPO chart — a price row that traded during periods
            B, E and F shows <span className="font-mono">B E F</span> in its first three print
            columns, in order; a column's position is just a print slot, not a fixed period, so
            the same column can hold different letters on different rows), then{" "}
            <b>TPO</b> count, then a small <b>Volume</b> bar (scaled to the session's busiest
            price, owner: "VOLUME &amp; tpo TWO COLUMN MERGE IT ONE WITH SMALL BAR"). Scan the
            shape of the filled columns down the price axis and it traces the session's profile
            (bell / P / b). <b>POC</b> = the busiest TPO price. The <b>IB</b> column marks the{" "}
            <b>Initial Balance</b> range — the range set by the opening periods, a common gauge
            for whether the rest of the session stays inside it or extends beyond: <b>hi</b> /{" "}
            <b>lo</b> at its top/bottom price,{" "}
            <span className="rounded bg-sky-50 px-1 text-sky-700 border-l-2 border-sky-400">
              │
            </span>{" "}
            through the range between.
          </p>
        </div>
      </div>

      {mp.events && (
        <div className="mt-4 border-t border-slate-100 pt-3">
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Auction events (docs/14) — descriptive, not trade signals
          </h4>
          <EventList ev={mp.events} />
        </div>
      )}
        </>
      )}
    </Panel>
  );
}
