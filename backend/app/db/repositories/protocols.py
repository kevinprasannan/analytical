"""Repository protocols + plain value objects used across the worker pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import TYPE_CHECKING, Protocol

from analytical_core.enums import (
    AnalysisScope,
    AnalysisStatus,
    InstrumentPhaseOutcome,
    InstrumentType,
    PhaseStatus,
    RunPhase,
    RunStatus,
    RunTrigger,
    SignalLabel,
    Timeframe,
)

if TYPE_CHECKING:
    from app.db.repositories.market_data import MarketDataRepository


@dataclass(frozen=True, slots=True)
class InstrumentView:
    id: int
    contract_key: str
    instrument_type: InstrumentType
    has_volume: bool
    has_intraday_oi: bool
    provider_symbol: str


@dataclass(frozen=True, slots=True)
class ResultWrite:
    instrument_id: int
    analysis_key: str
    scope: AnalysisScope
    as_of_ts: datetime
    status: AnalysisStatus
    result: dict
    algo_version: str
    params_id: str
    params_hash: str
    timeframe: Timeframe | None = None
    session_date: date | None = None
    snapshot_ts: datetime | None = None
    carried: bool = False
    carried_from_result_id: int | None = None
    summary: dict = field(default_factory=dict)
    input_window_start: datetime | None = None
    input_window_end: datetime | None = None
    bars_used: int | None = None
    coverage_ratio: float | None = None

    def scope_ref(self) -> str:
        """Collapsed key for the ``current_*`` projection."""
        if self.scope is AnalysisScope.PER_TIMEFRAME:
            assert self.timeframe is not None
            return f"PER_TIMEFRAME:{self.timeframe.value}"
        return self.scope.value  # "SESSION" | "SNAPSHOT"

    def scope_key(self) -> str:
        """Full natural key for ``analysis_results`` (one row per run)."""
        if self.scope is AnalysisScope.PER_TIMEFRAME:
            assert self.timeframe is not None
            return f"PER_TIMEFRAME:{self.timeframe.value}"
        if self.scope is AnalysisScope.SESSION:
            return f"SESSION:{self.session_date}"
        return f"SNAPSHOT:{self.snapshot_ts.isoformat()}"  # type: ignore[union-attr]


@dataclass(frozen=True, slots=True)
class FactorWrite:
    analysis_key: str
    scope: AnalysisScope
    sub_score: float
    confidence: float
    weight: float
    contribution: float
    reason: str | None = None
    raw_values: dict | None = None
    rationale: dict | None = None
    analysis_result_id: int | None = None


@dataclass(frozen=True, slots=True)
class ScoreWrite:
    instrument_id: int
    timeframe: Timeframe
    as_of_ts: datetime
    composite_score: float
    raw_label: SignalLabel
    effective_label: SignalLabel
    confidence: float
    low_confidence: bool
    strategy: str
    scoring_version: str
    params_hash: str
    weights: dict
    denom: float | None
    warnings: list[str]
    explanation: str
    factors: tuple[FactorWrite, ...]


class RunRepository(Protocol):
    def next_cycle_seq(self) -> int: ...
    def create_run(
        self,
        *,
        cycle_seq: int,
        trigger: RunTrigger,
        phases_requested: list[str],
        algo_version: str,
        scoring_version: str,
        config_snapshot: dict,
        params_hash: str,
    ) -> int: ...
    def set_phase_status(
        self,
        run_id: int,
        phase: RunPhase,
        status: PhaseStatus,
        *,
        counts: dict,
        started_at: datetime | None,
        finished_at: datetime | None,
        detail: dict | None = None,
    ) -> None: ...
    def set_instrument_status(
        self,
        run_id: int,
        instrument_id: int,
        phase: RunPhase,
        outcome: InstrumentPhaseOutcome,
        detail: dict | None = None,
    ) -> None: ...
    def finalize_run(self, run_id: int, status: RunStatus, finished_at: datetime) -> None: ...
    def get_run_status(self, run_id: int) -> RunStatus: ...
    def count_runs(self) -> int: ...


class InstrumentRepository(Protocol):
    def list_tracked(self) -> list[InstrumentView]: ...


@dataclass(frozen=True, slots=True)
class ResultFingerprint:
    """What the ANALYZE recompute guard compares (docs/02 §3.5).

    ``result_id`` and ``summary`` are already resolved through any carry chain, so
    a fresh carry points straight at the real result and its projection keeps the
    values.
    """

    result_id: int
    input_window_end: datetime | None
    params_hash: str
    algo_version: str
    last_bar_final: bool
    summary: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RunAnalysisRow:
    """A same-run analysis result resolved for scoring (carries followed)."""

    result_id: int
    analysis_key: str
    scope: AnalysisScope
    timeframe: Timeframe | None
    status: AnalysisStatus
    values: dict
    aux: dict
    meta: dict
    warnings: list[str]


class AnalysisResultRepository(Protocol):
    def upsert_result(self, run_id: int, write: ResultWrite) -> int: ...
    def last_fingerprint(
        self, instrument_id: int, analysis_key: str, scope_key: str
    ) -> ResultFingerprint | None: ...
    def list_run_results(self, run_id: int, instrument_id: int) -> list[RunAnalysisRow]: ...


@dataclass(frozen=True, slots=True)
class MarketProfileCache:
    source_max_ts: datetime | None
    params_hash: str


@dataclass(frozen=True, slots=True)
class MarketProfileSessionRef:
    """Lean prior-session reference for the event layer (docs/14 §14.8)."""

    session_date: date
    poc: float | None
    vah: float | None
    val: float | None
    session_high: float | None
    session_low: float | None
    close: float | None


@dataclass(frozen=True, slots=True)
class MarketProfileSessionWrite:
    instrument_id: int
    session_date: date
    profile_type: str  # "TPO" | "VOLUME"
    bin_size: float | None
    poc: float | None
    vah: float | None
    val: float | None
    ib_high: float | None
    ib_low: float | None
    session_high: float | None
    session_low: float | None
    profile_shape: str | None
    is_session_complete: bool
    bins: dict | list | None
    source_max_ts: datetime | None
    algo_version: str
    params_hash: str
    close: float | None = None
    events: dict | None = None
    mp_events_version: str | None = None


class MarketProfileRepository(Protocol):
    def get_cache(
        self, instrument_id: int, session_date: date, profile_type: str
    ) -> MarketProfileCache | None: ...
    def get_prior_session(
        self, instrument_id: int, before_date: date, profile_type: str
    ) -> MarketProfileSessionRef | None: ...
    def upsert_session(self, write: MarketProfileSessionWrite) -> None: ...


class ScoreRepository(Protocol):
    def previous_composite(
        self, instrument_id: int, timeframe: Timeframe, before_run_id: int
    ) -> float | None: ...
    def upsert_score(self, run_id: int, write: ScoreWrite) -> int: ...


class ProjectionRepository(Protocol):
    def upsert_current_analysis(self, write: ResultWrite, analysis_result_id: int) -> None: ...
    def upsert_current_score(
        self, write: ScoreWrite, signal_score_id: int, run_id: int, delta: float | None
    ) -> None: ...
    def rebuild_projections(self) -> None: ...


@dataclass(slots=True)
class Repositories:
    runs: RunRepository
    instruments: InstrumentRepository
    analysis_results: AnalysisResultRepository
    scores: ScoreRepository
    projections: ProjectionRepository
    #: market-data persistence for the real INGEST phase (Phase 2.6). Standalone
    #: repo (docs/03 §5.2 / §5.6) — not one of the analysis/scoring repos above.
    market_data: MarketDataRepository
    #: Market Profile session cache (docs/03 §5.4, docs/05 §10.11 recompute guard).
    market_profile: MarketProfileRepository | None = None
