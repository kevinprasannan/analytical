"""Authoritative enum contract (docs/12-ENUM-CONTRACT.md).

Single source of truth. The PostgreSQL ``ENUM`` types and the API/DTO schemas are
*derived* from this module and continuously checked against it
(``tests/test_enum_contract.py`` / CI job ``enum-contract``).

Storage form: ``UPPER_SNAKE_CASE`` string values, **except** ``analysis_key``
which is ``lower_snake_case`` (it is a JSON map key and a URL path segment).

Usage:
    python -m analytical_core.enums --emit-sql     # CREATE TYPE ... statements
    python -m analytical_core.enums --emit-json    # {name: {values, materialized_in_db}}
"""

from __future__ import annotations

import argparse
import json
import sys
from enum import StrEnum

# --------------------------------------------------------------------------------------
# Market / instrument
# --------------------------------------------------------------------------------------


class Timeframe(StrEnum):
    M1 = "M1"
    M5 = "M5"
    M15 = "M15"
    H1 = "H1"
    D1 = "D1"


class InstrumentType(StrEnum):
    INDEX = "INDEX"
    FUTURE = "FUTURE"
    OPTION = "OPTION"


class InstrumentSegment(StrEnum):
    INDEX = "INDEX"
    FUT = "FUT"
    OPT = "OPT"


class OptionType(StrEnum):
    CE = "CE"
    PE = "PE"


class ExpiryKind(StrEnum):
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"


class DataKind(StrEnum):
    OHLCV = "OHLCV"
    OI = "OI"


# --------------------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------------------


class AnalysisScope(StrEnum):
    PER_TIMEFRAME = "PER_TIMEFRAME"
    SESSION = "SESSION"
    SNAPSHOT = "SNAPSHOT"


class AnalysisKey(StrEnum):
    RSI = "rsi"
    BOLLINGER = "bollinger"
    EMA7 = "ema7"
    GOLDEN_CROSS = "golden_cross"
    VOLUME = "volume"
    OPEN_INTEREST = "open_interest"
    MARKET_PROFILE = "market_profile"
    ORDER_BLOCK = "order_block"
    CANDLES = "candles"


class AnalysisStatus(StrEnum):
    OK = "OK"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    ERROR = "ERROR"


class ProfileType(StrEnum):
    TPO = "TPO"
    VOLUME = "VOLUME"


class MarketProfileShape(StrEnum):
    NORMAL = "NORMAL"
    P_SHAPE = "P_SHAPE"
    B_SHAPE = "B_SHAPE"
    DOUBLE_DISTRIBUTION = "DOUBLE_DISTRIBUTION"
    TREND_UP = "TREND_UP"
    TREND_DOWN = "TREND_DOWN"


class OIBehavior(StrEnum):
    LONG_BUILDUP = "LONG_BUILDUP"
    SHORT_BUILDUP = "SHORT_BUILDUP"
    LONG_UNWINDING = "LONG_UNWINDING"
    SHORT_COVERING = "SHORT_COVERING"
    INDETERMINATE = "INDETERMINATE"


class Direction(StrEnum):
    """Shared by ``oi_direction`` and ``price_direction`` (docs/12 §4)."""

    UP = "UP"
    DOWN = "DOWN"
    FLAT = "FLAT"


class BollingerPosition(StrEnum):
    ABOVE_UPPER = "ABOVE_UPPER"
    UPPER_HALF = "UPPER_HALF"
    MIDDLE = "MIDDLE"
    LOWER_HALF = "LOWER_HALF"
    BELOW_LOWER = "BELOW_LOWER"


class MASlopeState(StrEnum):
    RISING = "RISING"
    FALLING = "FALLING"
    FLAT = "FLAT"
    UNKNOWN = "UNKNOWN"


class RSIState(StrEnum):
    OVERBOUGHT = "OVERBOUGHT"
    OVERSOLD = "OVERSOLD"
    NEUTRAL = "NEUTRAL"


class GoldenCrossType(StrEnum):
    GOLDEN = "GOLDEN"
    DEATH = "DEATH"
    NONE_IN_WINDOW = "NONE_IN_WINDOW"


