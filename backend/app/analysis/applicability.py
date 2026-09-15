"""Analysis applicability by instrument type (docs/04 §4).

Decides *which* analyses run and at what *scope*, and where the matrix says an
analysis does not apply to the instrument type, emits ``NOT_APPLICABLE``. The
matrix also pre-empts a couple of cases as ``INSUFFICIENT_DATA`` (open interest
with no OI feed; option Market Profile, whose premium-range profile is usually
too shallow); genuine coverage/warm-up ``INSUFFICIENT_DATA`` is decided by the
engine at run time.

**OPTION is chain-only (docs/04 §2.3/§4).** A tracked option contributes its
latest premium + OI to the option-chain view (docs/05 §11), which computes IV /
greeks / PCR / max-pain on read. The premium series itself is not a V1 analysis
input, so every premium-series technical (``rsi`` / ``bollinger`` / ``ema7`` /
``volume``) is ``NOT_APPLICABLE`` for OPTION; only ``open_interest`` runs. This
keeps a wide chain (hundreds of strikes) within the per-cycle ANALYZE budget.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from analytical_core.enums import (
    USER_FACING_TIMEFRAMES,
    AnalysisKey,
    AnalysisScope,
    AnalysisStatus,
    InstrumentType,
    Timeframe,
)
from app.db.repositories.protocols import InstrumentView
from app.providers.capabilities import ProviderCapabilities, resolve_oi_plan

_PT = AnalysisScope.PER_TIMEFRAME
_SESSION = AnalysisScope.SESSION


@dataclass(frozen=True, slots=True)
class PlannedAnalysis:
    analysis_key: str
    scope: AnalysisScope
    status: AnalysisStatus
    timeframe: Timeframe | None = None
    session_date: date | None = None
    snapshot_ts: datetime | None = None
    reason: str | None = None


def plan_analyses(
    instrument: InstrumentView,
    caps: ProviderCapabilities,
    *,
    as_of: datetime,
    session_date: date,
) -> list[PlannedAnalysis]:
    it = instrument.instrument_type
    is_option = it is InstrumentType.OPTION
    plans: list[PlannedAnalysis] = []

    # OPTION is chain-only: the premium series is not a V1 analysis input.
    _CHAIN_ONLY = (
        "option is chain-only (docs/04 §2.3/§4): the premium series is not a V1 "
        "analysis input; IV / greeks / PCR come from the option-chain view (docs/05 §11)"
    )

    # --- PER_TIMEFRAME technicals (rsi / bollinger / ema7 / order_block / candles): OPTION -> NA ---
    for key in (
        AnalysisKey.RSI,
        AnalysisKey.BOLLINGER,
        AnalysisKey.EMA7,
        AnalysisKey.ORDER_BLOCK,
        AnalysisKey.CANDLES,
    ):
        for tf in USER_FACING_TIMEFRAMES:
            plans.append(
                PlannedAnalysis(
                    key.value,
                    _PT,
                    AnalysisStatus.NOT_APPLICABLE if is_option else AnalysisStatus.OK,
                    timeframe=tf,
                    reason=_CHAIN_ONLY if is_option else None,
                )
            )

    # --- golden_cross: INDEX only (docs/04 §4, H1); dated contracts -> NOT_APPLICABLE ---
    if it is InstrumentType.INDEX:
        plans.append(
            PlannedAnalysis(
                AnalysisKey.GOLDEN_CROSS.value, _PT, AnalysisStatus.OK, timeframe=Timeframe.D1
            )
        )
    else:
        plans.append(
            PlannedAnalysis(
                AnalysisKey.GOLDEN_CROSS.value,
                _PT,
                AnalysisStatus.NOT_APPLICABLE,
                timeframe=Timeframe.D1,
                reason="dated contract history is shorter than slow_period; "
                "index trend is represented by the INDEX instrument",
            )
        )

    # --- volume: applicable where the instrument reports volume; OPTION is chain-only ---
    for tf in USER_FACING_TIMEFRAMES:
        if is_option:
            plans.append(
                PlannedAnalysis(
                    AnalysisKey.VOLUME.value,
                    _PT,
                    AnalysisStatus.NOT_APPLICABLE,
                    timeframe=tf,
                    reason=_CHAIN_ONLY,
                )
            )
        elif instrument.has_volume:
            plans.append(
                PlannedAnalysis(AnalysisKey.VOLUME.value, _PT, AnalysisStatus.OK, timeframe=tf)
            )
        else:
            plans.append(
                PlannedAnalysis(
                    AnalysisKey.VOLUME.value,
                    _PT,
                    AnalysisStatus.NOT_APPLICABLE,
                    timeframe=tf,
                    reason="instrument/provider has no volume",
                )
            )

    # --- open_interest: FUTURE/OPTION only; scope from provider capability ---
    oi_plan = resolve_oi_plan(caps)
    oi_scope = oi_plan.scope or AnalysisScope.SNAPSHOT
    oi_kwargs = (
        {"snapshot_ts": as_of}
        if oi_scope is AnalysisScope.SNAPSHOT
        else {"timeframe": Timeframe.D1}
    )
    if it in (InstrumentType.FUTURE, InstrumentType.OPTION):
        if oi_plan.available:
            plans.append(
                PlannedAnalysis(
                    AnalysisKey.OPEN_INTEREST.value, oi_scope, AnalysisStatus.OK, **oi_kwargs
                )
            )
        else:
            plans.append(
                PlannedAnalysis(
                    AnalysisKey.OPEN_INTEREST.value,
                    oi_scope,
                    AnalysisStatus.INSUFFICIENT_DATA,
                    reason=oi_plan.reason,
                    **oi_kwargs,
                )
            )
    else:  # INDEX -> no OI by design
        plans.append(
            PlannedAnalysis(
                AnalysisKey.OPEN_INTEREST.value,
                oi_scope,
                AnalysisStatus.NOT_APPLICABLE,
                reason="index instruments have no open interest",
                **oi_kwargs,
            )
        )

    # --- market_profile: SESSION scope. OPTION commonly INSUFFICIENT_DATA (docs/04 §4) ---
    if it is InstrumentType.OPTION:
        plans.append(
            PlannedAnalysis(
                AnalysisKey.MARKET_PROFILE.value,
                _SESSION,
                AnalysisStatus.INSUFFICIENT_DATA,
                session_date=session_date,
                reason="option premium-range profile is usually too shallow for a session profile",
            )
        )
    else:
        plans.append(
            PlannedAnalysis(
                AnalysisKey.MARKET_PROFILE.value,
                _SESSION,
                AnalysisStatus.OK,
                session_date=session_date,
            )
        )

    return plans
