"""Index-constituent weightage view (docs/07 §4.14, docs/15).

Descriptive — weight, contribution, breadth, beta/correlation for the names that
make up an index, ordered by weight. No signal, no BUY/SELL.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Constituent(BaseModel):
    symbol: str
    name: str
    sector: str
    rank: int  # 1 = heaviest
    weight_pct: float
    cumulative_weight_pct: float
    ltp: float | None = None
    prev_close: float | None = None
    change_pct: float | None = None
    contribution_pct: float | None = None  # index percent added by this name today
    contribution_points: float | None = None  # ~index points (needs the index prev close)
    contribution_rank: int | None = None  # 1 = most positive
    abs_contribution_rank: int | None = None  # 1 = biggest mover of the index either way
    beta: float | None = None
    correlation: float | None = None
    r_squared: float | None = None


class Concentration(BaseModel):
    top1_pct: float
    top5_pct: float
    top10_pct: float
    hhi: float


class SectorWeight(BaseModel):
    sector: str
    weight_pct: float
    count: int
    contribution_pct: float | None = None
    contribution_points: float | None = None  # sector's index points today


class Breadth(BaseModel):
    covered: int
    advances: int
    declines: int
    unchanged: int
    up_weight_pct: float
    down_weight_pct: float
    advance_decline_weight: float
    net_contribution_pct: float | None = None
    net_contribution_points: float | None = None  # Σ contribution_points ≈ index points today
    top5_move_share: float | None = None


class IndexConstituentsResponse(BaseModel):
    index_id: int
    index_symbol: str
    as_of: str | None = None
    historical: bool = False  # true when as_of_date replayed a past session, not a live quote
    weights_effective_date: str | None = None
    source: str  # "seed" | provider name
    n_constituents: int
    total_weight_pct: float
    index_ltp: float | None = None
    index_prev_close: float | None = None
    index_change_pct: float | None = None
    concentration: Concentration
    sectors: list[SectorWeight] = Field(default_factory=list)
    breadth: Breadth | None = None
    items: list[Constituent] = Field(default_factory=list)
    beta_lookback: int | None = None
    algo_version: str
    index_constituents_version: str