class Divergence(StrEnum):
    """RSI price/oscillator divergence (docs/05 §4)."""

    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NONE = "NONE"


class VolumeTrend(StrEnum):
    """Sign of the OLS slope of volume over the MA window (docs/05 §8)."""

    RISING = "RISING"
    FALLING = "FALLING"
    FLAT = "FLAT"


class VolumeUpDownState(StrEnum):
    """Up/down bar mix over the MA window (docs/05 §8)."""

    MORE_UP = "MORE_UP"
    MORE_DOWN = "MORE_DOWN"
    BALANCED = "BALANCED"
    ALL_UP = "ALL_UP"
    ALL_DOWN = "ALL_DOWN"


class OrderBlockBias(StrEnum):
    """Net structural lean from the active order blocks (docs/05 §9a)."""

    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class OrderBlockZoneState(StrEnum):
    """Where price sits relative to the nearest active order blocks (docs/05 §9a)."""

    OUTSIDE = "OUTSIDE"
    IN_BULLISH = "IN_BULLISH"  # price is inside a bullish (demand) order block
    IN_BEARISH = "IN_BEARISH"  # price is inside a bearish (supply) order block


class CandlePattern(StrEnum):
    """Major candlestick patterns recognised by ``candles`` (docs/05 §9b)."""

    DOJI = "DOJI"
    GRAVESTONE_DOJI = "GRAVESTONE_DOJI"
    DRAGONFLY_DOJI = "DRAGONFLY_DOJI"
    MARUBOZU = "MARUBOZU"
    HAMMER = "HAMMER"
    INVERTED_HAMMER = "INVERTED_HAMMER"
    HANGING_MAN = "HANGING_MAN"
    SHOOTING_STAR = "SHOOTING_STAR"
    BULLISH_ENGULFING = "BULLISH_ENGULFING"
    BEARISH_ENGULFING = "BEARISH_ENGULFING"
    BULLISH_HARAMI = "BULLISH_HARAMI"
    BEARISH_HARAMI = "BEARISH_HARAMI"
    PIERCING_LINE = "PIERCING_LINE"
    DARK_CLOUD_COVER = "DARK_CLOUD_COVER"
    MORNING_STAR = "MORNING_STAR"
    EVENING_STAR = "EVENING_STAR"


