"""Live instrument quote (docs/07 §4.10).

``GET /instruments/{id}/quote`` — a REST snapshot from the active provider: full
market quote (LTP, OHLC, volume, OI, circuit limits) plus live option greeks for
an OPTION. Read-only; not persisted; never an engine input.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api import services
from app.api.deps import get_db
from app.api.errors import ApiError, not_found
from app.api.schemas.quote import InstrumentQuote, QuoteGreeks
from app.providers.base import ProviderAuthError, ProviderError

router = APIRouter(prefix="/api/v1", tags=["quote"])


def _f(v: Decimal | float | None) -> float | None:
    return None if v is None else float(v)


@router.get("/instruments/{instrument_id}/quote", response_model=InstrumentQuote)
def instrument_quote(instrument_id: int, db: Session = Depends(get_db)) -> InstrumentQuote:
    try:
        q = services.instrument_quote(db, instrument_id)
    except ProviderAuthError as exc:
        raise ApiError(503, "Provider Unauthenticated", f"provider auth failed: {exc}") from exc
    except ProviderError as exc:
        raise ApiError(502, "Provider Error", f"provider quote call failed: {exc}") from exc
    if q is None:
        raise not_found("instrument or its active provider mapping")

    full = q["full"]
    g = q["greeks"]
    return InstrumentQuote(
        instrument_id=q["instrument_id"],
        contract_key=q["contract_key"],
        provider=q["provider"],
        provider_symbol=q["provider_symbol"],
        last_price=_f(getattr(full, "last_price", None)),
        open=_f(getattr(full, "open", None)),
        high=_f(getattr(full, "high", None)),
        low=_f(getattr(full, "low", None)),
        close=_f(getattr(full, "close", None)),
        volume=getattr(full, "day_volume", None),
        average_price=_f(getattr(full, "average_price", None)),
        oi=getattr(full, "oi", None),
        net_change=_f(getattr(full, "net_change", None)),
        total_buy_qty=getattr(full, "total_buy_qty", None),
        total_sell_qty=getattr(full, "total_sell_qty", None),
        lower_circuit=_f(getattr(full, "lower_circuit", None)),
        upper_circuit=_f(getattr(full, "upper_circuit", None)),
        ts=getattr(full, "ts", None).isoformat() if getattr(full, "ts", None) else None,
        greeks=(
            None
            if g is None
            else QuoteGreeks(
                last_price=_f(g.last_price),
                iv=g.iv,
                delta=g.delta,
                gamma=g.gamma,
                theta=g.theta,
                vega=g.vega,
                oi=g.oi,
                volume=g.day_volume,
            )
        ),
    )
