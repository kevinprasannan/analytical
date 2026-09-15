"""Key levels from the last two completed sessions' profiles (docs/05 §10.12).

Pure and deterministic. Takes the previous two sessions' Market-Profile levels
(POC / VAH / VAL / IB / session high-low), the latest price, and a per-instrument
proximity band, and returns:

* the two sessions side by side (shape, day-type, value levels, close-vs-value);
* one price-sorted list of every level, each tagged with signed distance from
  the latest price and a **proximity tier** (AT / NEAR / APPROACHING / FAR);
* an ``acceptance`` read per near level from the recent M5 bars — whether price
  has *accepted* through it or *rejected* off it.

Descriptive: it says where the map's lines are and whether price is near one.
It emits **no bias, no BUY/SELL, no target / stop**.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

KEY_LEVELS_VERSION = "0.1.0"


class KeyLevelKind(StrEnum):
    POC = "POC"
    VAH = "VAH"
    VAL = "VAL"
    IB_HIGH = "IB_HIGH"
    IB_LOW = "IB_LOW"
    HIGH = "HIGH"
    LOW = "LOW"


class KeyLevelTier(StrEnum):
    AT = "AT"  # within the tightest band
    NEAR = "NEAR"
    APPROACHING = "APPROACHING"
    FAR = "FAR"


class KeyLevelSide(StrEnum):
    ABOVE = "ABOVE"
    BELOW = "BELOW"
    AT = "AT"


class KeyLevelAcceptance(StrEnum):
    ACCEPTED_ABOVE = "ACCEPTED_ABOVE"
    ACCEPTED_BELOW = "ACCEPTED_BELOW"
    REJECTED_FROM_ABOVE = "REJECTED_FROM_ABOVE"
    REJECTED_FROM_BELOW = "REJECTED_FROM_BELOW"
    TESTING = "TESTING"
    UNTOUCHED = "UNTOUCHED"


@dataclass(frozen=True, slots=True)
class LevelSession:
    label: str  # "D-1" (previous session) | "D-2"
    date: str  # ISO
    shape: str | None
    day_type: str | None
    poc: float | None
    vah: float | None
    val: float | None
    ib_high: float | None
    ib_low: float | None
    high: float | None
    low: float | None
    close: float | None
    complete: bool


@dataclass(frozen=True, slots=True)
class RecentBar:
    high: float
    low: float
    close: float


@dataclass(frozen=True, slots=True)
class Bands:
    at: float
    near: float
    approaching: float

    def validate(self) -> None:
        if not (0 < self.at < self.near < self.approaching):
            raise ValueError("bands must be 0 < at < near < approaching")


@dataclass(frozen=True, slots=True)
class KeyLevel:
    price: float
    kind: str
    session: str  # "D-1" | "D-2"
    session_date: str
    distance: float  # signed points, level - last_price (+ = level above price)
    distance_pct: float
    tier: str
    side: str
    acceptance: str | None = None


@dataclass(frozen=True, slots=True)
class KeyLevelsView:
    last_price: float
    bands: dict
    sessions: list[dict]
    levels: list[KeyLevel]
    alerts: list[KeyLevel]  # tier != FAR, nearest first
    nearest_above: KeyLevel | None
    nearest_below: KeyLevel | None
    key_levels_version: str = field(default=KEY_LEVELS_VERSION)


_CLOSE_VS_VALUE = ("close_vs_value",)


def _close_vs_value(s: LevelSession) -> str | None:
    if s.close is None or s.vah is None or s.val is None:
        return None
    if s.close > s.vah:
        return "ABOVE"
    if s.close < s.val:
        return "BELOW"
    return "INSIDE"


def _levels_of(s: LevelSession) -> list[tuple[str, float]]:
    pairs = [
        (KeyLevelKind.POC, s.poc),
        (KeyLevelKind.VAH, s.vah),
        (KeyLevelKind.VAL, s.val),
        (KeyLevelKind.IB_HIGH, s.ib_high),
        (KeyLevelKind.IB_LOW, s.ib_low),
        (KeyLevelKind.HIGH, s.high),
        (KeyLevelKind.LOW, s.low),
    ]
    return [(k.value, float(v)) for k, v in pairs if v is not None]


def _tier(abs_dist: float, b: Bands) -> KeyLevelTier:
    if abs_dist <= b.at:
        return KeyLevelTier.AT
    if abs_dist <= b.near:
        return KeyLevelTier.NEAR
    if abs_dist <= b.approaching:
        return KeyLevelTier.APPROACHING
    return KeyLevelTier.FAR


def _acceptance(
    price_level: float,
    last_price: float,
    recent: Sequence[RecentBar],
    *,
    accept_bars: int,
    reject_lookback: int,
    at_band: float,
) -> KeyLevelAcceptance:
    if not recent:
        return KeyLevelAcceptance.TESTING if abs(last_price - price_level) <= at_band else (
            KeyLevelAcceptance.UNTOUCHED
        )
    tail = recent[-accept_bars:]
    if len(tail) == accept_bars:
        if last_price > price_level and all(b.close > price_level for b in tail):
            return KeyLevelAcceptance.ACCEPTED_ABOVE
        if last_price < price_level and all(b.close < price_level for b in tail):
            return KeyLevelAcceptance.ACCEPTED_BELOW
    look = recent[-reject_lookback:]
    if last_price <= price_level and any(
        b.high > price_level and b.close <= price_level for b in look
    ):
        return KeyLevelAcceptance.REJECTED_FROM_ABOVE
    if last_price >= price_level and any(
        b.low < price_level and b.close >= price_level for b in look
    ):
        return KeyLevelAcceptance.REJECTED_FROM_BELOW
    if abs(last_price - price_level) <= at_band:
        return KeyLevelAcceptance.TESTING
    return KeyLevelAcceptance.UNTOUCHED


def build_key_levels(
    sessions: Sequence[LevelSession],
    *,
    last_price: float,
    bands: Bands,
    recent: Sequence[RecentBar] | None = None,
    accept_bars: int = 3,
    reject_lookback: int = 6,
) -> KeyLevelsView:
    """``sessions`` = the previous two completed sessions, newest first (``D-1``
    then ``D-2``). ``recent`` = the latest M5 bars (oldest → newest) for the
    acceptance read; omit for level/proximity only."""
    bands.validate()
    recent = list(recent or [])

    levels: list[KeyLevel] = []
    for s in sessions:
        for kind, px in _levels_of(s):
            dist = px - last_price
            ad = abs(dist)
            tier = _tier(ad, bands)
            side = (
                KeyLevelSide.ABOVE
                if dist > 0
                else KeyLevelSide.BELOW
                if dist < 0
                else KeyLevelSide.AT
            )
            acc: str | None = None
            # only the levels price is actually testing get an acceptance read;
            # for a distant level "accepted above/below" would just restate `side`.
            if tier in (KeyLevelTier.AT, KeyLevelTier.NEAR):
                acc = _acceptance(
                    px,
                    last_price,
                    recent,
                    accept_bars=accept_bars,
                    reject_lookback=reject_lookback,
                    at_band=bands.at,
                ).value
            levels.append(
                KeyLevel(
                    price=round(px, 2),
                    kind=kind,
                    session=s.label,
                    session_date=s.date,
                    distance=round(dist, 2),
                    distance_pct=round(dist / last_price * 100.0, 4) if last_price else 0.0,
                    tier=tier.value,
                    side=side.value,
                    acceptance=acc,
                )
            )

    levels.sort(key=lambda x: (-x.price, x.kind, x.session))
    alerts = sorted(
        (x for x in levels if x.tier != KeyLevelTier.FAR.value), key=lambda x: abs(x.distance)
    )
    above = [x for x in levels if x.side == KeyLevelSide.ABOVE.value]
    below = [x for x in levels if x.side == KeyLevelSide.BELOW.value]
    nearest_above = min(above, key=lambda x: x.distance, default=None)
    nearest_below = max(below, key=lambda x: x.distance, default=None)

    return KeyLevelsView(
        last_price=round(last_price, 2),
        bands={"at": bands.at, "near": bands.near, "approaching": bands.approaching},
        sessions=[
            {
                "label": s.label,
                "date": s.date,
                "shape": s.shape,
                "day_type": s.day_type,
                "poc": s.poc,
                "vah": s.vah,
                "val": s.val,
                "ib_high": s.ib_high,
                "ib_low": s.ib_low,
                "high": s.high,
                "low": s.low,
                "close": s.close,
                "close_vs_value": _close_vs_value(s),
                "complete": s.complete,
            }
            for s in sessions
        ],
        levels=levels,
        alerts=alerts,
        nearest_above=nearest_above,
        nearest_below=nearest_below,
    )
