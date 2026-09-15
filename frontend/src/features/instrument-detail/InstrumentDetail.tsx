import { Link, useParams } from "react-router-dom";
import {
  useInstrument,
  useInstrumentAnalyses,
  useMarketProfile,
  usePivots,
  useScoreDetail,
} from "@/api/queries";
import { useTimeframe, TIMEFRAMES } from "@/lib/timeframe";
import { ANALYSIS_ORDER } from "@/lib/scope";
import { compositeClass } from "@/lib/scoreBands";
import type { AnalysisItem, SignalLabel } from "@/api/generated/schema";
import {
  Badge,
  DataTable,
  LabelChip,
  Panel,
  ProblemError,
  Skeleton,
  StatGrid,
} from "@/components/primitives";
import { num, price, score } from "@/lib/format";
import { LastUpdated } from "@/components/LastUpdated";
import { AnalysisPanel } from "./panels";
import { MarketProfilePanel } from "./MarketProfilePanel";
import { ConstituentsPanel } from "./ConstituentsPanel";
import { KeyLevelsPanel } from "./KeyLevelsPanel";
import { CandlesGridPanel } from "./CandlesGridPanel";
import { GoldenCrossGridPanel } from "./GoldenCrossGridPanel";
import { FvgGridPanel } from "./FvgGridPanel";
import { PivotsPanel } from "./PivotsPanel";

