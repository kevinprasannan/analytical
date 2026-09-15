"""Backtesting (docs/16). Pure, deterministic, descriptive — no signal."""

from __future__ import annotations

from analytical_core.backtest.orb import (
    INDEX_ORB_VERSION,
    Bar,
    DayBars,
    DayResult,
    OrbAggregate,
    OrbConfig,
    OrbResult,
    TargetOutcome,
    TargetStat,
    WeekdayStat,
    run_orb,
)

__all__ = [
    "INDEX_ORB_VERSION",
    "Bar",
    "DayBars",
    "DayResult",
    "OrbAggregate",
    "OrbConfig",
    "OrbResult",
    "TargetOutcome",
    "TargetStat",
    "WeekdayStat",
    "run_orb",
]
