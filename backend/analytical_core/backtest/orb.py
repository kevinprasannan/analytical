"""Opening-range breakout (ORB) backtest (docs/16).

Pure and deterministic, stdlib only. For each trading day: take the high/low of
a *range window*, watch a *breakout window* for the first bar to **close**
beyond either edge (a wick alone doesn't count — see ``_day``), then measure —
from the breakout minute to a configurable cut-off — whether price reached a
multiple of the range (target, checked intrabar) before hitting the opposite
edge (stop, also intrabar). Aggregates hit-rates across the sample.

Descriptive research. It classifies past sessions and emits **no signal, no
label, no BUY/SELL**.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

INDEX_ORB_VERSION = "0.1.0"

_LONG = "LONG"
_SHORT = "SHORT"
_NONE = "NONE"


@dataclass(frozen=True, slots=True)
class Bar:
    minute: int  # IST minute-of-day, 0..1439 (bar-open)
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True, slots=True)
class DayBars:
    date: str  # ISO
    weekday: int  # 0 = Monday
    bars: tuple[Bar, ...]  # one session, ascending by minute


@dataclass(frozen=True, slots=True)
class OrbConfig:
    range_start: int
    range_end: int  # exclusive
    break_start: int
    break_end: int  # inclusive
    measure_until: int  # inclusive
    target_mults: tuple[float, ...] = (0.5, 1.0)

    def validate(self) -> None:
        vals = [
            self.range_start,
            self.range_end,
            self.break_start,
            self.break_end,
            self.measure_until,
        ]
        if any(not (0 <= v < 1440) for v in vals):
            raise ValueError("all times must be an IST minute-of-day in [0, 1440)")
        if not self.range_start < self.range_end:
            raise ValueError("range_start must be < range_end")
        if not self.break_start <= self.break_end:
            raise ValueError("break_start must be <= break_end")
        if self.range_end > self.break_end:
            raise ValueError("range must close no later than the breakout window")
        if self.break_start > self.measure_until:
            raise ValueError("measure_until must be >= break_start")
        if not self.target_mults or any(m <= 0 for m in self.target_mults):
            raise ValueError("target_mults must be positive")


@dataclass(frozen=True, slots=True)
class TargetOutcome:
    mult: float
    hit: bool
    minutes_to_hit: int | None  # from the breakout minute
    stopped_first: bool  # the stop was reached before this target (or instead of it)


@dataclass(frozen=True, slots=True)
class DayResult:
    date: str
    weekday: int
    range_high: float | None
    range_low: float | None
    range_size: float | None
    direction: str  # LONG | SHORT | NONE
    break_minute: int | None
    break_immediate: bool
    entry_level: float | None
    stop_level: float | None
    stop_hit: bool
    stop_minute: int | None
    mfe_r: float | None  # max favourable excursion from entry_level, in range units
    mae_r: float | None  # max adverse excursion (positive = against the trade)
    targets: tuple[TargetOutcome, ...]
    note: str | None


@dataclass(frozen=True, slots=True)
class TargetStat:
    mult: float
    hits: int
    hit_rate: float  # hits / n_breakout
    avg_minutes_to_hit: float | None


@dataclass(frozen=True, slots=True)
class WeekdayStat:
    weekday: int
    n: int
    n_breakout: int
    per_target_hit_rate: tuple[tuple[float, float], ...]  # (mult, rate over n_breakout)


@dataclass(frozen=True, slots=True)
class OrbAggregate:
    n_days: int
    n_with_range: int
    n_breakout: int
    breakout_rate: float
    n_long: int
    n_short: int
    n_immediate: int
    stop_rate: float  # stops / n_breakout
    avg_range_size: float | None
    avg_mfe_r: float | None
    avg_mae_r: float | None
    per_target: tuple[TargetStat, ...]
    by_weekday: tuple[WeekdayStat, ...]


@dataclass(frozen=True, slots=True)
class OrbResult:
    config: OrbConfig
    aggregate: OrbAggregate
    days: tuple[DayResult, ...]
    index_orb_version: str = field(default=INDEX_ORB_VERSION)


# ---------------------------------------------------------------------------


def _window(bars: Sequence[Bar], lo: int, hi: int, *, inclusive_hi: bool) -> list[Bar]:
    return [b for b in bars if lo <= b.minute < hi or (inclusive_hi and b.minute == hi)]


def _day(day: DayBars, cfg: OrbConfig) -> DayResult:
    empty_targets = tuple(TargetOutcome(m, False, None, False) for m in cfg.target_mults)

    def none(note: str) -> DayResult:
        return DayResult(
            date=day.date,
            weekday=day.weekday,
            range_high=None,
            range_low=None,
            range_size=None,
            direction=_NONE,
            break_minute=None,
            break_immediate=False,
            entry_level=None,
            stop_level=None,
            stop_hit=False,
            stop_minute=None,
            mfe_r=None,
            mae_r=None,
            targets=empty_targets,
            note=note,
        )

    rng = _window(day.bars, cfg.range_start, cfg.range_end, inclusive_hi=False)
    if not rng:
        return none("no bars in the range window")
    r_hi = max(b.high for b in rng)
    r_lo = min(b.low for b in rng)
    r_size = r_hi - r_lo
    if r_size <= 0:
        return none("range has zero size")

    win = _window(day.bars, cfg.break_start, cfg.break_end, inclusive_hi=True)
    if not win:
        return _none_with_range(
            day, r_hi, r_lo, r_size, empty_targets, "no bars in the breakout window"
        )

    direction = _NONE
    break_minute: int | None = None
    immediate = False

    # breakout requires a CONFIRMED CLOSE beyond the edge, not just a wick — a
    # bar that pokes through on the high/low but closes back inside is not
    # counted, so a shakeout wick can't flip the call (docs/16 §1).
    first = win[0]
    if first.open > r_hi and first.close >= r_hi:
        direction, break_minute, immediate = _LONG, cfg.break_start, True
    elif first.open < r_lo and first.close <= r_lo:
        direction, break_minute, immediate = _SHORT, cfg.break_start, True
    else:
        for b in win:
            if b.close >= r_hi:
                direction, break_minute = _LONG, b.minute
                break
            if b.close <= r_lo:
                direction, break_minute = _SHORT, b.minute
                break

    if direction == _NONE:
        return _none_with_range(day, r_hi, r_lo, r_size, empty_targets, "no breakout in the window")

    entry = r_hi if direction == _LONG else r_lo
    stop = r_lo if direction == _LONG else r_hi
    path = [b for b in day.bars if break_minute <= b.minute <= cfg.measure_until]

    stop_hit = False
    stop_minute: int | None = None
    mfe = mae = 0.0
    tgt_hit_minute: dict[float, int] = {}

    for b in path:
        if direction == _LONG:
            mfe = max(mfe, b.high - entry)
            mae = max(mae, entry - b.low)
            hit_stop = b.low <= stop
            for m in cfg.target_mults:
                if m not in tgt_hit_minute and b.high >= entry + m * r_size:
                    # pessimistic tie-break: if this same bar also hits the stop,
                    # the stop counts first (see docs/16)
                    if not hit_stop:
                        tgt_hit_minute[m] = b.minute
        else:
            mfe = max(mfe, entry - b.low)
            mae = max(mae, b.high - entry)
            hit_stop = b.high >= stop
            for m in cfg.target_mults:
                if m not in tgt_hit_minute and b.low <= entry - m * r_size:
                    if not hit_stop:
                        tgt_hit_minute[m] = b.minute
        if hit_stop and not stop_hit:
            stop_hit = True
            stop_minute = b.minute
            break  # once stopped, no further targets can be "first"

    targets: list[TargetOutcome] = []
    for m in cfg.target_mults:
        if m in tgt_hit_minute:
            targets.append(TargetOutcome(m, True, tgt_hit_minute[m] - break_minute, False))
        else:
            targets.append(TargetOutcome(m, False, None, stop_hit))

    return DayResult(
        date=day.date,
        weekday=day.weekday,
        range_high=round(r_hi, 4),
        range_low=round(r_lo, 4),
        range_size=round(r_size, 4),
        direction=direction,
        break_minute=break_minute,
        break_immediate=immediate,
        entry_level=round(entry, 4),
        stop_level=round(stop, 4),
        stop_hit=stop_hit,
        stop_minute=stop_minute,
        mfe_r=round(mfe / r_size, 4),
        mae_r=round(mae / r_size, 4),
        targets=tuple(targets),
        note=None,
    )


def _none_with_range(day, r_hi, r_lo, r_size, empty_targets, note) -> DayResult:
    return DayResult(
        date=day.date,
        weekday=day.weekday,
        range_high=round(r_hi, 4),
        range_low=round(r_lo, 4),
        range_size=round(r_size, 4),
        direction=_NONE,
        break_minute=None,
        break_immediate=False,
        entry_level=None,
        stop_level=None,
        stop_hit=False,
        stop_minute=None,
        mfe_r=None,
        mae_r=None,
        targets=empty_targets,
        note=note,
    )


def _aggregate(cfg: OrbConfig, results: Sequence[DayResult]) -> OrbAggregate:
    with_range = [r for r in results if r.range_size is not None]
    broke = [r for r in results if r.direction != _NONE]
    nb = len(broke)

    def _rate(x: int) -> float:
        return round(x / nb, 4) if nb else 0.0

    per_target: list[TargetStat] = []
    for i, m in enumerate(cfg.target_mults):
        hits = [r.targets[i] for r in broke if r.targets[i].hit]
        mins = [t.minutes_to_hit for t in hits if t.minutes_to_hit is not None]
        per_target.append(
            TargetStat(
                mult=m,
                hits=len(hits),
                hit_rate=_rate(len(hits)),
                avg_minutes_to_hit=round(sum(mins) / len(mins), 2) if mins else None,
            )
        )

    by_weekday: list[WeekdayStat] = []
    for wd in range(7):
        wdays = [r for r in results if r.weekday == wd]
        if not wdays:
            continue
        wbroke = [r for r in wdays if r.direction != _NONE]
        wnb = len(wbroke)
        rates = tuple(
            (
                m,
                round(sum(1 for r in wbroke if r.targets[i].hit) / wnb, 4) if wnb else 0.0,
            )
            for i, m in enumerate(cfg.target_mults)
        )
        by_weekday.append(
            WeekdayStat(weekday=wd, n=len(wdays), n_breakout=wnb, per_target_hit_rate=rates)
        )

    sizes = [r.range_size for r in with_range if r.range_size]
    mfes = [r.mfe_r for r in broke if r.mfe_r is not None]
    maes = [r.mae_r for r in broke if r.mae_r is not None]

    return OrbAggregate(
        n_days=len(results),
        n_with_range=len(with_range),
        n_breakout=nb,
        breakout_rate=round(nb / len(with_range), 4) if with_range else 0.0,
        n_long=sum(1 for r in broke if r.direction == _LONG),
        n_short=sum(1 for r in broke if r.direction == _SHORT),
        n_immediate=sum(1 for r in broke if r.break_immediate),
        stop_rate=_rate(sum(1 for r in broke if r.stop_hit)),
        avg_range_size=round(sum(sizes) / len(sizes), 4) if sizes else None,
        avg_mfe_r=round(sum(mfes) / len(mfes), 4) if mfes else None,
        avg_mae_r=round(sum(maes) / len(maes), 4) if maes else None,
        per_target=tuple(per_target),
        by_weekday=tuple(by_weekday),
    )


def run_orb(days: Sequence[DayBars], config: OrbConfig) -> OrbResult:
    config.validate()
    results = tuple(_day(d, config) for d in days)
    return OrbResult(config=config, aggregate=_aggregate(config, results), days=results)
