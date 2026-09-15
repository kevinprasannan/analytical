"""Market Profile event layer (docs/14) — pure, deterministic, no look-ahead.

An **extension** of ``docs/05`` §10: the existing :func:`build_profile` produces
the ``Profile``; this module derives per-bracket FACTS, then a typed EVENT stream
(with a lifecycle state machine + strength grade), then session CLASSIFICATION
(day type / silhouette / tension). No FastAPI, SQLAlchemy, httpx or IO. No
BUY/SELL — the output is analytical state consumed by the Scoring Engine.

Slice 1 (docs/14 §14.9): the MVP event set, day type, one tension. Developing
values are recomputed by slicing the M5 series to each bracket close and reusing
:func:`build_profile`; slice 2 replaces this with an incremental accumulator.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum

from analytical_core.enums import InstrumentType, ProfileType
from analytical_core.market_profile.config import MarketProfileConfig
from analytical_core.market_profile.engine import (
    ProfileResult,
    _overlapped_bins,
    build_profile,
    resolve_bin_size,
    session_periods,
)
from analytical_core.params import canonical_json
from analytical_core.series import OHLCVSeries

MP_EVENTS_VERSION = "0.1.0"

_DP = 4


def _r(x: float | None) -> float | None:
    return None if x is None else round(x, _DP)


# ======================================================================================
# enums (module-local until wired to API/DB — docs/14 §14.9 slice 3)
# ======================================================================================


class MPState(StrEnum):
    NOT_TRIGGERED = "NOT_TRIGGERED"
    TRIGGERED = "TRIGGERED"
    DEVELOPING = "DEVELOPING"
    CONFIRMED = "CONFIRMED"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"


class MPStrength(StrEnum):
    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"
    CONTEXT = "CONTEXT"


class MPCategory(StrEnum):
    OPENING = "OPENING"
    ACCEPTANCE = "ACCEPTANCE"
    VALUE = "VALUE"
    POC = "POC"
    IB = "IB"
    BREAKOUT = "BREAKOUT"
    STRUCTURE = "STRUCTURE"
    SHAPE = "SHAPE"
    MULTI_TF = "MULTI_TF"
    TENSION = "TENSION"


class MPDayType(StrEnum):
    NORMAL = "NORMAL"
    NORMAL_VARIATION = "NORMAL_VARIATION"
    TREND_UP = "TREND_UP"
    TREND_DOWN = "TREND_DOWN"
    DOUBLE_DISTRIBUTION = "DOUBLE_DISTRIBUTION"
    NEUTRAL = "NEUTRAL"
    NEUTRAL_EXTREME = "NEUTRAL_EXTREME"
    RANGE = "RANGE"
    LARGE_RANGE = "LARGE_RANGE"
    UNDETERMINED = "UNDETERMINED"


class MPSilhouette(StrEnum):
    BALANCED_D = "BALANCED_D"
    P_SHAPE = "P_SHAPE"
    B_SHAPE = "B_SHAPE"
    THIN_I = "THIN_I"
    BIMODAL = "BIMODAL"
    UNDETERMINED = "UNDETERMINED"


# relation of one bracket to one level
_ABOVE_FULL = "ABOVE_FULL"
_ABOVE_PARTIAL = "ABOVE_PARTIAL"
_SPANNING = "SPANNING"
_BELOW_PARTIAL = "BELOW_PARTIAL"
_BELOW_FULL = "BELOW_FULL"


# ======================================================================================
# config (module-local; slice 3 may merge into app_settings market_profile_events.*)
# ======================================================================================


@dataclass(frozen=True, slots=True)
class MPEventConfig:
    accept_frac: float = 0.80  # fraction of a bracket's bins beyond L to "count"
    accept_brackets: int = 2  # consecutive ABOVE/BELOW_FULL to develop acceptance
    value_shift_frac: float = 0.25  # min VA-edge / POC shift vs prior, as frac of prior width
    va_overlap_bal: float = 0.60  # VA overlap frac >= this => balance
    poor_extreme_tpo: int = 2  # max TPO count at the exact extreme to still call it "poor"
    excess_min_bins: int = 2  # min single-print run at an extreme for excess
    single_print_min_run: int = 2
    gap_flat_atr: float = 0.20  # |open-prev_close| < this*ATR => FLAT
    gap_large_atr: float = 1.00  # >= this*ATR => LARGE
    near_poc_bins: float = 1.0  # |open-prev_poc| <= this*bin => AT/NEAR_POC
    drift_min_brackets: int = 3  # monotonic developing-POC brackets for a drift
    drift_atr_frac: float = 0.15  # min net drift as a fraction of ATR
    trend_one_tf_frac: float = 0.70  # fraction of post-IB brackets one-timeframing for a trend
    trend_va_width_max: float = 0.50  # VA width / range ceiling for a trend day
    trend_ib_range_frac: float = 0.35  # ib_range / session_range ceiling for a trend day
    normal_ib_range_frac: float = 0.85  # ib_range / session_range floor for NORMAL day
    ib_ext_one_sided_x: float = 1.00  # extension >= x*ib_range on one side => ONE_SIDED
    ib_ext_two_sided_x: float = 0.50  # both sides >= x*ib_range => TWO_SIDED
    ib_ext_dead_x: float = 0.15  # other side < x*ib_range for a clean one-sided call
    neutral_extreme_frac: float = 0.15  # close within this frac of range edge for NEUTRAL_EXTREME
    large_range_pctile: float = 0.85  # trailing session-range percentile for LARGE_RANGE
    hvn_frac_of_max: float = 0.70  # local max >= this * max_count => HVN
    lvn_frac_of_neighbours: float = 0.50  # local min <= this * mean(flanking HVN) => LVN

    def as_dict(self) -> dict:
        return {
            f: getattr(self, f)
            for f in (
                "accept_frac",
                "accept_brackets",
                "value_shift_frac",
                "va_overlap_bal",
                "poor_extreme_tpo",
                "excess_min_bins",
                "single_print_min_run",
                "gap_flat_atr",
                "gap_large_atr",
                "near_poc_bins",
                "drift_min_brackets",
                "drift_atr_frac",
                "trend_one_tf_frac",
                "trend_va_width_max",
                "trend_ib_range_frac",
                "normal_ib_range_frac",
                "ib_ext_one_sided_x",
                "ib_ext_two_sided_x",
                "ib_ext_dead_x",
                "neutral_extreme_frac",
                "large_range_pctile",
                "hvn_frac_of_max",
                "lvn_frac_of_neighbours",
            )
        }


# ======================================================================================
# inputs / outputs
# ======================================================================================


@dataclass(frozen=True, slots=True)
class PriorProfile:
    """Lean reference to the prior session's *final* profile (docs/14 §14.8)."""

    session_date: str
    poc: float | None
    vah: float | None
    val: float | None
    high: float | None
    low: float | None
    close: float | None
    is_atypical: bool = False

    @property
    def available(self) -> bool:
        return None not in (self.poc, self.vah, self.val, self.high, self.low, self.close)

    @property
    def va_width(self) -> float:
        if self.vah is None or self.val is None:
            return 0.0
        return max(0.0, self.vah - self.val)

    @classmethod
    def from_profile_result(
        cls, session_date: str, pr: ProfileResult, *, is_atypical: bool = False
    ) -> PriorProfile:
        return cls(
            session_date=session_date,
            poc=pr.poc,
            vah=pr.vah,
            val=pr.val,
            high=pr.session_high,
            low=pr.session_low,
            close=pr.close,
            is_atypical=is_atypical,
        )


