"""Top-N constituents — levels + indicators (docs/07 §4.20, docs/15).

``GET /instruments/{index_id}/constituents/levels`` — for the top-``n`` index
members by weight: prev-day CPR / pivots, the 52-week range, RSI (D1 + H1),
Bollinger (D1) and the MA trend. Every candle fetched live from the provider on
read (constituents are not tracked / not ingested) — heavy, cache it. INDEX
only. Descriptive — no signal, no BUY/SELL.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api import services
from app.api.deps import get_db
from app.api.errors import not_found
from app.api.schemas.constituent_levels import ConstituentLevelsResponse

router = APIRouter(prefix="/api/v1", tags=["constituents"])


@router.get(
    "/instruments/{index_id}/constituents/levels",
    response_model=ConstituentLevelsResponse,
)
def constituent_levels(
    index_id: int,
    n: int = Query(10, ge=1, le=20, description="top-N members by weight"),
    db: Session = Depends(get_db),
) -> ConstituentLevelsResponse:
    res = services.constituent_levels(db, index_id, n=n)
    if res is None:
        raise not_found("INDEX instrument with seeded weights")
    return ConstituentLevelsResponse.model_validate(res)
