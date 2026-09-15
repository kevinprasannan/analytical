"""Option-chain response (docs/07 §4.4, docs/05 §11). Table only — no charts."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChainLeg(BaseModel):
    strike: float
    option_type: str
    ltp: float | None = None
    oi: int | None = None
    oi_change: int | None = None
    volume: int | None = None
    day_open: float | None = None  # this contract's O/H/L/C for the trading day
    day_high: float | None = None
    day_low: float | None = None
    day_close: float | None = None
    open_at_high: bool = False  # premium opened at the session high (topped at the bell)
    open_at_low: bool = False  # premium opened at the session low (bottomed at the bell)
    oi_change_pct: float | None = None  # ΔOI as a fraction of opening OI (0.42 == +42%)
    crowded: bool = False  # this strike carries an outsized share of its side's fresh OI
    iv: float | None = None  # annualised fraction (0.1523 == 15.23%)
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None  # per calendar day
    vega: float | None = None  # per 1% vol


class ChainRow(BaseModel):
    strike: float
    call: ChainLeg | None = None
    put: ChainLeg | None = None


class OptionChainResponse(BaseModel):
    underlying_id: int
    underlying_symbol: str
    spot: float
    expiry: str
    expiries: list[str] = Field(default_factory=list)
    days_to_expiry: int
    t_years: float
    risk_free_rate: float
    atm_strike: float | None = None
    pcr_oi: float | None = None
    pcr_volume: float | None = None
    max_pain_strike: float | None = None
    total_call_oi: int
    total_put_oi: int
    crowded_side: str = "BALANCED"  # CALLS | PUTS | BALANCED — side drawing the fresh OI
    crowded_call_strike: float | None = None
    crowded_put_strike: float | None = None
    crowded_call_frac: float | None = None
    crowded_put_frac: float | None = None
    algo_version: str
    rows: list[ChainRow] = Field(default_factory=list)