export function InstrumentDetail() {
  const id = Number(useParams().id);
  const [tf, setTf] = useTimeframe();
  const inst = useInstrument(id);
  const analyses = useInstrumentAnalyses(id, tf);
  const scoreQ = useScoreDetail(id, tf);
  const mpQ = useMarketProfile(id);
  const pv = usePivots(id); // shared cache with PivotsPanel — gives the latest price

  if (inst.isLoading) return <Skeleton rows={8} />;
  if (inst.isError) return <ProblemError error={inst.error} onRetry={() => inst.refetch()} />;
  const d = inst.data!;

  const perTf = (analyses.data?.items ?? [])
    .filter((a) => a.scope === "PER_TIMEFRAME")
    .sort((a, b) => ANALYSIS_ORDER.indexOf(a.analysis_key) - ANALYSIS_ORDER.indexOf(b.analysis_key));
  const oi = (analyses.data?.items ?? []).find((a) => a.analysis_key === "open_interest");
  const mpItem = (analyses.data?.items ?? []).find((a) => a.analysis_key === "market_profile");

  return (
    <div className="space-y-5">
      {/* frozen top bar — stays pinned while the long panel stack scrolls */}
      <div className="sticky top-0 z-20 -mx-4 flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-slate-200 bg-white/95 px-4 py-2 backdrop-blur supports-[backdrop-filter]:bg-white/80">
        <div className="flex flex-wrap items-baseline gap-x-2">
          <h1 className="text-lg font-bold">{d.contract_key}</h1>
          {(() => {
            const lp = pv.data?.last_price;
            const pc = pv.data?.timeframes?.DAILY?.current?.from_period.close;
            const chg = lp != null && pc != null && pc !== 0 ? ((lp - pc) / pc) * 100 : null;
            if (lp == null) return null;
            return (
              <span className="tabular-nums">
                <b className="text-base">{price(lp)}</b>
                {chg != null && (
                  <span
                    className={`ml-1 text-xs ${chg >= 0 ? "text-emerald-600" : "text-rose-600"}`}
                  >
                    {chg >= 0 ? "+" : ""}
                    {num(chg, 2)}%
                  </span>
                )}
              </span>
            );
          })()}
          <span className="text-xs text-slate-500">
            {d.instrument_type} · {d.exchange}/{d.segment}
            {d.expiry_date ? ` · exp ${d.expiry_date}` : ""}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <label className="flex items-center gap-1 text-slate-500">
            tf
            <select
              className="rounded border border-slate-300 bg-white px-1 py-0.5 font-medium text-slate-800"
              value={tf}
              onChange={(e) => setTf(e.target.value as (typeof TIMEFRAMES)[number])}
            >
              {TIMEFRAMES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>
          {scoreQ.data ? (
            <>
              <LabelChip
                label={scoreQ.data.effective_label as SignalLabel}
                clamped={scoreQ.data.low_confidence}
              />
              <span className={`text-sm font-bold ${compositeClass(scoreQ.data.composite_score)}`}>
                {score(scoreQ.data.composite_score)}
              </span>
            </>
          ) : (
            <span className="text-slate-400">no score</span>
          )}
          <LastUpdated q={[analyses, scoreQ, mpQ, pv]} />
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Badge tone={d.is_tracked ? "ok" : "muted"}>{d.is_tracked ? "tracked" : "not tracked"}</Badge>
        <Badge tone={d.has_volume ? "ok" : "muted"}>volume {d.has_volume ? "yes" : "no"}</Badge>
        <Badge tone={d.has_intraday_oi ? "ok" : "muted"}>intraday OI {d.has_intraday_oi ? "yes" : "no"}</Badge>
        <Link className="text-blue-700 underline" to={`/instruments/${id}/series?tf=${tf}`}>series</Link>
        <Link className="text-blue-700 underline" to={`/instruments/${id}/runs`}>runs</Link>
        {d.instrument_type !== "OPTION" && (
          <Link className="text-blue-700 underline" to={`/instruments/${id}/daily-digest`}>
            daily digest
          </Link>
        )}
        {d.instrument_type === "INDEX" && (
          <>
            <Link className="text-blue-700 underline" to={`/instruments/${id}/option-chain`}>
              option chain
            </Link>
            <Link className="text-blue-700 underline" to={`/instruments/${id}/oi-pulse`}>
              OI pulse
            </Link>
            <Link className="text-blue-700 underline" to={`/instruments/${id}/oi-movers`}>
              OI movers
            </Link>
            <Link className="text-blue-700 underline" to={`/instruments/${id}/premium-decay`}>
              premium decay
            </Link>
            <Link className="text-blue-700 underline" to={`/instruments/${id}/backtest`}>
              backtest
            </Link>
          </>
        )}
      </div>

      <Panel
        title={`Score — ${tf}`}
        right={scoreQ.data && <span className={`text-lg font-bold ${compositeClass(scoreQ.data.composite_score)}`}>{score(scoreQ.data.composite_score)}</span>}
      >
        {scoreQ.isLoading && <Skeleton rows={3} />}
        {scoreQ.isError && <p className="text-sm text-slate-500">No score for this timeframe yet.</p>}
        {scoreQ.data && (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-3">
              <LabelChip label={scoreQ.data.effective_label as SignalLabel} clamped={scoreQ.data.low_confidence} />
              {scoreQ.data.low_confidence && (
                <span className="text-xs text-slate-500">
                  clamped from <b>{scoreQ.data.raw_label.replace(/_/g, " ").toLowerCase()}</b>
                </span>
              )}
              <span className="text-sm text-slate-600">confidence {num(scoreQ.data.confidence, 2)}</span>
              <span className="text-xs text-slate-400">run #{scoreQ.data.run_id}</span>
            </div>
            {scoreQ.data.warnings.length > 0 && (
              <ul className="list-disc pl-5 text-xs text-amber-700">
                {scoreQ.data.warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            )}
            {scoreQ.data.explanation && (
              <p className="rounded bg-slate-50 p-2 text-sm text-slate-700">{scoreQ.data.explanation}</p>
            )}
            <DataTable
              cols={[
                { key: "k", header: "Analysis", cell: (f) => f.analysis_key },
                { key: "sub", header: "Sub-score", align: "right", cell: (f) => score(f.sub_score) },
                { key: "conf", header: "Conf", align: "right", cell: (f) => num(f.confidence, 2) },
                { key: "w", header: "Weight", align: "right", cell: (f) => num(f.weight, 2) },
                { key: "c", header: "Contribution", align: "right", cell: (f) => score(f.contribution) },
                { key: "r", header: "Reason", cell: (f) => f.reason ?? "—" },
              ]}
              rows={scoreQ.data.factors}
              rowKey={(f) => f.analysis_key}
            />
            <p className="text-right font-mono text-xs text-slate-500">
              Σ contribution ={" "}
              {score(scoreQ.data.factors.reduce((s, f) => s + f.contribution, 0))} · composite{" "}
              {score(scoreQ.data.composite_score)}
            </p>
          </div>
        )}
      </Panel>

      {analyses.isLoading && <Skeleton rows={6} />}
      {analyses.isError && <ProblemError error={analyses.error} onRetry={() => analyses.refetch()} />}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {perTf.map((a: AnalysisItem) => (
          <AnalysisPanel key={a.analysis_key + a.scope} a={a} />
        ))}
        {oi && <AnalysisPanel key="oi" a={oi} />}
      </div>

      {d.instrument_type !== "OPTION" && <CandlesGridPanel instrumentId={id} />}

      {d.instrument_type !== "OPTION" && <GoldenCrossGridPanel instrumentId={id} />}

      {d.instrument_type !== "OPTION" && <FvgGridPanel instrumentId={id} />}

      {mpQ.data && <MarketProfilePanel mp={mpQ.data} instrumentId={id} />}
      {!mpQ.data && mpItem && (
        <Panel title="Market Profile (session)" muted>
          <StatGrid rows={[["Status", mpItem.status], ["Reason", mpItem.reason ?? "—"]]} />
        </Panel>
      )}

      <KeyLevelsPanel instrumentId={id} />

      <PivotsPanel instrumentId={id} />

      {d.instrument_type === "INDEX" && <ConstituentsPanel indexId={id} />}
    </div>
  );
}
