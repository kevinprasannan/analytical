/** TanStack Query hooks — one per API resource the UI reads. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import { istSessionWindow } from "@/lib/marketClock";
import type {
  AnalysisRuns,
  AnalysisSeries,
  OrbBacktestParams,
  OrbBacktestResponse,
  Applicability,
  AstroStudyResponse,
  BarsResponse,
  CalendarResponse,
  CalendarStatus,
  ConfigPatchResponse,
  ConfigResponse,
  AlmanacParams,
  AlmanacResponse,
  DashaParams,
  DashaResponse,
  MoonDashaParams,
  MoonDashaResponse,
  DayDetailResponse,
  KpTimelineResponse,
  DayLogParams,
  DayLogResponse,
  HealthReady,
  InstrumentAnalyses,
  InstrumentCatalog,
  InstrumentCoverage,
  InstrumentCreate,
  InstrumentCreated,
  InstrumentDeleted,
  InstrumentDetail,
  InstrumentSummary,
  MarketBoard,
  MarketProfile,
  MetaVersions,
  OptionChainResponse,
  OptionStrategyResponse,
  IndexConstituentsResponse,
  ConstituentLevelsResponse,
  OiPulseResponse,
  OiMoversResponse,
  PremiumDecayResponse,
  DailyDigestResponse,
  KeyLevelsResponse,
  CandlesGridResponse,
  GoldenCrossGridResponse,
  FvgGridResponse,
  PivotsResponse,
  DailyDigestParams,
  Page,
  RunDetail,
  RunSummary,
  ScoreDetail,
  ScoreHistory,
  ScoreListItem,
  Timeframe,
} from "./generated/schema";

const k = {
  meta: ["meta"] as const,
  health: ["health", "ready"] as const,
  applicability: ["meta", "applicability"] as const,
  config: ["config"] as const,
  calStatus: ["calendar", "status"] as const,
};

export const useMetaVersions = () =>
  useQuery({ queryKey: k.meta, queryFn: () => api.get<MetaVersions>("/meta/versions") });

export const useHealthReady = (refetchInterval?: number | false) =>
  useQuery({
    queryKey: k.health,
    queryFn: () => api.get<HealthReady>("/health/ready"),
    refetchInterval,
  });

export const useApplicability = () =>
  useQuery({ queryKey: k.applicability, queryFn: () => api.get<Applicability>("/meta/applicability") });

export const useBoard = (refetchInterval?: number | false) =>
  useQuery({
    queryKey: ["board"] as const,
    queryFn: () => api.get<MarketBoard>("/board"),
    refetchInterval,
  });

export const useCalendarStatus = (refetchInterval?: number | false) =>
  useQuery({
    queryKey: k.calStatus,
    queryFn: () => api.get<CalendarStatus>("/calendar/status"),
    refetchInterval,
  });

export const useCalendar = (start: string, end: string) =>
  useQuery({
    queryKey: ["calendar", start, end],
    queryFn: () => api.get<CalendarResponse>("/calendar", { start, end }),
    enabled: !!start && !!end,
  });

// -- scores (watchlist) --------------------------------------------
export interface ScoreFilters {
  timeframe: Timeframe;
  instrument_type?: string;
  label?: string;
  min_confidence?: number;
  sort?: string;
}
export const useScores = (f: ScoreFilters, refetchInterval?: number) =>
  useQuery({
    queryKey: ["scores", f],
    queryFn: () =>
      api.get<Page<ScoreListItem>>("/scores", {
        timeframe: f.timeframe,
        instrument_type: f.instrument_type,
        label: f.label,
        min_confidence: f.min_confidence,
        sort: f.sort ?? "-composite_score",
        limit: 500,
      }),
    refetchInterval,
  });

// -- instruments -------------------------------------------------
export const useInstruments = (params: {
  is_tracked?: boolean;
  instrument_type?: string;
  q?: string;
  sort?: string;
}) =>
  useQuery({
    queryKey: ["instruments", params],
    queryFn: () =>
      api.get<Page<InstrumentSummary>>("/instruments", { ...params, limit: 500 }),
  });

export const useInstrument = (id: number) =>
  useQuery({
    queryKey: ["instrument", id],
    queryFn: () => api.get<InstrumentDetail>(`/instruments/${id}`),
    enabled: Number.isFinite(id),
  });

export const useCoverage = (id: number) =>
  useQuery({
    queryKey: ["instrument", id, "coverage"],
    queryFn: () => api.get<InstrumentCoverage>(`/instruments/${id}/coverage`),
    enabled: Number.isFinite(id),
  });

export const useBars = (id: number, timeframe: Timeframe) =>
  useQuery({
    queryKey: ["instrument", id, "bars", timeframe],
    queryFn: () =>
      api.get<BarsResponse>(`/instruments/${id}/bars`, { timeframe, limit: 200 }),
    enabled: Number.isFinite(id),
  });

export const usePatchInstrument = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { id: number; is_tracked?: boolean; profile_bin_size?: string }) =>
      api.patch<InstrumentDetail>(`/instruments/${v.id}`, {
        is_tracked: v.is_tracked,
        profile_bin_size: v.profile_bin_size,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["instruments"] });
      qc.invalidateQueries({ queryKey: ["scores"] });
    },
  });
};

export const useInstrumentCatalog = (q: string, instrument_type?: string) =>
  useQuery({
    queryKey: ["catalog", q, instrument_type ?? ""] as const,
    queryFn: () =>
      api.get<InstrumentCatalog>("/instruments/catalog", {
        q,
        instrument_type,
        limit: 20,
      }),
    enabled: q.trim().length >= 2,
    staleTime: 60_000,
  });

export const useCreateInstrument = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: InstrumentCreate) =>
      api.post<InstrumentCreated>("/instruments", body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["instruments"] });
      qc.invalidateQueries({ queryKey: ["board"] });
    },
  });
};

export const useDeleteInstrument = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { id: number; force?: boolean }) =>
      api.del<InstrumentDeleted>(`/instruments/${v.id}`, v.force ? { force: true } : undefined),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["instruments"] });
      qc.invalidateQueries({ queryKey: ["board"] });
      qc.invalidateQueries({ queryKey: ["scores"] });
    },
  });
};

// -- analyses --------------------------------------------------
export const useInstrumentAnalyses = (id: number, timeframe: Timeframe) =>
  useQuery({
    queryKey: ["instrument", id, "analyses", timeframe],
    queryFn: () =>
      api.get<InstrumentAnalyses>(`/instruments/${id}/analyses`, { timeframe }),
    enabled: Number.isFinite(id),
  });

export const useAnalysisSeries = (id: number, key: string, timeframe: Timeframe) =>
  useQuery({
    queryKey: ["instrument", id, "series", key, timeframe],
    queryFn: () =>
      api.get<AnalysisSeries>(`/instruments/${id}/analyses/${key}/series`, { timeframe }),
    enabled: Number.isFinite(id) && !!key,
  });

export const useAnalysisRuns = (id: number, key: string) =>
  useQuery({
    queryKey: ["instrument", id, "analysis-runs", key],
    queryFn: () => api.get<AnalysisRuns>(`/instruments/${id}/analyses/${key}/runs`),
    enabled: Number.isFinite(id) && !!key,
  });

export const useMarketProfile = (id: number, sessionDate?: string) =>
  useQuery({
    queryKey: ["instrument", id, "market-profile", sessionDate ?? "latest"] as const,
    queryFn: () => {
      const qs = sessionDate ? `?session_date=${sessionDate}` : "";
      return api.get<MarketProfile>(`/instruments/${id}/market-profile${qs}`);
    },
    enabled: Number.isFinite(id),
    retry: false,
  });

// -- score detail ------------------------------------------------
export const useScoreDetail = (id: number, timeframe: Timeframe) =>
  useQuery({
    queryKey: ["instrument", id, "score", timeframe],
    queryFn: () => api.get<ScoreDetail>(`/instruments/${id}/score`, { timeframe }),
    enabled: Number.isFinite(id),
    retry: false,
  });

export const useScoreHistory = (id: number, timeframe: Timeframe) =>
  useQuery({
    queryKey: ["instrument", id, "score-history", timeframe],
    queryFn: () =>
      api.get<ScoreHistory>(`/instruments/${id}/score/history`, { timeframe }),
    enabled: Number.isFinite(id),
  });

// -- runs -------------------------------------------------------
export const useRuns = () =>
  useQuery({ queryKey: ["runs"], queryFn: () => api.get<Page<RunSummary>>("/runs", { limit: 100 }) });

export const useRun = (id: number) =>
  useQuery({
    queryKey: ["run", id],
    queryFn: () => api.get<RunDetail>(`/runs/${id}`),
    enabled: Number.isFinite(id),
  });

export const useTriggerRun = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { phases: string[] }) =>
      api.post<RunDetail>("/runs", { trigger: "MANUAL", phases: v.phases }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["runs"] });
      qc.invalidateQueries({ queryKey: ["scores"] });
    },
  });
};

// -- option chain -------------------------------------------
export const useOptionChain = (underlyingId: number, expiry?: string) =>
  useQuery({
    queryKey: ["option-chain", underlyingId, expiry ?? "near"] as const,
    queryFn: () =>
      api.get<OptionChainResponse>(
        `/instruments/${underlyingId}/option-chain${expiry ? `?expiry=${expiry}` : ""}`,
      ),
    // spot + ATM re-derive server-side each poll — the chain follows the money live
    refetchInterval: () => (istSessionWindow() ? 30_000 : false),
    placeholderData: (prev) => prev,
  });

// -- index constituents / weightage (docs/15) -------------
export const useIndexConstituents = (
  indexId: number,
  opts: { effectiveDate?: string; includeBeta?: boolean; lookback?: number; asOfDate?: string } = {},
) =>
  useQuery({
    queryKey: [
      "index-constituents",
      indexId,
      opts.effectiveDate ?? "latest",
      opts.includeBeta ?? false,
      opts.lookback ?? 60,
      opts.asOfDate ?? "live",
    ] as const,
    queryFn: () => {
      const qs = new URLSearchParams();
      if (opts.effectiveDate) qs.set("effective_date", opts.effectiveDate);
      if (opts.includeBeta) qs.set("include_beta", "true");
      if (opts.lookback) qs.set("lookback", String(opts.lookback));
      if (opts.asOfDate) qs.set("as_of_date", opts.asOfDate);
      const q = qs.toString();
      return api.get<IndexConstituentsResponse>(
        `/instruments/${indexId}/constituents${q ? `?${q}` : ""}`,
      );
    },
    refetchInterval: () => (opts.asOfDate ? false : istSessionWindow() ? 60_000 : false),
  });

// -- top-N constituents: levels + indicators (docs/07 §4.20) --
// heavy (live provider fetch per name) — enable only when the section is shown
export const useConstituentLevels = (indexId: number, n: number, enabled: boolean) =>
  useQuery({
    queryKey: ["constituent-levels", indexId, n] as const,
    queryFn: () =>
      api.get<ConstituentLevelsResponse>(`/instruments/${indexId}/constituents/levels`, { n }),
    enabled,
    staleTime: 5 * 60_000,
    refetchInterval: () => (istSessionWindow() ? 5 * 60_000 : false),
    retry: false,
  });

// -- opening-range breakout backtest (docs/16) ------------
export const useOrbBacktest = (
  indexId: number,
  params: OrbBacktestParams,
  enabled: boolean,
) =>
  useQuery({
    queryKey: ["orb-backtest", indexId, params] as const,
    queryFn: () => {
      const qs = new URLSearchParams();
      Object.entries(params).forEach(([k, v]) => {
        if (v != null && v !== "") qs.set(k, String(v));
      });
      const q = qs.toString();
      return api.get<OrbBacktestResponse>(
        `/instruments/${indexId}/backtest/orb${q ? `?${q}` : ""}`,
      );
    },
    enabled,
    staleTime: 5 * 60_000,
  });

// -- OI-based option-strategy suggestions ------------------
export const useOptionStrategies = (underlyingId: number, expiry?: string) =>
  useQuery({
    queryKey: ["option-strategies", underlyingId, expiry ?? "near"] as const,
    queryFn: () =>
      api.get<OptionStrategyResponse>(
        `/instruments/${underlyingId}/option-strategies${expiry ? `?expiry=${expiry}` : ""}`,
      ),
    refetchInterval: () => (istSessionWindow() ? 60_000 : false),
  });

// -- OI pulse (trending OI) --------------------------------
export const useOiPulse = (
  underlyingId: number,
  opts: { expiry?: string; traceUp?: number; traceDown?: number } = {},
) =>
  useQuery({
    queryKey: [
      "oi-pulse",
      underlyingId,
      opts.expiry ?? "near",
      opts.traceUp ?? "all",
      opts.traceDown ?? "all",
    ] as const,
    queryFn: () => {
      const qs = new URLSearchParams();
      if (opts.expiry) qs.set("expiry", opts.expiry);
      if (opts.traceUp != null) qs.set("trace_up", String(opts.traceUp));
      if (opts.traceDown != null) qs.set("trace_down", String(opts.traceDown));
      const q = qs.toString();
      return api.get<OiPulseResponse>(
        `/instruments/${underlyingId}/oi-pulse${q ? `?${q}` : ""}`,
      );
    },
    // only during session hours (~15:40 IST cutoff) — after that the pulse is fixed
    refetchInterval: () => (istSessionWindow() ? 60_000 : false),
  });

// -- big OI movement, options only (docs/05 §11.4) --------
export const useOiMovers = (
  underlyingId: number,
  opts: { top?: number; timeBand?: number; moneyness?: string[] } = {},
) =>
  useQuery({
    queryKey: [
      "oi-movers",
      underlyingId,
      opts.top ?? 15,
      opts.timeBand ?? 15,
      [...(opts.moneyness ?? [])].sort().join(","),
    ] as const,
    queryFn: () => {
      const qs = new URLSearchParams({ top: String(opts.top ?? 15), time_band: String(opts.timeBand ?? 15) });
      (opts.moneyness ?? []).forEach((m) => qs.append("moneyness", m));
      return api.get<OiMoversResponse>(`/instruments/${underlyingId}/oi-movers?${qs}`);
    },
    refetchInterval: () => (istSessionWindow() ? 45_000 : false),
    placeholderData: (prev) => prev,
    retry: false,
  });

// -- premium decay: theta vs. the session's actual move (docs/05 §11.6) --
export const usePremiumDecay = (underlyingId: number, opts: { expiry?: string } = {}) =>
  useQuery({
    queryKey: ["premium-decay", underlyingId, opts.expiry ?? "near"] as const,
    queryFn: () => {
      const qs = new URLSearchParams();
      if (opts.expiry) qs.set("expiry", opts.expiry);
      const q = qs.toString();
      return api.get<PremiumDecayResponse>(
        `/instruments/${underlyingId}/premium-decay${q ? `?${q}` : ""}`,
      );
    },
    refetchInterval: () => (istSessionWindow() ? 45_000 : false),
    placeholderData: (prev) => prev,
    retry: false,
  });

// -- daily digest (OHLC + PDH/PDL break + day profile) -----
export const useDailyDigest = (instrumentId: number, params: DailyDigestParams = {}) =>
  useQuery({
    queryKey: ["daily-digest", instrumentId, params] as const,
    queryFn: () =>
      api.get<DailyDigestResponse>(`/instruments/${instrumentId}/daily-digest`, { ...params }),
    placeholderData: (prev) => prev,
  });

// -- key levels (docs/05 §10.12) --------------------------------
export const useKeyLevels = (instrumentId: number) =>
  useQuery({
    queryKey: ["key-levels", instrumentId] as const,
    queryFn: () => api.get<KeyLevelsResponse>(`/instruments/${instrumentId}/key-levels`),
    refetchInterval: () => (istSessionWindow() ? 60_000 : false),
    placeholderData: (prev) => prev,
    retry: false,
  });

// -- multi-timeframe candle grid (docs/05 §9b) -----------------
export const useCandlesGrid = (instrumentId: number, limit = 5) =>
  useQuery({
    queryKey: ["candles-grid", instrumentId, limit] as const,
    queryFn: () =>
      api.get<CandlesGridResponse>(`/instruments/${instrumentId}/candles-grid`, { limit }),
    refetchInterval: () => (istSessionWindow() ? 60_000 : false),
    placeholderData: (prev) => prev,
    retry: false,
  });

// -- Golden Cross per timeframe (docs/05 §7) -------------------
export const useGoldenCrossGrid = (instrumentId: number) =>
  useQuery({
    queryKey: ["golden-cross-grid", instrumentId] as const,
    queryFn: () =>
      api.get<GoldenCrossGridResponse>(`/instruments/${instrumentId}/golden-cross-grid`),
    refetchInterval: () => (istSessionWindow() ? 60_000 : false),
    placeholderData: (prev) => prev,
    retry: false,
  });

// -- ICT swing Fair Value Gaps per timeframe (docs/05 §9c) -----
export const useFvgGrid = (instrumentId: number) =>
  useQuery({
    queryKey: ["fvg-grid", instrumentId] as const,
    queryFn: () => api.get<FvgGridResponse>(`/instruments/${instrumentId}/fvg-grid`),
    refetchInterval: () => (istSessionWindow() ? 60_000 : false),
    placeholderData: (prev) => prev,
    retry: false,
  });

// -- CPR + classic pivots, daily/weekly/monthly (docs/05 §10.13) --
export const usePivots = (
  instrumentId: number,
  opts: { dailyOn?: string; dailyYears?: number } = {},
) =>
  useQuery({
    queryKey: ["pivots", instrumentId, opts.dailyOn ?? null, opts.dailyYears ?? null] as const,
    queryFn: () =>
      api.get<PivotsResponse>(`/instruments/${instrumentId}/pivots`, {
        ...(opts.dailyOn ? { daily_on: opts.dailyOn, daily_years: opts.dailyYears ?? 20 } : {}),
      }),
    refetchInterval: () => (istSessionWindow() ? 60_000 : false),
    placeholderData: (prev) => prev,
    retry: false,
  });

// -- astro x market study -----------------------------------
export const useAstroStudy = (opts: { underlying?: string; start?: string; end?: string } = {}) => {
  const underlying = opts.underlying ?? "NIFTY-INDEX";
  return useQuery({
    queryKey: ["astro-study", underlying, opts.start ?? "", opts.end ?? ""] as const,
    queryFn: () =>
      api.get<AstroStudyResponse>("/astro/study", {
        underlying,
        start: opts.start,
        end: opts.end,
      }),
  });
};

export const useAstroDays = (params: DayLogParams) =>
  useQuery({
    queryKey: ["astro-days", params] as const,
    queryFn: () => api.get<DayLogResponse>("/astro/days", { ...params }),
    placeholderData: (prev) => prev, // keep the last page visible while the next loads
  });

export const useAstroAlmanac = (params: AlmanacParams) =>
  useQuery({
    queryKey: ["astro-almanac", params] as const,
    queryFn: () => api.get<AlmanacResponse>("/astro/almanac", { ...params }),
    placeholderData: (prev) => prev,
  });

export const useAstroDasha = (params: DashaParams = {}) =>
  useQuery({
    queryKey: ["astro-dasha", params] as const,
    queryFn: () => api.get<DashaResponse>("/astro/dasha", { ...params }),
    placeholderData: (prev) => prev,
  });

export const useAstroMoonDasha = (params: MoonDashaParams | undefined) =>
  useQuery({
    queryKey: ["astro-moon-dasha", params] as const,
    queryFn: () => api.get<MoonDashaResponse>("/astro/dasha/moon", { ...params }),
    enabled: !!params?.d,
    placeholderData: (prev) => prev,
  });

export const useAstroDayDetail = (d: string | undefined, underlying = "NIFTY-INDEX") =>
  useQuery({
    queryKey: ["astro-day", d ?? "", underlying] as const,
    queryFn: () => api.get<DayDetailResponse>(`/astro/days/${d}`, { underlying }),
    enabled: !!d,
  });

export const useAstroKpTimeline = (
  d: string | undefined,
  end: string,
  level: "sub" | "sub_sub",
  underlying = "NIFTY-INDEX",
) =>
  useQuery({
    queryKey: ["astro-kp-timeline", d ?? "", end, level, underlying] as const,
    queryFn: () =>
      api.get<KpTimelineResponse>(`/astro/days/${d}/kp-timeline`, { end, level, underlying }),
    enabled: !!d,
    placeholderData: (prev) => prev,
  });

// -- config ---------------------------------------------------
export const useConfig = () =>
  useQuery({ queryKey: k.config, queryFn: () => api.get<ConfigResponse>("/config") });

export const useConfigSchema = () =>
  useQuery({
    queryKey: ["config", "schema"],
    queryFn: () => api.get<Record<string, unknown>>("/config/schema"),
  });

export const usePatchConfig = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: Record<string, unknown>) =>
      api.patch<ConfigPatchResponse>("/config", patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: k.config }),
  });
};