class CandleBias(StrEnum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class CandleStrength(StrEnum):
    WEAK = "WEAK"
    MODERATE = "MODERATE"
    STRONG = "STRONG"


# --------------------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------------------


class SignalLabel(StrEnum):
    STRONG_BEARISH = "STRONG_BEARISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"
    BULLISH = "BULLISH"
    STRONG_BULLISH = "STRONG_BULLISH"


class ScoringStrategy(StrEnum):
    WEIGHTED_V1 = "weighted_v1"


# --------------------------------------------------------------------------------------
# Run / operations
# --------------------------------------------------------------------------------------


class RunTrigger(StrEnum):
    SCHEDULED = "SCHEDULED"
    MANUAL = "MANUAL"
    BACKFILL = "BACKFILL"


class RunStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class RunPhase(StrEnum):
    INGEST = "INGEST"
    ANALYZE = "ANALYZE"
    SCORE = "SCORE"


class PhaseStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class InstrumentPhaseOutcome(StrEnum):
    OK = "OK"
    DEGRADED = "DEGRADED"
    SKIPPED = "SKIPPED"
    ERROR = "ERROR"


class WatermarkStatus(StrEnum):
    OK = "OK"
    ERROR = "ERROR"
    RATE_LIMITED = "RATE_LIMITED"
    AUTH_FAILED = "AUTH_FAILED"


class ProviderAuthState(StrEnum):
    OK = "OK"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


# --------------------------------------------------------------------------------------
# Registry + DB materialisation set
# --------------------------------------------------------------------------------------

#: contract name -> enum class. This is the list the migrations and the contract
#: test iterate over (docs/12 §1).
ENUM_REGISTRY: dict[str, type[StrEnum]] = {
    "timeframe": Timeframe,
    "instrument_type": InstrumentType,
    "instrument_segment": InstrumentSegment,
    "option_type": OptionType,
    "expiry_kind": ExpiryKind,
    "data_kind": DataKind,
    "analysis_scope": AnalysisScope,
    "analysis_key": AnalysisKey,
    "analysis_status": AnalysisStatus,
    "profile_type": ProfileType,
    "market_profile_shape": MarketProfileShape,
    "oi_behavior": OIBehavior,
    "direction": Direction,
    "bollinger_position": BollingerPosition,
    "ma_slope_state": MASlopeState,
    "rsi_state": RSIState,
    "golden_cross_type": GoldenCrossType,
    "divergence": Divergence,
    "volume_trend": VolumeTrend,
    "volume_up_down_state": VolumeUpDownState,
    "order_block_bias": OrderBlockBias,
    "order_block_zone_state": OrderBlockZoneState,
    "candle_pattern": CandlePattern,
    "candle_bias": CandleBias,
    "candle_strength": CandleStrength,
    "signal_label": SignalLabel,
    "scoring_strategy": ScoringStrategy,
    "run_trigger": RunTrigger,
    "run_status": RunStatus,
    "run_phase": RunPhase,
    "phase_status": PhaseStatus,
    "instrument_phase_outcome": InstrumentPhaseOutcome,
    "watermark_status": WatermarkStatus,
    "provider_auth_state": ProviderAuthState,
}

#: Contract names materialised as native PostgreSQL ``ENUM`` types because a
#: column stores them (docs/03 §4). Others are contract/API-only (they appear in
#: JSONB payloads or API responses, never as a column) and get no PG type.
#: Design choice: create a PG type only where a column needs it.
DB_ENUMS: tuple[str, ...] = (
    "timeframe",
    "instrument_type",
    "instrument_segment",
    "option_type",
    "expiry_kind",
    "data_kind",
    "analysis_scope",
    "analysis_status",
    "profile_type",
    "market_profile_shape",
    "signal_label",
    "run_trigger",
    "run_status",
    "run_phase",
    "phase_status",
    "instrument_phase_outcome",
    "watermark_status",
)

#: ``analysis_key`` is stored as ``text`` + a CHECK (docs/03 §4), not a PG enum.
ANALYSIS_KEY_CHECK_VALUES: tuple[str, ...] = tuple(m.value for m in AnalysisKey)

#: User-facing analysis timeframes (docs/12 §4). ``M1`` is an ingestion/aggregation
#: source only and is never a ``PER_TIMEFRAME`` analysis timeframe.
USER_FACING_TIMEFRAMES: tuple[Timeframe, ...] = (
    Timeframe.M5,
    Timeframe.M15,
    Timeframe.H1,
    Timeframe.D1,
)


def values(name: str) -> list[str]:
    """Ordered value strings for a registered enum."""
    return [m.value for m in ENUM_REGISTRY[name]]


def emit_sql() -> str:
    """``CREATE TYPE`` statements for every DB-materialised enum, in registry order."""
    lines: list[str] = []
    for name in DB_ENUMS:
        vals = ", ".join(_sql_quote(v) for v in values(name))
        lines.append(f"CREATE TYPE {name} AS ENUM ({vals});")
    return "\n".join(lines) + "\n"


def emit_drop_sql() -> str:
    """``DROP TYPE`` statements for every DB-materialised enum (reverse order)."""
    return "\n".join(f"DROP TYPE IF EXISTS {name};" for name in reversed(DB_ENUMS)) + "\n"


def emit_json() -> dict[str, dict[str, object]]:
    """Full registry for ``GET /api/v1/meta/enums`` and the contract test."""
    return {
        name: {
            "values": values(name),
            "materialized_in_db": name in DB_ENUMS,
        }
        for name in ENUM_REGISTRY
    }


def _sql_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="analytical_core.enums")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--emit-sql", action="store_true")
    group.add_argument("--emit-json", action="store_true")
    args = parser.parse_args(argv)
    if args.emit_sql:
        sys.stdout.write(emit_sql())
    else:
        sys.stdout.write(json.dumps(emit_json(), indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - thin CLI shim
    raise SystemExit(_main())
