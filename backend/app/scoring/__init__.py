"""SCORE phase — real ``weighted_v1`` scoring (Phase: Scoring, docs/06).

Per (eligible instrument, user-facing timeframe): gather the same-run analyses
(carries followed), build a ``ScoringInput`` with ``expected_analyses`` as data,
call the pure engine, persist ``signal_scores`` + ``score_factors``, and update
``current_signal_scores`` with ``delta_vs_previous``.

Analytical labels only — never BUY/SELL (docs/06 §1).
"""

from __future__ import annotations

from datetime import UTC, datetime

from analytical_core.enums import (
    USER_FACING_TIMEFRAMES,
    AnalysisScope,
    InstrumentPhaseOutcome,
    PhaseStatus,
    RunPhase,
    SignalLabel,
    Timeframe,
)
from analytical_core.scoring import (
    FactorInput,
    InstrumentRef,
    ScoringConfig,
    ScoringInput,
    default_config,
    expected_analyses,
    score,
)
from app.db.repositories.protocols import (
    AnalysisResultRepository,
    FactorWrite,
    InstrumentView,
    ProjectionRepository,
    RunAnalysisRow,
    ScoreRepository,
    ScoreWrite,
)
from app.pipeline import PhaseOutcome

_SESSION_OR_SNAPSHOT_KEYS = {"market_profile", "open_interest"}


class ScoringService:
    def __init__(
        self,
        scores: ScoreRepository,
        projections: ProjectionRepository,
        analysis_results: AnalysisResultRepository | None = None,
        *,
        config: ScoringConfig | None = None,
        now: datetime | None = None,
    ) -> None:
        self.scores = scores
        self.projections = projections
        self.analysis_results = analysis_results
        self.config = config or default_config()
        self.now = now or datetime.now(tz=UTC)

    def run(
        self, run_id: int, instruments: list[InstrumentView], eligible: set[int]
    ) -> PhaseOutcome:
        outcome = PhaseOutcome(phase=RunPhase.SCORE, status=PhaseStatus.RUNNING)

        for inst in instruments:
            if inst.id not in eligible:
                outcome.record(inst.id, InstrumentPhaseOutcome.SKIPPED)
                continue
            try:
                rows = (
                    self.analysis_results.list_run_results(run_id, inst.id)
                    if self.analysis_results is not None
                    else []
                )
                for tf in USER_FACING_TIMEFRAMES:
                    self._score_one(run_id, inst, tf, rows)
                outcome.record(inst.id, InstrumentPhaseOutcome.OK)
            except Exception as exc:  # per-instrument resilience
                outcome.record(inst.id, InstrumentPhaseOutcome.ERROR)
                outcome.detail.setdefault("errors", {})[str(inst.id)] = repr(exc)

        outcome.status = _roll_up(outcome)
        return outcome

    def _score_one(
        self,
        run_id: int,
        inst: InstrumentView,
        tf: Timeframe,
        rows: list[RunAnalysisRow],
    ) -> None:
        factors = tuple(
            FactorInput(
                analysis_key=r.analysis_key,
                scope=r.scope,
                status=r.status,
                values=r.values,
                aux=r.aux,
                meta=r.meta,
            )
            for r in rows
            if (r.scope is AnalysisScope.PER_TIMEFRAME and r.timeframe is tf)
            or r.analysis_key in _SESSION_OR_SNAPSHOT_KEYS
        )
        result_id_by_key = {r.analysis_key: r.result_id for r in rows}

        inp = ScoringInput(
            instrument=InstrumentRef(
                instrument_id=inst.id,
                instrument_type=inst.instrument_type,
                expected_analyses=expected_analyses(
                    inst.instrument_type, has_volume=inst.has_volume
                ),
            ),
            timeframe=tf.value,
            as_of_ts=self.now,
            factors=factors,
        )
        cr = score(inp, self.config)

        write = ScoreWrite(
            instrument_id=inst.id,
            timeframe=tf,
            as_of_ts=self.now,
            composite_score=cr.composite_score,
            raw_label=SignalLabel(cr.raw_label),
            effective_label=SignalLabel(cr.effective_label),
            confidence=cr.confidence,
            low_confidence=cr.low_confidence,
            strategy=cr.strategy,
            scoring_version=cr.scoring_version,
            params_hash=cr.params_hash,
            weights=cr.weights,
            denom=cr.denom,
            warnings=list(cr.warnings),
            explanation=cr.explanation,
            factors=tuple(
                FactorWrite(
                    analysis_key=f.analysis_key,
                    scope=f.scope,
                    sub_score=f.sub_score,
                    confidence=f.confidence,
                    weight=f.weight,
                    contribution=f.contribution,
                    reason=f.reason,
                    raw_values=f.raw_values,
                    rationale=f.rationale,
                    analysis_result_id=result_id_by_key.get(f.analysis_key),
                )
                for f in cr.factors
            ),
        )
        prev = self.scores.previous_composite(inst.id, tf, run_id)
        delta = None if prev is None else round(write.composite_score - prev, 6)
        sid = self.scores.upsert_score(run_id, write)
        self.projections.upsert_current_score(write, sid, run_id, delta)


def _roll_up(outcome: PhaseOutcome) -> PhaseStatus:
    vals = set(outcome.instrument_outcomes.values())
    if not vals or vals == {InstrumentPhaseOutcome.OK}:
        return PhaseStatus.SUCCEEDED
    if vals == {InstrumentPhaseOutcome.SKIPPED}:
        return PhaseStatus.SKIPPED
    return PhaseStatus.PARTIAL
