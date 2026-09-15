"""Engine input containers (docs/04 §3.1).

Pure data. The caller (`app/analysis/`) builds these from `ohlcv_bars` /
`open_interest` rows; the indicators in `analytical_core.indicators` consume them
and never see an `Instrument`, a DB row, or a provider.

Contract (docs/04 §3.1 "Contract rules"):
  * `ts` strictly increasing, unique, tz-aware **UTC**, bar-open;
  * OHLC finite, `low <= min(open, close, high)` not enforced (provider truth),
    but no NaN/inf;
  * `volume >= 0`;
  * no bar is fabricated for a no-trade interval — gaps are real (`docs/05` §3.4);
  * `expected_grid_len` is the session-anchored period count, for `coverage_ratio`.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time

from analytical_core.enums import AnalysisScope, Timeframe


class SeriesContractError(ValueError):
    """An input series violates the docs/04 §3.1 contract."""


def _check_ts(ts: Sequence[datetime]) -> None:
    """Require tz-aware, strictly increasing timestamps. The offset need not be
    zero — a bar-open instant rendered in IST is the same instant as in UTC; the
    caller is expected to normalise, but ordering/awareness is what the engine
    needs (`docs/04` §3.1)."""
    prev: datetime | None = None
    for t in ts:
        if t.tzinfo is None or t.utcoffset() is None:
            raise SeriesContractError(f"timestamp {t!r} is not tz-aware")
        if prev is not None and t <= prev:
            raise SeriesContractError(f"timestamps not strictly increasing at {t!r}")
        prev = t


def _check_finite(name: str, xs: Sequence[float]) -> None:
    for x in xs:
        if not math.isfinite(x):
            raise SeriesContractError(f"{name} contains a non-finite value: {x!r}")


@dataclass(frozen=True, slots=True)
class OHLCVSeries:
    timeframe: Timeframe
    ts: tuple[datetime, ...]
    open: tuple[float, ...]
    high: tuple[float, ...]
    low: tuple[float, ...]
    close: tuple[float, ...]
    volume: tuple[int, ...]
    is_final: tuple[bool, ...]
    expected_grid_len: int

    def __post_init__(self) -> None:
        n = len(self.ts)
        for name in ("open", "high", "low", "close", "volume", "is_final"):
            if len(getattr(self, name)) != n:
                raise SeriesContractError(
                    f"{name} length {len(getattr(self, name))} != ts length {n}"
                )
        _check_ts(self.ts)
        for name in ("open", "high", "low", "close"):
            _check_finite(name, getattr(self, name))
        if any(v < 0 for v in self.volume):
            raise SeriesContractError("volume has a negative value")
        if self.expected_grid_len < 0:
            raise SeriesContractError("expected_grid_len must be >= 0")

    def __len__(self) -> int:
        return len(self.ts)

    @property
    def last_bar_final(self) -> bool:
        return bool(self.is_final[-1]) if self.is_final else True

    @property
    def coverage_ratio(self) -> float:
        if self.expected_grid_len <= 0:
            return 1.0
        return round(len(self.ts) / self.expected_grid_len, 6)

    @property
    def gap_count(self) -> int:
        """Missing interior periods vs a contiguous fill of the observed span."""
        return max(0, self.expected_grid_len - len(self.ts)) if self.expected_grid_len else 0


@dataclass(frozen=True, slots=True)
class OpenInterestSeries:
    scope: AnalysisScope  # PER_TIMEFRAME (branch A) or SNAPSHOT (branch B)
    ts: tuple[datetime, ...]
    oi: tuple[int, ...]
    price: tuple[float, ...]  # the instrument's OWN price series, aligned 1:1
    provider_oi_change: tuple[int, ...] | None = None  # cross-check only; NOT used
    is_final: tuple[bool, ...] | None = None

    def __post_init__(self) -> None:
        n = len(self.ts)
        if len(self.oi) != n or len(self.price) != n:
            raise SeriesContractError("oi/price length mismatch with ts")
        if self.provider_oi_change is not None and len(self.provider_oi_change) != n:
            raise SeriesContractError("provider_oi_change length mismatch with ts")
        if self.is_final is not None and len(self.is_final) != n:
            raise SeriesContractError("is_final length mismatch with ts")
        _check_ts(self.ts)
        _check_finite("price", self.price)
        if any(v < 0 for v in self.oi):
            raise SeriesContractError("oi has a negative value")

    def __len__(self) -> int:
        return len(self.ts)

    @property
    def last_bar_final(self) -> bool:
        if not self.is_final:
            return True
        return bool(self.is_final[-1])


@dataclass(frozen=True, slots=True)
class SessionSpec:
    tz: str = "Asia/Kolkata"
    session_open_ist: time = time(9, 15)
    session_close_ist: time = time(15, 30)
    session_date: date | None = None

    def open_close_utc(self, on: date) -> tuple[datetime, datetime]:
        from zoneinfo import ZoneInfo

        z = ZoneInfo(self.tz)
        o = datetime.combine(on, self.session_open_ist, tzinfo=z).astimezone(UTC)
        c = datetime.combine(on, self.session_close_ist, tzinfo=z).astimezone(UTC)
        return o, c