@dataclass(slots=True)
class BracketSnapshot:
    """Developing state at one bracket's close — derived only from brackets 0..index."""

    index: int
    letter: str
    end_ts: datetime
    minutes_to_close: int
    bracket_open: float
    bracket_high: float
    bracket_low: float
    bracket_close: float
    developing_poc: float | None
    developing_vah: float | None
    developing_val: float | None
    developing_high: float
    developing_low: float
    ib_high: float | None
    ib_low: float | None
    ext_up: float
    ext_dn: float
    rel: dict[str, str] = field(default_factory=dict)  # level name -> ABOVE_FULL / ...
    missing: bool = False


@dataclass(slots=True)
class StructuralFacts:
    single_print_bins: list[float]
    excess_high: bool
    excess_low: bool
    excess_high_run: int
    excess_low_run: int
    poor_high: bool
    poor_low: bool
    hvn_bins: list[float]
    lvn_bins: list[float]
    n_distributions: int
    distribution_split: float | None  # separating price when n_distributions >= 2
    thin_frac: float


@dataclass(slots=True)
class OpeningFacts:
    session_open: float
    location: str  # ABOVE_RANGE / ABOVE_VALUE / INSIDE_VALUE / BELOW_VALUE / BELOW_RANGE / UNKNOWN
    above_prev_high: bool
    below_prev_low: bool
    gap_ticks: float | None
    gap_atr: float | None
    gap_band: str  # FLAT / SMALL / MEDIUM / LARGE (unsigned) / UNKNOWN
    gap_sign: int  # -1 / 0 / +1
    near_prev_poc: str  # AT_POC / NEAR / AWAY / UNKNOWN


@dataclass(slots=True)
class SessionFacts:
    session_date: str
    instrument_type: str
    is_atypical: bool
    bin_size: float
    n_periods_total: int
    is_session_complete: bool
    opening: OpeningFacts
    snapshots: list[BracketSnapshot]
    final: ProfileResult | None
    structural: StructuralFacts | None
    prior: PriorProfile
    atr: float | None
    params_hash: str

    @property
    def last(self) -> BracketSnapshot | None:
        return self.snapshots[-1] if self.snapshots else None


@dataclass(slots=True)
class MPEvent:
    id: str
    category: str
    state: str
    strength: str
    level: str | None = None
    direction: str | None = None  # UP / DOWN / None
    basis: str = "TPO"
    degraded: bool = False
    confirmed_close_only: bool = False
    state_history: list[dict] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    def transition(self, state: str, snap: BracketSnapshot | None, **evidence) -> None:
        if self.state_history and self.state_history[-1]["state"] == state:
            return
        self.state = state
        self.state_history.append(
            {
                "state": state,
                "bracket_index": (snap.index if snap else None),
                "minutes_to_close": (snap.minutes_to_close if snap else None),
                "evidence": evidence,
            }
        )


@dataclass(slots=True)
class DayTypeResult:
    day_type: str
    provisional: bool
    candidates: list[dict]  # [{type, conditions_met, conditions_total}]
    silhouette: str


@dataclass(slots=True)
class MPEventResult:
    version: str
    status: str  # OK / INSUFFICIENT_DATA
    reason: str | None
    facts: SessionFacts | None
    events: list[MPEvent]
    day_type: DayTypeResult | None
    tensions: list[dict]
    params_hash: str


# ======================================================================================
# facts
# ======================================================================================


def _slice_series(series: OHLCVSeries, upto: datetime, tz) -> OHLCVSeries:
    idx = [i for i in range(len(series)) if series.ts[i].astimezone(tz) < upto]
    keep = tuple(idx)
    return replace(
        series,
        ts=tuple(series.ts[i] for i in keep),
        open=tuple(series.open[i] for i in keep),
        high=tuple(series.high[i] for i in keep),
        low=tuple(series.low[i] for i in keep),
        close=tuple(series.close[i] for i in keep),
        volume=tuple(series.volume[i] for i in keep),
        is_final=tuple(series.is_final[i] for i in keep),
    )


def _rel_to_level(
    bracket_low: float, bracket_high: float, level: float, bin_size: float, accept_frac: float
) -> str:
    bins = _overlapped_bins(bracket_low, bracket_high, bin_size)
    if not bins:
        return _SPANNING
    tol = bin_size / 2.0
    above = sum(1 for b in bins if b > level + tol)
    below = sum(1 for b in bins if b + bin_size < level - tol + bin_size)  # b's top edge < level
    n = len(bins)
    frac_above = above / n
    frac_below = below / n
    if frac_above >= accept_frac:
        return _ABOVE_FULL
    if frac_below >= accept_frac:
        return _BELOW_FULL
    if bracket_low < level < bracket_high:
        return _SPANNING
    if frac_above > 0:
        return _ABOVE_PARTIAL
    if frac_below > 0:
        return _BELOW_PARTIAL
    return _SPANNING


def _structural_from_bins(
    bins: list[dict], bin_size: float, evcfg: MPEventConfig
) -> StructuralFacts:
    if not bins:
        return StructuralFacts([], False, False, 0, 0, False, False, [], [], 1, None, 0.0)
    prices = [float(b["price_low"]) for b in bins]
    counts = [int(b.get("tpo_count", 0)) for b in bins]
    order = sorted(range(len(prices)), key=lambda i: prices[i])
    prices = [prices[i] for i in order]
    counts = [counts[i] for i in order]
    n = len(prices)
    max_c = max(counts) if counts else 0

    single = [prices[i] for i in range(n) if counts[i] == 1]
    thin_frac = sum(1 for c in counts if c <= 1) / n if n else 0.0

    # excess = single-print run anchored at an extreme
    lo_run = 0
    for i in range(n):
        if counts[i] == 1:
            lo_run += 1
        else:
            break
    hi_run = 0
    for i in range(n - 1, -1, -1):
        if counts[i] == 1:
            hi_run += 1
        else:
            break
    excess_low = lo_run >= evcfg.excess_min_bins
    excess_high = hi_run >= evcfg.excess_min_bins
    poor_low = (not excess_low) and n > 0 and counts[0] > evcfg.poor_extreme_tpo
    poor_high = (not excess_high) and n > 0 and counts[-1] > evcfg.poor_extreme_tpo

    # HVN / LVN — simple local extrema with a prominence rule (slice 2: z-score smoothing)
    hvn: list[float] = []
    for i in range(1, n - 1):
        if (
            counts[i] >= counts[i - 1]
            and counts[i] >= counts[i + 1]
            and counts[i] >= evcfg.hvn_frac_of_max * max_c
        ):
            hvn.append(prices[i])
    lvn: list[float] = []
    for i in range(1, n - 1):
        if counts[i] <= counts[i - 1] and counts[i] <= counts[i + 1]:
            left = max(counts[:i]) if i else 0
            right = max(counts[i + 1 :]) if i + 1 < n else 0
            flank = (left + right) / 2.0 if (left and right) else max(left, right)
            if flank and counts[i] <= evcfg.lvn_frac_of_neighbours * flank:
                lvn.append(prices[i])

    # distributions: peaks >=12% of total separated by a valley <=4%
    total = math.fsum(counts) or 1.0
    peaks = [i for i in range(n) if counts[i] >= 0.12 * total]
    n_dist = 1
    split = None
    for a, b in zip(peaks, peaks[1:], strict=False):
        if any(counts[k] <= 0.04 * total for k in range(a + 1, b)):
            n_dist += 1
            valley = min(range(a + 1, b), key=lambda k: counts[k])
            split = prices[valley]
    return StructuralFacts(
        single_print_bins=single,
        excess_high=excess_high,
        excess_low=excess_low,
        excess_high_run=hi_run,
        excess_low_run=lo_run,
        poor_high=poor_high,
        poor_low=poor_low,
        hvn_bins=hvn,
        lvn_bins=lvn,
        n_distributions=n_dist,
        distribution_split=split,
        thin_frac=round(thin_frac, 4),
    )


