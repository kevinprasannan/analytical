"""Big OI movement — options only (docs/07 §4.22, docs/05 §11.4).

``GET /instruments/{underlying_id}/oi-movers`` — the near-expiry option strikes
that added / reduced the most open interest today, each with session ΔOI, the
last-15-min ΔOI, and a buildup label. Built on the OI-pulse ladder; computed on
read, not persisted. Positioning labels only — no BUY/SELL.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api import services
from app.api.deps import get_db
from app.api.errors import ApiError, not_found
from app.api.schemas.oi_movers import OiMoversResponse

router = APIRouter(prefix="/api/v1", tags=["oi-movers"])

_MONEYNESS = {"DEEP_ITM", "ITM", "ATM", "OTM", "DEEP_OTM"}
_TIME_BANDS = (3, 5, 10, 15)


@router.get("/instruments/{underlying_id}/oi-movers", response_model=OiMoversResponse)
def oi_movers(
    underlying_id: int,
    top: int = Query(15, ge=3, le=40, description="rows per list (added / reduced)"),
    time_band: int = Query(15, description="minutes for the 'Δ recent' column: 3 | 5 | 10 | 15"),
    moneyness: list[str] = Query(
        default=[],
        description="restrict to buckets: DEEP_ITM / ITM / ATM / OTM / DEEP_OTM (repeatable)",
    ),
    db: Session = Depends(get_db),
) -> OiMoversResponse:
    if time_band not in _TIME_BANDS:
        raise ApiError(422, "Unprocessable Entity", f"time_band must be one of {list(_TIME_BANDS)}")
    mny = {x.upper() for x in moneyness}
    if mny - _MONEYNESS:
        raise ApiError(
            422, "Unprocessable Entity", f"moneyness must be one of {sorted(_MONEYNESS)}"
        )
    res = services.oi_movers(
        db, underlying_id, top=top, recent_window_min=int(time_band), moneyness=mny or None
    )
    if res is None:
        raise not_found("oi movers (no option instruments / no spot for this underlying)")
    return OiMoversResponse.model_validate(res)
