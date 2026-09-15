"""Thread-safe provider request budget (Phase 2.5, docs/02 §6.7).

Two limits enforced on every acquisition:

* a per-second ceiling (``PROVIDER_MAX_RPS``, minimum spacing between requests);
* a rolling 30-minute quota (``PROVIDER_30MIN_BUDGET`` — 10 % headroom under the
  Upstox 2000/30min ceiling, docs/11 PV-5).

``acquire()`` blocks (sleeps) until both are satisfied, so a backfill running
several instruments concurrently cannot exceed the provider's limits. The clock
and sleep are injectable for deterministic tests.
"""

from __future__ import annotations

import threading
import time as _time
from collections import deque
from collections.abc import Callable

_WINDOW_SECONDS = 30 * 60


class RequestBudget:
    def __init__(
        self,
        *,
        max_rps: float,
        per_30min: int,
        window_seconds: int = _WINDOW_SECONDS,
        time_fn: Callable[[], float] = _time.monotonic,
        sleep_fn: Callable[[float], None] = _time.sleep,
    ) -> None:
        self._min_interval = 1.0 / max_rps if max_rps > 0 else 0.0
        self._per_30min = per_30min
        self._window = window_seconds
        self._time = time_fn
        self._sleep = sleep_fn
        self._lock = threading.Lock()
        self._last: float | None = None
        self._hits: deque[float] = deque()  # monotonic timestamps of granted requests
        self.granted = 0
        self.waited_seconds = 0.0

    def _prune(self, now: float) -> None:
        cutoff = now - self._window
        while self._hits and self._hits[0] <= cutoff:
            self._hits.popleft()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = self._time()
                self._prune(now)

                spacing_wait = 0.0
                if self._min_interval > 0.0 and self._last is not None:
                    spacing_wait = max(0.0, self._min_interval - (now - self._last))

                quota_wait = 0.0
                if self._per_30min > 0 and len(self._hits) >= self._per_30min:
                    quota_wait = (self._hits[0] + self._window) - now

                wait = max(spacing_wait, quota_wait)
                if wait <= 0.0:
                    self._last = now
                    self._hits.append(now)
                    self.granted += 1
                    return
                self.waited_seconds += wait
            # sleep outside the lock so other threads can re-evaluate
            self._sleep(wait)

    def snapshot(self) -> dict[str, float | int]:
        with self._lock:
            self._prune(self._time())
            return {
                "granted": self.granted,
                "in_window": len(self._hits),
                "budget_30min": self._per_30min,
                "waited_seconds": round(self.waited_seconds, 3),
            }
