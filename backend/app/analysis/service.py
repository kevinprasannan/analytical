"""ANALYZE phase — real indicators (Phase 3, docs/02 §3.5, docs/05 §4–§9).

For each eligible instrument and each applicable ``(analysis, scope)`` (docs/04
§4): load recent bars from the market-data store, build an ``analytical_core``
series, run the deterministic indicator, and write ``analysis_results`` (with the
provenance columns) + ``current_analysis_results`` under the current run.

**Recompute guard (docs/02 §3.5):** if the latest input bar ``ts`` is unchanged,
that bar is final, and ``params_hash`` + ``algo_version`` are unchanged since the
last stored result for ``(instrument, analysis_key, scope_key)``, skip the engine
and write a light ``carried = true`` row referencing the prior result.

``market_profile`` runs through :meth:`_run_market_profile` (docs/05 §10).
Applicability-matrix ``NOT_APPLICABLE`` / ``INSUFFICIENT_DATA`` plans get a
:func:`matrix_status_result` row (no engine, full provenance).
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from analytical_core.enums import (
    AnalysisScope,
    AnalysisStatus,
    InstrumentPhaseOutcome,
    PhaseStatus,
    RunPhase,
    Timeframe,
)
from analytical_core.indicators import (
    bollinger,
    candles,
    ema7,
    golden_cross,
    open_interest,
    order_block,
    rsi,
    volume,
)
from analytical_core.params import effective_params, params_hash, params_id
from analytical_core.results import AnalysisResult, matrix_status_result
from analytical_core.series import OHLCVSeries, OpenInterestSeries
from analytical_core.versioning import ALGO_VERSION
from app.analysis.applicability import PlannedAnalysis, plan_analyses
from app.db.repositories.market_data import MarketDataRepository
from app.db.repositories.protocols import (
    AnalysisResultRepository,
    InstrumentView,
    ProjectionRepository,
    ResultWrite,
)
from app.pipeline import PhaseOutcome
from app.providers.capabilities import ProviderCapabilities

_LOAD_LIMIT = {
    "rsi": 120,
    "bollinger": 200,
    "ema7": 60,
    "golden_cross": 320,
    "volume": 80,
    "open_interest": 60,
    "order_block": 160,
    "candles": 40,
}


class AnalysisService:
    def __init__(
        self,
        results: AnalysisResultRepository,
        projections: ProjectionRepository,
        capabilities: ProviderCapabilities,
        *,
        market_data: MarketDataRepository | None = None,
        market_profile_repo=None,
        market_profile_config=None,
        provider_id: str = "upstox",
        now: datetime | None = None,
    ) -> None:
        self.results = results
        self.projections = projections
        self.caps = capabilities
        self.market_data = market_data
        self.market_profile_repo = market_profile_repo
        self.market_profile_config = market_profile_config
        self.provider_id = provider_id
        self.now = now or datetime.now(tz=UTC)

    def run(
        self, run_id: int, instruments: list[InstrumentView], eligible: set[int]
    ) -> PhaseOutcome:
        outcome = PhaseOutcome(phase=RunPhase.ANALYZE, status=PhaseStatus.RUNNING)
        session_date = self.now.date()

        for inst in instruments:
            if inst.id not in eligible:
                outcome.record(inst.id, InstrumentPhaseOutcome.SKIPPED)
                continue
            try:
                for plan in plan_analyses(
                    inst, self.caps, as_of=self.now, session_date=session_date
                ):
                    self._one(run_id, inst, plan, session_date)
                outcome.record(inst.id, InstrumentPhaseOutcome.OK)
            except Exception as exc:  # per-instrument resilience
                outcome.record(inst.id, InstrumentPhaseOutcome.ERROR)
                outcome.detail.setdefault("errors", {})[str(inst.id)] = repr(exc)

        outcome.status = _roll_up(outcome)
        return outcome

    # -- one (instrument, analysis, scope) -------------------------------
    def _one(
        self, run_id: int, inst: InstrumentView, plan: PlannedAnalysis, session_date: date
    ) -> None:
        key = plan.analysis_key
        scope_key = _scope_key(plan)

        if (
            key == "market_profile"
            and plan.status is AnalysisStatus.OK
            and self.market_data is not None
            and self.market_profile_repo is not None
        ):
            self._run_market_profile(run_id, inst, plan, scope_key)
            return

        # matrix-level NOT_APPLICABLE / INSUFFICIENT / market_profile -> no engine
        if plan.status is not AnalysisStatus.OK or key == "market_profile":
            res = matrix_status_result(
                analysis_key=key,
                scope=plan.scope,
                as_of_ts=self.now,
                status=plan.status,
                reason=plan.reason,
            )
            self._persist(run_id, inst, plan, scope_key, res, bars_used=None, coverage=None)
            return

        can_compute = self.market_data is not None and key in _LOAD_LIMIT
        if not can_compute:  # no market-data seam wired (memory-only dev)
            res = matrix_status_result(
                analysis_key=key, scope=plan.scope, as_of_ts=self.now, status=AnalysisStatus.OK
            )
            self._persist(run_id, inst, plan, scope_key, res, bars_used=None, coverage=None)
            return

        if key == "open_interest":
            self._run_oi(run_id, inst, plan, scope_key)
            return

        bars = self.market_data.load_bars(
            instrument_id=inst.id,
            timeframe=plan.timeframe or Timeframe.D1,
            provider=self.provider_id,
            limit=_LOAD_LIMIT[key],
        )
        if not bars:
            res = _insufficient(key, plan.scope, self.now, "no bars ingested for this timeframe")
            self._persist(run_id, inst, plan, scope_key, res, bars_used=0, coverage=0.0)
            return

        eff_hash = params_hash(effective_params(key))
        if self._carry(run_id, inst, plan, scope_key, bars[-1], eff_hash):
            return

        series = _ohlcv_series(bars, plan.timeframe or Timeframe.D1)
        res = _dispatch(key, series, inst)
        self._persist(
            run_id,
            inst,
            plan,
            scope_key,
            res,
            bars_used=len(bars),
            coverage=series.coverage_ratio,
        )

    def _run_oi(
        self, run_id: int, inst: InstrumentView, plan: PlannedAnalysis, scope_key: str
    ) -> None:
        tf = plan.timeframe or Timeframe.D1
        assert self.market_data is not None
        oi_rows = self.market_data.load_oi(
            instrument_id=inst.id, timeframe=Timeframe.M1, provider=self.provider_id, limit=6000
        )
        d1 = self.market_data.load_bars(
            instrument_id=inst.id, timeframe=Timeframe.D1, provider=self.provider_id, limit=400
        )
        pts = _oi_daily_points(oi_rows, d1)
        if len(pts) < 2:
            res = _insufficient(
                "open_interest", plan.scope, self.now, "fewer than 2 daily OI points"
            )
            self._persist(run_id, inst, plan, scope_key, res, bars_used=len(pts), coverage=None)
            return
        ts, oi, price, poc, isf = zip(*pts, strict=True)
        ois = OpenInterestSeries(
            scope=plan.scope,
            ts=ts,
            oi=oi,
            price=price,
            provider_oi_change=poc,
            is_final=isf,
        )
        eff_hash = params_hash(effective_params("open_interest"))
        fake_last = _FakeBar(ts[-1], bool(isf[-1]))
        if self._carry(run_id, inst, plan, scope_key, fake_last, eff_hash):
            return
        res = open_interest(ois, instrument_type=inst.instrument_type)
        _ = tf  # scope_key already encodes the timeframe
        self._persist(run_id, inst, plan, scope_key, res, bars_used=len(pts), coverage=None)

    def _run_market_profile(
        self, run_id: int, inst: InstrumentView, plan: PlannedAnalysis, scope_key: str
    ) -> None:
        from analytical_core.enums import AnalysisStatus as _AS
        from analytical_core.market_profile import MarketProfileConfig, market_profile
        from analytical_core.market_profile.events import MP_EVENTS_VERSION
        from analytical_core.results import AnalysisResult as _AR
        from analytical_core.versioning import ALGO_VERSION as _AV
        from app.db.repositories.protocols import MarketProfileSessionWrite
        from app.ingestion.session import nse_session_window

        assert self.market_data is not None and self.market_profile_repo is not None
        cfg = self.market_profile_config or MarketProfileConfig()
        sdate = plan.session_date or self.now.date()
        window = nse_session_window(sdate)
        bars_all = self.market_data.load_bars(
            instrument_id=inst.id, timeframe=Timeframe.M5, provider=self.provider_id, limit=200
        )
        bars = [b for b in bars_all if window.open_utc <= b.ts.astimezone(UTC) <= window.close_utc]
        # event-layer version folded in so an MP_EVENTS_VERSION bump forces recompute
        eff_hash = params_hash({"mp": cfg.hashable(), "mp_events_v": MP_EVENTS_VERSION})

        if len(bars) < cfg.min_periods_for_result:
            res = _insufficient(
                "market_profile", plan.scope, self.now, "not enough session bars for a profile"
            )
            self._persist(run_id, inst, plan, scope_key, res, bars_used=len(bars), coverage=None)
            return

        source_max_ts = max(b.ts for b in bars).astimezone(UTC)
        cache = self.market_profile_repo.get_cache(inst.id, sdate, "TPO")
        if (
            cache is not None
            and cache.params_hash == eff_hash
            and cache.source_max_ts is not None
            and cache.source_max_ts == source_max_ts
        ):
            fake = _FakeBar(source_max_ts, True)
            if self._carry(run_id, inst, plan, scope_key, fake, eff_hash):
                return

        series = _ohlcv_series(bars, Timeframe.M5)
        out = market_profile(
            series,
            config=cfg,
            session_open=window.open_utc,
            session_close=window.close_utc,
            session_date=sdate,
            instrument_type=inst.instrument_type,
            has_volume=inst.has_volume,
            price_ref=float(bars[0].open),
            underlying_symbol=inst.contract_key.split("-")[0],
            now=self.now,
        )
        if out.status != "OK":
            res = _insufficient(
                "market_profile", plan.scope, self.now, out.reason or "insufficient"
            )
            self._persist(run_id, inst, plan, scope_key, res, bars_used=len(bars), coverage=None)
            return

        # -- Market Profile event layer (docs/14) — never breaks the cycle -------
        from analytical_core.market_profile import (
            PriorProfile,
            event_result_to_dict,
            run_event_engine,
        )

        prior_ref = self.market_profile_repo.get_prior_session(inst.id, sdate, "TPO")
        prior = (
            PriorProfile(
                session_date=str(prior_ref.session_date),
                poc=prior_ref.poc,
                vah=prior_ref.vah,
                val=prior_ref.val,
                high=prior_ref.session_high,
                low=prior_ref.session_low,
                close=prior_ref.close,
            )
            if prior_ref is not None
            else PriorProfile(str(sdate), None, None, None, None, None, None)
        )
        try:
            ev_res = run_event_engine(
                series,
                config=cfg,
                session_open=window.open_utc,
                session_close=window.close_utc,
                session_date=sdate,
                instrument_type=inst.instrument_type,
                has_volume=inst.has_volume,
                price_ref=float(bars[0].open),
                underlying_symbol=inst.contract_key.split("-")[0],
                prior=prior,
                atr=None,
                now=self.now,
            )
            events_blob: dict | None = event_result_to_dict(ev_res)
        except Exception as exc:  # noqa: BLE001 - isolate the event layer
            events_blob = {
                "version": MP_EVENTS_VERSION,
                "status": "ERROR",
                "reason": str(exc)[:200],
                "events": [],
                "tensions": [],
                "day_type": None,
                "facts": None,
            }

        for ptype, pr in out.profiles.items():
            self.market_profile_repo.upsert_session(
                MarketProfileSessionWrite(
                    instrument_id=inst.id,
                    session_date=sdate,
                    profile_type=ptype,
                    bin_size=pr.bin_size,
                    poc=pr.poc,
                    vah=pr.vah,
                    val=pr.val,
                    ib_high=pr.ib_high,
                    ib_low=pr.ib_low,
                    session_high=pr.session_high,
                    session_low=pr.session_low,
                    profile_shape=pr.profile_shape,
                    is_session_complete=pr.is_session_complete,
                    close=pr.close,
                    bins={"bins": pr.bins},
                    events=events_blob if ptype == "TPO" else None,
                    mp_events_version=MP_EVENTS_VERSION if ptype == "TPO" else None,
                    source_max_ts=source_max_ts,
                    algo_version=_AV,
                    params_hash=eff_hash,
                )
            )

        tpo = out.profiles["TPO"]
        values = tpo.values(sdate, window.open_utc, window.close_utc)
        result = _AR(
            analysis_key="market_profile",
            scope=plan.scope,
            status=_AS.OK,
            as_of_ts=self.now,
            values=values,
            aux={"close": values["close"], "vwap_proxy": round(tpo.vwap_proxy, 4)},
            series=None,
            warnings=(),
            meta={
                "algo_version": _AV,
                "params_id": params_id("market_profile"),
                "params_hash": eff_hash,
                "params": out.params,
                "source_max_ts": source_max_ts.isoformat(),
                "input_window_start": window.open_utc.isoformat(),
                "input_window_end": source_max_ts.isoformat(),
                "last_bar_final": bool(bars[-1].is_final),
            },
        )
        self._persist(run_id, inst, plan, scope_key, result, bars_used=len(bars), coverage=None)

    # -- recompute guard ------------------------------------------------
    def _carry(
        self,
        run_id: int,
        inst: InstrumentView,
        plan: PlannedAnalysis,
        scope_key: str,
        last_bar: _FakeBar,
        eff_hash: str,
    ) -> bool:
        fp = self.results.last_fingerprint(inst.id, plan.analysis_key, scope_key)
        if (
            fp is not None
            and last_bar.is_final
            and fp.last_bar_final
            and fp.params_hash == eff_hash
            and fp.algo_version == ALGO_VERSION
            and fp.input_window_end == last_bar.ts
        ):
            write = ResultWrite(
                instrument_id=inst.id,
                analysis_key=plan.analysis_key,
                scope=plan.scope,
                as_of_ts=self.now,
                status=AnalysisStatus.OK,
                result={"carried": True, "carried_from_result_id": fp.result_id},
                algo_version=ALGO_VERSION,
                params_id=params_id(plan.analysis_key),
                params_hash=eff_hash,
                timeframe=plan.timeframe,
                session_date=plan.session_date,
                snapshot_ts=plan.snapshot_ts,
                carried=True,
                carried_from_result_id=fp.result_id,
                input_window_end=last_bar.ts,
                summary={**fp.summary, "carried": True},
            )
            rid = self.results.upsert_result(run_id, write)
            self.projections.upsert_current_analysis(write, rid)
            return True
        return False

    # -- persistence --------------------------------------------------
    def _persist(
        self,
        run_id: int,
        inst: InstrumentView,
        plan: PlannedAnalysis,
        scope_key: str,
        res: AnalysisResult,
        *,
        bars_used: int | None,
        coverage: float | None,
    ) -> None:
        meta = res.meta
        write = ResultWrite(
            instrument_id=inst.id,
            analysis_key=plan.analysis_key,
            scope=plan.scope,
            as_of_ts=res.as_of_ts,
            status=res.status,
            result={
                "values": res.values,
                "aux": res.aux,
                "series": res.series,
                "warnings": list(res.warnings),
                "meta": meta,
            },
            algo_version=meta.get("algo_version", ALGO_VERSION),
            params_id=meta.get("params_id", params_id(plan.analysis_key)),
            params_hash=(
                meta.get("params_hash", params_hash(effective_params(plan.analysis_key)))
                if plan.analysis_key in _LOAD_LIMIT
                else meta.get("params_hash", "")
            ),
            timeframe=plan.timeframe,
            session_date=plan.session_date,
            snapshot_ts=plan.snapshot_ts,
            input_window_start=_parse(meta.get("input_window_start")),
            input_window_end=_parse(meta.get("input_window_end")),
            bars_used=bars_used if bars_used is not None else meta.get("bars_used"),
            coverage_ratio=coverage if coverage is not None else meta.get("coverage_ratio"),
            summary={"values": res.values, "aux": res.aux},
        )
        rid = self.results.upsert_result(run_id, write)
        self.projections.upsert_current_analysis(write, rid)


# ======================================================================================
# helpers
# ======================================================================================


class _FakeBar:
    __slots__ = ("ts", "is_final")

    def __init__(self, ts: datetime, is_final: bool) -> None:
        self.ts = ts
        self.is_final = is_final


def _dispatch(key: str, series: OHLCVSeries, inst: InstrumentView) -> AnalysisResult:
    if key == "rsi":
        return rsi(series)
    if key == "bollinger":
        return bollinger(series)
    if key == "ema7":
        return ema7(series)
    if key == "golden_cross":
        return golden_cross(series, instrument_type=inst.instrument_type)
    if key == "volume":
        return volume(series, has_volume=inst.has_volume)
    if key == "order_block":
        return order_block(series)
    if key == "candles":
        return candles(series)
    raise KeyError(key)  # pragma: no cover


def _ohlcv_series(bars, timeframe: Timeframe) -> OHLCVSeries:
    return OHLCVSeries(
        timeframe=timeframe,
        ts=tuple(b.ts.astimezone(UTC) for b in bars),
        open=tuple(float(b.open) for b in bars),
        high=tuple(float(b.high) for b in bars),
        low=tuple(float(b.low) for b in bars),
        close=tuple(float(b.close) for b in bars),
        volume=tuple(int(b.volume) for b in bars),
        is_final=tuple(bool(b.is_final) for b in bars),
        expected_grid_len=len(bars),  # Phase 3: session-anchored denominator TBD
    )


def _oi_daily_points(oi_rows, d1_bars):
    """Collapse M1 OI to one point per IST trading date (last value), paired with
    that date's D1 close as the instrument's own price series."""
    from zoneinfo import ZoneInfo

    ist = ZoneInfo("Asia/Kolkata")
    by_date: dict[date, tuple[int, int | None, bool]] = {}
    for r in oi_rows:
        d = r.ts.astimezone(ist).date()
        by_date[d] = (r.oi, r.provider_oi_change, bool(r.is_final))  # last wins (ascending)
    close_by_date = {b.ts.astimezone(ist).date(): float(b.close) for b in d1_bars}
    out = []
    for d in sorted(by_date):
        if d not in close_by_date:
            continue
        oi, poc, isf = by_date[d]
        out.append(
            (
                datetime.combine(d, datetime.min.time(), tzinfo=ZoneInfo("UTC")),
                oi,
                close_by_date[d],
                poc if poc is not None else 0,
                isf,
            )
        )
    return out


def _scope_key(plan: PlannedAnalysis) -> str:
    if plan.scope is AnalysisScope.PER_TIMEFRAME:
        return f"PER_TIMEFRAME:{plan.timeframe.value}"  # type: ignore[union-attr]
    if plan.scope is AnalysisScope.SESSION:
        return f"SESSION:{plan.session_date}"
    return f"SNAPSHOT:{plan.snapshot_ts.isoformat()}"  # type: ignore[union-attr]


def _insufficient(key: str, scope: AnalysisScope, as_of: datetime, reason: str) -> AnalysisResult:
    from analytical_core.indicators._common import insufficient as _ins

    return _ins(analysis_key=key, scope=scope, as_of_ts=as_of, reason=reason)


def _parse(v: str | None) -> datetime | None:
    return datetime.fromisoformat(v) if v else None


def _roll_up(outcome: PhaseOutcome) -> PhaseStatus:
    vals = set(outcome.instrument_outcomes.values())
    if not vals or vals == {InstrumentPhaseOutcome.OK}:
        return PhaseStatus.SUCCEEDED
    if vals == {InstrumentPhaseOutcome.SKIPPED}:
        return PhaseStatus.SKIPPED
    return PhaseStatus.PARTIAL
