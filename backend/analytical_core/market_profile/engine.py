"""Market Profile engine (docs/05 §10). Deterministic; shared period model +
bucketing + POC / value-area / shape between the TPO and Volume builders."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from analytical_core.enums import InstrumentType, ProfileType
from analytical_core.market_profile.config import MarketProfileConfig
from analytical_core.series import OHLCVSeries

_DP = 4


def _r(x: float | None) -> float | None:
    return None if x is None else round(x, _DP)


def _letter(i: int) -> str:
    if i < 26:
        return chr(65 + i)
    if i < 52:
        return chr(97 + (i - 26))
    return f"[{i}]"


@dataclass(frozen=True, slots=True)
class Period:
    index: int
    start: datetime
    end: datetime
    letter: str
    is_partial: bool


def session_periods(
    session_open: datetime,
    session_close: datetime,
    tpo_minutes: int,
    partial_period_policy: str = "KEEP",
) -> list[Period]:
    tpo = timedelta(minutes=tpo_minutes)
    span = session_close - session_open
    n_full = int(span // tpo)
    remainder = span - n_full * tpo
    periods: list[Period] = []
    for i in range(n_full):
        start = session_open + i * tpo
        periods.append(Period(i, start, start + tpo, _letter(i), is_partial=False))
    if remainder > timedelta(0):
        start = session_open + n_full * tpo
        if partial_period_policy == "MERGE_PREV" and periods:
            prev = periods[-1]
            periods[-1] = Period(
                prev.index, prev.start, session_close, prev.letter, is_partial=False
            )
        elif partial_period_policy == "DROP":
            pass
        else:  # KEEP
            periods.append(Period(n_full, start, session_close, _letter(n_full), is_partial=True))
    return periods


def _period_of(ts: datetime, periods: Sequence[Period]) -> Period | None:
    for p in periods:
        if p.start <= ts < p.end:
            return p
    # a bar exactly at close belongs to the last period
    if periods and ts == periods[-1].end:
        return periods[-1]
    return None


# ======================================================================================
# result types
# ======================================================================================


@dataclass(slots=True)
class ProfileResult:
    profile_type: str
    bin_size: float
    poc: float | None
    vah: float | None
    val: float | None
    value_area_pct: float
    ib_high: float | None
    ib_low: float | None
    ib_complete: bool
    session_high: float
    session_low: float
    range: float
    close: float
    close_vs_poc: str
    close_vs_vah: str
    close_vs_val: str
    close_in_value_area: bool
    profile_shape: str
    is_session_complete: bool
    n_periods_elapsed: int
    n_periods_total: int
    vwap_proxy: float
    bins: list[dict] = field(default_factory=list)
    excluded_bars: int = 0
    gap_count: int = 0

    def values(self, session_date, s_start, s_end) -> dict:
        return {
            "profile_type": self.profile_type,
            "session_date": str(session_date),
            "session_start_ts": s_start.isoformat(),
            "session_end_ts": s_end.isoformat(),
            "bin_size": _r(self.bin_size),
            "poc": _r(self.poc),
            "vah": _r(self.vah),
            "val": _r(self.val),
            "value_area_pct": self.value_area_pct,
            "ib_high": _r(self.ib_high),
            "ib_low": _r(self.ib_low),
            "ib_complete": self.ib_complete,
            "session_high": _r(self.session_high),
            "session_low": _r(self.session_low),
            "range": _r(self.range),
            "close": _r(self.close),
            "close_vs_poc": self.close_vs_poc,
            "close_vs_vah": self.close_vs_vah,
            "close_vs_val": self.close_vs_val,
            "close_in_value_area": self.close_in_value_area,
            "profile_shape": self.profile_shape,
            "is_session_complete": self.is_session_complete,
            "n_periods_elapsed": self.n_periods_elapsed,
            "n_periods_total": self.n_periods_total,
        }


@dataclass(slots=True)
class MarketProfileOutput:
    status: str  # "OK" | "INSUFFICIENT_DATA"
    reason: str | None
    profiles: dict[str, ProfileResult]
    params: dict
    source_max_ts: str | None


# ======================================================================================
# bin size (docs/05 §10.4)
# ======================================================================================


def _round_to_increment(x: float, increment: float) -> float:
    if increment <= 0:
        return x
    return round(x / increment) * increment


def resolve_bin_size(
    *,
    instrument_type: InstrumentType,
    config: MarketProfileConfig,
    price_ref: float,
    tick_size: float,
    underlying_symbol: str | None,
    explicit: float | None,
) -> float:
    if explicit is not None and explicit > 0:
        return float(explicit)
    if instrument_type is InstrumentType.OPTION:
        return max(float(tick_size or 0.05), abs(price_ref) * config.option_bin_pct)
    inc = config.increment_by_underlying.get(
        (underlying_symbol or "").upper(), config.default_increment
    )
    derived = _round_to_increment(abs(price_ref) * config.bin_pct, inc)
    return max(derived, inc)


# ======================================================================================
# builder
# ======================================================================================


def _bin_lo(price: float, bin_size: float) -> float:
    return math.floor(price / bin_size) * bin_size


def _overlapped_bins(low: float, high: float, bin_size: float) -> list[float]:
    start = _bin_lo(low, bin_size)
    end = _bin_lo(high, bin_size)
    out: list[float] = []
    b = start
    # guard against fp drift
    while b <= end + bin_size * 1e-9:
        out.append(round(b, 10))
        b += bin_size
    return out or [start]


def _classify(
    *,
    metric: dict[float, float],
    total: float,
    poc: float,
    vah: float,
    val: float,
    session_high: float,
    session_low: float,
    close: float,
    cfg: MarketProfileConfig,
) -> str:
    rng = session_high - session_low
    if rng <= 0:
        return "NORMAL"
    poc_pos = (poc - session_low) / rng
    va_width = (vah - val) / rng
    lo_third_hi = session_low + rng / 3.0
    hi_third_lo = session_high - rng / 3.0
    lower = math.fsum(m for b, m in metric.items() if b < lo_third_hi)
    upper = math.fsum(m for b, m in metric.items() if b >= hi_third_lo)

    if close >= vah and poc_pos >= cfg.trend_poc_pos and va_width <= cfg.trend_va_width_max:
        return "TREND_UP"
    if close <= val and poc_pos <= (1 - cfg.trend_poc_pos) and va_width <= cfg.trend_va_width_max:
        return "TREND_DOWN"
    if poc_pos >= cfg.p_b_poc_pos and (lower / total) <= cfg.tail_pct:
        return "P_SHAPE"
    if poc_pos <= (1 - cfg.p_b_poc_pos) and (upper / total) <= cfg.tail_pct:
        return "B_SHAPE"
    peaks = [b for b, mm in metric.items() if mm >= cfg.dd_peak_pct * total]
    if len(peaks) >= 2:
        peaks.sort()
        prices = sorted(metric)
        for i in range(len(peaks) - 1):
            lo_i = prices.index(peaks[i])
            hi_i = prices.index(peaks[i + 1])
            if any(metric[prices[k]] <= cfg.dd_valley_pct * total for k in range(lo_i + 1, hi_i)):
                return "DOUBLE_DISTRIBUTION"
    return "NORMAL"


def _rel(x: float, ref: float, tol: float) -> str:
    if abs(x - ref) < tol:
        return "AT"
    return "ABOVE" if x > ref else "BELOW"


def build_profile(
    series: OHLCVSeries,
    periods: list[Period],
    kind: ProfileType,
    *,
    bin_size: float,
    config: MarketProfileConfig,
    session_open: datetime,
    session_close: datetime,
    now: datetime,
) -> ProfileResult | None:
    tol = bin_size / 2.0
    letters_at: dict[float, set[str]] = {}
    vol_at: dict[float, list[float]] = {}
    excluded = 0
    seen_periods: set[int] = set()
    highs: list[float] = []
    lows: list[float] = []
    typ_vol: list[tuple[float, float]] = []
    last_close = float(series.close[-1]) if len(series) else 0.0

    for i in range(len(series)):
        ts = series.ts[i].astimezone(session_open.tzinfo)
        if not (session_open <= ts < session_close) and ts != session_close:
            excluded += 1
            continue
        p = _period_of(ts, periods)
        if p is None:
            excluded += 1
            continue
        seen_periods.add(p.index)
        lo, hi, c = float(series.low[i]), float(series.high[i]), float(series.close[i])
        highs.append(hi)
        lows.append(lo)
        vol = float(series.volume[i])
        typ_vol.append(((hi + lo + c) / 3.0, vol))
        obins = _overlapped_bins(lo, hi, bin_size)
        for b in obins:
            letters_at.setdefault(b, set()).add(p.letter)
        if kind is ProfileType.VOLUME:
            share = vol / len(obins)
            for b in obins:
                vol_at.setdefault(b, []).append(share)

    if not highs:
        return None
    session_high = max(highs)
    session_low = min(lows)

    if kind is ProfileType.TPO:
        metric = {b: float(len(s)) for b, s in letters_at.items()}
    else:
        metric = {b: math.fsum(v) for b, v in vol_at.items()}
    total = math.fsum(metric.values())
    if total <= 0.0 or not metric:
        return None

    span_bins = (
        int(round((_bin_lo(session_high, bin_size) - _bin_lo(session_low, bin_size)) / bin_size))
        + 1
    )
    if span_bins < config.min_bins:
        return None

    vol_total = math.fsum(v for _t, v in typ_vol)
    if vol_total > 0:
        vwap = math.fsum(t * v for t, v in typ_vol) / vol_total
    else:
        vwap = (session_high + session_low) / 2.0

    prices = sorted(metric)
    max_m = max(metric.values())
    candidates = [b for b in prices if metric[b] == max_m]
    poc = min(candidates, key=lambda b: (abs(b - vwap), b))
    poc_idx = prices.index(poc)

    n = len(prices)
    va = {poc_idx}
    running = metric[poc]
    up, down = poc_idx + 1, poc_idx - 1
    step = 2 if config.va_expansion == "PAIR" else 1
    target = config.value_area_pct * total
    guard = 0
    while running < target and (up < n or down >= 0) and guard < 4 * n + 8:
        guard += 1
        up_in, down_in = up < n, down >= 0
        take_up: bool
        if up_in and down_in:
            up_val = metric[prices[up]] + (
                metric[prices[up + 1]] if step == 2 and up + 1 < n else 0.0
            )
            dn_val = metric[prices[down]] + (
                metric[prices[down - 1]] if step == 2 and down - 1 >= 0 else 0.0
            )
            take_up = up_val >= dn_val
        else:
            take_up = up_in
        if take_up:
            for _ in range(step):
                if up < n:
                    va.add(up)
                    running += metric[prices[up]]
                    up += 1
        else:
            for _ in range(step):
                if down >= 0:
                    va.add(down)
                    running += metric[prices[down]]
                    down -= 1
    vah = max(prices[i] for i in va)
    val = min(prices[i] for i in va)

    ib_hi = ib_lo = None
    ib_ct = config.ib_periods
    ib_seen = sum(1 for k in range(ib_ct) if k in seen_periods)
    if ib_seen >= ib_ct:
        ib_bars = [
            (float(series.high[i]), float(series.low[i]))
            for i in range(len(series))
            if (pp := _period_of(series.ts[i].astimezone(session_open.tzinfo), periods)) is not None
            and pp.index < ib_ct
        ]
        if ib_bars:
            ib_hi = max(h for h, _ in ib_bars)
            ib_lo = min(low_ for _, low_ in ib_bars)

    shape = _classify(
        metric=metric,
        total=total,
        poc=poc,
        vah=vah,
        val=val,
        session_high=session_high,
        session_low=session_low,
        close=last_close,
        cfg=config,
    )
    is_complete = now >= session_close

    bins = [
        (
            {
                "price_low": round(b, _DP),
                "tpo_count": int(metric[b]),
                # the TPO letters that printed at this price, oldest first (e.g.
                # "ABC") — the classic letter-profile read, alongside the count
                "letters": "".join(sorted(letters_at.get(b, ()))),
            }
            if kind is ProfileType.TPO
            else {"price_low": round(b, _DP), "volume": round(metric[b], _DP)}
        )
        for b in prices
    ]

    return ProfileResult(
        profile_type=kind.value,
        bin_size=bin_size,
        poc=poc,
        vah=vah,
        val=val,
        value_area_pct=config.value_area_pct,
        ib_high=ib_hi,
        ib_low=ib_lo,
        ib_complete=ib_seen >= ib_ct,
        session_high=session_high,
        session_low=session_low,
        range=session_high - session_low,
        close=last_close,
        close_vs_poc=_rel(last_close, poc, tol),
        close_vs_vah=_rel(last_close, vah, tol),
        close_vs_val=_rel(last_close, val, tol),
        close_in_value_area=val - tol <= last_close <= vah + tol,
        profile_shape=shape,
        is_session_complete=is_complete,
        n_periods_elapsed=len(seen_periods),
        n_periods_total=len(periods),
        vwap_proxy=vwap,
        bins=bins,
        excluded_bars=excluded,
    )


def market_profile(
    series: OHLCVSeries,
    *,
    config: MarketProfileConfig,
    session_open: datetime,
    session_close: datetime,
    session_date,
    instrument_type: InstrumentType,
    has_volume: bool,
    price_ref: float,
    tick_size: float = 0.05,
    underlying_symbol: str | None = None,
    profile_bin_size: float | None = None,
    now: datetime,
) -> MarketProfileOutput:
    params = config.as_dict()
    source_max_ts = series.ts[-1].isoformat() if len(series) else None
    periods = session_periods(
        session_open, session_close, config.tpo_minutes, config.partial_period_policy
    )
    elapsed = len(
        {
            p.index
            for i in range(len(series))
            if (p := _period_of(series.ts[i].astimezone(session_open.tzinfo), periods)) is not None
        }
    )
    if elapsed < config.min_periods_for_result:
        return MarketProfileOutput(
            status="INSUFFICIENT_DATA",
            reason=f"only {elapsed} of {config.min_periods_for_result} periods elapsed",
            profiles={},
            params=params,
            source_max_ts=source_max_ts,
        )

    bin_size = resolve_bin_size(
        instrument_type=instrument_type,
        config=config,
        price_ref=price_ref,
        tick_size=tick_size,
        underlying_symbol=underlying_symbol,
        explicit=profile_bin_size,
    )

    tpo = build_profile(
        series,
        periods,
        ProfileType.TPO,
        bin_size=bin_size,
        config=config,
        session_open=session_open,
        session_close=session_close,
        now=now,
    )
    if tpo is None:
        return MarketProfileOutput(
            status="INSUFFICIENT_DATA",
            reason="price range too small for a meaningful profile",
            profiles={},
            params=params,
            source_max_ts=source_max_ts,
        )
    profiles = {ProfileType.TPO.value: tpo}
    if has_volume:
        vp = build_profile(
            series,
            periods,
            ProfileType.VOLUME,
            bin_size=bin_size,
            config=config,
            session_open=session_open,
            session_close=session_close,
            now=now,
        )
        if vp is not None:
            profiles[ProfileType.VOLUME.value] = vp

    return MarketProfileOutput(
        status="OK", reason=None, profiles=profiles, params=params, source_max_ts=source_max_ts
    )
