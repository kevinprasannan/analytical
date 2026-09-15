"""Scores (docs/07 §4.5). Hot list from ``current_signal_scores``; history from
``signal_scores``. Analytical labels only — never BUY/SELL."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from analytical_core.enums import InstrumentType, Timeframe
from app.api import services
from app.api.deps import get_db
from app.api.errors import not_found
from app.api.schemas.common import Page
from app.api.schemas.scores import (
    ScoreDetail,
    ScoreFactorItem,
    ScoreHistory,
    ScoreHistoryPoint,
    ScoreListItem,
)

router = APIRouter(prefix="/api/v1", tags=["scores"])


@router.get("/scores", response_model=Page[ScoreListItem])
def list_scores(
    timeframe: Timeframe,
    db: Session = Depends(get_db),
    instrument_type: InstrumentType | None = None,
    label: str | None = None,
    min_confidence: float | None = Query(None, ge=0.0, le=1.0),
    sort: str = "-composite_score",
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> Page[ScoreListItem]:
    rows, total = services.list_current_scores(
        db,
        timeframe=timeframe,
        instrument_type=instrument_type,
        label=label,
        min_confidence=min_confidence,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    items = [
        ScoreListItem(
            instrument_id=s.instrument_id,
            contract_key=ck,
            symbol=sym,
            timeframe=s.timeframe,
            composite_score=float(s.composite_score),
            raw_label=s.raw_label,
            effective_label=s.effective_label,
            confidence=float(s.confidence),
            low_confidence=s.low_confidence,
            as_of_ts=s.as_of_ts,
            run_id=s.run_id,
            delta_vs_previous=(
                float(s.delta_vs_previous) if s.delta_vs_previous is not None else None
            ),
            warnings=list(s.warnings or []),
        )
        for s, ck, sym in rows
    ]
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/instruments/{instrument_id}/score", response_model=ScoreDetail)
def instrument_score(
    instrument_id: int, timeframe: Timeframe, db: Session = Depends(get_db)
) -> ScoreDetail:
    if services.get_instrument(db, instrument_id) is None:
        raise not_found("instrument")
    got = services.score_detail(db, instrument_id, timeframe)
    if got is None:
        raise not_found(f"score at {timeframe.value}")
    cur, row, factors = got
    return ScoreDetail(
        instrument_id=instrument_id,
        timeframe=timeframe,
        composite_score=float(cur.composite_score),
        raw_label=cur.raw_label,
        effective_label=cur.effective_label,
        confidence=float(cur.confidence),
        low_confidence=cur.low_confidence,
        as_of_ts=cur.as_of_ts,
        run_id=cur.run_id,
        strategy=row.strategy if row else "",
        scoring_version=row.scoring_version if row else "",
        params_hash=row.params_hash if row else "",
        weights={k: float(v) for k, v in (row.weights or {}).items()} if row else {},
        denom=float(row.denom) if row and row.denom is not None else None,
        delta_vs_previous=(
            float(cur.delta_vs_previous) if cur.delta_vs_previous is not None else None
        ),
        warnings=list((row.warnings if row else cur.warnings) or []),
        explanation=row.explanation if row else None,
        factors=[
            ScoreFactorItem(
                analysis_key=f.analysis_key,
                scope=f.scope,
                raw_values=f.raw_values or {},
                sub_score=float(f.sub_score),
                confidence=float(f.confidence),
                weight=float(f.weight),
                contribution=float(f.contribution),
                reason=f.reason,
                rationale=f.rationale or {},
            )
            for f in factors
        ],
    )


@router.get("/instruments/{instrument_id}/score/history", response_model=ScoreHistory)
def score_history(
    instrument_id: int,
    timeframe: Timeframe,
    db: Session = Depends(get_db),
    limit: int = Query(100, ge=1, le=1000),
) -> ScoreHistory:
    if services.get_instrument(db, instrument_id) is None:
        raise not_found("instrument")
    rows = services.score_history(db, instrument_id, timeframe, limit=limit)
    return ScoreHistory(
        instrument_id=instrument_id,
        timeframe=timeframe,
        points=[
            ScoreHistoryPoint(
                run_id=r.run_id,
                as_of_ts=r.as_of_ts,
                composite_score=float(r.composite_score),
                raw_label=r.raw_label,
                effective_label=r.effective_label,
                confidence=float(r.confidence),
                low_confidence=r.low_confidence,
            )
            for r in rows
        ],
    )
