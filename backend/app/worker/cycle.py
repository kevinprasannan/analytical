"""The one-cycle lifecycle (docs/02 §4)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

import structlog

from analytical_core.enums import (
    InstrumentPhaseOutcome,
    PhaseStatus,
    RunPhase,
    RunStatus,
    RunTrigger,
)
from analytical_core.market_profile import MarketProfileConfig
from analytical_core.params import params_hash
from analytical_core.scoring import ScoringConfig
from analytical_core.versioning import ALGO_VERSION, SCORING_VERSION
from app.analysis.service import AnalysisService
from app.config import Settings, get_settings
from app.db.repositories.protocols import Repositories
from app.ingestion import IngestionService
from app.pipeline import PhaseOutcome
from app.providers.base import MarketDataProvider, ProviderError
from app.scoring import ScoringService
from app.worker.hooks import fire_run_completed

_LOG = structlog.get_logger("worker.cycle")

DEFAULT_PHASES: tuple[RunPhase, ...] = (RunPhase.INGEST, RunPhase.ANALYZE, RunPhase.SCORE)


def create_pending_run(
    repos: Repositories,
    *,
    trigger: RunTrigger = RunTrigger.MANUAL,
    phases: tuple[RunPhase, ...] = DEFAULT_PHASES,
    app_settings: dict | None = None,
    extra_snapshot: dict | None = None,
) -> tuple[int, int]:
    """Allocate a ``cycle_seq`` and write the ``analysis_runs`` row (status RUNNING).

    Split out of :func:`run_cycle` so an async ``POST /runs`` can create the row
    up-front, return its id, and hand execution to a background task via
    ``run_cycle(..., run_id=..., cycle_seq=...)``.
    """
    scoring_config = ScoringConfig.from_app_settings(app_settings)
    mp_config = MarketProfileConfig.from_app_settings(app_settings)
    cycle_seq = repos.runs.next_cycle_seq()
    config_snapshot: dict = {
        "phases": [p.value for p in phases],
        "algo_version": ALGO_VERSION,
        "scoring_version": SCORING_VERSION,
        "scoring": scoring_config.as_effective_dict(),
        "market_profile": mp_config.as_dict(),
    }
    if extra_snapshot:
        config_snapshot.update(extra_snapshot)
    run_id = repos.runs.create_run(
        cycle_seq=cycle_seq,
        trigger=trigger,
        phases_requested=[p.value for p in phases],
        algo_version=ALGO_VERSION,
        scoring_version=SCORING_VERSION,
        config_snapshot=config_snapshot,
        params_hash=params_hash(config_snapshot),
    )
    return run_id, cycle_seq


@dataclass(slots=True)
class CycleResult:
    run_id: int
    cycle_seq: int
    status: RunStatus
    phases: dict[RunPhase, PhaseOutcome] = field(default_factory=dict)
    crashed: bool = False


def run_cycle(
    repos: Repositories,
    provider: MarketDataProvider,
    *,
    trigger: RunTrigger = RunTrigger.MANUAL,
    phases: tuple[RunPhase, ...] = DEFAULT_PHASES,
    now_fn: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
    settings: Settings | None = None,
    app_settings: dict | None = None,
    run_id: int | None = None,
    cycle_seq: int | None = None,
    on_complete: Callable[[CycleResult], None] | None = None,
) -> CycleResult:
    """Run exactly one execution cycle. Tolerates partial provider/instrument failure.

    Never raises for provider/instrument-level problems: they become
    DEGRADED/SKIPPED/ERROR outcomes and a PARTIAL / FAILED run status.

    ``app_settings`` (the flat ``app_settings`` key/value map) is folded into the
    effective ``ScoringConfig`` / ``MarketProfileConfig`` for this cycle and
    recorded in ``analysis_runs.config_snapshot`` (docs/06 §7, docs/05 §10.1).
    ``None`` ⇒ engine defaults.

    ``run_id`` + ``cycle_seq`` (both, or neither): reuse a row already written by
    :func:`create_pending_run` instead of creating one here — the async
    ``POST /runs`` path.
    """
    settings = settings or get_settings()
    scoring_config = ScoringConfig.from_app_settings(app_settings)
    mp_config = MarketProfileConfig.from_app_settings(app_settings)
    if run_id is None:
        run_id, cycle_seq = create_pending_run(
            repos, trigger=trigger, phases=phases, app_settings=app_settings
        )
    elif cycle_seq is None:
        raise ValueError("run_cycle: pass cycle_seq together with run_id")

    tokens = structlog.contextvars.bind_contextvars(run_id=run_id, cycle_seq=cycle_seq)
    result = CycleResult(run_id=run_id, cycle_seq=cycle_seq, status=RunStatus.RUNNING)
    try:
        instruments = repos.instruments.list_tracked()
        try:
            caps = provider.capabilities()
        except ProviderError as exc:  # provider inert -> cannot analyse; FAILED cycle
            _LOG.error("provider.capabilities failed", error=str(exc))
            _fail_all_phases(repos, run_id, phases, now_fn(), reason=str(exc))
            repos.runs.finalize_run(run_id, RunStatus.FAILED, now_fn())
            result.status = RunStatus.FAILED
            _fire_hook(on_complete, result)
            return result

        eligible: set[int] = {inst.id for inst in instruments}

        # --- INGEST ---
        if RunPhase.INGEST in phases:
            po = _run_phase(
                repos,
                run_id,
                RunPhase.INGEST,
                now_fn,
                lambda: IngestionService(
                    provider, repos.market_data, settings=settings, now=now_fn()
                ).run(instruments),
            )
            result.phases[RunPhase.INGEST] = po
            eligible = po.eligible_ids() if po.instrument_outcomes else eligible

        # --- ANALYZE ---
        if RunPhase.ANALYZE in phases:
            po = _run_phase(
                repos,
                run_id,
                RunPhase.ANALYZE,
                now_fn,
                lambda: AnalysisService(
                    repos.analysis_results,
                    repos.projections,
                    caps,
                    market_data=repos.market_data,
                    market_profile_repo=repos.market_profile,
                    market_profile_config=mp_config,
                    provider_id=settings.active_provider,
                    now=now_fn(),
                ).run(run_id, instruments, eligible),
            )
            result.phases[RunPhase.ANALYZE] = po
            eligible = po.eligible_ids() if po.instrument_outcomes else eligible

        # --- SCORE ---
        if RunPhase.SCORE in phases:
            po = _run_phase(
                repos,
                run_id,
                RunPhase.SCORE,
                now_fn,
                lambda: ScoringService(
                    repos.scores,
                    repos.projections,
                    repos.analysis_results,
                    config=scoring_config,
                    now=now_fn(),
                ).run(run_id, instruments, eligible),
            )
            result.phases[RunPhase.SCORE] = po

        result.status = _final_status(result.phases)
        repos.runs.finalize_run(run_id, result.status, now_fn())
        _LOG.info("cycle complete", status=result.status.value)
        _fire_hook(on_complete, result)
        return result
    except Exception as exc:  # unexpected -> mark FAILED, do not propagate a crash
        result.crashed = True
        result.status = RunStatus.FAILED
        _LOG.error("cycle crashed", error=repr(exc))
        try:
            repos.runs.finalize_run(run_id, RunStatus.FAILED, now_fn())
        except Exception:  # pragma: no cover
            pass
        _fire_hook(on_complete, result)
        return result
    finally:
        structlog.contextvars.reset_contextvars(**tokens)


def _fire_hook(hook: Callable[[CycleResult], None] | None, result: CycleResult) -> None:
    """`run-completed` hook point (docs/02 §3.7). A hook must never break a cycle.

    Fires the per-call ``on_complete`` (if any) plus every subscriber in
    ``app.worker.hooks`` (the always-on structured-log sink, and future ones like
    alerts).
    """
    if hook is not None:
        try:
            hook(result)
        except Exception as exc:  # pragma: no cover - defensive
            _LOG.error("run-completed hook raised", error=repr(exc))
    fire_run_completed(result)


def _run_phase(
    repos: Repositories,
    run_id: int,
    phase: RunPhase,
    now_fn: Callable[[], datetime],
    body: Callable[[], PhaseOutcome],
) -> PhaseOutcome:
    started = now_fn()
    repos.runs.set_phase_status(
        run_id, phase, PhaseStatus.RUNNING, counts={}, started_at=started, finished_at=None
    )
    try:
        po = body()
    except Exception as exc:  # a whole phase could not run
        finished = now_fn()
        repos.runs.set_phase_status(
            run_id,
            phase,
            PhaseStatus.FAILED,
            counts={},
            started_at=started,
            finished_at=finished,
            detail={"error": repr(exc)},
        )
        return PhaseOutcome(phase=phase, status=PhaseStatus.FAILED, detail={"error": repr(exc)})
    finished = now_fn()
    for iid, oc in po.instrument_outcomes.items():
        repos.runs.set_instrument_status(run_id, iid, phase, oc)
    repos.runs.set_phase_status(
        run_id,
        phase,
        po.status,
        counts=po.counts,
        started_at=started,
        finished_at=finished,
        detail=po.detail,
    )
    return po


def _fail_all_phases(repos, run_id, phases, now, *, reason: str) -> None:
    for p in phases:
        repos.runs.set_phase_status(
            run_id,
            p,
            PhaseStatus.FAILED,
            counts={},
            started_at=now,
            finished_at=now,
            detail={"reason": reason},
        )


def _final_status(phases: dict[RunPhase, PhaseOutcome]) -> RunStatus:
    statuses = {po.status for po in phases.values()}
    if PhaseStatus.FAILED in statuses:
        return RunStatus.FAILED
    non_ok = any(
        oc is not InstrumentPhaseOutcome.OK
        for po in phases.values()
        for oc in po.instrument_outcomes.values()
    )
    if non_ok or statuses & {PhaseStatus.PARTIAL, PhaseStatus.SKIPPED}:
        return RunStatus.PARTIAL
    return RunStatus.SUCCEEDED
