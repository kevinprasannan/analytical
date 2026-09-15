"""Live quote response (docs/07 §4.10). REST snapshot — never an engine input."""

from __future__ import annotations

from pydantic import BaseModel


class QuoteGreeks(BaseModel):
    last_price: float | None = None
    iv: float | None = None  # annualised fraction (0.1523 == 15.23%)
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    oi: int | None = None
    volume: int | None = None


class InstrumentQuote(BaseModel):
    instrument_id: int
    contract_key: str
    provider: str
    provider_symbol: str
    last_price: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: int | None = None
    average_price: float | None = None
    oi: int | None = None
    net_change: float | None = None
    total_buy_qty: int | None = None
    total_sell_qty: int | None = None
    lower_circuit: float | None = None
    upper_circuit: float | None = None
    ts: str | None = None
    greeks: QuoteGreeks | None = None
