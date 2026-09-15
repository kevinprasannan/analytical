"""Premium decay (docs/07 §4.23, docs/05 §11.6).

``GET /instruments/{underlying_id}/premium-decay`` — for one underlying's near
expiry, per strike the decay theta alone would predict since today's session
open, set against what the premium actually did. Computed on read from the
live option chain (IV/theta) + M1 premium bars; not persisted.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from analytical_core.options import premium_decay_to_dict
from app.api import services
from app.api.deps import get_db
from app.api.errors import not_found
from app.api.schemas.premium_decay import PremiumDecayResponse

router = APIRouter(prefix="/api/v1", tags=["premium-decay"])


@router.get("/instruments/{underlying_id}/premium-decay", response_model=PremiumDecayResponse)
def premium_decay(
    underlying_id: int,
    expiry: date | None = None,
    db: Session = Depends(get_db),
) -> PremiumDecayResponse:
    if services.get_instrument(db, underlying_id) is None:
        raise not_found("instrument")
    d = services.premium_decay(db, underlying_id, expiry=expiry)
    if d is None:
        raise not_found("premium decay (no option instruments / no spot / unknown expiry)")
    payload = premium_decay_to_dict(d)
    payload["underlying_id"] = underlying_id
    payload["expiries"] = [e.isoformat() for e in services.option_expiries(db, underlying_id)]
    return PremiumDecayResponse.model_validate(payload)
