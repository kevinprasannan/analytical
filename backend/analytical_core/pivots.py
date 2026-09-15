"""Central Pivot Range (CPR) + classic floor pivots (docs/05 §10.13).

Pure and deterministic. Given a completed period's high / low / close it returns
that period's **forward-looking** levels — the pivot, the CPR band (TC / pivot /
BC), and the three classic support / resistance steps (R1-R3, S1-S3). A small
helper classifies this period's CPR against the previous one (higher / lower /
overlapping / inside / outside value) and labels the band width.

Descriptive only: these are reference lines drawn from arithmetic on OHLC. It
emits **no bias, no BUY/SELL, no target / stop**.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

PIVOTS_VERSION = "0.1.0"

_EPS = 1e-9


class CprRelation(StrEnum):
    HIGHER_VALUE = "HIGHER_VALUE"  # whole CPR above the previous CPR
    LOWER_VALUE = "LOWER_VALUE"  # whole CPR below the previous CPR
    OVERLAPPING = "OVERLAPPING"  # partial overlap
    INSIDE_VALUE = "INSIDE_VALUE"  # this CPR sits within the previous CPR
    OUTSIDE_VALUE = "OUTSIDE_VALUE"  # this CPR engulfs the previous CPR
    UNCHANGED = "UNCHANGED"  # virtually identical band


class CprWidth(StrEnum):
    NARROW = "NARROW"  # tight band
    AVERAGE = "AVERAGE"
    WIDE = "WIDE"


@dataclass(frozen=True, slots=True)
class PivotLevels:
    """One period's forward-looking levels, derived from its H / L / C."""

    high: float
    low: float
    close: float
    pivot: float
    tc: float  # top central  = 2*pivot - bc  (by formula; may fall below bc)
    bc: float  # bottom central = (high + low) / 2
    cpr_top: float  # max(tc, bc)
    cpr_bottom: float  # min(tc, bc)
    cpr_width: float  # cpr_top - cpr_bottom
    cpr_width_pct: float  # width / pivot * 100
    r1: float
    r2: float
    r3: float
    s1: float
    s2: float
    s3: float

    def levels(self) -> list[tuple[str, float]]:
        """(name, price) for every line, resistance high → support low."""
        return [
            ("R3", self.r3),
            ("R2", self.r2),
            ("R1", self.r1),
            ("TC", self.cpr_top),
            ("P", self.pivot),
            ("BC", self.cpr_bottom),
            ("S1", self.s1),
            ("S2", self.s2),
            ("S3", self.s3),
        ]


def compute_pivots(high: float, low: float, close: float) -> PivotLevels:
    """CPR + classic floor pivots from a completed period's H / L / C."""
    h, low_, c = float(high), float(low), float(close)
    if not (h >= low_):
        raise ValueError(f"high {h} < low {low_}")
    p = (h + low_ + c) / 3.0
    bc = (h + low_) / 2.0
    tc = 2.0 * p - bc
    top, bot = (tc, bc) if tc >= bc else (bc, tc)
    rng = h - low_
    width = top - bot
    return PivotLevels(
        high=h,
        low=low_,
        close=c,
        pivot=p,
        tc=tc,
        bc=bc,
        cpr_top=top,
        cpr_bottom=bot,
        cpr_width=width,
        cpr_width_pct=(width / p * 100.0) if p else 0.0,
        r1=2.0 * p - low_,
        r2=p + rng,
        r3=h + 2.0 * (p - low_),
        s1=2.0 * p - h,
        s2=p - rng,
        s3=low_ - 2.0 * (h - p),
    )


def cpr_relation(current: PivotLevels, previous: PivotLevels) -> CprRelation:
    """How this period's CPR band sits against the previous period's."""
    if (
        abs(current.cpr_top - previous.cpr_top) <= _EPS
        and abs(current.cpr_bottom - previous.cpr_bottom) <= _EPS
    ):
        return CprRelation.UNCHANGED
    if current.cpr_bottom >= previous.cpr_top - _EPS:
        return CprRelation.HIGHER_VALUE
    if current.cpr_top <= previous.cpr_bottom + _EPS:
        return CprRelation.LOWER_VALUE
    inside = (
        current.cpr_top <= previous.cpr_top + _EPS
        and current.cpr_bottom >= previous.cpr_bottom - _EPS
    )
    if inside:
        return CprRelation.INSIDE_VALUE
    outside = (
        current.cpr_top >= previous.cpr_top - _EPS
        and current.cpr_bottom <= previous.cpr_bottom + _EPS
    )
    if outside:
        return CprRelation.OUTSIDE_VALUE
    return CprRelation.OVERLAPPING


def width_band(width_pct: float, *, narrow: float = 0.25, wide: float = 0.75) -> CprWidth:
    """NARROW / AVERAGE / WIDE from the CPR width as a % of the pivot.

    A narrow CPR is the classic 'expect a trending / wide-range day' tell; a
    wide CPR points to a range / rotational day. Descriptive, not a signal.
    """
    if width_pct <= narrow:
        return CprWidth.NARROW
    if width_pct >= wide:
        return CprWidth.WIDE
    return CprWidth.AVERAGE
