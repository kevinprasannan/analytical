"""``MarketProfileConfig`` (docs/05 §10.1) — every default is a config key."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from analytical_core.params import canonical_json


@dataclass(frozen=True, slots=True)
class MarketProfileConfig:
    tpo_minutes: int = 30
    ib_periods: int = 2
    value_area_pct: float = 0.70
    partial_period_policy: str = "KEEP"  # KEEP | MERGE_PREV | DROP
    va_expansion: str = "PAIR"  # PAIR | SINGLE
    vp_distribution: str = "UNIFORM"  # V1 only value
    source_timeframe: str = "M5"
    min_periods_for_result: int = 3
    min_bins: int = 10

    # --- bin size (docs/05 §10.4) ---------------------------------------
    bin_pct: float = 0.00025  # INDEX / FUTURE: 0.025% of price_ref
    option_bin_pct: float = 0.01  # OPTION: 1% of premium_ref
    increment_by_underlying: dict[str, float] = field(
        default_factory=lambda: {"NIFTY": 5.0, "BANKNIFTY": 10.0}
    )
    default_increment: float = 5.0

    # --- shape thresholds (docs/05 §10.8) --------------------------------
    tail_pct: float = 0.15
    dd_peak_pct: float = 0.12
    dd_valley_pct: float = 0.04
    trend_va_width_max: float = 0.50
    trend_poc_pos: float = 0.66
    p_b_poc_pos: float = 0.60

    def as_dict(self) -> dict[str, Any]:
        return {
            "tpo_minutes": self.tpo_minutes,
            "ib_periods": self.ib_periods,
            "value_area_pct": self.value_area_pct,
            "partial_period_policy": self.partial_period_policy,
            "va_expansion": self.va_expansion,
            "vp_distribution": self.vp_distribution,
            "source_timeframe": self.source_timeframe,
            "min_periods_for_result": self.min_periods_for_result,
            "min_bins": self.min_bins,
            "bin_pct": self.bin_pct,
            "option_bin_pct": self.option_bin_pct,
            "increment_by_underlying": self.increment_by_underlying,
            "default_increment": self.default_increment,
            "tail_pct": self.tail_pct,
            "dd_peak_pct": self.dd_peak_pct,
            "dd_valley_pct": self.dd_valley_pct,
            "trend_va_width_max": self.trend_va_width_max,
            "trend_poc_pos": self.trend_poc_pos,
            "p_b_poc_pos": self.p_b_poc_pos,
        }

    def hashable(self) -> str:
        return canonical_json(self.as_dict())

    @classmethod
    def from_app_settings(cls, settings: Mapping[str, Any] | None) -> MarketProfileConfig:
        """Defaults with any ``market_profile.*`` override from ``app_settings``
        merged on top (docs/05 §10.1)."""
        s = settings or {}
        cfg = cls()
        changes: dict[str, Any] = {}
        for name, caster in (
            ("tpo_minutes", int),
            ("ib_periods", int),
            ("value_area_pct", float),
            ("va_expansion", str),
            ("partial_period_policy", str),
            ("min_periods_for_result", int),
            ("min_bins", int),
        ):
            v = s.get(f"market_profile.{name}")
            if v is not None:
                changes[name] = caster(v)
        return replace(cfg, **changes) if changes else cfg
