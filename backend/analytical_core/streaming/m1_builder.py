"""Pure M1-from-ticks builder (docs/02 §3.4, docs/05 §3).

Feed it ticks (LTP + cumulative session volume + OI); it emits **1-minute OHLCV
bars anchored to the wall-clock minute, bar-open tz-aware UTC**. No IO, no
dependency. Deterministic given a tick sequence + `now` for flushes.

Rules:
* ``open`` = first tick's LTP in the minute; ``high``/``low`` extremes;
  ``close`` = last tick's LTP.
* ``volume`` = last cumulative volume seen in the minute − the cumulative volume
  carried from the previous minute's last tick (0 for the very first bucket).
* ``open_interest`` = last non-``None`` OI seen in the minute.
* A minute with **zero ticks emits no bar** — never fabricated (docs/05 §3.4).
* A bucket becomes ``is_final`` once its minute ended ≥ ``grace_seconds`` ago
  (period end + grace, docs/05 §3.6). Until then it is the forming bar.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

_MINUTE = timedelta(minutes=1)


@dataclass(frozen=True, slots=True)
class Tick:
    instrument_id: int
    ts: datetime  # tz-aware
    ltp: float
    cum_volume: int  # cumulative traded volume for the session so far
    oi: int | None = None


@dataclass(frozen=True, slots=True)
class StreamBar:
    instrument_id: int
    minute: datetime  # bar-open, tz-aware UTC
    open: float
    high: float
    low: float
    close: float
    volume: int
    open_interest: int | None
    is_final: bool


def _floor_minute(ts: datetime) -> datetime:
    return ts.astimezone(UTC).replace(second=0, microsecond=0)


@dataclass(slots=True)
class _Bucket:
    minute: datetime
    open: float
    high: float
    low: float
    close: float
    open_cum: int  # cum volume carried from the prior minute's last tick
    last_cum: int
    oi: int | None

    @classmethod
    def start(cls, t: Tick, minute: datetime, prev_last_cum: int | None) -> _Bucket:
        base = prev_last_cum if prev_last_cum is not None else t.cum_volume
        return cls(minute, t.ltp, t.ltp, t.ltp, t.ltp, base, t.cum_volume, t.oi)

    def update(self, t: Tick) -> None:
        if t.ltp > self.high:
            self.high = t.ltp
        if t.ltp < self.low:
            self.low = t.ltp
        self.close = t.ltp
        if t.cum_volume >= self.last_cum:
            self.last_cum = t.cum_volume
        if t.oi is not None:
            self.oi = t.oi

    def to_bar(self, iid: int, *, is_final: bool) -> StreamBar:
        return StreamBar(
            instrument_id=iid,
            minute=self.minute,
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=max(0, self.last_cum - self.open_cum),
            open_interest=self.oi,
            is_final=is_final,
        )


class M1Accumulator:
    """One instance per streamer. Holds the current forming bucket per instrument."""

    def __init__(self, *, grace_seconds: int = 90) -> None:
        self._grace = timedelta(seconds=grace_seconds)
        self._cur: dict[int, _Bucket] = {}

    def _is_final(self, minute: datetime, at: datetime) -> bool:
        return at.astimezone(UTC) >= minute + _MINUTE + self._grace

    def on_tick(self, t: Tick) -> list[StreamBar]:
        """Ingest one tick; return any bar(s) whose minute just rolled over."""
        m = _floor_minute(t.ts)
        b = self._cur.get(t.instrument_id)
        if b is None:
            self._cur[t.instrument_id] = _Bucket.start(t, m, None)
            return []
        if m < b.minute:
            return []  # out-of-order / stale tick for a closed minute — ignore
        if m == b.minute:
            b.update(t)
            return []
        # a later minute began -> the current bucket is closed
        rolled = b.to_bar(t.instrument_id, is_final=self._is_final(b.minute, t.ts))
        self._cur[t.instrument_id] = _Bucket.start(t, m, b.last_cum)
        return [rolled]

    def flush(self, now: datetime) -> list[StreamBar]:
        """Emit every forming bucket: finalised + dropped if its minute ended ≥
        grace ago, otherwise a non-final forming snapshot."""
        out: list[StreamBar] = []
        for iid, b in list(self._cur.items()):
            if self._is_final(b.minute, now):
                out.append(b.to_bar(iid, is_final=True))
                del self._cur[iid]
            else:
                out.append(b.to_bar(iid, is_final=False))
        return out

    def pending(self) -> list[StreamBar]:
        """Current forming buckets as non-final snapshots (no state change)."""
        return [b.to_bar(iid, is_final=False) for iid, b in self._cur.items()]
