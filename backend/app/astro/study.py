"""Astro x market cross-check (docs/13 §5) — descriptive statistics only.

Joins NIFTY daily candles to ``astro_days`` and summarises next-close return by
weekday / Moon nakshatra / lagna rashi / tithi / paksha. This is exploratory
research: it describes what *has* happened in the sample, it does **not** predict
and emits no trading instruction.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

_DAILY_SQL = text(
    """
    with d1 as (
        select b.ts::date as d, b.open, b.high, b.low, b.close,
               lag(b.close) over (order by b.ts) as prev_close
        from ohlcv_bars b
        join instruments i on i.id = b.instrument_id and i.contract_key = :ck
        where b.timeframe = 'D1'
    )
    select d1.d, d1.open, d1.high, d1.low, d1.close, d1.prev_close,
           ad.day_name, ad.weekday, ad.weekday_lord,
           ad.moon_nakshatra, ad.moon_nakshatra_index, ad.moon_nakshatra_lord, ad.moon_rashi,
           ad.lagna_rashi, ad.lagna_rashi_index,
           ad.tithi, ad.paksha
    from d1
    join astro_days ad on ad.as_of_date = d1.d
    where d1.prev_close is not null and d1.prev_close > 0
    order by d1.d
    """
)

_NAK_ORDER = [
    "Ashwini",
    "Bharani",
    "Krittika",
    "Rohini",
    "Mrigashira",
    "Ardra",
    "Punarvasu",
    "Pushya",
    "Ashlesha",
    "Magha",
    "Purva Phalguni",
    "Uttara Phalguni",
    "Hasta",
    "Chitra",
    "Swati",
    "Vishakha",
    "Anuradha",
    "Jyeshtha",
    "Mula",
    "Purva Ashadha",
    "Uttara Ashadha",
    "Shravana",
    "Dhanishta",
    "Shatabhisha",
    "Purva Bhadrapada",
    "Uttara Bhadrapada",
    "Revati",
]
_RASHI_ORDER = [
    "Mesha",
    "Vrishabha",
    "Mithuna",
    "Karka",
    "Simha",
    "Kanya",
    "Tula",
    "Vrischika",
    "Dhanu",
    "Makara",
    "Kumbha",
    "Meena",
]
_DAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]


@dataclass(slots=True)
class Bucket:
    key: str
    n: int
    mean_ret: float
    median_ret: float
    std_ret: float
    pct_up: float
    mean_range: float
    total_ret: float  # sum of daily % (simple, not compounded)
    best: float
    worst: float


@dataclass(slots=True)
class StudyResult:
    underlying: str
    first: date
    last: date
    n_days: int
    baseline: Bucket
    by_weekday: list[Bucket] = field(default_factory=list)
    by_weekday_lord: list[Bucket] = field(default_factory=list)
    by_moon_nakshatra: list[Bucket] = field(default_factory=list)
    by_moon_nakshatra_lord: list[Bucket] = field(default_factory=list)
    by_lagna_rashi: list[Bucket] = field(default_factory=list)
    by_moon_rashi: list[Bucket] = field(default_factory=list)
    by_tithi: list[Bucket] = field(default_factory=list)
    by_paksha: list[Bucket] = field(default_factory=list)


def _bucket_dict(b: Bucket) -> dict:
    return {
        "key": b.key,
        "n": b.n,
        "mean_ret": round(b.mean_ret, 4),
        "median_ret": round(b.median_ret, 4),
        "std_ret": round(b.std_ret, 4),
        "pct_up": round(b.pct_up, 2),
        "mean_range": round(b.mean_range, 4),
        "total_ret": round(b.total_ret, 2),
        "best": round(b.best, 3),
        "worst": round(b.worst, 3),
    }


def result_to_dict(r: StudyResult) -> dict:
    groups = (
        "by_weekday",
        "by_weekday_lord",
        "by_moon_nakshatra",
        "by_moon_nakshatra_lord",
        "by_lagna_rashi",
        "by_moon_rashi",
        "by_tithi",
        "by_paksha",
    )
    out: dict = {
        "underlying": r.underlying,
        "first": r.first.isoformat(),
        "last": r.last.isoformat(),
        "n_days": r.n_days,
        "baseline": _bucket_dict(r.baseline),
    }
    for g in groups:
        out[g] = [_bucket_dict(b) for b in getattr(r, g)]
    return out


def _bucket(key: str, rets: list[float], ranges: list[float]) -> Bucket:
    n = len(rets)
    return Bucket(
        key=key,
        n=n,
        mean_ret=statistics.fmean(rets),
        median_ret=statistics.median(rets),
        std_ret=statistics.pstdev(rets) if n > 1 else 0.0,
        pct_up=100.0 * sum(1 for r in rets if r > 0) / n,
        mean_range=statistics.fmean(ranges),
        total_ret=sum(rets),
        best=max(rets),
        worst=min(rets),
    )


def _group(rows: list[dict], key_fn, order: list | None = None) -> list[Bucket]:
    acc: dict[str, tuple[list[float], list[float]]] = {}
    for r in rows:
        k = key_fn(r)
        acc.setdefault(k, ([], []))
        acc[k][0].append(r["ret"])
        acc[k][1].append(r["range"])
    buckets = [_bucket(k, v[0], v[1]) for k, v in acc.items()]
    if order:
        pos = {name: i for i, name in enumerate(order)}
        buckets.sort(key=lambda b: pos.get(b.key, 999))
    else:
        buckets.sort(key=lambda b: b.key)
    return buckets


def run_study(
    session: Session,
    *,
    underlying: str = "NIFTY-INDEX",
    start: date | None = None,
    end: date | None = None,
) -> StudyResult:
    raw = session.execute(_DAILY_SQL, {"ck": underlying}).mappings().all()
    rows: list[dict] = []
    for m in raw:
        if start and m["d"] < start:
            continue
        if end and m["d"] > end:
            continue
        pc = float(m["prev_close"])
        rows.append(
            {
                "d": m["d"],
                "ret": (float(m["close"]) - pc) / pc * 100.0,
                "range": (float(m["high"]) - float(m["low"])) / pc * 100.0,
                "day_name": m["day_name"],
                "weekday_lord": m["weekday_lord"].title(),
                "moon_nakshatra": m["moon_nakshatra"],
                "moon_nakshatra_lord": m["moon_nakshatra_lord"].title(),
                "moon_rashi": m["moon_rashi"],
                "lagna_rashi": m["lagna_rashi"],
                "tithi": m["tithi"],
                "paksha": m["paksha"],
            }
        )
    if not rows:
        raise ValueError("no overlapping NIFTY D1 / astro_days rows for the given range")

    all_ret = [r["ret"] for r in rows]
    all_rng = [r["range"] for r in rows]
    return StudyResult(
        underlying=underlying,
        first=rows[0]["d"],
        last=rows[-1]["d"],
        n_days=len(rows),
        baseline=_bucket("All days", all_ret, all_rng),
        by_weekday=_group(rows, lambda r: r["day_name"], _DAY_ORDER),
        by_weekday_lord=_group(rows, lambda r: r["weekday_lord"]),
        by_moon_nakshatra=_group(rows, lambda r: r["moon_nakshatra"], _NAK_ORDER),
        by_moon_nakshatra_lord=_group(rows, lambda r: r["moon_nakshatra_lord"]),
        by_lagna_rashi=_group(rows, lambda r: r["lagna_rashi"], _RASHI_ORDER),
        by_moon_rashi=_group(rows, lambda r: r["moon_rashi"], _RASHI_ORDER),
        by_tithi=_group(rows, lambda r: f"{r['tithi']:02d}"),
        by_paksha=_group(rows, lambda r: r["paksha"]),
    )
