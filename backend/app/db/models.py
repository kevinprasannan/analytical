"""SQLAlchemy models for the Phase-1 schema (docs/03 §5).

Only tables needed for Phase 1 are defined. No speculative tables (task D).
Every FK declares an explicit ``ondelete`` per docs/03 §5. Enum columns use
``pg_enum`` (native PG types created by the baseline migration).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from analytical_core.enums import (
    ANALYSIS_KEY_CHECK_VALUES,
    AnalysisScope,
    AnalysisStatus,
    DataKind,
    ExpiryKind,
    InstrumentPhaseOutcome,
    InstrumentSegment,
    InstrumentType,
    MarketProfileShape,
    OptionType,
    PhaseStatus,
    ProfileType,
    RunPhase,
    RunStatus,
    RunTrigger,
    SignalLabel,
    Timeframe,
    WatermarkStatus,
)
from app.db.base import Base, pg_enum

_TS = DateTime(timezone=True)
_PRICE = Numeric(18, 4)
_RATIO = Numeric(12, 6)
_ANALYSIS_KEY_IN = ", ".join(f"'{v}'" for v in ANALYSIS_KEY_CHECK_VALUES)
_PT_TF_IN = "'M5', 'M15', 'H1', 'D1'"  # PER_TIMEFRAME analysis timeframes (docs/03 §5.4)


def _pk() -> Mapped[int]:
    return mapped_column(BigInteger, primary_key=True, autoincrement=True)


# ======================================================================================
# 5.1 Reference / registry
# ======================================================================================


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = _pk()
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(_TS, server_default=func.now(), nullable=False)


class Instrument(Base):
    __tablename__ = "instruments"
    __table_args__ = (
        UniqueConstraint(
            "instrument_type",
            "underlying_id",
            "expiry_date",
            "expiry_kind",
            "strike_price",
            "option_type",
            name="contract_identity",
        ),
        CheckConstraint("underlying_id <> id", name="no_self_underlying"),
    )

    id: Mapped[int] = _pk()
    contract_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str | None] = mapped_column(Text)
    exchange: Mapped[str] = mapped_column(Text, nullable=False, server_default="NSE")
    segment: Mapped[InstrumentSegment] = mapped_column(
        pg_enum(InstrumentSegment, "instrument_segment"), nullable=False
    )
    instrument_type: Mapped[InstrumentType] = mapped_column(
        pg_enum(InstrumentType, "instrument_type"), nullable=False
    )
    underlying_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("instruments.id", ondelete="RESTRICT")
    )
    expiry_date: Mapped[date | None] = mapped_column(Date)
    expiry_kind: Mapped[ExpiryKind | None] = mapped_column(pg_enum(ExpiryKind, "expiry_kind"))
    strike_price: Mapped[Decimal | None] = mapped_column(_PRICE)
    option_type: Mapped[OptionType | None] = mapped_column(pg_enum(OptionType, "option_type"))
    lot_size: Mapped[int | None] = mapped_column(Integer)
    tick_size: Mapped[Decimal | None] = mapped_column(_PRICE)
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default="INR")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    is_tracked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    has_volume: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    has_intraday_oi: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    profile_bin_size: Mapped[Decimal | None] = mapped_column(_PRICE)
    created_at: Mapped[datetime] = mapped_column(_TS, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        _TS, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ProviderInstrumentMap(Base):
    __tablename__ = "provider_instrument_map"
    __table_args__ = (
        UniqueConstraint("provider", "provider_symbol", name="provider_symbol"),
        UniqueConstraint("provider", "instrument_id", name="provider_instrument"),
    )

    id: Mapped[int] = _pk()
    instrument_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    provider_symbol: Mapped[str] = mapped_column(Text, nullable=False)
    provider_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")


class MarketCalendar(Base):
    __tablename__ = "market_calendar"
    __table_args__ = (
        UniqueConstraint("exchange", "segment", "calendar_date", name="exchange_segment_date"),
    )

    id: Mapped[int] = _pk()
    exchange: Mapped[str] = mapped_column(Text, nullable=False, server_default="NSE")
    segment: Mapped[str] = mapped_column(Text, nullable=False, server_default="FO")
    calendar_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_trading_day: Mapped[bool] = mapped_column(Boolean, nullable=False)
    session_open_ist: Mapped[str] = mapped_column(Time, nullable=False, server_default="09:15")
    session_close_ist: Mapped[str] = mapped_column(Time, nullable=False, server_default="15:30")
    session_type: Mapped[str] = mapped_column(Text, nullable=False, server_default="NORMAL")
    note: Mapped[str | None] = mapped_column(Text)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        _TS, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ProviderCredential(Base):
    __tablename__ = "provider_credentials"

    id: Mapped[int] = _pk()
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    secret_ref: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")


# ======================================================================================
# 5.2 Market data
# ======================================================================================


class OhlcvBar(Base):
    __tablename__ = "ohlcv_bars"
    __table_args__ = (
        UniqueConstraint("instrument_id", "timeframe", "ts", "provider", name="bar_identity"),
        Index("ix_ohlcv_bars_instrument_timeframe_ts", "instrument_id", "timeframe", "ts"),
    )

    id: Mapped[int] = _pk()
    instrument_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=False
    )
    timeframe: Mapped[Timeframe] = mapped_column(pg_enum(Timeframe, "timeframe"), nullable=False)
    ts: Mapped[datetime] = mapped_column(_TS, nullable=False)
    open: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    high: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    low: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    close: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    is_final: Mapped[bool] = mapped_column(Boolean, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(_TS, server_default=func.now(), nullable=False)


class OpenInterest(Base):
    """Populated only in docs/11 PV-4 branch A (per-candle OI)."""

    __tablename__ = "open_interest"
    __table_args__ = (
        UniqueConstraint("instrument_id", "timeframe", "ts", "provider", name="oi_identity"),
    )

    id: Mapped[int] = _pk()
    instrument_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=False
    )
    timeframe: Mapped[Timeframe] = mapped_column(pg_enum(Timeframe, "timeframe"), nullable=False)
    ts: Mapped[datetime] = mapped_column(_TS, nullable=False)
    oi: Mapped[int] = mapped_column(BigInteger, nullable=False)
    provider_oi_change: Mapped[int | None] = mapped_column(BigInteger)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    is_final: Mapped[bool] = mapped_column(Boolean, nullable=False)


class OiSnapshot(Base):
    """Populated in docs/11 PV-4 branch B (snapshot OI) — the Phase-1 default."""

    __tablename__ = "oi_snapshots"
    __table_args__ = (
        UniqueConstraint("instrument_id", "provider", "snapshot_ts", name="oi_snapshot_identity"),
        Index("ix_oi_snapshots_instrument_snapshot_ts", "instrument_id", "snapshot_ts"),
    )

    id: Mapped[int] = _pk()
    instrument_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=False
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_ts: Mapped[datetime] = mapped_column(_TS, nullable=False)
    oi: Mapped[int] = mapped_column(BigInteger, nullable=False)
    provider_oi_change: Mapped[int | None] = mapped_column(BigInteger)
    day_volume: Mapped[int | None] = mapped_column(BigInteger)
    instrument_price: Mapped[Decimal | None] = mapped_column(_PRICE)
    ingested_at: Mapped[datetime] = mapped_column(_TS, server_default=func.now(), nullable=False)


# ======================================================================================
# 5.3 Runs
# ======================================================================================


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id: Mapped[int] = _pk()
    cycle_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    trigger: Mapped[RunTrigger] = mapped_column(pg_enum(RunTrigger, "run_trigger"), nullable=False)
    status: Mapped[RunStatus] = mapped_column(pg_enum(RunStatus, "run_status"), nullable=False)
    phases_requested: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    started_at: Mapped[datetime] = mapped_column(_TS, server_default=func.now(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(_TS)
    algo_version: Mapped[str] = mapped_column(Text, nullable=False)
    scoring_version: Mapped[str] = mapped_column(Text, nullable=False)
    config_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    params_hash: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)


class RunPhaseStatus(Base):
    __tablename__ = "run_phase_status"

    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("analysis_runs.id", ondelete="CASCADE"), primary_key=True
    )
    phase: Mapped[RunPhase] = mapped_column(pg_enum(RunPhase, "run_phase"), primary_key=True)
    status: Mapped[PhaseStatus] = mapped_column(
        pg_enum(PhaseStatus, "phase_status"), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(_TS)
    finished_at: Mapped[datetime | None] = mapped_column(_TS)
    counts: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")


class RunInstrumentStatus(Base):
    __tablename__ = "run_instrument_status"

    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("analysis_runs.id", ondelete="CASCADE"), primary_key=True
    )
    instrument_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("instruments.id", ondelete="CASCADE"), primary_key=True
    )
    phase: Mapped[RunPhase] = mapped_column(pg_enum(RunPhase, "run_phase"), primary_key=True)
    outcome: Mapped[InstrumentPhaseOutcome] = mapped_column(
        pg_enum(InstrumentPhaseOutcome, "instrument_phase_outcome"), nullable=False
    )
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")


# ======================================================================================
# 5.4 Analysis results
# ======================================================================================

# ``scope_key`` is an app-maintained ``text`` column, not a Postgres GENERATED
# column: a GENERATED expression must be IMMUTABLE and ``enum::text`` /
# ``timestamptz::text`` casts are only STABLE (docs/03 §5.4 said "generated"; this
# is the smallest deterministic equivalent under that PG constraint). The
# repository layer sets it via ``ResultWrite.scope_key()`` and a CHECK keeps it
# consistent with ``scope``.
_SCOPE_KEY_CK = (
    "(scope = 'PER_TIMEFRAME' AND scope_key = 'PER_TIMEFRAME:' || timeframe::text) "
    "OR (scope = 'SESSION' AND scope_key LIKE 'SESSION:%') "
    "OR (scope = 'SNAPSHOT' AND scope_key LIKE 'SNAPSHOT:%')"
)

_SCOPE_SHAPE_CK = (
    "(scope = 'PER_TIMEFRAME' AND timeframe IS NOT NULL AND session_date IS NULL "
    f"   AND snapshot_ts IS NULL AND timeframe::text IN ({_PT_TF_IN})) "
    "OR (scope = 'SESSION' AND session_date IS NOT NULL AND timeframe IS NULL "
    "   AND snapshot_ts IS NULL) "
    "OR (scope = 'SNAPSHOT' AND snapshot_ts IS NOT NULL AND timeframe IS NULL "
    "   AND session_date IS NULL)"
)


class AnalysisResultRow(Base):
    __tablename__ = "analysis_results"
    __table_args__ = (
        CheckConstraint(f"analysis_key IN ({_ANALYSIS_KEY_IN})", name="analysis_key_known"),
        CheckConstraint(_SCOPE_SHAPE_CK, name="scope_shape"),
        CheckConstraint(_SCOPE_KEY_CK, name="scope_key_matches"),
        UniqueConstraint(
            "run_id", "instrument_id", "analysis_key", "scope_key", name="result_identity"
        ),
        Index(
            "ix_analysis_results_lookup",
            "instrument_id",
            "analysis_key",
            "scope_key",
            "as_of_ts",
        ),
        Index("ix_analysis_results_run", "run_id"),
        Index("ix_analysis_results_run_status", "run_id", "status"),
    )

    id: Mapped[int] = _pk()
    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    instrument_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=False
    )
    analysis_key: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[AnalysisScope] = mapped_column(
        pg_enum(AnalysisScope, "analysis_scope"), nullable=False
    )
    timeframe: Mapped[Timeframe | None] = mapped_column(pg_enum(Timeframe, "timeframe"))
    session_date: Mapped[date | None] = mapped_column(Date)
    snapshot_ts: Mapped[datetime | None] = mapped_column(_TS)
    scope_key: Mapped[str] = mapped_column(Text, nullable=False)
    as_of_ts: Mapped[datetime] = mapped_column(_TS, nullable=False)
    status: Mapped[AnalysisStatus] = mapped_column(
        pg_enum(AnalysisStatus, "analysis_status"), nullable=False
    )
    result: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    algo_version: Mapped[str] = mapped_column(Text, nullable=False)
    params_id: Mapped[str] = mapped_column(Text, nullable=False)
    params_hash: Mapped[str] = mapped_column(Text, nullable=False)
    input_window_start: Mapped[datetime | None] = mapped_column(_TS)
    input_window_end: Mapped[datetime | None] = mapped_column(_TS)
    bars_used: Mapped[int | None] = mapped_column(Integer)
    coverage_ratio: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    carried: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    carried_from_result_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("analysis_results.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(_TS, server_default=func.now(), nullable=False)


class MarketProfileSession(Base):
    __tablename__ = "market_profile_sessions"
    __table_args__ = (
        UniqueConstraint(
            "instrument_id", "session_date", "profile_type", name="mp_session_identity"
        ),
    )

    id: Mapped[int] = _pk()
    instrument_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False
    )
    session_date: Mapped[date] = mapped_column(Date, nullable=False)
    profile_type: Mapped[ProfileType] = mapped_column(
        pg_enum(ProfileType, "profile_type"), nullable=False
    )
    bin_size: Mapped[Decimal | None] = mapped_column(_PRICE)
    poc: Mapped[Decimal | None] = mapped_column(_PRICE)
    vah: Mapped[Decimal | None] = mapped_column(_PRICE)
    val: Mapped[Decimal | None] = mapped_column(_PRICE)
    ib_high: Mapped[Decimal | None] = mapped_column(_PRICE)
    ib_low: Mapped[Decimal | None] = mapped_column(_PRICE)
    session_high: Mapped[Decimal | None] = mapped_column(_PRICE)
    session_low: Mapped[Decimal | None] = mapped_column(_PRICE)
    profile_shape: Mapped[MarketProfileShape | None] = mapped_column(
        pg_enum(MarketProfileShape, "market_profile_shape")
    )
    is_session_complete: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    close: Mapped[Decimal | None] = mapped_column(_PRICE)
    bins: Mapped[dict | None] = mapped_column(JSONB)
    #: Market Profile event layer (docs/14). Compact ``event_result_to_dict`` blob.
    events: Mapped[dict | None] = mapped_column(JSONB)
    mp_events_version: Mapped[str | None] = mapped_column(Text)
    source_max_ts: Mapped[datetime | None] = mapped_column(_TS)
    algo_version: Mapped[str] = mapped_column(Text, nullable=False)
    params_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(_TS, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        _TS, server_default=func.now(), onupdate=func.now(), nullable=False
    )


_SCOPE_REF_CK = (
    "(scope = 'PER_TIMEFRAME' AND timeframe IS NOT NULL AND scope_ref = "
    "   'PER_TIMEFRAME:' || timeframe::text AND session_date IS NULL AND snapshot_ts IS NULL) "
    "OR (scope = 'SESSION' AND scope_ref = 'SESSION' AND timeframe IS NULL) "
    "OR (scope = 'SNAPSHOT' AND scope_ref = 'SNAPSHOT' AND timeframe IS NULL)"
)


class CurrentAnalysisResult(Base):
    """Hot-read projection (docs/03 §5.5). Collapsed ``scope_ref`` key."""

    __tablename__ = "current_analysis_results"
    __table_args__ = (CheckConstraint(_SCOPE_REF_CK, name="scope_ref_shape"),)

    instrument_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("instruments.id", ondelete="CASCADE"), primary_key=True
    )
    analysis_key: Mapped[str] = mapped_column(Text, primary_key=True)
    scope_ref: Mapped[str] = mapped_column(Text, primary_key=True)
    scope: Mapped[AnalysisScope] = mapped_column(
        pg_enum(AnalysisScope, "analysis_scope"), nullable=False
    )
    timeframe: Mapped[Timeframe | None] = mapped_column(pg_enum(Timeframe, "timeframe"))
    session_date: Mapped[date | None] = mapped_column(Date)
    snapshot_ts: Mapped[datetime | None] = mapped_column(_TS)
    analysis_result_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("analysis_results.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[AnalysisStatus] = mapped_column(
        pg_enum(AnalysisStatus, "analysis_status"), nullable=False
    )
    as_of_ts: Mapped[datetime] = mapped_column(_TS, nullable=False)
    algo_version: Mapped[str] = mapped_column(Text, nullable=False)
    params_hash: Mapped[str] = mapped_column(Text, nullable=False)
    carried: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    summary: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    updated_at: Mapped[datetime] = mapped_column(
        _TS, server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ======================================================================================
# 5.5 Scoring + current projection
# ======================================================================================


class SignalScore(Base):
    __tablename__ = "signal_scores"
    __table_args__ = (
        UniqueConstraint("run_id", "instrument_id", "timeframe", name="score_identity"),
        Index("ix_signal_scores_lookup", "instrument_id", "timeframe", "as_of_ts"),
        Index("ix_signal_scores_run", "run_id"),
    )

    id: Mapped[int] = _pk()
    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    instrument_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=False
    )
    timeframe: Mapped[Timeframe] = mapped_column(pg_enum(Timeframe, "timeframe"), nullable=False)
    as_of_ts: Mapped[datetime] = mapped_column(_TS, nullable=False)
    composite_score: Mapped[Decimal] = mapped_column(_RATIO, nullable=False)
    raw_label: Mapped[SignalLabel] = mapped_column(
        pg_enum(SignalLabel, "signal_label"), nullable=False
    )
    effective_label: Mapped[SignalLabel] = mapped_column(
        pg_enum(SignalLabel, "signal_label"), nullable=False
    )
    confidence: Mapped[Decimal] = mapped_column(_RATIO, nullable=False)
    low_confidence: Mapped[bool] = mapped_column(Boolean, nullable=False)
    strategy: Mapped[str] = mapped_column(Text, nullable=False)
    scoring_version: Mapped[str] = mapped_column(Text, nullable=False)
    params_hash: Mapped[str] = mapped_column(Text, nullable=False)
    weights: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    denom: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    warnings: Mapped[list | None] = mapped_column(JSONB)
    explanation: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(_TS, server_default=func.now(), nullable=False)


class ScoreFactor(Base):
    __tablename__ = "score_factors"

    id: Mapped[int] = _pk()
    signal_score_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("signal_scores.id", ondelete="CASCADE"), nullable=False
    )
    analysis_result_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("analysis_results.id", ondelete="SET NULL")
    )
    analysis_key: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[AnalysisScope] = mapped_column(
        pg_enum(AnalysisScope, "analysis_scope"), nullable=False
    )
    raw_values: Mapped[dict | None] = mapped_column(JSONB)
    sub_score: Mapped[Decimal] = mapped_column(_RATIO, nullable=False)
    confidence: Mapped[Decimal] = mapped_column(_RATIO, nullable=False)
    weight: Mapped[Decimal] = mapped_column(_RATIO, nullable=False)
    contribution: Mapped[Decimal] = mapped_column(_RATIO, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    rationale: Mapped[dict | None] = mapped_column(JSONB)


class CurrentSignalScore(Base):
    __tablename__ = "current_signal_scores"

    instrument_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("instruments.id", ondelete="CASCADE"), primary_key=True
    )
    timeframe: Mapped[Timeframe] = mapped_column(pg_enum(Timeframe, "timeframe"), primary_key=True)
    signal_score_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("signal_scores.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    composite_score: Mapped[Decimal] = mapped_column(_RATIO, nullable=False)
    confidence: Mapped[Decimal] = mapped_column(_RATIO, nullable=False)
    raw_label: Mapped[SignalLabel] = mapped_column(
        pg_enum(SignalLabel, "signal_label"), nullable=False
    )
    effective_label: Mapped[SignalLabel] = mapped_column(
        pg_enum(SignalLabel, "signal_label"), nullable=False
    )
    low_confidence: Mapped[bool] = mapped_column(Boolean, nullable=False)
    as_of_ts: Mapped[datetime] = mapped_column(_TS, nullable=False)
    delta_vs_previous: Mapped[Decimal | None] = mapped_column(_RATIO)
    warnings: Mapped[list | None] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        _TS, server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ======================================================================================
# 5.6 Operations
# ======================================================================================


class IngestionWatermark(Base):
    __tablename__ = "ingestion_watermarks"
    __table_args__ = (
        UniqueConstraint(
            "instrument_id", "timeframe", "data_kind", "provider", name="watermark_identity"
        ),
    )

    id: Mapped[int] = _pk()
    instrument_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=False
    )
    timeframe: Mapped[Timeframe] = mapped_column(pg_enum(Timeframe, "timeframe"), nullable=False)
    data_kind: Mapped[DataKind] = mapped_column(pg_enum(DataKind, "data_kind"), nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    last_complete_ts: Mapped[datetime | None] = mapped_column(_TS)
    last_verified_ts: Mapped[datetime | None] = mapped_column(_TS)
    last_attempt_at: Mapped[datetime | None] = mapped_column(_TS)
    last_status: Mapped[WatermarkStatus | None] = mapped_column(
        pg_enum(WatermarkStatus, "watermark_status")
    )
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")


# ======================================================================================
# 5.7 Astro cross-check (docs/13) — side tables, no FK into the market schema.
#     Joined to market data by calendar date for the astro x market study.
# ======================================================================================

_ASTRO_BODIES = "'SUN','MOON','MARS','MERCURY','JUPITER','VENUS','SATURN','RAHU','KETU'"
_ASTRO_GRAHAS = "'SUN','MOON','MARS','MERCURY','JUPITER','VENUS','SATURN'"


class AstroPosition(Base):
    """Sidereal (Lahiri) position of one graha at 09:00 IST on one date."""

    __tablename__ = "astro_positions"
    __table_args__ = (
        UniqueConstraint("as_of_date", "body", name="astro_positions_identity"),
        CheckConstraint(f"body IN ({_ASTRO_BODIES})", name="body_valid"),
        CheckConstraint("pada BETWEEN 1 AND 4", name="pada_range"),
        Index("ix_astro_positions_as_of_date", "as_of_date"),
    )

    id: Mapped[int] = _pk()
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    as_of_ts: Mapped[datetime] = mapped_column(_TS, nullable=False)  # 03:30 UTC
    body: Mapped[str] = mapped_column(String(8), nullable=False)
    longitude: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)  # sidereal 0-360
    latitude: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)
    speed_longitude: Mapped[Decimal] = mapped_column(Numeric(11, 6), nullable=False)  # deg/day
    retrograde: Mapped[bool] = mapped_column(Boolean, nullable=False)
    rashi_index: Mapped[int] = mapped_column(Integer, nullable=False)  # 0-11
    rashi: Mapped[str] = mapped_column(String(16), nullable=False)
    degree: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)  # within sign
    nakshatra_index: Mapped[int] = mapped_column(Integer, nullable=False)  # 0-26
    nakshatra: Mapped[str] = mapped_column(String(24), nullable=False)
    pada: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-4
    nakshatra_lord: Mapped[str] = mapped_column(String(8), nullable=False)
    dignity: Mapped[str | None] = mapped_column(String(16))
    ayanamsha: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(_TS, server_default=func.now(), nullable=False)


class AstroShadbala(Base):
    """Classical Parashari Shadbala (virupas) for one graha on one date."""

    __tablename__ = "astro_shadbala"
    __table_args__ = (
        UniqueConstraint("as_of_date", "graha", name="astro_shadbala_identity"),
        CheckConstraint(f"graha IN ({_ASTRO_GRAHAS})", name="graha_valid"),
        Index("ix_astro_shadbala_as_of_date", "as_of_date"),
    )

    id: Mapped[int] = _pk()
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    as_of_ts: Mapped[datetime] = mapped_column(_TS, nullable=False)
    graha: Mapped[str] = mapped_column(String(8), nullable=False)
    sthana_bala: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)  # virupa
    dig_bala: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    kala_bala: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    cheshta_bala: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    naisargika_bala: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    drik_bala: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    total_virupa: Mapped[Decimal] = mapped_column(Numeric(11, 4), nullable=False)
    total_rupa: Mapped[Decimal] = mapped_column(Numeric(9, 4), nullable=False)
    required_rupa: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    strength_ratio: Mapped[Decimal] = mapped_column(Numeric(9, 4), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-7 (1 = strongest)
    ishta_phala: Mapped[Decimal] = mapped_column(Numeric(9, 4), nullable=False)
    kashta_phala: Mapped[Decimal] = mapped_column(Numeric(9, 4), nullable=False)
    graha_yuddha: Mapped[bool] = mapped_column(Boolean, nullable=False)
    components: Mapped[dict] = mapped_column(JSONB, nullable=False)  # full flat virupa breakdown
    source: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(_TS, server_default=func.now(), nullable=False)


class AstroDay(Base):
    """Denormalised per-day chart scalars (weekday, lagna, Moon nakshatra, tithi)
    for the astro x market study (docs/13 §5)."""

    __tablename__ = "astro_days"
    __table_args__ = (
        CheckConstraint("tithi BETWEEN 1 AND 30", name="tithi_range"),
        Index("ix_astro_days_weekday", "weekday"),
        Index("ix_astro_days_moon_nakshatra_index", "moon_nakshatra_index"),
        Index("ix_astro_days_lagna_rashi_index", "lagna_rashi_index"),
    )

    as_of_date: Mapped[date] = mapped_column(Date, primary_key=True)
    as_of_ts: Mapped[datetime] = mapped_column(_TS, nullable=False)
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)  # 0=Mon..6=Sun
    day_name: Mapped[str] = mapped_column(String(9), nullable=False)
    weekday_lord: Mapped[str] = mapped_column(String(8), nullable=False)
    lagna_longitude: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)
    lagna_rashi_index: Mapped[int] = mapped_column(Integer, nullable=False)
    lagna_rashi: Mapped[str] = mapped_column(String(16), nullable=False)
    lagna_nakshatra_index: Mapped[int] = mapped_column(Integer, nullable=False)
    lagna_nakshatra: Mapped[str] = mapped_column(String(24), nullable=False)
    lagna_pada: Mapped[int] = mapped_column(Integer, nullable=False)
    moon_rashi_index: Mapped[int] = mapped_column(Integer, nullable=False)
    moon_rashi: Mapped[str] = mapped_column(String(16), nullable=False)
    moon_nakshatra_index: Mapped[int] = mapped_column(Integer, nullable=False)
    moon_nakshatra: Mapped[str] = mapped_column(String(24), nullable=False)
    moon_pada: Mapped[int] = mapped_column(Integer, nullable=False)
    moon_nakshatra_lord: Mapped[str] = mapped_column(String(8), nullable=False)
    sun_rashi_index: Mapped[int] = mapped_column(Integer, nullable=False)
    sun_rashi: Mapped[str] = mapped_column(String(16), nullable=False)
    tithi: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-30
    paksha: Mapped[str] = mapped_column(String(8), nullable=False)  # Shukla | Krishna
    sunrise_ts: Mapped[datetime] = mapped_column(_TS, nullable=False)
    sunset_ts: Mapped[datetime] = mapped_column(_TS, nullable=False)
    ayanamsha: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(_TS, server_default=func.now(), nullable=False)


class IndexWeight(Base):
    """Seeded free-float index weights for an index's constituents (docs/15).

    Reference data, owner-maintained — reloaded from the NSE/niftyindices
    factsheet on each semi-annual rebalance. Not tracked instruments, not
    ingested; the constituent read joins these to a quote-on-read snapshot.
    One row per (index_key, symbol, effective_date)."""

    __tablename__ = "index_weights"
    __table_args__ = (
        UniqueConstraint("index_key", "symbol", "effective_date", name="index_weights_identity"),
        Index("ix_index_weights_lookup", "index_key", "effective_date"),
    )

    id: Mapped[int] = _pk()
    index_key: Mapped[str] = mapped_column(String(32), nullable=False)  # e.g. NIFTY-INDEX
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)  # rebalance date
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)  # NSE equity symbol
    name: Mapped[str] = mapped_column(String(96), nullable=False)
    sector: Mapped[str] = mapped_column(String(48), nullable=False)
    weight_pct: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)  # 0..100
    provider: Mapped[str | None] = mapped_column(String(24))  # for quote-on-read
    provider_symbol: Mapped[str | None] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default="seed")
    created_at: Mapped[datetime] = mapped_column(_TS, server_default=func.now(), nullable=False)


ALL_TABLES = tuple(Base.metadata.sorted_tables)
