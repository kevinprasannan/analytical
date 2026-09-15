/** Instrument Manager (docs/08 §4.5) — browse, track/untrack, add, delete. */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  useCreateInstrument,
  useDeleteInstrument,
  useInstrumentCatalog,
  useInstruments,
  usePatchInstrument,
} from "@/api/queries";
import type { CatalogItem, InstrumentCreate, InstrumentSummary } from "@/api/generated/schema";
import { ApiError } from "@/api/client";
import { Badge, DataTable, Empty, ProblemError, Skeleton } from "@/components/primitives";
import { LastUpdated } from "@/components/LastUpdated";
import { price } from "@/lib/format";

const TYPES = ["", "INDEX", "FUTURE", "OPTION"];
const SEG: Record<string, InstrumentCreate["segment"]> = {
  INDEX: "INDEX",
  FUTURE: "FUT",
  OPTION: "OPT",
};

const KNOWN_INDEX = [
  { symbol: "NIFTY", provider_symbol: "NSE_INDEX|Nifty 50" },
  { symbol: "BANKNIFTY", provider_symbol: "NSE_INDEX|Nifty Bank" },
  { symbol: "SENSEX", provider_symbol: "BSE_INDEX|SENSEX" },
];

function AddForm({ indexes, onClose }: { indexes: InstrumentSummary[]; onClose: () => void }) {
  const create = useCreateInstrument();
  const [f, setF] = useState<InstrumentCreate>({
    instrument_type: "INDEX",
    segment: "INDEX",
    provider_symbol: "",
    symbol: "",
    is_tracked: true,
  });
  const set = (patch: Partial<InstrumentCreate>) => setF((p) => ({ ...p, ...patch }));
  const isDeriv = f.instrument_type !== "INDEX";
  const isOpt = f.instrument_type === "OPTION";

  // -- provider-symbol autosuggest (docs/07 §4.2 GET /instruments/catalog) ----
  const [pq, setPq] = useState("");
  const [dq, setDq] = useState("");
  const [openList, setOpenList] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setDq(pq.trim()), 200);
    return () => clearTimeout(t);
  }, [pq]);
  const cat = useInstrumentCatalog(dq);

  const pick = (c: CatalogItem) => {
    const t = c.instrument_type as InstrumentCreate["instrument_type"];
    const under =
      (c.underlying_symbol &&
        indexes.find((i) => i.symbol === c.underlying_symbol)?.contract_key) ||
      undefined;
    setF((p) => ({
      ...p,
      provider_symbol: c.provider_symbol,
      instrument_type: t,
      segment: SEG[t] ?? p.segment,
      symbol: c.underlying_symbol || c.trading_symbol || p.symbol,
      display_name: c.name || undefined,
      exchange: c.exchange || (c.provider_symbol.startsWith("BSE") ? "BSE" : "NSE"),
      underlying_symbol: c.underlying_symbol ?? undefined,
      underlying_contract_key: under ?? p.underlying_contract_key,
      expiry_date: c.expiry_date ?? undefined,
      expiry_kind: (c.expiry_kind as InstrumentCreate["expiry_kind"]) ?? undefined,
      strike_price: c.strike_price ?? undefined,
      option_type: (c.option_type as InstrumentCreate["option_type"]) ?? undefined,
    }));
    setPq("");
    setDq("");
    setOpenList(false);
  };

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    create.mutate(
      {
        ...f,
        exchange: f.provider_symbol.startsWith("BSE") ? "BSE" : "NSE",
        strike_price: f.strike_price ? Number(f.strike_price) : undefined,
      },
      { onSuccess: onClose },
    );
  };

  const input = "rounded border border-slate-300 px-2 py-1 text-sm";
  return (
    <form onSubmit={submit} className="rounded-lg border border-slate-200 bg-slate-50 p-3">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-800">Add instrument</h3>
        <button type="button" onClick={onClose} className="text-xs text-slate-500 hover:text-slate-900">
          cancel
        </button>
      </div>

      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-0.5 text-xs text-slate-500">
          type
          <select
            className={input}
            value={f.instrument_type}
            onChange={(e) => {
              const t = e.target.value as InstrumentCreate["instrument_type"];
              set({ instrument_type: t, segment: SEG[t] });
            }}
          >
            {["INDEX", "FUTURE", "OPTION"].map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </label>

        <label className="relative flex flex-col gap-0.5 text-xs text-slate-500">
          provider symbol (Upstox key)
          <input
            className={`${input} w-72`}
            required
            autoComplete="off"
            placeholder="type a name — nifty 50, banknifty fut…"
            value={f.provider_symbol}
            onChange={(e) => {
              set({ provider_symbol: e.target.value });
              setPq(e.target.value);
              setOpenList(true);
            }}
            onFocus={() => {
              if (f.provider_symbol.trim().length >= 2) {
                setPq(f.provider_symbol);
                setOpenList(true);
              }
            }}
            onBlur={() => window.setTimeout(() => setOpenList(false), 150)}
          />
          {openList && dq.length >= 2 && (
            <div className="absolute left-0 top-full z-20 mt-1 max-h-72 w-[28rem] overflow-auto rounded-md border border-slate-300 bg-white shadow-lg">
              {cat.isLoading && <div className="px-3 py-2 text-slate-400">searching…</div>}
              {cat.data && !cat.data.available && (
                <div className="px-3 py-2 text-amber-600">
                  no Upstox master files on the server — type the key manually
                </div>
              )}
              {cat.data?.available && cat.data.items.length === 0 && (
                <div className="px-3 py-2 text-slate-400">no match</div>
              )}
              {cat.data?.items.map((c) => (
                <button
                  key={c.provider_symbol}
                  type="button"
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => pick(c)}
                  className="flex w-full items-center gap-2 border-b border-slate-100 px-3 py-1.5 text-left last:border-0 hover:bg-slate-50"
                >
                  <span className="font-mono text-[11px] text-slate-700">{c.provider_symbol}</span>
                  <span className="truncate text-slate-500">{c.name}</span>
                  <span className="ml-auto flex shrink-0 items-center gap-1 text-slate-400">
                    {c.expiry_date && <span>{c.expiry_date}</span>}
                    {c.option_type && <span>{c.option_type}</span>}
                    <Badge tone="muted">{c.instrument_type}</Badge>
                    {c.in_db && <Badge tone="ok">in DB</Badge>}
                  </span>
                </button>
              ))}
            </div>
          )}
        </label>

        <label className="flex flex-col gap-0.5 text-xs text-slate-500">
          symbol
          <input
            className={`${input} w-28`}
            placeholder="NIFTY"
            value={f.symbol ?? ""}
            onChange={(e) => set({ symbol: e.target.value })}
          />
        </label>

        {isDeriv && (
          <>
            <label className="flex flex-col gap-0.5 text-xs text-slate-500">
              underlying
              <select
                className={input}
                value={f.underlying_contract_key ?? ""}
                onChange={(e) => set({ underlying_contract_key: e.target.value || undefined })}
              >
                <option value="">—</option>
                {indexes.map((i) => (
                  <option key={i.id} value={i.contract_key}>
                    {i.contract_key}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-0.5 text-xs text-slate-500">
              expiry
              <input
                type="date"
                className={input}
                value={f.expiry_date ?? ""}
                onChange={(e) => set({ expiry_date: e.target.value || undefined })}
              />
            </label>
            <label className="flex flex-col gap-0.5 text-xs text-slate-500">
              kind
              <select
                className={input}
                value={f.expiry_kind ?? "MONTHLY"}
                onChange={(e) => set({ expiry_kind: e.target.value as "WEEKLY" | "MONTHLY" })}
              >
                <option>MONTHLY</option>
                <option>WEEKLY</option>
              </select>
            </label>
          </>
        )}

        {isOpt && (
          <>
            <label className="flex flex-col gap-0.5 text-xs text-slate-500">
              strike
              <input
                type="number"
                step="0.05"
                className={`${input} w-24`}
                value={(f.strike_price as number | undefined) ?? ""}
                onChange={(e) => set({ strike_price: e.target.value ? Number(e.target.value) : undefined })}
              />
            </label>
            <label className="flex flex-col gap-0.5 text-xs text-slate-500">
              CE/PE
              <select
                className={input}
                value={f.option_type ?? "CE"}
                onChange={(e) => set({ option_type: e.target.value as "CE" | "PE" })}
              >
                <option>CE</option>
                <option>PE</option>
              </select>
            </label>
          </>
        )}

        <label className="flex items-center gap-1 text-xs text-slate-600">
          <input
            type="checkbox"
            checked={f.is_tracked ?? true}
            onChange={(e) => set({ is_tracked: e.target.checked })}
          />
          track
        </label>

        <button
          type="submit"
          disabled={create.isPending || !f.provider_symbol}
          className="rounded bg-slate-800 px-3 py-1.5 text-sm text-white disabled:opacity-50"
        >
          {create.isPending ? "adding…" : "Add"}
        </button>
      </div>

      {f.instrument_type === "INDEX" && (
        <div className="mt-2 flex gap-2 text-xs text-slate-500">
          quick:
          {KNOWN_INDEX.map((k) => (
            <button
              key={k.symbol}
              type="button"
              className="rounded border border-slate-300 px-1.5 hover:bg-white"
              onClick={() => set({ provider_symbol: k.provider_symbol, symbol: k.symbol })}
            >
              {k.symbol}
            </button>
          ))}
        </div>
      )}
      {create.isError && <ProblemError error={create.error} />}
    </form>
  );
}

export function InstrumentManager() {
  const [type, setType] = useState("");
  const [tracked, setTracked] = useState<string>("");
  const [q, setQ] = useState("");
  const [showAdd, setShowAdd] = useState(false);

  const list = useInstruments({
    instrument_type: type || undefined,
    is_tracked: tracked === "" ? undefined : tracked === "yes",
    q: q || undefined,
    sort: "contract_key",
  });
  const indexList = useInstruments({ instrument_type: "INDEX", sort: "contract_key" });
  const patch = usePatchInstrument();
  const del = useDeleteInstrument();

  const remove = (r: InstrumentSummary) => {
    if (!window.confirm(`Delete ${r.contract_key} and all its bars / OI / scores? This cannot be undone.`))
      return;
    del.mutate(
      { id: r.id },
      {
        onError: (e) => {
          if (e instanceof ApiError && e.status === 409) {
            if (window.confirm(`${e.problem.detail}\n\nForce-delete it and its dependents?`)) {
              del.mutate({ id: r.id, force: true });
            }
          }
        },
      },
    );
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="flex items-baseline gap-2 text-lg font-bold">
          Instruments
          <LastUpdated q={list} className="font-normal" />
        </h1>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="search contract / symbol"
            className="w-56 rounded border border-slate-300 px-2 py-1"
          />
          <select value={type} onChange={(e) => setType(e.target.value)} className="rounded border border-slate-300 px-2 py-1">
            {TYPES.map((t) => (
              <option key={t} value={t}>
                {t || "all types"}
              </option>
            ))}
          </select>
          <select value={tracked} onChange={(e) => setTracked(e.target.value)} className="rounded border border-slate-300 px-2 py-1">
            <option value="">tracked: any</option>
            <option value="yes">tracked</option>
            <option value="no">not tracked</option>
          </select>
          <button
            onClick={() => setShowAdd((s) => !s)}
            className="rounded bg-slate-800 px-3 py-1 text-white"
          >
            {showAdd ? "close" : "+ Add"}
          </button>
        </div>
      </div>

      {showAdd && (
        <AddForm indexes={indexList.data?.items ?? []} onClose={() => setShowAdd(false)} />
      )}

      {list.isLoading && <Skeleton rows={12} />}
      {list.isError && <ProblemError error={list.error} onRetry={() => list.refetch()} />}
      {list.data && list.data.items.length === 0 && (
        <Empty>
          No instruments — add one above, or run{" "}
          <span className="font-mono">analytical-instruments build-universe</span> on the backend.
        </Empty>
      )}
      {list.data && list.data.items.length > 0 && (
        <>
          <p className="text-xs text-slate-500">{list.data.total} instruments</p>
          <DataTable<InstrumentSummary>
            cols={[
              {
                key: "ck",
                header: "Contract",
                cell: (r) => (
                  <Link className="text-blue-700 hover:underline" to={`/instruments/${r.id}`}>
                    {r.contract_key}
                  </Link>
                ),
              },
              { key: "type", header: "Type", cell: (r) => <Badge tone="muted">{r.instrument_type}</Badge> },
              { key: "expiry", header: "Expiry", cell: (r) => r.expiry_date ?? "—" },
              { key: "strike", header: "Strike", align: "right", cell: (r) => price(r.strike_price) },
              {
                key: "caps",
                header: "Caps",
                cell: (r) => (
                  <span className="flex gap-1">
                    {r.has_volume && <Badge tone="ok">vol</Badge>}
                    {r.has_intraday_oi && <Badge tone="ok">OI</Badge>}
                  </span>
                ),
              },
              {
                key: "track",
                header: "Tracked",
                cell: (r) => (
                  <button
                    disabled={patch.isPending}
                    onClick={() => patch.mutate({ id: r.id, is_tracked: !r.is_tracked })}
                    className={`rounded px-2 py-0.5 text-xs ring-1 ${
                      r.is_tracked
                        ? "bg-emerald-50 text-emerald-700 ring-emerald-300"
                        : "bg-slate-50 text-slate-500 ring-slate-300"
                    }`}
                  >
                    {r.is_tracked ? "tracked — untrack" : "track"}
                  </button>
                ),
              },
              {
                key: "del",
                header: "",
                cell: (r) => (
                  <button
                    disabled={del.isPending}
                    onClick={() => remove(r)}
                    title={`Delete ${r.contract_key}`}
                    className="rounded px-1.5 py-0.5 text-xs text-rose-600 hover:bg-rose-50 disabled:opacity-40"
                  >
                    delete
                  </button>
                ),
              },
            ]}
            rows={list.data.items}
            rowKey={(r) => r.id}
          />
        </>
      )}
      {(patch.isError || del.isError) && <ProblemError error={patch.error ?? del.error} />}
    </div>
  );
}
