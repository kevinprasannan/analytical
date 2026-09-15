"""Assemble worker dependencies from settings (production wiring).

Adds Phase 2.6:
  * the live provider is built with a shared thread-safe request budget so the
    concurrent INGEST fetch stays under the provider limits (docs/02 §6.7);
  * a Postgres **session-level advisory lock** enforces single-flight — a
    scheduled tick that fires while a cycle runs is skipped, not queued
    (docs/02 §3.7).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import func, select

from app.config import Settings, get_settings
from app.db.repositories import Repositories
from app.db.repositories.sqlalchemy import build_sqlalchemy_repositories
from app.db.session import session_scope
from app.ingestion.budget import RequestBudget
from app.providers.base import MarketDataProvider
from app.providers.factory import build_live_provider
from app.settings_store import load_app_settings

WorkerContext = tuple[Repositories, MarketDataProvider, dict[str, Any]]

#: stable arbitrary key for the single-flight advisory lock.
CYCLE_ADVISORY_LOCK_KEY = 0x414E4C_43_31  # "ANL C 1"


class SingleFlightBusy(RuntimeError):
    """Another cycle already holds the advisory lock; this tick is skipped."""


@contextmanager
def worker_context(
    settings: Settings | None = None,
    *,
    single_flight: bool = True,
) -> Iterator[WorkerContext]:
    settings = settings or get_settings()
    budget = RequestBudget(
        max_rps=settings.provider_max_rps, per_30min=settings.provider_30min_budget
    )
    provider, close = build_live_provider(settings, budget=budget)
    try:
        with session_scope(settings) as session:
            locked = False
            if single_flight:
                locked = bool(
                    session.execute(
                        select(func.pg_try_advisory_lock(CYCLE_ADVISORY_LOCK_KEY))
                    ).scalar_one()
                )
                if not locked:
                    raise SingleFlightBusy("another execution cycle is running")
            try:
                yield (
                    build_sqlalchemy_repositories(session),
                    provider,
                    load_app_settings(session),
                )
            finally:
                if locked:
                    session.execute(select(func.pg_advisory_unlock(CYCLE_ADVISORY_LOCK_KEY)))
    finally:
        close()
