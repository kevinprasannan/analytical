"""Gap-fade streak study (docs/07 §4.26, docs/05 §9f).

``GET /instruments/{id}/gap-fade-study`` — for every historical day that
gaps one way but closes the other (both reversal directions: gap-up-then-
close-down, and its mirror gap-down-then-close-up), the resulting streak
length, the consolidation box that followed, and which way it eventually
broke. Not a backtest (no entry/exit/target/stop) — a descriptive historical
study. Pure math (`analytical_core.gap_fade_study`), computed on read, not
persisted, not scored. Descriptive — no signal, no BUY/SELL.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api import services
from app.api.deps import get_db
from app.api.errors import not_found
from app.api.schemas.gap_fade_study import GapFadeStudyResponse

router = APIRouter(prefix="/api/v1", tags=["gap-fade-study"])


@router.get("/instruments/{instrument_id}/gap-fade-study", response_model=GapFadeStudyResponse)
def gap_fade_study(
    instrument_id: int,
    gap_up_min_pct: float = Query(0.5, description='gap_pct >= this counts as "gapped up"'),
    chg_down_max_pct: float = Query(-0.5, description='change_pct <= this counts as "closed down"'),
    gap_down_max_pct: float = Query(-0.5, description='gap_pct <= this counts as "gapped down"'),
    chg_up_min_pct: float = Query(0.5, description='change_pct >= this counts as "closed up"'),
    box_days: int = Query(3, ge=1, le=20, description="days after the streak that set the box"),
    breakout_buffer_pct: float = Query(0.3, ge=0, description="% the close must clear the box by"),
    max_breakout_search_days: int = Query(90, ge=5, le=400),
    db: Session = Depends(get_db),
) -> GapFadeStudyResponse:
    res = services.gap_fade_study(
        db,
        instrument_id,
        gap_up_min_pct=gap_up_min_pct,
        chg_down_max_pct=chg_down_max_pct,
        gap_down_max_pct=gap_down_max_pct,
        chg_up_min_pct=chg_up_min_pct,
        box_days=box_days,
        breakout_buffer_pct=breakout_buffer_pct,
        max_breakout_search_days=max_breakout_search_days,
    )
    if res is None:
        raise not_found("instrument")
    return GapFadeStudyResponse.model_validate(res)
