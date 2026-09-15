"""Health + readiness (docs/07 §4.1)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.api import services
from app.api.deps import get_db
from app.config import get_settings
from app.providers.registry import get_provider
from app.worker.deps import CYCLE_ADVISORY_LOCK_KEY

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
def ready(db: Session = Depends(get_db)) -> dict[str, Any]:
    settings = get_settings()

    db_ok = False
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    provider_auth = "UNKNOWN"
    try:
        provider_auth = get_provider(settings).auth_state().value
    except Exception:
        provider_auth = "UNKNOWN"

    worker_running: bool | None = None
    last_cycle_seq: int | None = None
    last_ok_age: float | None = None
    seeded_until: str | None = None
    cycle_overrun: bool | None = None
    if db_ok:
        try:
            # A try-lock that succeeds means no cycle holds the single-flight
            # advisory lock (docs/02 §3.7); release it again immediately.
            got = bool(
                db.execute(select(func.pg_try_advisory_lock(CYCLE_ADVISORY_LOCK_KEY))).scalar_one()
            )
            worker_running = not got
            if got:
                db.execute(select(func.pg_advisory_unlock(CYCLE_ADVISORY_LOCK_KEY)))

            latest = services.latest_run(db)
            last_cycle_seq = latest.cycle_seq if latest else None
            if latest and latest.started_at and latest.finished_at:
                dur = (latest.finished_at - latest.started_at).total_seconds()
                cycle_overrun = dur > settings.cycle_interval_seconds

            ok = services.last_successful_run(db)
            if ok and ok.finished_at:
                last_ok_age = (
                    datetime.now(tz=UTC) - ok.finished_at.astimezone(UTC)
                ).total_seconds()

            seeded = services.calendar_seeded_until(db)
            seeded_until = seeded.isoformat() if seeded else None
        except Exception:
            pass

    m1_age: float | None = None
    if db_ok:
        try:
            m1_age = services.recent_m1_bar_age_seconds(db)
        except Exception:
            m1_age = None

    return {
        "db_ok": db_ok,
        "provider_auth": provider_auth,
        "active_provider": settings.active_provider,
        "worker_running": worker_running,
        "calendar_seeded_until": seeded_until,
        "last_cycle_seq": last_cycle_seq,
        "last_successful_cycle_age_seconds": last_ok_age,
        "cycle_overrun": cycle_overrun,
        "stream_enabled": settings.stream_enabled,
        "stream_in_process": settings.run_stream_in_process,
        "recent_m1_bar_age_seconds": m1_age,
    }
