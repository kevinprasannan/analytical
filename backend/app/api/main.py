"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from app.api.errors import install_error_handlers
from app.config import get_settings
from app.logging import configure_logging

_LOG = structlog.get_logger("api")

_TITLE = "Analytical API"
_DESC = (
    "Analytical decision-support for NSE markets. Read-only market data + "
    "deterministic analyses + run audit. No BUY/SELL/execution endpoints — now "
    "or ever (docs/07 §1, §6)."
)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Optionally run the periodic worker and/or the streamer in-process
    (docs/02 §3.7, §3.4)."""
    import threading

    settings = get_settings()
    scheduler = None
    if settings.run_worker_in_process:
        from app.worker.scheduler import build_scheduler, run_scheduled_cycle

        scheduler = build_scheduler(lambda: run_scheduled_cycle(settings), settings)
        scheduler.start()
        _LOG.info("in-process worker scheduler started", interval=settings.cycle_interval_seconds)

    stream_stop = None
    stream_thread = None
    if settings.run_stream_in_process and settings.stream_enabled:
        from app.ingestion.stream import serve as stream_serve

        stream_stop = threading.Event()
        stream_thread = threading.Thread(
            target=stream_serve,
            kwargs={"settings": settings, "stop_event": stream_stop, "install_signals": False},
            name="stream-ingestor",
            daemon=True,
        )
        stream_thread.start()
        _LOG.info("in-process streamer started", mode=settings.stream_mode)
    try:
        yield
    finally:
        if stream_stop is not None:
            stream_stop.set()
            if stream_thread is not None:
                stream_thread.join(timeout=10)
            _LOG.info("in-process streamer stopped")
        if scheduler is not None:
            scheduler.shutdown(wait=True)
            _LOG.info("in-process worker scheduler stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(level=settings.log_level, json_output=settings.log_json)

    app = FastAPI(title=_TITLE, version="1.0.0", description=_DESC, lifespan=_lifespan)

    from app.api.routers import (
        analyses,
        astro,
        backtest,
        board,
        calendar,
        candles_grid,
        config,
        constituent_levels,
        crt_grid,
        daily_digest,
        event_calendar,
        fvg_grid,
        gann_cycles,
        gap_fade_study,
        golden_cross_grid,
        health,
        index_constituents,
        instruments,
        key_levels,
        meta,
        oi_movers,
        oi_pulse,
        option_chain,
        option_strategy,
        pivots,
        premium_decay,
        quote,
        runs,
        scores,
    )

    for r in (
        health.router,
        meta.router,
        board.router,
        instruments.router,
        index_constituents.router,
        constituent_levels.router,
        backtest.router,
        analyses.router,
        scores.router,
        runs.router,
        config.router,
        calendar.router,
        option_chain.router,
        option_strategy.router,
        oi_pulse.router,
        oi_movers.router,
        daily_digest.router,
        key_levels.router,
        candles_grid.router,
        golden_cross_grid.router,
        fvg_grid.router,
        crt_grid.router,
        gann_cycles.router,
        gap_fade_study.router,
        event_calendar.router,
        pivots.router,
        premium_decay.router,
        quote.router,
        astro.router,
    ):
        app.include_router(r)

    install_error_handlers(app)
    return app


app = create_app()
