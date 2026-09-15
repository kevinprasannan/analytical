"""PostgreSQL-backed repositories (used with a live DB / ``@pytest.mark.db``)."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from analytical_core.enums import (
    AnalysisScope,
    RunStatus,
    Timeframe,
)
from app.db import models as m
from app.db.repositories.protocols import (
    InstrumentView,
    Repositories,
    ResultWrite,
    ScoreWrite,
)


class SaRunRepository:
    def __init__(self, session: Session) -> None:
        self.db = session

    def next_cycle_seq(self) -> int:
        current = self.db.execute(select(func.max(m.AnalysisRun.cycle_seq))).scalar()
        return int(current or 0) + 1

    def create_run(self, **kw) -> int:
        row = m.AnalysisRun(status=RunStatus.RUNNING, **kw)
        self.db.add(row)
        self.db.flush()
        return int(row.id)

    def set_phase_status(
        self, run_id, phase, status, *, counts, started_at, finished_at, detail=None
    ) -> None:
        stmt = pg_insert(m.RunPhaseStatus).values(
            run_id=run_id,
            phase=phase,
            status=status,
            counts=counts,
            started_at=started_at,
            finished_at=finished_at,
            detail=detail or {},
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["run_id", "phase"],
            set_={
                "status": stmt.excluded.status,
                "counts": stmt.excluded.counts,
                "started_at": stmt.excluded.started_at,
                "finished_at": stmt.excluded.finished_at,
                "detail": stmt.excluded.detail,
            },
        )
        self.db.execute(stmt)

    def set_instrument_status(self, run_id, instrument_id, phase, outcome, detail=None) -> None:
        stmt = pg_insert(m.RunInstrumentStatus).values(
            run_id=run_id,
            instrument_id=instrument_id,
            phase=phase,
            outcome=outcome,
            detail=detail or {},
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["run_id", "instrument_id", "phase"],
            set_={"outcome": stmt.excluded.outcome, "detail": stmt.excluded.detail},
        )
        self.db.execute(stmt)

    def finalize_run(self, run_id, status, finished_at) -> None:
        run = self.db.get(m.AnalysisRun, run_id)
        run.status = status
        run.finished_at = finished_at

    def get_run_status(self, run_id) -> RunStatus:
        return self.db.get(m.AnalysisRun, run_id).status

    def count_runs(self) -> int:
        return int(self.db.execute(select(func.count()).select_from(m.AnalysisRun)).scalar() or 0)


class SaInstrumentRepository:
    def __init__(self, session: Session) -> None:
        self.db = session

    def list_tracked(self) -> list[InstrumentView]:
        j = (
            select(m.Instrument, m.ProviderInstrumentMap.provider_symbol)
            .join(
                m.ProviderInstrumentMap,
                m.ProviderInstrumentMap.instrument_id == m.Instrument.id,
            )
            .where(m.Instrument.is_tracked.is_(True))
            .where(m.ProviderInstrumentMap.is_active.is_(True))
            .order_by(m.Instrument.id)
        )
        out: list[InstrumentView] = []
        for inst, provider_symbol in self.db.execute(j).all():
            out.append(
                InstrumentView(
                    id=inst.id,
                    contract_key=inst.contract_key,
                    instrument_type=inst.instrument_type,
                    has_volume=inst.has_volume,
                    has_intraday_oi=inst.has_intraday_oi,
                    provider_symbol=provider_symbol,
                )
            )
        return out


class SaAnalysisResultRepository:
    def __init__(self, session: Session) -> None:
        self.db = session

    def upsert_result(self, run_id: int, w: ResultWrite) -> int:
        values = dict(
            run_id=run_id,
            instrument_id=w.instrument_id,
            analysis_key=w.analysis_key,
            scope=w.scope,
            timeframe=w.timeframe,
            session_date=w.session_date,
            snapshot_ts=w.snapshot_ts,
            scope_key=w.scope_key(),
            as_of_ts=w.as_of_ts,
            status=w.status,
            result=w.result,
            algo_version=w.algo_version,
            params_id=w.params_id,
            params_hash=w.params_hash,
            carried=w.carried,
            carried_from_result_id=w.carried_from_result_id,
            input_window_start=w.input_window_start,
            input_window_end=w.input_window_end,
            bars_used=w.bars_used,
            coverage_ratio=w.coverage_ratio,
        )
        stmt = pg_insert(m.AnalysisResultRow).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["run_id", "instrument_id", "analysis_key", "scope_key"],
            set_={k: getattr(stmt.excluded, k) for k in values if k != "run_id"},
        ).returning(m.AnalysisResultRow.id)
        return int(self.db.execute(stmt).scalar_one())

    def list_run_results(self, run_id, instrument_id):
        from app.db.repositories.protocols import RunAnalysisRow

        rows = self.db.execute(
            select(m.AnalysisResultRow).where(
                m.AnalysisResultRow.run_id == run_id,
                m.AnalysisResultRow.instrument_id == instrument_id,
            )
        ).scalars()
        out: list[RunAnalysisRow] = []
        for r in rows:
            payload = r.result or {}
            if r.carried and r.carried_from_result_id is not None:
                src = self.db.get(m.AnalysisResultRow, r.carried_from_result_id)
                payload = (src.result if src is not None else {}) or {}
            out.append(
                RunAnalysisRow(
                    result_id=r.id,
                    analysis_key=r.analysis_key,
                    scope=r.scope,
                    timeframe=r.timeframe,
                    status=r.status,
                    values=payload.get("values", {}) or {},
                    aux=payload.get("aux", {}) or {},
                    meta=payload.get("meta", {}) or {},
                    warnings=list(payload.get("warnings", []) or []),
                )
            )
        return out

    def last_fingerprint(self, instrument_id, analysis_key, scope_key):
        from app.db.repositories.protocols import ResultFingerprint

        row = self.db.execute(
            select(
                m.AnalysisResultRow.id,
                m.AnalysisResultRow.input_window_end,
                m.AnalysisResultRow.params_hash,
                m.AnalysisResultRow.algo_version,
                m.AnalysisResultRow.result,
            )
            .where(
                m.AnalysisResultRow.instrument_id == instrument_id,
                m.AnalysisResultRow.analysis_key == analysis_key,
                m.AnalysisResultRow.scope_key == scope_key,
            )
            .order_by(m.AnalysisResultRow.id.desc())
            .limit(1)
        ).one_or_none()
        if row is None:
            return None
        root_id, root_result = int(row.id), row.result or {}
        seen = {root_id}
        while root_result.get("carried") and root_result.get("carried_from_result_id"):
            nxt = int(root_result["carried_from_result_id"])
            if nxt in seen:
                break
            seen.add(nxt)
            got = self.db.execute(
                select(m.AnalysisResultRow.id, m.AnalysisResultRow.result).where(
                    m.AnalysisResultRow.id == nxt
                )
            ).one_or_none()
            if got is None:
                break
            root_id, root_result = int(got.id), got.result or {}
        meta = root_result.get("meta", {})
        return ResultFingerprint(
            result_id=root_id,
            input_window_end=row.input_window_end,
            params_hash=row.params_hash,
            algo_version=row.algo_version,
            last_bar_final=bool(meta.get("last_bar_final", True)),
            summary={"values": root_result.get("values", {}), "aux": root_result.get("aux", {})},
        )


class SaScoreRepository:
    def __init__(self, session: Session) -> None:
        self.db = session

    def previous_composite(self, instrument_id, timeframe, before_run_id) -> float | None:
        stmt = (
            select(m.SignalScore.composite_score)
            .where(m.SignalScore.instrument_id == instrument_id)
            .where(m.SignalScore.timeframe == timeframe)
            .where(m.SignalScore.run_id < before_run_id)
            .order_by(m.SignalScore.run_id.desc())
            .limit(1)
        )
        val = self.db.execute(stmt).scalar()
        return float(val) if val is not None else None

    def upsert_score(self, run_id: int, w: ScoreWrite) -> int:
        row = m.SignalScore(
            run_id=run_id,
            instrument_id=w.instrument_id,
            timeframe=w.timeframe,
            as_of_ts=w.as_of_ts,
            composite_score=w.composite_score,
            raw_label=w.raw_label,
            effective_label=w.effective_label,
            confidence=w.confidence,
            low_confidence=w.low_confidence,
            strategy=w.strategy,
            scoring_version=w.scoring_version,
            params_hash=w.params_hash,
            weights=w.weights,
            denom=w.denom,
            warnings=list(w.warnings),
            explanation=w.explanation,
        )
        self.db.add(row)
        self.db.flush()
        for f in w.factors:
            self.db.add(
                m.ScoreFactor(
                    signal_score_id=row.id,
                    analysis_result_id=f.analysis_result_id,
                    analysis_key=f.analysis_key,
                    scope=f.scope,
                    raw_values=f.raw_values,
                    sub_score=f.sub_score,
                    confidence=f.confidence,
                    weight=f.weight,
                    contribution=f.contribution,
                    reason=f.reason,
                    rationale=f.rationale,
                )
            )
        return int(row.id)


class SaProjectionRepository:
    def __init__(self, session: Session) -> None:
        self.db = session

    def upsert_current_analysis(self, w: ResultWrite, analysis_result_id: int) -> None:
        values = dict(
            instrument_id=w.instrument_id,
            analysis_key=w.analysis_key,
            scope_ref=w.scope_ref(),
            scope=w.scope,
            timeframe=w.timeframe,
            session_date=w.session_date,
            snapshot_ts=w.snapshot_ts,
            analysis_result_id=analysis_result_id,
            status=w.status,
            as_of_ts=w.as_of_ts,
            algo_version=w.algo_version,
            params_hash=w.params_hash,
            carried=w.carried,
            summary=w.summary,
        )
        stmt = pg_insert(m.CurrentAnalysisResult).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["instrument_id", "analysis_key", "scope_ref"],
            set_={
                k: getattr(stmt.excluded, k)
                for k in values
                if k not in ("instrument_id", "analysis_key", "scope_ref")
            },
        )
        self.db.execute(stmt)

    def upsert_current_score(self, w: ScoreWrite, signal_score_id, run_id, delta) -> None:
        values = dict(
            instrument_id=w.instrument_id,
            timeframe=w.timeframe,
            signal_score_id=signal_score_id,
            run_id=run_id,
            composite_score=w.composite_score,
            confidence=w.confidence,
            raw_label=w.raw_label,
            effective_label=w.effective_label,
            low_confidence=w.low_confidence,
            as_of_ts=w.as_of_ts,
            delta_vs_previous=delta,
            warnings=list(w.warnings),
        )
        stmt = pg_insert(m.CurrentSignalScore).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["instrument_id", "timeframe"],
            set_={
                k: getattr(stmt.excluded, k)
                for k in values
                if k not in ("instrument_id", "timeframe")
            },
        )
        self.db.execute(stmt)

    def rebuild_projections(self) -> None:
        self.db.execute(m.CurrentAnalysisResult.__table__.delete())
        self.db.execute(m.CurrentSignalScore.__table__.delete())
        # latest analysis_results per (instrument, analysis_key, scope_key)
        ar = m.AnalysisResultRow
        latest_ar = (
            select(ar)
            .order_by(
                ar.instrument_id, ar.analysis_key, ar.scope_key, ar.run_id.desc(), ar.id.desc()
            )
            .distinct(ar.instrument_id, ar.analysis_key, ar.scope_key)
        )
        for row in self.db.execute(latest_ar).scalars():
            scope_ref = (
                f"PER_TIMEFRAME:{row.timeframe.value}"
                if row.scope is AnalysisScope.PER_TIMEFRAME
                else row.scope.value
            )
            self.db.execute(
                pg_insert(m.CurrentAnalysisResult)
                .values(
                    instrument_id=row.instrument_id,
                    analysis_key=row.analysis_key,
                    scope_ref=scope_ref,
                    scope=row.scope,
                    timeframe=row.timeframe,
                    session_date=row.session_date,
                    snapshot_ts=row.snapshot_ts,
                    analysis_result_id=row.id,
                    status=row.status,
                    as_of_ts=row.as_of_ts,
                    algo_version=row.algo_version,
                    params_hash=row.params_hash,
                    carried=row.carried,
                    summary=row.result,
                )
                .on_conflict_do_nothing()
            )
        ss = m.SignalScore
        latest_ss = (
            select(ss)
            .order_by(ss.instrument_id, ss.timeframe, ss.run_id.desc(), ss.id.desc())
            .distinct(ss.instrument_id, ss.timeframe)
        )
        for row in self.db.execute(latest_ss).scalars():
            prev = self.previous_composite_value(row.instrument_id, row.timeframe, row.run_id)
            delta = None if prev is None else round(float(row.composite_score) - prev, 6)
            self.db.execute(
                pg_insert(m.CurrentSignalScore)
                .values(
                    instrument_id=row.instrument_id,
                    timeframe=row.timeframe,
                    signal_score_id=row.id,
                    run_id=row.run_id,
                    composite_score=row.composite_score,
                    confidence=row.confidence,
                    raw_label=row.raw_label,
                    effective_label=row.effective_label,
                    low_confidence=row.low_confidence,
                    as_of_ts=row.as_of_ts,
                    delta_vs_previous=delta,
                    warnings=row.warnings,
                )
                .on_conflict_do_nothing()
            )

    def previous_composite_value(
        self, instrument_id: int, timeframe: Timeframe, before_run_id: int
    ) -> float | None:
        val = self.db.execute(
            select(m.SignalScore.composite_score)
            .where(m.SignalScore.instrument_id == instrument_id)
            .where(m.SignalScore.timeframe == timeframe)
            .where(m.SignalScore.run_id < before_run_id)
            .order_by(m.SignalScore.run_id.desc())
            .limit(1)
        ).scalar()
        return float(val) if val is not None else None


def build_sqlalchemy_repositories(session: Session) -> Repositories:
    from app.db.repositories.market_data import SaMarketDataRepository
    from app.db.repositories.market_profile import SaMarketProfileRepository

    return Repositories(
        runs=SaRunRepository(session),
        instruments=SaInstrumentRepository(session),
        analysis_results=SaAnalysisResultRepository(session),
        scores=SaScoreRepository(session),
        projections=SaProjectionRepository(session),
        market_data=SaMarketDataRepository(session),
        market_profile=SaMarketProfileRepository(session),
    )
