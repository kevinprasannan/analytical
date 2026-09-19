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
from app.api.schemas.oi_movers import OiLadderResponse, OiMoverLtpTraceResponse, OiMoversResponse

router = APIRouter(prefix="/api/v1", tags=["oi-movers"])

_MONEYNESS = {"DEEP_ITM", "ITM", "ATM", "OTM", "DEEP_OTM"}
_TIME_BANDS = (1, 3, 5, 10, 15)
_OPTION_TYPES = {"CE", "PE"}


@router.get("/instruments/{underlying_id}/oi-movers", response_model=OiMoversResponse)
def oi_movers(
    underlying_id: int,
    top: int = Query(15, ge=3, le=40, description="rows per list (added / reduced)"),
    time_band: int = Query(
        15, description="minutes for the 'Δ recent' column: 1 | 3 | 5 | 10 | 15"
    ),
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


@router.get(
    "/instruments/{underlying_id}/oi-movers/ltp-trace", response_model=OiMoverLtpTraceResponse
)
def oi_mover_ltp_trace(
    underlying_id: int,
    strike: float = Query(..., description="the option's strike price"),
    option_type: str = Query(..., description="CE | PE"),
    db: Session = Depends(get_db),
) -> OiMoverLtpTraceResponse:
    option_type = option_type.upper()
    if option_type not in _OPTION_TYPES:
        raise ApiError(422, "Unprocessable Entity", "option_type must be CE or PE")
    res = services.oi_mover_ltp_trace(db, underlying_id, strike=strike, option_type=option_type)
    if res is None:
        raise not_found("no matching option instrument for this strike / option_type / expiry")
    return OiMoverLtpTraceResponse.model_validate(res)


@router.get("/instruments/{underlying_id}/oi-ladder", response_model=OiLadderResponse)
def oi_ladder(
    underlying_id: int,
    marks: int = Query(3, ge=2, le=8, description="number of time columns"),
    step_min: int = Query(1, description="minutes between columns: 1 | 3 | 5 | 10 | 15"),
    window_up: int = Query(6, ge=0, le=50, description="strikes above ATM to include"),
    window_down: int = Query(6, ge=0, le=50, description="strikes below ATM to include"),
    db: Session = Depends(get_db),
) -> OiLadderResponse:
    if step_min not in _TIME_BANDS:
        raise ApiError(422, "Unprocessable Entity", f"step_min must be one of {list(_TIME_BANDS)}")
    res = services.oi_ladder(
        db,
        underlying_id,
        marks=marks,
        step_min=step_min,
        window_up=window_up,
        window_down=window_down,
    )
    if res is None:
        raise not_found("oi ladder (no option instruments / no spot for this underlying)")
    return OiLadderResponse.model_validate(res)
