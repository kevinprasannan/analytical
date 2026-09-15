"""``StubMarketFeed`` — a deterministic synthetic tick stream (docs/02 §3.4).

For dev + tests: no network, no auth. Emits ``minutes`` worth of ticks per
subscribed symbol at ``interval_seconds`` spacing, a smooth price walk with
monotonically rising cumulative volume and slowly rising OI. Finite — the
iterator ends after the last tick (or when :meth:`close` is called).
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime, timedelta

from app.providers.base import StreamTick


def _base_price(symbol: str) -> float:
    return 100.0 + (abs(hash(symbol)) % 9000)


class StubMarketFeed:
    def __init__(
        self,
        *,
        start: datetime | None = None,
        minutes: int = 3,
        interval_seconds: int = 5,
    ) -> None:
        self._start = (start or datetime(2026, 8, 31, 3, 45, tzinfo=UTC)).astimezone(UTC)
        self._minutes = minutes
        self._interval = interval_seconds
        self._closed = False

    def close(self) -> None:
        self._closed = True

    def subscribe(
        self, provider_symbols: Sequence[str], *, mode: str = "full"
    ) -> Iterator[StreamTick]:
        n = (self._minutes * 60) // self._interval
        state = {s: (_base_price(s), 0) for s in provider_symbols}
        for i in range(n):
            if self._closed:
                return
            ts = self._start + timedelta(seconds=i * self._interval)
            for s in provider_symbols:
                base, cum = state[s]
                ltp = round(base + base * 0.001 * math.sin(i / 7.0) + i * 0.02, 2)
                cum += 10 + (i % 5)
                oi = 10_000 + i * 3 if mode != "ltpc" else None
                state[s] = (base, cum)
                yield StreamTick(provider_symbol=s, ts=ts, ltp=ltp, cum_volume=cum, oi=oi)