def _opening_facts(
    session_open_px: float,
    prior: PriorProfile,
    atr: float | None,
    bin_size: float,
    evcfg: MPEventConfig,
) -> OpeningFacts:
    if not prior.available:
        return OpeningFacts(
            session_open_px, "UNKNOWN", False, False, None, None, "UNKNOWN", 0, "UNKNOWN"
        )
    assert prior.vah is not None and prior.val is not None
    assert prior.high is not None and prior.low is not None and prior.close is not None
    o = session_open_px
    if o > prior.high:
        loc = "ABOVE_RANGE"
    elif o < prior.low:
        loc = "BELOW_RANGE"
    elif o > prior.vah:
        loc = "ABOVE_VALUE"
    elif o < prior.val:
        loc = "BELOW_VALUE"
    else:
        loc = "INSIDE_VALUE"
    gap = o - prior.close
    gap_atr = (gap / atr) if (atr and atr > 0) else None
    if gap_atr is None:
        band = "UNKNOWN"
    elif abs(gap_atr) < evcfg.gap_flat_atr:
        band = "FLAT"
    elif abs(gap_atr) >= evcfg.gap_large_atr:
        band = "LARGE"
    elif abs(gap_atr) >= 0.5:
        band = "MEDIUM"
    else:
        band = "SMALL"
    near = "UNKNOWN"
    if prior.poc is not None:
        d = abs(o - prior.poc)
        near = (
            "AT_POC"
            if d <= evcfg.near_poc_bins * bin_size
            else "NEAR" if d <= 3 * evcfg.near_poc_bins * bin_size else "AWAY"
        )
    return OpeningFacts(
        session_open=o,
        location=loc,
        above_prev_high=o > prior.high,
        below_prev_low=o < prior.low,
        gap_ticks=_r(gap),
        gap_atr=_r(gap_atr),
        gap_band=band,
        gap_sign=(0 if gap == 0 else (1 if gap > 0 else -1)),
        near_prev_poc=near,
    )


