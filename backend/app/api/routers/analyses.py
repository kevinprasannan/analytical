"""Analyses (docs/07 §4.4). Hot list from ``current_analysis_results``;
series + runs from ``analysis_results``."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from analytical_core.enums import InstrumentType, Timeframe
from app.api import services
from app.api.deps import get_db
from app.api.errors import not_found
from app.api.schemas.analysis import AnalysisItem, InstrumentAnalyses
from app.api.schemas.common import Page
from app.api.schemas.market_profile import (
    MarketProfileResponse,
    MPEventsBlock,
    ProfileBins,
)

router = APIRouter(prefix="/api/v1", tags=["analyses"])


@router.get("/analyses", response_model=Page[AnalysisItem])
def list_analyses(
    db: Session = Depends(get_db),
    timeframe: Timeframe | None = None,
    instrument_type: InstrumentType | None = None,
    analysis_key: str | None = None,
    status: str | None = None,
    is_tracked: bool = True,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> Page[AnalysisItem]:
    items, total = services.list_current_analyses(
        db,
        timeframe=timeframe,
        instrument_type=instrument_type,
        analysis_key=analysis_key,
        status=status,
        is_tracked=is_tracked,
        limit=limit,
        offset=offset,
    )
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/instruments/{instrument_id}/analyses", response_model=InstrumentAnalyses)
def instrument_analyses(
    instrument_id: int, timeframe: Timeframe, db: Session = Depends(get_db)
) -> InstrumentAnalyses:
    if services.get_instrument(db, instrument_id) is None:
        raise not_found("instrument")
    return InstrumentAnalyses(
        instrument_id=instrument_id,
        timeframe=timeframe,
        items=services.instrument_analyses(db, instrument_id, timeframe),
    )


@router.get("/instruments/{instrument_id}/analyses/{analysis_key}", response_model=AnalysisItem)
def one_analysis(
    instrument_id: int,
    analysis_key: str,
    timeframe: Timeframe | None = None,
    db: Session = Depends(get_db),
) -> AnalysisItem:
    """``timeframe`` is required for a per-timeframe analysis (RSI, EMA, …) and
    ignored for a ``SESSION`` / ``SNAPSHOT`` one (market_profile, index
    open_interest)."""
    if services.get_instrument(db, instrument_id) is None:
        raise not_found("instrument")
    item = services.one_analysis(db, instrument_id, analysis_key, timeframe)
    if item is None:
        where = (
            f"at {timeframe.value}"
            if timeframe is not None
            else "(pass ?timeframe= for a per-timeframe analysis)"
        )
        raise not_found(f"analysis {analysis_key!r} {where}")
    return item


@router.get("/instruments/{instrument_id}/analyses/{analysis_key}/series")
def analysis_series(
    instrument_id: int,
    analysis_key: str,
    timeframe: Timeframe,
    db: Session = Depends(get_db),
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(500, ge=1, le=5000),
) -> dict[str, Any]:
    if services.get_instrument(db, instrument_id) is None:
        raise not_found("instrument")
    points = services.analysis_series(
        db, instrument_id, analysis_key, timeframe=timeframe, start=start, end=end, limit=limit
    )
    return {
        "instrument_id": instrument_id,
        "analysis_key": analysis_key,
        "timeframe": timeframe.value,
        "points": points,
    }


@router.get("/instruments/{instrument_id}/market-profile", response_model=MarketProfileResponse)
def market_profile(
    instrument_id: int,
    db: Session = Depends(get_db),
    session_date: str | None = None,
    profile_type: str | None = Query(None, pattern="^(TPO|VOLUME)$"),
) -> MarketProfileResponse:
    from datetime import date as _date

    if services.get_instrument(db, instrument_id) is None:
        raise not_found("instrument")
    sd = (
        _date.fromisoformat(session_date)
        if session_date
        else services.latest_market_profile_date(db, instrument_id)
    )
    if sd is None:
        raise not_found("market profile")
    got = services.market_profile_view(db, instrument_id, sd, profile_type)
    if got is None:
        raise not_found(f"market profile for {sd}")
    rows, close_vals = got
    tpo = next((r for r in rows if r.profile_type.value == "TPO"), rows[0])
    return MarketProfileResponse(
        instrument_id=instrument_id,
        session_date=sd,
        is_session_complete=tpo.is_session_complete,
        bin_size=float(tpo.bin_size) if tpo.bin_size is not None else None,
        poc=float(tpo.poc) if tpo.poc is not None else None,
        vah=float(tpo.vah) if tpo.vah is not None else None,
        val=float(tpo.val) if tpo.val is not None else None,
        ib_high=float(tpo.ib_high) if tpo.ib_high is not None else None,
        ib_low=float(tpo.ib_low) if tpo.ib_low is not None else None,
        session_high=float(tpo.session_high) if tpo.session_high is not None else None,
        session_low=float(tpo.session_low) if tpo.session_low is not None else None,
        profile_shape=tpo.profile_shape,
        close=close_vals.get("close"),
        close_vs_poc=close_vals.get("close_vs_poc"),
        close_vs_vah=close_vals.get("close_vs_vah"),
        close_vs_val=close_vals.get("close_vs_val"),
        close_in_value_area=close_vals.get("close_in_value_area"),
        profiles={
            r.profile_type.value: ProfileBins(bins=(r.bins or {}).get("bins", [])) for r in rows
        },
        events=MPEventsBlock.model_validate(tpo.events) if tpo.events else None,
    )


@router.get("/instruments/{instrument_id}/analyses/{analysis_key}/runs")
def analysis_runs(
    instrument_id: int,
    analysis_key: str,
    db: Session = Depends(get_db),
    scope: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
) -> dict[str, Any]:
    if services.get_instrument(db, instrument_id) is None:
        raise not_found("instrument")
    return {
        "instrument_id": instrument_id,
        "analysis_key": analysis_key,
        "runs": services.analysis_runs(db, instrument_id, analysis_key, scope=scope, limit=limit),
    }
