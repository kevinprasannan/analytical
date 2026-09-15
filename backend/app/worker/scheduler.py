"""APScheduler wiring + the scheduled-cycle tick (docs/02 §3.7).

One tick == one attempt at one execution cycle. Overlap is prevented three ways:
``max_instances=1`` + ``coalesce=True`` on the job (within a process) and the
Postgres advisory lock in :func:`app.worker.deps.worker_context` (across
processes / an out-of-band ``POST /runs``). A tick that lands while a cycle is
still running is skipped and logged, never queued.

The tick is also session-gated (:mod:`app.worker.calendar_gate`): outside the
NSE trading window it is a cheap no-op.

``build_scheduler`` returns a non-started ``BackgroundScheduler`` for embedding
in the API process (``RUN_WORKER_IN_PROCESS=true``). ``serve`` runs it as a
standalone process that blocks until SIGINT/SIGTERM.
"""

from __future__ import annotations

import signal
import threading
from collections.abc import Callable
from datetime import UTC, datetime

import structlog
from apscheduler.schedulers.background import BackgroundScheduler

from analytical_core.enums import RunTrigger
from app.config import Settings, get_settings
from app.db.session import session_scope
from app.logging import configure_logging
from app.worker.calendar_gate import evaluate_gate

_LOG = structlog.get_logger("worker.scheduler")
_JOB_ID = "analytical-cycle"
_ASTRO_JOB_ID = "analytical-astro-catchup"
_ROLL_JOB_ID = "analytical-universe-roll"
_BACKUP_JOB_ID = "analytical-db-backup"


def run_astro_catch_up(settings: Settings | None = None) -> None:
    """Timer job (docs/13 §5.4): fill any missing weekday astro rows up to today.

    Offline + idempotent + separate from the engine cycle — never raises into the
    scheduler.
    """
    settings = settings or get_settings()
    try:
        from app.astro.daily import run_catch_up

        with session_scope(settings) as session:
            run_catch_up(session, settings=settings)
    except Exception as exc:  # pragma: no cover - defensive; keep the loop alive
        _LOG.error("astro catch-up failed", error=repr(exc))


def run_universe_roll(settings: Settings | None = None) -> None:
    """Timer job (docs/04 §2.3): re-download the Upstox master and re-roll the
    tracked option universe against the current spot, so the strikes stay centred
    on the money and new weekly expiries are picked up. Idempotent; the next
    engine cycle ingests any newly-tracked contracts. Never raises."""
    settings = settings or get_settings()
    try:
        from app.instruments.roll import download_upstox_masters, roll_universe

        paths = [str(p) for p in download_upstox_masters(settings.upstox_master_dir)]
        with session_scope(settings) as session:
            report = roll_universe(session, master_paths=paths, provider=settings.active_provider)
        _LOG.info(
            "universe roll done",
            now_tracked=report["now_tracked"],
            added=report["tracked_added"],
            removed=report["tracked_removed"],
            spots=report["spots"],
        )
    except Exception as exc:  # pragma: no cover - defensive; keep the loop alive
        _LOG.error("universe roll failed", error=repr(exc))


def run_db_backup(settings: Settings | None = None) -> None:
    """Timer job: nightly ``pg_dump`` to ``db_backup_dir``, pruned to the newest
    ``db_backup_keep``. Never raises into the scheduler."""
    settings = settings or get_settings()
    try:
        from app.ops.backup import run_backup

        run_backup(settings)
    except Exception as exc:  # pragma: no cover - defensive; keep the loop alive
        _LOG.error("db backup failed", error=repr(exc))


def build_scheduler(
    run_once: Callable[[], object],
    settings: Settings | None = None,
) -> BackgroundScheduler:
    settings = settings or get_settings()
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        run_once,
        trigger="interval",
        seconds=settings.cycle_interval_seconds,
        id=_JOB_ID,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=30,
    )
    if settings.astro_daily_catchup:
        scheduler.add_job(
            lambda: run_astro_catch_up(settings),
            trigger="interval",
            seconds=settings.astro_catchup_interval_seconds,
            id=_ASTRO_JOB_ID,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=600,
        )
    if settings.universe_daily_roll:
        scheduler.add_job(
            lambda: run_universe_roll(settings),
            trigger="interval",
            seconds=settings.universe_roll_interval_seconds,
            id=_ROLL_JOB_ID,
            next_run_time=datetime.now(UTC),  # roll once on start
            max_instances=1,
            coalesce=True,
            misfire_grace_time=900,
        )
    if settings.db_backup_enabled:
        scheduler.add_job(
            lambda: run_db_backup(settings),
            trigger="interval",
            seconds=settings.db_backup_interval_seconds,
            id=_BACKUP_JOB_ID,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )
    return scheduler


def run_scheduled_cycle(settings: Settings | None = None) -> None:
    """One scheduled tick: gate on the session, then run a cycle under single-flight.

    Never raises — a scheduler job that raises would just be logged by APScheduler
    and the loop would carry on anyway; doing it here keeps the log line ours.
    """
    settings = settings or get_settings()
    try:
        with session_scope(settings) as session:
            decision = evaluate_gate(session, settings=settings)
        if not decision.should_run:
            _LOG.info("scheduled tick skipped", reason=decision.reason)
            return

        from app.worker.cycle import run_cycle
        from app.worker.deps import SingleFlightBusy, worker_context

        try:
            with worker_context(settings) as (repos, provider, app_settings):
                result = run_cycle(
                    repos,
                    provider,
                    trigger=RunTrigger.SCHEDULED,
                    settings=settings,
                    app_settings=app_settings,
                )
            _LOG.info(
                "scheduled cycle complete",
                run_id=result.run_id,
                cycle_seq=result.cycle_seq,
                status=result.status.value,
            )
        except SingleFlightBusy:
            _LOG.info("scheduled tick skipped", reason="a cycle is already running")
    except Exception as exc:  # pragma: no cover - defensive; keep the loop alive
        _LOG.error("scheduled tick failed", error=repr(exc))


def serve(settings: Settings | None = None, *, run_on_start: bool | None = None) -> int:
    """Run the periodic loop until SIGINT/SIGTERM. Blocks. Returns a process exit code."""
    settings = settings or get_settings()
    configure_logging(level=settings.log_level, json_output=settings.log_json)
    run_on_start = settings.scheduler_run_on_start if run_on_start is None else run_on_start

    stop = threading.Event()
    scheduler = build_scheduler(lambda: run_scheduled_cycle(settings), settings)

    def _handle(signum, _frame):  # noqa: ANN001 - signal handler signature
        _LOG.info("scheduler shutdown signal", signal=signal.Signals(signum).name)
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _handle)

    scheduler.start()
    _LOG.info(
        "scheduler started",
        interval_seconds=settings.cycle_interval_seconds,
        session_only=settings.scheduler_session_only,
        astro_catchup=settings.astro_daily_catchup,
    )
    if settings.astro_daily_catchup:
        run_astro_catch_up(settings)  # get "today" in place immediately
    if run_on_start:
        run_scheduled_cycle(settings)

    stop.wait()
    scheduler.shutdown(wait=True)
    _LOG.info("scheduler stopped")
    return 0
