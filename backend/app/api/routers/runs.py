"""Runs / cycles (docs/07 §4.6).

``POST /runs`` is **async**: it writes the ``analysis_runs`` row, returns
``202`` + ``Location``, and executes the cycle in a background task. Clients poll
``GET /runs/{id}``. A repeated ``Idempotency-Key`` (within
``idempotency_window_seconds``) replays the existing run with ``200`` instead of
starting another cycle. A cycle already in flight → ``409`` + ``Retry-After``.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, Header, Query, Response
from sqlalchemy.orm import Session

from analytical_core.enums import RunPhase, RunStatus, RunTrigger
from app.api import services
from app.api.deps import Principal, get_current_principal, get_db
from app.api.errors import conflict, not_found
from app.api.schemas.common import Page
from app.api.schemas.runs import (
    InstrumentStatusItem,
    PhaseStatusItem,
    RunDetail,
    RunSummary,
    RunTriggerRequest,
)
from app.config import Settings, get_settings

router = APIRouter(prefix="/api/v1/runs", tags=["runs"])
_LOG = structlog.get_logger("api.runs")


def _summary(run) -> RunSummary:
    return RunSummary(
        id=run.id,
        cycle_seq=run.cycle_seq,
        trigger=run.trigger,
        status=run.status,
        started_at=run.started_at,
        finished_at=run.finished_at,
        algo_version=run.algo_version,
        scoring_version=run.scoring_version,
    )


@router.get("", response_model=Page[RunSummary])
def list_runs(
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> Page[RunSummary]:
    rows, total = services.list_runs(db, limit=limit, offset=offset)
    return Page(items=[_summary(r) for r in rows], total=total, limit=limit, offset=offset)


@router.get("/{run_id}", response_model=RunDetail)
def get_run(run_id: int, db: Session = Depends(get_db)) -> RunDetail:
    run = services.get_run(db, run_id)
    if run is None:
        raise not_found("run")
    detail = RunDetail(
        **_summary(run).model_dump(),
        phases_requested=list(run.phases_requested or []),
        config_snapshot=run.config_snapshot or {},
        params_hash=run.params_hash,
    )
    detail.phase_status = [
        PhaseStatusItem(
            phase=p.phase,
            status=p.status,
            started_at=p.started_at,
            finished_at=p.finished_at,
            counts=p.counts or {},
            detail=p.detail or {},
        )
        for p in services.run_phase_status(db, run_id)
    ]
    detail.instrument_status = [
        InstrumentStatusItem(instrument_id=i.instrument_id, phase=i.phase, outcome=i.outcome.value)
        for i in services.run_instrument_status(db, run_id)
    ]
    return detail


@router.post("", response_model=RunDetail, status_code=202)
def trigger_run(
    body: RunTriggerRequest,
    response: Response,
    background_tasks: BackgroundTasks,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    _principal: Principal = Depends(get_current_principal),
) -> RunDetail:
    from app.worker.cycle import create_pending_run
    from app.worker.deps import SingleFlightBusy, worker_context

    settings = get_settings()
    trigger = body.trigger if body.trigger != RunTrigger.SCHEDULED else RunTrigger.MANUAL
    phases = tuple(body.phases)

    if idempotency_key:
        prior = services.find_run_by_idempotency_key(
            db, idempotency_key, settings.idempotency_window_seconds
        )
        if prior is not None:
            response.status_code = 200
            response.headers["Location"] = f"/api/v1/runs/{prior.id}"
            return get_run(prior.id, db)

    try:
        with worker_context(settings) as (repos, _provider, app_settings):
            run_id, cycle_seq = create_pending_run(
                repos,
                trigger=trigger,
                phases=phases,
                app_settings=app_settings,
                extra_snapshot=({"idempotency_key": idempotency_key} if idempotency_key else None),
            )
    except SingleFlightBusy:
        raise conflict("an execution cycle is already running", retry_after=30) from None

    background_tasks.add_task(_execute_cycle, settings, run_id, cycle_seq, trigger, phases)
    response.headers["Location"] = f"/api/v1/runs/{run_id}"
    return get_run(run_id, db)


def _execute_cycle(
    settings: Settings,
    run_id: int,
    cycle_seq: int,
    trigger: RunTrigger,
    phases: tuple[RunPhase, ...],
) -> None:
    """Background body for an async ``POST /runs``. ``run_cycle`` already absorbs
    provider/instrument-level failure; this only has to handle not starting."""
    from app.providers.base import ProviderError
    from app.worker.cycle import run_cycle
    from app.worker.deps import SingleFlightBusy, worker_context

    try:
        with worker_context(settings) as (repos, provider, app_settings):
            run_cycle(
                repos,
                provider,
                run_id=run_id,
                cycle_seq=cycle_seq,
                trigger=trigger,
                phases=phases,
                settings=settings,
                app_settings=app_settings,
            )
    except SingleFlightBusy:
        _fail_pending(settings, run_id, "another cycle acquired the single-flight lock")
    except ProviderError as exc:  # pragma: no cover - provider wiring
        _fail_pending(settings, run_id, f"provider unavailable: {exc}")
    except Exception as exc:  # pragma: no cover - defensive
        _fail_pending(settings, run_id, repr(exc))


def _fail_pending(settings: Settings, run_id: int, reason: str) -> None:
    from datetime import UTC, datetime

    from app.db.repositories.sqlalchemy import build_sqlalchemy_repositories
    from app.db.session import session_scope

    _LOG.warning("async cycle did not run", run_id=run_id, reason=reason)
    try:
        with session_scope(settings) as s:
            build_sqlalchemy_repositories(s).runs.finalize_run(
                run_id, RunStatus.FAILED, datetime.now(tz=UTC)
            )
    except Exception as exc:  # pragma: no cover - defensive
        _LOG.error("could not finalize pending run", run_id=run_id, error=repr(exc))
