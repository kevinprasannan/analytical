"""OI-based option-strategy suggestions (docs/07 §4.13, docs/05 §11.5).

Owner-authorised 2026-09-03 — a bounded revision of decision 15 / hard rule 7:
this resource (and only this one) returns option structures with per-leg
``BUY`` / ``SELL`` actions and quantity ratios. Every payload carries
``disclaimer`` — illustrative analytical output derived from open interest,
**not** investment advice, **not** a recommendation, **not** an order.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class StrategyLeg(BaseModel):
    action: str  # BUY | SELL
    lots: int  # relative quantity (the ratio)
    option_type: str  # CE | PE
    strike: float
    role: str  # short_body | long_wing | long_leg | short_leg
    ltp: float | None = None
    oi: int | None = None
    oi_change: int | None = None
    expiry: str | None = None  # ISO date; None => the book's near expiry (calendars)


class StrategySuggestion(BaseModel):
    name: str
    family: str  # CONDOR_FLY | STRANGLE_STRADDLE | VERTICAL | RATIO | CALENDAR
    view: str
    direction_bias: str  # NEUTRAL | BULLISH | BEARISH
    risk: str  # DEFINED | UNDEFINED
    net: str  # CREDIT | DEBIT | UNKNOWN
    legs: list[StrategyLeg] = Field(default_factory=list)
    est_net_premium: float | None = None  # + credit / − debit, index points, 1× set
    breakevens: list[float] = Field(default_factory=list)
    lower_breakeven: float | None = None
    upper_breakeven: float | None = None
    spot_inside_breakevens: bool | None = None
    max_profit: float | None = None
    max_loss: float | None = None
    reward_risk: float | None = None  # max_profit / |max_loss|
    pop: float | None = None  # probability of profit at expiry (lognormal, ATM IV)
    pop_basis: str = "NONE"  # LOGNORMAL_IV | LOGNORMAL_NEAR_RANGE | NONE
    edge_score: float | None = None  # pop × reward_risk — ranking key
    high_pop: bool = False
    rationale: str
    caveats: list[str] = Field(default_factory=list)


class MarketView(BaseModel):
    # RANGEBOUND | LEAN_BULLISH | LEAN_BEARISH | TREND_BULLISH | TREND_BEARISH | VOL_EXPANSION
    label: str
    confidence: float  # 0..1
    evidence: list[str] = Field(default_factory=list)
    spot: float
    atm_strike: float
    step: float
    support_wall: float | None = None
    resistance_wall: float | None = None
    max_pain: float | None = None
    pcr_oi: float | None = None
    net_ce_oi_change: int
    net_pe_oi_change: int
    crowded_side: str
    days_to_expiry: int


class OptionStrategyResponse(BaseModel):
    underlying_symbol: str
    spot: float
    expiry: str  # ISO date
    days_to_expiry: int
    view: MarketView
    suggestions: list[StrategySuggestion] = Field(default_factory=list)
    atm_iv: float | None = None  # the vol the lognormal PoP used
    far_expiry: str | None = None  # second expiry loaded for calendars, if any
    ranked_by: str = "OI_VIEW"  # EDGE (pop × reward_risk) | OI_VIEW
    disclaimer: str
    algo_version: str
