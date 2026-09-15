"""Explicit provider capability model + resolution helpers (task F).

The application asks ``provider.capabilities()`` and branches on the answer.
No module elsewhere is allowed to assume a specific provider supports a specific
feature.

``OIMode`` is a provider-layer concept only (not a DB/API contract enum, so it is
not in ``analytical_core.enums`` — documented Phase-1 choice).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from analytical_core.enums import AnalysisScope, Timeframe


class OIMode(StrEnum):
    NONE = "NONE"
    SNAPSHOT = "SNAPSHOT"
    PER_TIMEFRAME = "PER_TIMEFRAME"


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    provider: str
    auth_kind: str  # "static-token" | "oauth-daily" | "oauth-daily-manual" | "none" | "unknown"
    supports_instrument_master: bool
    native_timeframes: frozenset[Timeframe]
    aggregatable_from: Timeframe | None  # e.g. Timeframe.M1
    oi_mode: OIMode
    max_history_days: Mapping[str, int] = field(default_factory=dict)
    rate_limit_per_sec: int | None = None
    #: sustained-throughput limits (docs/11 PV-5). ``None`` = not published.
    requests_per_minute: int | None = None
    requests_per_30min: int | None = None
    #: earliest available date per Timeframe value (docs/11 PV-3).
    historical_since: Mapping[str, date] = field(default_factory=dict)
    #: max date-range span (days) a single history request may cover (docs/11 PV-3).
    max_range_days: Mapping[str, int] = field(default_factory=dict)
    notes: str = ""

    # --- queries the rest of the app uses instead of hard-coding assumptions ---

    def has_oi(self) -> bool:
        return self.oi_mode is not OIMode.NONE

    def oi_scope(self) -> AnalysisScope | None:
        return {
            OIMode.NONE: None,
            OIMode.SNAPSHOT: AnalysisScope.SNAPSHOT,
            OIMode.PER_TIMEFRAME: AnalysisScope.PER_TIMEFRAME,
        }[self.oi_mode]

    def serves_timeframe(self, tf: Timeframe) -> bool:
        return tf in self.native_timeframes or self.can_aggregate(tf)

    def can_aggregate(self, tf: Timeframe) -> bool:
        return (
            self.aggregatable_from is not None and self.aggregatable_from in self.native_timeframes
        )

    def needs_aggregation(self, tf: Timeframe) -> bool:
        return tf not in self.native_timeframes and self.can_aggregate(tf)

    def history_days(self, tf: Timeframe) -> int | None:
        return self.max_history_days.get(tf.value)


@dataclass(frozen=True, slots=True)
class TimeframePlan:
    timeframe: Timeframe
    mode: str  # "native" | "aggregate" | "unavailable"
    aggregate_from: Timeframe | None = None


def resolve_timeframe_plan(
    caps: ProviderCapabilities, wanted: tuple[Timeframe, ...]
) -> dict[Timeframe, TimeframePlan]:
    """For each wanted analysis timeframe say how (if at all) it can be sourced."""
    plan: dict[Timeframe, TimeframePlan] = {}
    for tf in wanted:
        if tf in caps.native_timeframes:
            plan[tf] = TimeframePlan(tf, "native")
        elif caps.needs_aggregation(tf):
            plan[tf] = TimeframePlan(tf, "aggregate", caps.aggregatable_from)
        else:
            plan[tf] = TimeframePlan(tf, "unavailable")
    return plan


@dataclass(frozen=True, slots=True)
class OIPlan:
    available: bool
    scope: AnalysisScope | None
    reason: str


def resolve_oi_plan(caps: ProviderCapabilities) -> OIPlan:
    if not caps.has_oi():
        return OIPlan(False, None, "provider reports no open-interest capability")
    return OIPlan(True, caps.oi_scope(), f"provider OI mode = {caps.oi_mode.value}")
