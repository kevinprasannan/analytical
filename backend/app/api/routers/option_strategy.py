"""OI-based option-strategy suggestions (docs/07 §4.13, docs/05 §11.5).

``GET /instruments/{underlying_id}/option-strategies`` — reads the option
chain's per-strike OI / ΔOI / LTP, classifies the positioning into a market
view, and returns candidate option structures (iron condor / fly, strangles,
verticals, 1×2 ratio spreads) with per-leg BUY/SELL + quantity.

**Owner-authorised 2026-09-03 — a bounded revision of decision 15 / hard rule 7.**
Every payload carries ``disclaimer``: illustrative analytical output derived
from open interest, not investment advice, not a recommendation, not an order.
Computed on read; not persisted.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from analytical_core.options.strategy import strategy_book_to_dict
from app.api import services
from app.api.deps import get_db
from app.api.errors import not_found
from app.api.schemas.option_strategy import OptionStrategyResponse

router = APIRouter(prefix="/api/v1", tags=["option-strategy"])


@router.get(
    "/instruments/{underlying_id}/option-strategies",
    response_model=OptionStrategyResponse,
)
def option_strategies(
    underlying_id: int,
    expiry: date | None = None,
    wing_points: float | None = Query(
        None, gt=0, description="wing width in index points (else strike-steps)"
    ),
    calendars: bool = Query(True, description="load a later expiry so calendars can be offered"),
    db: Session = Depends(get_db),
) -> OptionStrategyResponse:
    if services.get_instrument(db, underlying_id) is None:
        raise not_found("instrument")
    book = services.option_strategies(
        db, underlying_id, expiry=expiry, wing_points=wing_points, calendars=calendars
    )
    if book is None:
        raise not_found("option strategies (no option instruments / no spot / unknown expiry)")
    return OptionStrategyResponse.model_validate(strategy_book_to_dict(book))
