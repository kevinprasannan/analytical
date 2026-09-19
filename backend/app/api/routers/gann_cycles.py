"""Gann time cycles (docs/07 §4.25, docs/05 §9e).

``GET /instruments/{id}/gann-cycles`` — day-count projections from the
previous swing low/high, plus confluence clusters. Pure math
(`analytical_core.gann_cycles`), computed on read, not persisted, not scored.
Descriptive — no signal, no BUY/SELL.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api import services
from app.api.deps import get_db
from app.api.errors import not_found
from app.api.schemas.gann_cycles import GannCyclesResponse

router = APIRouter(prefix="/api/v1", tags=["gann-cycles"])


@router.get("/instruments/{instrument_id}/gann-cycles", response_model=GannCyclesResponse)
def gann_cycles(instrument_id: int, db: Session = Depends(get_db)) -> GannCyclesResponse:
    res = services.gann_cycles(db, instrument_id)
    if res is None:
        raise not_found("instrument")
    return GannCyclesResponse.model_validate(res)
