"""Streaming ingestor (docs/02 §3.4) — forming M1 bar + live OI only.

A separate long-running loop: `provider feed → analytical_core M1 builder →
ohlcv_bars / open_interest`. History, backfill and disconnect gap-fill stay on
REST. The deterministic cycle is untouched.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import structlog

from analytical_core.enums import Timeframe
from analytical_core.streaming import M1Accumulator, StreamBar, Tick
from app.config import Settings, get_settings
from app.db.repositories.market_data import MarketDataRepository, OIRow
from app.providers.base import StreamingMarketDataProvider

_LOG = structlog.get_logger("ingestion.stream")
_STREAM_SOURCE = "stream:m1"


def _to_bar(b: StreamBar):
    from app.providers.base import OHLCVBar

    return OHLCVBar(
        ts=b.minute,
        open=Decimal(str(b.open)),
        high=Decimal(str(b.high)),
        low=Decimal(str(b.low)),
        close=Decimal(str(b.close)),
        volume=b.volume,
        is_final=b.is_final,
        source=_STREAM_SOURCE,
        open_interest=b.open_interest,
    )


class StreamIngestor:
    def __init__(
        self,
        feed: StreamingMarketDataProvider,
        market_data: MarketDataRepository,
        *,
        symbol_to_instrument: dict[str, int],
        provider: str,
        grace_seconds: int = 90,
        flush_interval_seconds: int = 10,
        now_fn=lambda: datetime.now(tz=UTC),
        commit_fn=None,
    ) -> None:
        self._feed = feed
        self._repo = market_data
        self._map = symbol_to_instrument
        self._provider = provider
        self._acc = M1Accumulator(grace_seconds=grace_seconds)
        self._flush_every = timedelta(seconds=flush_interval_seconds)
        self._now = now_fn
        self._commit = commit_fn or (lambda: None)
        self._stop = threading.Event()
        self.bars_written = 0
        self.ticks_seen = 0

    def stop(self) -> None:
        self._stop.set()
        self._feed.close()

    def run(self, provider_symbols: Sequence[str], *, mode: str = "full") -> None:
        last_flush = self._now()
        for st in self._feed.subscribe(provider_symbols, mode=mode):
            if self._stop.is_set():
                break
            self.ticks_seen += 1
            iid = self._map.get(st.provider_symbol)
            if iid is None:
                continue
            self._persist(self._acc.on_tick(Tick(iid, st.ts, st.ltp, st.cum_volume, st.oi)))
            now = self._now()
            if now - last_flush >= self._flush_every:
                self._persist(self._acc.flush(now))
                self._commit()
                last_flush = now
        # feed ended -> finalise everything still forming
        self._persist(self._acc.flush(self._now() + timedelta(days=1)))
        self._commit()
        _LOG.info("stream ended", ticks=self.ticks_seen, bars_written=self.bars_written)

    def _persist(self, bars: list[StreamBar]) -> None:
        if not bars:
            return
        by_inst: dict[int, list[StreamBar]] = {}
        for b in bars:
            by_inst.setdefault(b.instrument_id, []).append(b)
        for iid, group in by_inst.items():
            self._repo.upsert_ohlcv_bars(
                instrument_id=iid,
                timeframe=Timeframe.M1,
                provider=self._provider,
                bars=[_to_bar(b) for b in group],
            )
            oi_rows = [
                OIRow(ts=b.minute, oi=b.open_interest, is_final=b.is_final)
                for b in group
                if b.open_interest is not None
            ]
            if oi_rows:
                self._repo.upsert_open_interest(
                    instrument_id=iid,
                    timeframe=Timeframe.M1,
                    provider=self._provider,
                    rows=oi_rows,
                )
            self.bars_written += len(group)


def build_symbol_map(session, provider: str) -> dict[str, int]:
    """`{provider_symbol: instrument_id}` for every tracked instrument."""
    from sqlalchemy import select

    from app.db import models as m

    rows = session.execute(
        select(m.ProviderInstrumentMap.provider_symbol, m.ProviderInstrumentMap.instrument_id)
        .join(m.Instrument, m.Instrument.id == m.ProviderInstrumentMap.instrument_id)
        .where(
            m.Instrument.is_tracked.is_(True),
            m.ProviderInstrumentMap.provider == provider,
            m.ProviderInstrumentMap.is_active.is_(True),
        )
    ).all()
    return {sym: iid for sym, iid in rows}


_GATE_RECHECK_SECONDS = 60


def serve(
    settings: Settings | None = None,
    *,
    mode: str | None = None,
    stop_event: threading.Event | None = None,
    install_signals: bool = True,
) -> int:
    """Run the streaming ingestor until stopped, reconnecting on a dropped feed.

    Session-gated (``scheduler_session_only`` + the shared ``market_calendar``
    window): outside the NSE session the loop idles and re-checks. Used by the
    ``analytical-worker stream`` CLI and, optionally, an in-process API thread.
    """
    from app.db.repositories.market_data import SaMarketDataRepository
    from app.db.session import session_scope
    from app.providers.factory import build_streaming_provider
    from app.worker.calendar_gate import evaluate_gate

    settings = settings or get_settings()
    mode = mode or settings.stream_mode
    stopping = stop_event or threading.Event()

    if install_signals:
        import signal

        def _sig(signum, _frame):  # noqa: ANN001
            _LOG.info("stream shutdown signal", signal=signal.Signals(signum).name)
            stopping.set()

        try:
            for s in (signal.SIGINT, signal.SIGTERM):
                signal.signal(s, _sig)
        except ValueError:  # not the main thread — caller drives stop_event
            pass

    while not stopping.is_set():
        with session_scope(settings) as gate_sess:
            gate = evaluate_gate(gate_sess, settings=settings)
        if not gate.should_run:
            _LOG.info("stream idle — outside session window", reason=gate.reason)
            stopping.wait(timeout=_GATE_RECHECK_SECONDS)
            continue

        feed, close = build_streaming_provider(settings)
        try:
            with session_scope(settings) as session:
                symbol_map = build_symbol_map(session, settings.active_provider)
                repo = SaMarketDataRepository(session)
                ing = StreamIngestor(
                    feed,
                    repo,
                    symbol_to_instrument=symbol_map,
                    provider=settings.active_provider,
                    grace_seconds=settings.finalize_grace_seconds,
                    flush_interval_seconds=settings.stream_flush_seconds,
                    commit_fn=session.commit,
                )
                _LOG.info("stream connected", instruments=len(symbol_map), mode=mode)
                ing.run(list(symbol_map), mode=mode)
        except Exception as exc:  # pragma: no cover - reconnect on any feed error
            _LOG.error("stream error; will reconnect", error=repr(exc))
        finally:
            close()
        if not stopping.is_set():
            stopping.wait(timeout=settings.stream_reconnect_seconds)
    _LOG.info("stream stopped")
    return 0
