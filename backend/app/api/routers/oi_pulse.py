"""OI pulse (docs/07 §4.11, docs/05 §11.4).

``GET /instruments/{underlying_id}/oi-pulse`` — trending open interest for one
expiry: the strike ladder with session / recent OI change and a positioning
label, PCR + max-pain now vs. at the open, the OI support / resistance walls, a
net option-writing bias, and a tabular session trace. Computed on read from this
session's per-minute OI + option M1 premium bars; not persisted.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from analytical_core.options import oi_pulse_to_dict
from app.api import services
from app.api.deps import get_db
from app.api.errors import not_found
from app.api.schemas.oi_pulse import OiPulseResponse

router = APIRouter(prefix="/api/v1", tags=["oi-pulse"])


@router.get("/instruments/{underlying_id}/oi-pulse", response_model=OiPulseResponse)
def oi_pulse(
    underlying_id: int,
    expiry: date | None = None,
    trace_up: int | None = Query(
        None, ge=0, le=50, description="session trace: keep N strikes above ATM (default: all)"
    ),
    trace_down: int | None = Query(
        None, ge=0, le=50, description="session trace: keep N strikes below ATM (default: all)"
    ),
    db: Session = Depends(get_db),
) -> OiPulseResponse:
    if services.get_instrument(db, underlying_id) is None:
        raise not_found("instrument")
    pulse = services.oi_pulse(
        db, underlying_id, expiry=expiry, trace_up=trace_up, trace_down=trace_down
    )
    if pulse is None:
        raise not_found("oi pulse (no option instruments / no spot / unknown expiry)")
    payload = oi_pulse_to_dict(pulse)
    payload["underlying_id"] = underlying_id
    payload["expiries"] = [e.isoformat() for e in services.option_expiries(db, underlying_id)]
    return OiPulseResponse.model_validate(payload)