def compute_facts(
    series: OHLCVSeries,
    *,
    config: MarketProfileConfig,
    evcfg: MPEventConfig,
    session_open: datetime,
    session_close: datetime,
    session_date,
    instrument_type: InstrumentType,
    has_volume: bool,
    price_ref: float,
    prior: PriorProfile,
    atr: float | None,
    now: datetime,
    tick_size: float = 0.05,
    underlying_symbol: str | None = None,
    profile_bin_size: float | None = None,
    is_atypical: bool = False,
) -> SessionFacts:
    tz = session_open.tzinfo
    periods = session_periods(
        session_open, session_close, config.tpo_minutes, config.partial_period_policy
    )
    bin_size = resolve_bin_size(
        instrument_type=instrument_type,
        config=config,
        price_ref=price_ref,
        tick_size=tick_size,
        underlying_symbol=underlying_symbol,
        explicit=profile_bin_size,
    )
    params_hash = canonical_json(
        {"mp": config.as_dict(), "ev": evcfg.as_dict(), "v": MP_EVENTS_VERSION}
    )

    open_px = float(series.open[0]) if len(series) else price_ref
    opening = _opening_facts(open_px, prior, atr, bin_size, evcfg)

    levels: dict[str, float] = {}
    if prior.available:
        levels.update(
            prev_vah=prior.vah,  # type: ignore[dict-item]
            prev_val=prior.val,  # type: ignore[dict-item]
            prev_poc=prior.poc,  # type: ignore[dict-item]
            prev_high=prior.high,  # type: ignore[dict-item]
            prev_low=prior.low,  # type: ignore[dict-item]
        )

    snapshots: list[BracketSnapshot] = []
    ib_periods = max(1, config.ib_periods)
    for p in periods:
        # a snapshot exists only once this bracket has closed as of `now` — no look-ahead
        if p.end > now:
            break
        b_idx = [i for i in range(len(series)) if p.start <= series.ts[i].astimezone(tz) < p.end]
        # developing profile from every bar in brackets 0..p (ts strictly before p.end)
        sub = _slice_series(series, p.end, tz)
        if len(sub) == 0:
            continue
        sub_periods = [q for q in periods if q.index <= p.index]
        dev = build_profile(
            sub,
            sub_periods,
            ProfileType.TPO,
            bin_size=bin_size,
            config=config,
            session_open=session_open,
            session_close=session_close,
            now=p.end,
        )
        if dev is None:
            continue
        b_high = max(float(series.high[i]) for i in b_idx) if b_idx else dev.session_high
        b_low = min(float(series.low[i]) for i in b_idx) if b_idx else dev.session_low
        b_open = float(series.open[b_idx[0]]) if b_idx else dev.close
        b_close = float(series.close[b_idx[-1]]) if b_idx else dev.close
        ib_hi = dev.ib_high
        ib_lo = dev.ib_low
        ext_up = max(0.0, dev.session_high - ib_hi) if ib_hi is not None else 0.0
        ext_dn = max(0.0, ib_lo - dev.session_low) if ib_lo is not None else 0.0

        rel: dict[str, str] = {}
        for name, lv in levels.items():
            rel[name] = _rel_to_level(b_low, b_high, lv, bin_size, evcfg.accept_frac)
        if ib_hi is not None and p.index >= ib_periods:
            rel["ib_high"] = _rel_to_level(b_low, b_high, ib_hi, bin_size, evcfg.accept_frac)
        if ib_lo is not None and p.index >= ib_periods:
            rel["ib_low"] = _rel_to_level(b_low, b_high, ib_lo, bin_size, evcfg.accept_frac)

        snapshots.append(
            BracketSnapshot(
                index=p.index,
                letter=p.letter,
                end_ts=p.end,
                minutes_to_close=max(0, int((session_close - p.end).total_seconds() // 60)),
                bracket_open=b_open,
                bracket_high=b_high,
                bracket_low=b_low,
                bracket_close=b_close,
                developing_poc=dev.poc,
                developing_vah=dev.vah,
                developing_val=dev.val,
                developing_high=dev.session_high,
                developing_low=dev.session_low,
                ib_high=ib_hi,
                ib_low=ib_lo,
                ext_up=round(ext_up, _DP),
                ext_dn=round(ext_dn, _DP),
                rel=rel,
                missing=not b_idx,
            )
        )

    is_complete = now >= session_close
    final = None
    structural = None
    if is_complete:
        final = build_profile(
            series,
            periods,
            ProfileType.TPO,
            bin_size=bin_size,
            config=config,
            session_open=session_open,
            session_close=session_close,
            now=now,
        )
        if final is not None:
            structural = _structural_from_bins(final.bins, bin_size, evcfg)
    elif snapshots:
        # a provisional structural read from the latest developing profile
        last_sub = _slice_series(series, snapshots[-1].end_ts, tz)
        prov = build_profile(
            last_sub,
            [q for q in periods if q.index <= snapshots[-1].index],
            ProfileType.TPO,
            bin_size=bin_size,
            config=config,
            session_open=session_open,
            session_close=session_close,
            now=snapshots[-1].end_ts,
        )
        if prov is not None:
            structural = _structural_from_bins(prov.bins, bin_size, evcfg)

    return SessionFacts(
        session_date=str(session_date),
        instrument_type=instrument_type.value,
        is_atypical=is_atypical,
        bin_size=bin_size,
        n_periods_total=len(periods),
        is_session_complete=is_complete,
        opening=opening,
        snapshots=snapshots,
        final=final,
        structural=structural,
        prior=prior,
        atr=atr,
        params_hash=params_hash,
    )


# ======================================================================================
# events
# ======================================================================================


def _acceptance_event(
    ev_id: str,
    level_name: str,
    direction: str,
    facts: SessionFacts,
    evcfg: MPEventConfig,
    *,
    is_range_extreme: bool,
) -> MPEvent | None:
    """Generic §14.5 state machine for 'does price accept beyond <level>?'."""
    prior = facts.prior
    if not prior.available:
        return None
    level = {
        "prev_vah": prior.vah,
        "prev_val": prior.val,
        "prev_high": prior.high,
        "prev_low": prior.low,
    }.get(level_name)
    if level is None and level_name not in ("ib_high", "ib_low"):
        return None

    up = direction == "UP"
    full = _ABOVE_FULL if up else _BELOW_FULL
    opp_full = _BELOW_FULL if up else _ABOVE_FULL
    ev = MPEvent(
        id=ev_id,
        category=MPCategory.ACCEPTANCE.value,
        state=MPState.NOT_TRIGGERED.value,
        strength=MPStrength.WEAK.value,
        level=level_name,
        direction=direction,
        confirmed_close_only=False,
    )
    consec_full = 0
    consec_opp = 0
    reached_dev = False
    reached_accept = False
    degraded = False
    for s in facts.snapshots:
        r = s.rel.get(level_name)
        if r is None:
            continue
        if s.missing:
            degraded = True
        dv_val = s.developing_val if up else s.developing_vah
        dyn_level = (
            (s.ib_high if up else s.ib_low) if level_name in ("ib_high", "ib_low") else level
        )
        if dyn_level is None:
            continue

        if (
            r in (_ABOVE_PARTIAL, _BELOW_PARTIAL, _SPANNING)
            and ev.state == MPState.NOT_TRIGGERED.value
        ):
            ev.transition(MPState.TRIGGERED.value, s, kind="PROBE", rel=r)
        if r == full:
            consec_full += 1
            consec_opp = 0
            if ev.state == MPState.NOT_TRIGGERED.value:
                ev.transition(MPState.TRIGGERED.value, s, kind="BREAK", rel=r)
            elif ev.state == MPState.TRIGGERED.value and consec_full == 1:
                ev.transition(MPState.TRIGGERED.value, s, kind="BREAK", rel=r)
            if consec_full >= evcfg.accept_brackets and not reached_accept:
                reached_dev = True
                if ev.state in (MPState.TRIGGERED.value, MPState.DEVELOPING.value):
                    ev.transition(
                        MPState.DEVELOPING.value,
                        s,
                        kind="DEVELOPING_ACCEPTANCE",
                        consecutive=consec_full,
                    )
            beyond_va = dv_val is not None and (
                (dv_val > dyn_level) if up else (dv_val < dyn_level)
            )
            if reached_dev and beyond_va and ev.state != MPState.CONFIRMED.value:
                reached_accept = True
                ev.transition(
                    MPState.CONFIRMED.value,
                    s,
                    kind="ACCEPTANCE",
                    developing_va_edge=_r(dv_val),
                )
                ev.strength = MPStrength.STRONG.value
        elif r == opp_full:
            consec_opp += 1
            consec_full = 0
            dev_poc = s.developing_poc
            origin_side = dev_poc is not None and (
                (dev_poc <= dyn_level) if up else (dev_poc >= dyn_level)
            )
            if (
                (reached_dev or reached_accept)
                and consec_opp >= 2
                and origin_side
                and ev.state != MPState.INVALIDATED.value
            ):
                ev.transition(
                    MPState.INVALIDATED.value,
                    s,
                    kind="FAILED_ACCEPTANCE",
                    developing_poc=_r(dev_poc),
                )
                ev.strength = MPStrength.STRONG.value
                break
            if (
                is_range_extreme
                and ev.state == MPState.TRIGGERED.value
                and s.developing_val is not None
                and s.developing_vah is not None
                and s.developing_val <= s.bracket_close <= s.developing_vah
                and origin_side
            ):
                ev.transition(
                    MPState.INVALIDATED.value, s, kind="FAILED_BREAKOUT", developing_poc=_r(dev_poc)
                )
                ev.strength = MPStrength.STRONG.value
                break
        else:
            consec_full = 0
            consec_opp = 0

    if ev.state in (MPState.TRIGGERED.value, MPState.DEVELOPING.value):
        if facts.is_session_complete:
            # SUSTAINED check at close
            if reached_accept and facts.final is not None:
                fv = facts.final.val if up else facts.final.vah
                fc = facts.final.close
                if fv is not None and (
                    (fv > level and fc > level) if up else (fv < level and fc < level)
                ):
                    ev.transition(
                        MPState.CONFIRMED.value,
                        facts.last,
                        kind="SUSTAINED_ACCEPTANCE",
                    )
                    ev.confirmed_close_only = True
            else:
                ev.transition(MPState.EXPIRED.value, facts.last, kind="EXPIRED")
    ev.degraded = degraded
    if ev.state == MPState.NOT_TRIGGERED.value:
        return None
    return ev


def _rejection_event(
    ev_id: str, level_name: str, direction: str, facts: SessionFacts, evcfg: MPEventConfig
) -> MPEvent | None:
    prior = facts.prior
    if not prior.available:
        return None
    up = direction == "UP"
    full = _ABOVE_FULL if up else _BELOW_FULL
    opp_full = _BELOW_FULL if up else _ABOVE_FULL
    ev = MPEvent(
        id=ev_id,
        category=MPCategory.ACCEPTANCE.value,
        state=MPState.NOT_TRIGGERED.value,
        strength=MPStrength.MODERATE.value,
        level=level_name,
        direction=direction,
    )
    probed = False
    probe_idx = -99
    for s in facts.snapshots:
        r = s.rel.get(level_name)
        if r is None:
            continue
        if r in (_ABOVE_PARTIAL, _BELOW_PARTIAL, _SPANNING, full):
            if not probed:
                probed = True
                probe_idx = s.index
                ev.transition(MPState.TRIGGERED.value, s, kind="PROBE_OR_BREAK", rel=r)
        elif r == opp_full and probed and s.index - probe_idx <= 2:
            in_value = (
                s.developing_val is not None
                and s.developing_vah is not None
                and s.developing_val <= s.bracket_close <= s.developing_vah
            )
            tail = (facts.structural is not None) and (
                (facts.structural.excess_high or facts.structural.poor_high is False)
                if up
                else (facts.structural.excess_low or facts.structural.poor_low is False)
            )
            ev.transition(
                MPState.CONFIRMED.value,
                s,
                kind="REJECTION",
                returned_into_value=in_value,
            )
            if facts.structural is not None and (
                (facts.structural.excess_high and up) or (facts.structural.excess_low and not up)
            ):
                ev.strength = MPStrength.STRONG.value
            _ = tail
            return ev
        elif r in (full,):
            # accepted after probing — this rejection event is invalidated
            if probed:
                ev.transition(MPState.INVALIDATED.value, s, kind="LATER_ACCEPTANCE")
                return ev
    if ev.state == MPState.NOT_TRIGGERED.value:
        return None
    return ev


def _developing_value_outside(facts: SessionFacts, evcfg: MPEventConfig) -> MPEvent | None:
    prior = facts.prior
    if not prior.available:
        return None
    ev = MPEvent(
        id="MP-015",
        category=MPCategory.ACCEPTANCE.value,
        state=MPState.NOT_TRIGGERED.value,
        strength=MPStrength.STRONG.value,
        level="prev_va",
    )
    brackets_outside = 0
    direction = None
    for s in facts.snapshots:
        dv, dh = s.developing_val, s.developing_vah
        if dv is None or dh is None:
            continue
        out_up = dv > prior.vah  # type: ignore[operator]
        out_dn = dh < prior.val  # type: ignore[operator]
        if out_up or out_dn:
            brackets_outside += 1
            direction = "UP" if out_up else "DOWN"
            if ev.state == MPState.NOT_TRIGGERED.value:
                ev.transition(MPState.TRIGGERED.value, s, kind="VALUE_OUTSIDE", direction=direction)
            elif brackets_outside >= 3 and ev.state == MPState.TRIGGERED.value:
                ev.transition(
                    MPState.DEVELOPING.value,
                    s,
                    kind="VALUE_BUILDING_OUTSIDE",
                    brackets=brackets_outside,
                )
        else:
            if ev.state in (MPState.TRIGGERED.value, MPState.DEVELOPING.value):
                ev.transition(MPState.INVALIDATED.value, s, kind="BACK_INSIDE_PRIOR_VA")
                ev.direction = direction
                return ev
            brackets_outside = 0
    ev.direction = direction
    if (
        ev.state in (MPState.DEVELOPING.value, MPState.TRIGGERED.value)
        and facts.is_session_complete
    ):
        if facts.final is not None and facts.final.val is not None and facts.final.vah is not None:
            agree = (
                facts.final.val > prior.vah  # type: ignore[operator]
                if direction == "UP"
                else facts.final.vah < prior.val  # type: ignore[operator]
            )
            ev.transition(
                MPState.CONFIRMED.value if agree else MPState.EXPIRED.value,
                facts.last,
                kind="CLOSE_CHECK",
                agree=agree,
            )
            ev.confirmed_close_only = True
    if ev.state == MPState.NOT_TRIGGERED.value:
        return None
    return ev


def _opening_events(facts: SessionFacts) -> list[MPEvent]:
    o = facts.opening
    out = [
        MPEvent(
            "MP-001",
            MPCategory.OPENING.value,
            MPState.CONFIRMED.value,
            MPStrength.CONTEXT.value,
            meta={"location": o.location},
            state_history=[
                {"state": "CONFIRMED", "bracket_index": 0, "evidence": {"loc": o.location}}
            ],
        ),
        MPEvent(
            "MP-002",
            MPCategory.OPENING.value,
            MPState.CONFIRMED.value,
            MPStrength.CONTEXT.value,
            meta={
                "above_prev_high": o.above_prev_high,
                "below_prev_low": o.below_prev_low,
            },
            state_history=[{"state": "CONFIRMED", "bracket_index": 0, "evidence": {}}],
        ),
        MPEvent(
            "MP-003",
            MPCategory.OPENING.value,
            MPState.CONFIRMED.value,
            MPStrength.CONTEXT.value,
            meta={"gap_band": o.gap_band, "gap_sign": o.gap_sign, "gap_atr": o.gap_atr},
            state_history=[{"state": "CONFIRMED", "bracket_index": 0, "evidence": {}}],
        ),
    ]
    return out


def _value_migration_event(facts: SessionFacts, evcfg: MPEventConfig) -> MPEvent | None:
    prior = facts.prior
    last = facts.last
    if not prior.available or last is None:
        return None
    t_vah = facts.final.vah if facts.is_session_complete and facts.final else last.developing_vah
    t_val = facts.final.val if facts.is_session_complete and facts.final else last.developing_val
    if t_vah is None or t_val is None:
        return None
    w = prior.va_width or facts.bin_size
    thr = evcfg.value_shift_frac * w
    d_vah = t_vah - prior.vah  # type: ignore[operator]
    d_val = t_val - prior.val  # type: ignore[operator]
    overlap = max(0.0, min(t_vah, prior.vah) - max(t_val, prior.val))  # type: ignore[arg-type]
    ov_frac = overlap / min(w, max(t_vah - t_val, facts.bin_size))
    if ov_frac >= evcfg.va_overlap_bal:
        direction = "OVERLAP"
    elif d_vah >= thr and d_val >= thr:
        direction = "UP"
    elif d_vah <= -thr and d_val <= -thr:
        direction = "DOWN"
    elif d_vah >= thr or d_val >= thr:
        direction = "UP_SKEW"
    elif d_vah <= -thr or d_val <= -thr:
        direction = "DOWN_SKEW"
    else:
        direction = "UNCHANGED"
    # topology
    if t_val > prior.vah:  # type: ignore[operator]
        topo = "FULLY_ABOVE"
    elif t_vah < prior.val:  # type: ignore[operator]
        topo = "FULLY_BELOW"
    elif ov_frac >= evcfg.va_overlap_bal:
        topo = "BALANCE"
    elif overlap > 0 and (t_vah + t_val) / 2 > prior.vah:  # type: ignore[operator]
        topo = "OVERLAP_HIGH"
    elif overlap > 0 and (t_vah + t_val) / 2 < prior.val:  # type: ignore[operator]
        topo = "OVERLAP_LOW"
    else:
        topo = "OVERLAP_MID"
    ev = MPEvent(
        "MP-030",
        MPCategory.VALUE.value,
        MPState.CONFIRMED.value if facts.is_session_complete else MPState.DEVELOPING.value,
        MPStrength.STRONG.value if facts.is_session_complete else MPStrength.MODERATE.value,
        direction=direction,
        confirmed_close_only=False,
        meta={
            "direction": direction,
            "topology": topo,
            "d_vah": _r(d_vah),
            "d_val": _r(d_val),
            "overlap_frac": _r(ov_frac),
        },
        state_history=[
            {
                "state": "CONFIRMED" if facts.is_session_complete else "DEVELOPING",
                "bracket_index": last.index,
                "evidence": {"direction": direction, "topology": topo},
            }
        ],
    )
    return ev


def _poc_events(facts: SessionFacts, evcfg: MPEventConfig) -> list[MPEvent]:
    out: list[MPEvent] = []
    prior = facts.prior
    last = facts.last
    if last is None:
        return out
    # MP-040 POC migration vs prior session
    if prior.available and prior.poc is not None:
        t_poc = (
            facts.final.poc if facts.is_session_complete and facts.final else last.developing_poc
        )
        if t_poc is not None:
            w = prior.va_width or facts.bin_size
            d = t_poc - prior.poc
            thr = evcfg.value_shift_frac * w
            mig = "UP" if d >= thr else "DOWN" if d <= -thr else "UNCHANGED"
            out.append(
                MPEvent(
                    "MP-040",
                    MPCategory.POC.value,
                    (
                        MPState.CONFIRMED.value
                        if facts.is_session_complete
                        else MPState.DEVELOPING.value
                    ),
                    MPStrength.STRONG.value,
                    direction=None if mig == "UNCHANGED" else mig,
                    meta={
                        "migration": mig,
                        "d_poc": _r(d),
                        "d_atr": _r(d / facts.atr) if facts.atr else None,
                    },
                    state_history=[
                        {
                            "state": "CONFIRMED" if facts.is_session_complete else "DEVELOPING",
                            "bracket_index": last.index,
                            "evidence": {"migration": mig},
                        }
                    ],
                )
            )
    # MP-041 developing-POC drift — longest monotonic run in the developing_poc series
    pocs = [s.developing_poc for s in facts.snapshots if s.developing_poc is not None]
    last_idx = next((s.index for s in reversed(facts.snapshots) if s.developing_poc is not None), 0)
    if len(pocs) >= evcfg.drift_min_brackets:
        best_dir = best_len = 0
        best_start = 0
        cur_dir = cur_start = 0
        for k in range(1, len(pocs)):
            step = 1 if pocs[k] > pocs[k - 1] else -1 if pocs[k] < pocs[k - 1] else 0
            if step != 0 and step == cur_dir:
                pass
            elif step != 0:
                cur_dir, cur_start = step, k - 1
            else:
                cur_dir, cur_start = 0, k
            cur_len = k - cur_start
            if cur_dir != 0 and cur_len > best_len:
                best_dir, best_len, best_start = cur_dir, cur_len, cur_start
        net = pocs[best_start + best_len] - pocs[best_start] if best_len else 0.0
        d_ok = bool(facts.atr) and abs(net) >= evcfg.drift_atr_frac * (facts.atr or 1.0)
        if best_len >= evcfg.drift_min_brackets and d_ok:
            out.append(
                MPEvent(
                    "MP-041",
                    MPCategory.POC.value,
                    MPState.DEVELOPING.value,
                    MPStrength.MODERATE.value,
                    direction="UP" if best_dir > 0 else "DOWN",
                    meta={"run": best_len, "net": _r(net)},
                    state_history=[
                        {
                            "state": "DEVELOPING",
                            "bracket_index": last_idx,
                            "evidence": {"run": best_len},
                        }
                    ],
                )
            )
    return out


def _ib_events(facts: SessionFacts, evcfg: MPEventConfig) -> list[MPEvent]:
    out: list[MPEvent] = []
    snaps = facts.snapshots
    ib = next((s for s in snaps if s.ib_high is not None), None)
    if ib is None:
        return out
    ib_hi, ib_lo = ib.ib_high, ib.ib_low
    assert ib_hi is not None and ib_lo is not None
    ib_range = max(ib_hi - ib_lo, facts.bin_size)
    post = [s for s in snaps if s.index > ib.index]
    broke_up = any(s.rel.get("ib_high") == _ABOVE_FULL for s in post)
    broke_dn = any(s.rel.get("ib_low") == _BELOW_FULL for s in post)
    state = (
        "BOTH" if (broke_up and broke_dn) else "UP" if broke_up else "DOWN" if broke_dn else "NONE"
    )
    out.append(
        MPEvent(
            "MP-051",
            MPCategory.IB.value,
            MPState.CONFIRMED.value if facts.is_session_complete else MPState.DEVELOPING.value,
            MPStrength.WEAK.value,
            direction=None if state in ("NONE", "BOTH") else state,
            meta={"broken": state, "ib_range": _r(ib_range)},
            state_history=[
                {
                    "state": "CONFIRMED" if facts.is_session_complete else "DEVELOPING",
                    "bracket_index": snaps[-1].index,
                    "evidence": {"broken": state},
                }
            ],
        )
    )
    # MP-052 extension size & sidedness
    last = snaps[-1]
    eu, ed = last.ext_up, last.ext_dn
    if eu >= evcfg.ib_ext_one_sided_x * ib_range and ed < evcfg.ib_ext_dead_x * ib_range:
        side = "ONE_SIDED_UP"
        strength = MPStrength.STRONG.value
    elif ed >= evcfg.ib_ext_one_sided_x * ib_range and eu < evcfg.ib_ext_dead_x * ib_range:
        side = "ONE_SIDED_DOWN"
        strength = MPStrength.STRONG.value
    elif eu >= evcfg.ib_ext_two_sided_x * ib_range and ed >= evcfg.ib_ext_two_sided_x * ib_range:
        side = "TWO_SIDED"
        strength = MPStrength.MODERATE.value
    elif eu > 0 or ed > 0:
        side = "SOME"
        strength = MPStrength.MODERATE.value
    else:
        side = "NONE"
        strength = MPStrength.CONTEXT.value
    out.append(
        MPEvent(
            "MP-052",
            MPCategory.IB.value,
            MPState.CONFIRMED.value if facts.is_session_complete else MPState.DEVELOPING.value,
            strength,
            meta={
                "sidedness": side,
                "ext_up_x": _r(eu / ib_range),
                "ext_dn_x": _r(ed / ib_range),
            },
            state_history=[
                {
                    "state": "CONFIRMED" if facts.is_session_complete else "DEVELOPING",
                    "bracket_index": last.index,
                    "evidence": {"sidedness": side},
                }
            ],
        )
    )
    # MP-053 directional after IB (one-timeframing)
    ot_up = _one_timeframing(post, "UP")
    ot_dn = _one_timeframing(post, "DOWN")
    if ot_up >= 3 or ot_dn >= 3:
        d = "UP" if ot_up >= ot_dn else "DOWN"
        out.append(
            MPEvent(
                "MP-053",
                MPCategory.IB.value,
                (
                    MPState.DEVELOPING.value
                    if not facts.is_session_complete
                    else MPState.CONFIRMED.value
                ),
                MPStrength.MODERATE.value,
                direction=d,
                meta={"one_timeframing": max(ot_up, ot_dn)},
                state_history=[
                    {
                        "state": "DEVELOPING",
                        "bracket_index": post[-1].index if post else ib.index,
                        "evidence": {"otf": max(ot_up, ot_dn)},
                    }
                ],
            )
        )
    return out


def _one_timeframing(snaps: list[BracketSnapshot], direction: str) -> int:
    """Longest run of consecutive brackets making a higher low (UP) / lower high (DOWN)."""
    best = run = 0
    for a, b in zip(snaps, snaps[1:], strict=False):
        ok = (
            (b.bracket_low > a.bracket_low)
            if direction == "UP"
            else (b.bracket_high < a.bracket_high)
        )
        run = run + 1 if ok else 0
        best = max(best, run)
    return best + 1 if best else 0


def _structure_events(facts: SessionFacts) -> list[MPEvent]:
    st = facts.structural
    if st is None:
        return []
    close_only = not facts.is_session_complete
    hi_state = "EXCESS" if st.excess_high else "POOR" if st.poor_high else "NEITHER"
    lo_state = "EXCESS" if st.excess_low else "POOR" if st.poor_low else "NEITHER"
    out = [
        MPEvent(
            "MP-070",
            MPCategory.STRUCTURE.value,
            MPState.CONFIRMED.value if facts.is_session_complete else MPState.DEVELOPING.value,
            (
                MPStrength.STRONG.value
                if ("EXCESS" in (hi_state, lo_state))
                else MPStrength.MODERATE.value
            ),
            confirmed_close_only=close_only,
            meta={
                "high": hi_state,
                "low": lo_state,
                "excess_high_run": st.excess_high_run,
                "excess_low_run": st.excess_low_run,
            },
            state_history=[
                {
                    "state": "CONFIRMED" if facts.is_session_complete else "DEVELOPING",
                    "bracket_index": facts.last.index if facts.last else 0,
                    "evidence": {"high": hi_state, "low": lo_state},
                }
            ],
        ),
    ]
    if st.poor_high or st.poor_low:
        out.append(
            MPEvent(
                "MP-072",
                MPCategory.STRUCTURE.value,
                MPState.CONFIRMED.value if facts.is_session_complete else MPState.DEVELOPING.value,
                MPStrength.MODERATE.value,
                confirmed_close_only=True,
                meta={"poor_high": st.poor_high, "poor_low": st.poor_low},
                state_history=[
                    {
                        "state": "DEVELOPING",
                        "bracket_index": facts.last.index if facts.last else 0,
                        "evidence": {},
                    }
                ],
            )
        )
    if st.n_distributions >= 2:
        out.append(
            MPEvent(
                "MP-075",
                MPCategory.STRUCTURE.value,
                MPState.CONFIRMED.value if facts.is_session_complete else MPState.DEVELOPING.value,
                MPStrength.STRONG.value if facts.is_session_complete else MPStrength.MODERATE.value,
                meta={"n_distributions": st.n_distributions, "split": _r(st.distribution_split)},
                state_history=[
                    {
                        "state": "CONFIRMED" if facts.is_session_complete else "DEVELOPING",
                        "bracket_index": facts.last.index if facts.last else 0,
                        "evidence": {"n": st.n_distributions},
                    }
                ],
            )
        )
    return out


def _narrative_events(events: list[MPEvent]) -> list[MPEvent]:
    by_id = {e.id: e for e in events}

    def outcome(accept_id: str, fail_extreme_id: str, direction: str) -> str:
        acc = by_id.get(accept_id)
        if acc is None:
            return "NONE"
        if acc.state == MPState.CONFIRMED.value:
            return f"ACCEPTANCE_{direction}"
        if acc.state == MPState.INVALIDATED.value:
            last_kind = acc.state_history[-1]["evidence"].get("kind") or (
                acc.state_history[-1].get("state")
            )
            return f"FAILED_{direction}" if last_kind else f"REJECTION_{direction}"
        if acc.state in (MPState.TRIGGERED.value, MPState.DEVELOPING.value):
            return f"ATTEMPTING_{direction}"
        return "NONE"

    out = []
    up = outcome("MP-010", "MP-016", "UP")
    dn = outcome("MP-011", "MP-017", "DOWN")
    if up != "NONE":
        out.append(
            MPEvent(
                "MP-060",
                MPCategory.BREAKOUT.value,
                MPState.CONFIRMED.value,
                MPStrength.MODERATE.value,
                direction="UP",
                meta={"outcome": up},
                state_history=[
                    {"state": "CONFIRMED", "bracket_index": None, "evidence": {"outcome": up}}
                ],
            )
        )
    if dn != "NONE":
        out.append(
            MPEvent(
                "MP-061",
                MPCategory.BREAKOUT.value,
                MPState.CONFIRMED.value,
                MPStrength.MODERATE.value,
                direction="DOWN",
                meta={"outcome": dn},
                state_history=[
                    {"state": "CONFIRMED", "bracket_index": None, "evidence": {"outcome": dn}}
                ],
            )
        )
    return out


def _tension_events(facts: SessionFacts, events: list[MPEvent]) -> list[dict]:
    by_id = {e.id: e for e in events}
    out: list[dict] = []
    acc_up = by_id.get("MP-010")
    acc_dn = by_id.get("MP-011")
    drift = by_id.get("MP-041")
    if (
        acc_up
        and acc_up.state in (MPState.DEVELOPING.value, MPState.CONFIRMED.value)
        and drift
        and drift.direction == "DOWN"
    ):
        out.append(
            {
                "id": "MP-110",
                "axis": "PRICE_VS_VALUE",
                "label": "DIVERGENCE_UP",
                "bull": [{"id": acc_up.id, "state": acc_up.state, "strength": acc_up.strength}],
                "bear": [{"id": drift.id, "state": drift.state, "strength": drift.strength}],
            }
        )
    if (
        acc_dn
        and acc_dn.state in (MPState.DEVELOPING.value, MPState.CONFIRMED.value)
        and drift
        and drift.direction == "UP"
    ):
        out.append(
            {
                "id": "MP-110",
                "axis": "PRICE_VS_VALUE",
                "label": "DIVERGENCE_DOWN",
                "bull": [{"id": drift.id, "state": drift.state, "strength": drift.strength}],
                "bear": [{"id": acc_dn.id, "state": acc_dn.state, "strength": acc_dn.strength}],
            }
        )
    return out


# ======================================================================================
# day type / silhouette
# ======================================================================================


def classify_day_type(
    facts: SessionFacts, *, evcfg: MPEventConfig, trailing_ranges: list[float] | None = None
) -> DayTypeResult:
    last = facts.last
    prof = facts.final if facts.is_session_complete and facts.final else None
    if last is None:
        return DayTypeResult(
            MPDayType.UNDETERMINED.value, True, [], MPSilhouette.UNDETERMINED.value
        )

    s_high = prof.session_high if prof else last.developing_high
    s_low = prof.session_low if prof else last.developing_low
    s_range = max(s_high - s_low, facts.bin_size)
    poc = prof.poc if prof else last.developing_poc
    vah = prof.vah if prof else last.developing_vah
    val = prof.val if prof else last.developing_val
    close = prof.close if prof else last.bracket_close
    ib = next((sn for sn in facts.snapshots if sn.ib_high is not None), None)
    ib_range = (
        (ib.ib_high - ib.ib_low) if ib and ib.ib_high is not None and ib.ib_low is not None else 0.0
    )
    ib_frac = (ib_range / s_range) if s_range else 1.0
    post = [sn for sn in facts.snapshots if ib and sn.index > ib.index]
    otf_up = _one_timeframing(post, "UP")
    otf_dn = _one_timeframing(post, "DOWN")
    otf_frac = (max(otf_up, otf_dn) / len(post)) if post else 0.0
    va_width_frac = (
        ((vah - val) / s_range) if (vah is not None and val is not None and s_range) else 1.0
    )
    poc_pos = ((poc - s_low) / s_range) if (poc is not None and s_range) else 0.5
    broke_up = any(sn.rel.get("ib_high") == _ABOVE_FULL for sn in post)
    broke_dn = any(sn.rel.get("ib_low") == _BELOW_FULL for sn in post)
    n_dist = facts.structural.n_distributions if facts.structural else 1
    eu, ed = last.ext_up, last.ext_dn

    cands: list[dict] = []

    def cand(name: str, conds: list[bool]) -> None:
        cands.append({"type": name, "conditions_met": sum(conds), "conditions_total": len(conds)})

    trend_up_conds = [
        otf_frac >= evcfg.trend_one_tf_frac and otf_up >= otf_dn,
        ib_frac <= evcfg.trend_ib_range_frac,
        va_width_frac <= evcfg.trend_va_width_max,
        close is not None and vah is not None and close >= vah,
        eu >= evcfg.ib_ext_one_sided_x * max(ib_range, facts.bin_size)
        and ed < evcfg.ib_ext_dead_x * max(ib_range, facts.bin_size),
    ]
    trend_dn_conds = [
        otf_frac >= evcfg.trend_one_tf_frac and otf_dn > otf_up,
        ib_frac <= evcfg.trend_ib_range_frac,
        va_width_frac <= evcfg.trend_va_width_max,
        close is not None and val is not None and close <= val,
        ed >= evcfg.ib_ext_one_sided_x * max(ib_range, facts.bin_size)
        and eu < evcfg.ib_ext_dead_x * max(ib_range, facts.bin_size),
    ]
    cand("TREND_UP", trend_up_conds)
    cand("TREND_DOWN", trend_dn_conds)
    cand("DOUBLE_DISTRIBUTION", [n_dist >= 2])
    cand("NEUTRAL", [broke_up and broke_dn])
    close_at_edge = close is not None and (
        (close - s_low) / s_range <= evcfg.neutral_extreme_frac
        or (s_high - close) / s_range <= evcfg.neutral_extreme_frac
    )
    cand("NEUTRAL_EXTREME", [broke_up and broke_dn, close_at_edge])
    cand("NORMAL_VARIATION", [evcfg.trend_ib_range_frac < ib_frac < evcfg.normal_ib_range_frac])
    cand("NORMAL", [ib_frac >= evcfg.normal_ib_range_frac])
    cand(
        "RANGE",
        [
            ib_frac >= evcfg.normal_ib_range_frac,
            eu + ed < evcfg.ib_ext_dead_x * max(ib_range, facts.bin_size),
        ],
    )
    if trailing_ranges:
        srt = sorted(trailing_ranges)
        p85 = srt[min(len(srt) - 1, int(evcfg.large_range_pctile * len(srt)))]
        cand("LARGE_RANGE", [s_range >= p85, not (all(trend_up_conds) or all(trend_dn_conds))])

    # resolution order
    order = [
        "TREND_UP",
        "TREND_DOWN",
        "DOUBLE_DISTRIBUTION",
        "NEUTRAL_EXTREME",
        "NEUTRAL",
        "NORMAL_VARIATION",
        "NORMAL",
        "RANGE",
        "LARGE_RANGE",
    ]
    by_name = {c["type"]: c for c in cands}
    chosen = MPDayType.UNDETERMINED.value
    for name in order:
        c = by_name.get(name)
        if c and c["conditions_met"] == c["conditions_total"]:
            chosen = name
            break

    # silhouette
    sil = MPSilhouette.UNDETERMINED.value
    if facts.structural is not None:
        st = facts.structural
        if st.n_distributions >= 2:
            sil = MPSilhouette.BIMODAL.value
        elif st.thin_frac >= 0.45:
            sil = MPSilhouette.THIN_I.value
        elif poc_pos >= 0.60 and st.excess_low_run >= 2:
            sil = MPSilhouette.P_SHAPE.value
        elif poc_pos <= 0.40 and st.excess_high_run >= 2:
            sil = MPSilhouette.B_SHAPE.value
        else:
            sil = MPSilhouette.BALANCED_D.value

    return DayTypeResult(
        day_type=chosen,
        provisional=not facts.is_session_complete,
        candidates=sorted(cands, key=lambda c: -c["conditions_met"]),
        silhouette=sil,
    )


# ======================================================================================
# top-level
# ======================================================================================


def detect_events(facts: SessionFacts, *, evcfg: MPEventConfig) -> list[MPEvent]:
    events: list[MPEvent] = []
    events.extend(_opening_events(facts))

    accept_specs = [
        ("MP-010", "prev_vah", "UP", False),
        ("MP-011", "prev_val", "DOWN", False),
        ("MP-016", "prev_high", "UP", True),
        ("MP-017", "prev_low", "DOWN", True),
        ("MP-019", "ib_high", "UP", True),
        ("MP-020", "ib_low", "DOWN", True),
    ]
    for ev_id, lvl, direction, is_range in accept_specs:
        e = _acceptance_event(ev_id, lvl, direction, facts, evcfg, is_range_extreme=is_range)
        if e is not None:
            events.append(e)

    for ev_id, lvl, direction in (
        ("MP-012", "prev_vah", "UP"),
        ("MP-013", "prev_val", "DOWN"),
    ):
        e = _rejection_event(ev_id, lvl, direction, facts, evcfg)
        if e is not None:
            events.append(e)

    dvo = _developing_value_outside(facts, evcfg)
    if dvo is not None:
        events.append(dvo)

    vm = _value_migration_event(facts, evcfg)
    if vm is not None:
        events.append(vm)
    events.extend(_poc_events(facts, evcfg))
    events.extend(_ib_events(facts, evcfg))
    events.extend(_structure_events(facts))
    events.extend(_narrative_events(events))
    return events


def run_event_engine(
    series: OHLCVSeries,
    *,
    config: MarketProfileConfig | None = None,
    evcfg: MPEventConfig | None = None,
    session_open: datetime,
    session_close: datetime,
    session_date,
    instrument_type: InstrumentType,
    has_volume: bool,
    price_ref: float,
    prior: PriorProfile,
    atr: float | None = None,
    now: datetime,
    tick_size: float = 0.05,
    underlying_symbol: str | None = None,
    profile_bin_size: float | None = None,
    is_atypical: bool = False,
    trailing_ranges: list[float] | None = None,
) -> MPEventResult:
    config = config or MarketProfileConfig()
    evcfg = evcfg or MPEventConfig()
    facts = compute_facts(
        series,
        config=config,
        evcfg=evcfg,
        session_open=session_open,
        session_close=session_close,
        session_date=session_date,
        instrument_type=instrument_type,
        has_volume=has_volume,
        price_ref=price_ref,
        prior=prior,
        atr=atr,
        now=now,
        tick_size=tick_size,
        underlying_symbol=underlying_symbol,
        profile_bin_size=profile_bin_size,
        is_atypical=is_atypical,
    )
    if not facts.snapshots:
        return MPEventResult(
            version=MP_EVENTS_VERSION,
            status="INSUFFICIENT_DATA",
            reason="no elapsed brackets with data",
            facts=facts,
            events=[],
            day_type=None,
            tensions=[],
            params_hash=facts.params_hash,
        )
    events = detect_events(facts, evcfg=evcfg)
    day_type = classify_day_type(facts, evcfg=evcfg, trailing_ranges=trailing_ranges)
    tensions = _tension_events(facts, events)
    return MPEventResult(
        version=MP_EVENTS_VERSION,
        status="OK",
        reason=None,
        facts=facts,
        events=events,
        day_type=day_type,
        tensions=tensions,
        params_hash=facts.params_hash,
    )


# ======================================================================================
# serialisation (compact, JSON-safe — for persistence / API)
# ======================================================================================


def _event_to_dict(e: MPEvent) -> dict:
    return {
        "id": e.id,
        "category": e.category,
        "state": e.state,
        "strength": e.strength,
        "level": e.level,
        "direction": e.direction,
        "basis": e.basis,
        "degraded": e.degraded,
        "confirmed_close_only": e.confirmed_close_only,
        "last_bracket": (e.state_history[-1]["bracket_index"] if e.state_history else None),
        "history": [{"state": h["state"], "bracket": h["bracket_index"]} for h in e.state_history],
        "meta": e.meta,
    }


def event_result_to_dict(res: MPEventResult) -> dict:
    """A compact JSON-safe view of an :class:`MPEventResult` for storage / API.

    The full per-bracket ``snapshots`` list is dropped; a single ``developing``
    block from the last snapshot and a small ``structural`` summary are kept.
    """
    f = res.facts
    out: dict = {
        "version": res.version,
        "status": res.status,
        "reason": res.reason,
        "params_hash": res.params_hash,
        "events": [_event_to_dict(e) for e in res.events],
        "tensions": res.tensions,
        "day_type": None,
        "facts": None,
    }
    if res.day_type is not None:
        out["day_type"] = {
            "day_type": res.day_type.day_type,
            "provisional": res.day_type.provisional,
            "silhouette": res.day_type.silhouette,
            "candidates": res.day_type.candidates,
        }
    if f is not None:
        last = f.last
        out["facts"] = {
            "session_date": f.session_date,
            "is_session_complete": f.is_session_complete,
            "n_brackets": len(f.snapshots),
            "bin_size": _r(f.bin_size),
            "opening": {
                "location": f.opening.location,
                "above_prev_high": f.opening.above_prev_high,
                "below_prev_low": f.opening.below_prev_low,
                "gap_band": f.opening.gap_band,
                "gap_sign": f.opening.gap_sign,
                "gap_atr": f.opening.gap_atr,
                "near_prev_poc": f.opening.near_prev_poc,
            },
            "developing": (
                {
                    "bracket": last.index,
                    "poc": _r(last.developing_poc),
                    "vah": _r(last.developing_vah),
                    "val": _r(last.developing_val),
                    "high": _r(last.developing_high),
                    "low": _r(last.developing_low),
                    "ib_high": _r(last.ib_high),
                    "ib_low": _r(last.ib_low),
                    "ext_up": _r(last.ext_up),
                    "ext_dn": _r(last.ext_dn),
                }
                if last is not None
                else None
            ),
            "structural": (
                {
                    "excess_high": f.structural.excess_high,
                    "excess_low": f.structural.excess_low,
                    "poor_high": f.structural.poor_high,
                    "poor_low": f.structural.poor_low,
                    "n_distributions": f.structural.n_distributions,
                    "hvn_bins": [_r(b) for b in f.structural.hvn_bins],
                    "lvn_bins": [_r(b) for b in f.structural.lvn_bins],
                    "single_print_bins": [_r(b) for b in f.structural.single_print_bins],
                    "thin_frac": f.structural.thin_frac,
                }
                if f.structural is not None
                else None
            ),
        }
    return out
