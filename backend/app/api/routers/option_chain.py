"""Option chain (docs/07 §4.4, docs/05 §11).

``GET /instruments/{underlying_id}/option-chain`` — the strike ladder for one
expiry with LTP / OI / volume from ingested data and IV + greeks + PCR +
max-pain from ``analytical_core.options``. Computed on read; not persisted.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api import services
from app.api.deps import get_db
from app.api.errors import not_found
from app.api.schemas.option_chain import ChainLeg, ChainRow, OptionChainResponse

router = APIRouter(prefix="/api/v1", tags=["option-chain"])


@router.get("/instruments/{underlying_id}/option-chain", response_model=OptionChainResponse)
def option_chain(
    underlying_id: int,
    expiry: date | None = None,
    db: Session = Depends(get_db),
) -> OptionChainResponse:
    if services.get_instrument(db, underlying_id) is None:
        raise not_found("instrument")
    chain = services.option_chain(db, underlying_id, expiry=expiry)
    if chain is None:
        raise not_found("option chain (no option instruments / no spot / unknown expiry)")

    def _leg(leg) -> ChainLeg | None:
        return None if leg is None else ChainLeg(**asdict(leg))

    return OptionChainResponse(
        underlying_id=underlying_id,
        underlying_symbol=chain.underlying_symbol,
        spot=chain.spot,
        expiry=chain.expiry,
        expiries=[e.isoformat() for e in services.option_expiries(db, underlying_id)],
        days_to_expiry=chain.days_to_expiry,
        t_years=chain.t_years,
        risk_free_rate=chain.risk_free_rate,
        atm_strike=chain.atm_strike,
        pcr_oi=chain.pcr_oi,
        pcr_volume=chain.pcr_volume,
        max_pain_strike=chain.max_pain_strike,
        total_call_oi=chain.total_call_oi,
        total_put_oi=chain.total_put_oi,
        crowded_side=chain.crowded_side,
        crowded_call_strike=chain.crowded_call_strike,
        crowded_put_strike=chain.crowded_put_strike,
        crowded_call_frac=chain.crowded_call_frac,
        crowded_put_frac=chain.crowded_put_frac,
        algo_version=chain.algo_version,
        rows=[ChainRow(strike=r.strike, call=_leg(r.call), put=_leg(r.put)) for r in chain.rows],
    )
