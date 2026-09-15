"""Per-day astro × market log (docs/13 §5.2).

``run_daylog`` joins the index D1 candle to ``astro_days`` and returns the
individual days (date, that day's close-to-close return, and the sky at
09:00 IST) with server-side filtering, sorting and pagination. A ``summary``
bucket describes the filtered set so a "weekday + tithi + nakshatra"
combination reads as a single market-performance report.

``day_detail`` drills into one date: the D1 OHLC, the H1 (hourly) bars for that
session, and the full 09:00 IST chart — panchang scalars, sidereal planetary
positions, and Parashari Shadbala.

Descriptive only — it reports what the sample did, it forecasts nothing and
emits no trading instruction (decision 15).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.astro import vedic
from app.astro.dasha import kp_chain, moon_dasha, moon_dasha_head
from app.astro.study import Bucket, _bucket, _bucket_dict

_IST = timezone(timedelta(hours=5, minutes=30))

#: process-wide Swiss-Ephemeris handle, lazily built (used only to place the Sun
#: at the new moon that started the current lunar month — see ``_chandra_masa``).
_ASTRO_ENGINE = None


def _engine():
    global _ASTRO_ENGINE
    if _ASTRO_ENGINE is None:
        from app.astro.ephemeris import AstroEngine

        _ASTRO_ENGINE = AstroEngine()
    return _ASTRO_ENGINE


def _chandra_masa(moon_lon: float | None, sun_lon: float | None, d: date) -> str | None:
    """Amanta lunar-month name for date ``d`` — the sign the Sun held at the
    new moon that began the month. The new-moon instant is back-estimated from
    the current Sun-Moon elongation (good to well under a degree of Sun travel),
    so month boundaries within ~a day of a sankranti are approximate; adhika
    (leap) months are not distinguished (docs/13 §5.3)."""
    if moon_lon is None or sun_lon is None:
        return None
    days_in = vedic.days_since_new_moon(moon_lon, sun_lon)
    nm_dt = datetime.combine(d, time(9, 0), tzinfo=_IST) - timedelta(days=days_in)
    try:
        sun_nm = _engine().position(nm_dt, "SUN")
    except Exception:  # pragma: no cover - ephemeris/data edge
        return None
    return vedic.MASA_NAMES[vedic.chandra_masa_index_from_newmoon_sun(sun_nm.rashi_index)]


#: session-length bases the Moon-anchored dasha is reported on (docs/13 §5.6)
MOON_DASHA_BASES: tuple[float, ...] = (390.0, 400.0)

_ROWS_SQL = text(
    """
    with d1 as (
        select b.ts::date as d, b.open, b.high, b.low, b.close,
               lag(b.close) over (order by b.ts) as prev_close
        from ohlcv_bars b
        join instruments i on i.id = b.instrument_id and i.contract_key = :ck
        where b.timeframe = 'D1'
    )
    select d1.d, d1.open, d1.high, d1.low, d1.close, d1.prev_close,
           ad.weekday, ad.day_name, ad.weekday_lord,
           ad.tithi, ad.paksha,
           ad.moon_nakshatra, ad.moon_nakshatra_lord, ad.moon_rashi, ad.moon_pada,
           ad.lagna_rashi, ad.sun_rashi,
           mp.longitude as moon_longitude
    from d1
    join astro_days ad on ad.as_of_date = d1.d
    left join astro_positions mp on mp.as_of_date = d1.d and mp.body = 'MOON'
    where d1.prev_close is not null and d1.prev_close > 0
    order by d1.d
    """
)

# sort token -> row-dict key (all ascending unless prefixed with '-')
SORT_KEYS = {
    "d": "d",
    "ret": "ret_pct",
    "range": "range_pct",
    "gap": "gap_pct",
    "close": "close",
    "tithi": "tithi",
    "pada": "moon_pada",
    "day": "day",
}

# filter param -> (row-dict key, caster)
_TEXT_FILTERS = (
    "weekday_lord",
    "paksha",
    "moon_nakshatra",
    "moon_nakshatra_lord",
    "moon_rashi",
    "lagna_rashi",
    "sun_rashi",
)


def _zero_bucket(key: str) -> Bucket:
    return Bucket(
        key=key,
        n=0,
        mean_ret=0.0,
        median_ret=0.0,
        std_ret=0.0,
        pct_up=0.0,
        mean_range=0.0,
        total_ret=0.0,
        best=0.0,
        worst=0.0,
    )


def _matches(row: dict, filters: dict[str, Any]) -> bool:
    wd = filters.get("weekday")
    if wd is not None:
        # accept an int 0-4 or a day name
        if isinstance(wd, int):
            if row["weekday"] != wd:
                return False
        elif row["day_name"].lower() != str(wd).lower():
            return False
    if filters.get("tithi") is not None and row["tithi"] != filters["tithi"]:
        return False
    if filters.get("month") is not None and row["month"] != filters["month"]:
        return False
    if filters.get("day") is not None and row["day"] != filters["day"]:
        return False
    if filters.get("moon_pada") is not None and row["moon_pada"] != filters["moon_pada"]:
        return False
    for f in _TEXT_FILTERS:
        want = filters.get(f)
        if want is not None and row[f].lower() != str(want).lower():
            return False
    return True


def run_daylog(
    session: Session,
    *,
    underlying: str = "NIFTY-INDEX",
    start: date | None = None,
    end: date | None = None,
    filters: dict[str, Any] | None = None,
    sort: str = "-ret",
    limit: int = 50,
    offset: int = 0,
) -> dict:
    desc = sort.startswith("-")
    token = sort[1:] if desc else sort
    if token not in SORT_KEYS:
        raise ValueError(f"unknown sort key {sort!r}; allowed: {sorted(SORT_KEYS)}")
    sort_field = SORT_KEYS[token]
    filters = {k: v for k, v in (filters or {}).items() if v is not None and v != ""}

    raw = session.execute(_ROWS_SQL, {"ck": underlying}).mappings().all()
    if not raw:
        raise ValueError("no overlapping D1 / astro_days rows")

    rows: list[dict] = []
    for m in raw:
        d = m["d"]
        if (start and d < start) or (end and d > end):
            continue
        pc = float(m["prev_close"])
        head = (
            moon_dasha_head(float(m["moon_longitude"]), 390.0)
            if m["moon_longitude"] is not None
            else None
        )
        rows.append(
            {
                "d": d.isoformat(),
                "month": d.month,
                "day": d.day,
                "close": round(float(m["close"]), 2),
                "prev_close": round(pc, 2),
                "ret_pct": round((float(m["close"]) - pc) / pc * 100.0, 3),
                "range_pct": round((float(m["high"]) - float(m["low"])) / pc * 100.0, 3),
                "gap_pct": round((float(m["open"]) - pc) / pc * 100.0, 3),
                "weekday": int(m["weekday"]),
                "day_name": m["day_name"],
                "weekday_lord": m["weekday_lord"].title(),
                "tithi": int(m["tithi"]),
                "paksha": m["paksha"],
                "moon_nakshatra": m["moon_nakshatra"],
                "moon_nakshatra_lord": m["moon_nakshatra_lord"].title(),
                "moon_rashi": m["moon_rashi"],
                "moon_pada": int(m["moon_pada"]),
                "lagna_rashi": m["lagna_rashi"],
                "sun_rashi": m["sun_rashi"],
                "dasha_lord": head["dasha_lord"] if head else None,
                "dasha_sub_lord": head["sub_lord"] if head else None,
                "dasha_balance_hms": head["dasha_balance_hms"] if head else None,
            }
        )

    matched = [r for r in rows if _matches(r, filters)]
    matched.sort(key=lambda r: r[sort_field], reverse=desc)

    if matched:
        rets = [r["ret_pct"] for r in matched]
        ranges = [r["range_pct"] for r in matched]
        summary = _bucket("filtered" if filters else "all days", rets, ranges)
        first = min(r["d"] for r in matched)
        last = max(r["d"] for r in matched)
    else:
        summary = _zero_bucket("no matching days")
        first = last = None

    page = matched[offset : offset + limit]
    return {
        "underlying": underlying,
        "first": first,
        "last": last,
        "total": len(matched),
        "limit": limit,
        "offset": offset,
        "sort": sort,
        "filters": {k: str(v) for k, v in filters.items()},
        "summary": _bucket_dict(summary),
        "items": page,
    }


# ---------------------------------------------------------------------------
# Almanac — every astro_days row (the sky), with or without a market candle
# ---------------------------------------------------------------------------

_ALMANAC_SQL = text(
    """
    with d1 as (
        select b.ts::date as d, b.open, b.high, b.low, b.close,
               lag(b.close) over (order by b.ts) as prev_close
        from ohlcv_bars b
        join instruments i on i.id = b.instrument_id and i.contract_key = :ck
        where b.timeframe = 'D1'
    )
    select ad.as_of_date as d,
           ad.weekday, ad.day_name, ad.weekday_lord, ad.tithi, ad.paksha,
           ad.moon_nakshatra, ad.moon_nakshatra_lord, ad.moon_rashi, ad.moon_pada,
           ad.lagna_rashi, ad.lagna_nakshatra, ad.sun_rashi,
           ad.sunrise_ts, ad.sunset_ts,
           d1.open, d1.high, d1.low, d1.close, d1.prev_close
    from astro_days ad
    left join d1 on d1.d = ad.as_of_date
    order by ad.as_of_date
    """
)

_ALMANAC_SORT = {"d": "d", "tithi": "tithi", "pada": "moon_pada", "day": "day"}


def run_almanac(
    session: Session,
    *,
    underlying: str = "NIFTY-INDEX",
    start: date | None = None,
    end: date | None = None,
    filters: dict[str, Any] | None = None,
    sort: str = "d",
    limit: int = 60,
    offset: int = 0,
) -> dict:
    """Every ``astro_days`` row (past or future) with its panchang scalars and,
    where a D1 candle exists, that day's return. ``start`` defaults to today (IST)
    so the natural view is "the sky for the days ahead"."""
    from datetime import datetime, timedelta, timezone

    _ist = timezone(timedelta(hours=5, minutes=30))
    desc = sort.startswith("-")
    token = sort[1:] if desc else sort
    if token not in _ALMANAC_SORT:
        raise ValueError(f"unknown sort key {sort!r}; allowed: {sorted(_ALMANAC_SORT)}")
    sort_field = _ALMANAC_SORT[token]
    filters = {k: v for k, v in (filters or {}).items() if v is not None and v != ""}
    if start is None and end is None:
        start = datetime.now(tz=_ist).date()

    raw = session.execute(_ALMANAC_SQL, {"ck": underlying}).mappings().all()
    rows: list[dict] = []
    for m in raw:
        d = m["d"]
        if (start and d < start) or (end and d > end):
            continue
        has_candle = m["close"] is not None
        pc = float(m["prev_close"]) if m["prev_close"] is not None else None
        ret = rng = None
        if has_candle and pc:
            c, hi, lo = float(m["close"]), float(m["high"]), float(m["low"])
            ret = round((c - pc) / pc * 100.0, 3)
            rng = round((hi - lo) / pc * 100.0, 3)
        rows.append(
            {
                "d": d.isoformat(),
                "month": d.month,
                "day": d.day,
                "weekday": int(m["weekday"]),
                "day_name": m["day_name"],
                "weekday_lord": m["weekday_lord"].title(),
                "tithi": int(m["tithi"]),
                "paksha": m["paksha"],
                "moon_nakshatra": m["moon_nakshatra"],
                "moon_nakshatra_lord": m["moon_nakshatra_lord"].title(),
                "moon_rashi": m["moon_rashi"],
                "moon_pada": int(m["moon_pada"]),
                "lagna_rashi": m["lagna_rashi"],
                "lagna_nakshatra": m["lagna_nakshatra"],
                "sun_rashi": m["sun_rashi"],
                "sunrise_ts": m["sunrise_ts"].isoformat() if m["sunrise_ts"] else None,
                "sunset_ts": m["sunset_ts"].isoformat() if m["sunset_ts"] else None,
                "has_candle": has_candle,
                "close": round(float(m["close"]), 2) if has_candle else None,
                "ret_pct": ret,
                "range_pct": rng,
            }
        )

    matched = [r for r in rows if _matches(r, filters)]
    matched.sort(key=lambda r: r[sort_field], reverse=desc)
    n = len(matched)
    return {
        "underlying": underlying,
        "first": min((r["d"] for r in matched), default=None),
        "last": max((r["d"] for r in matched), default=None),
        "total": n,
        "with_candle": sum(1 for r in matched if r["has_candle"]),
        "limit": limit,
        "offset": offset,
        "sort": sort,
        "filters": {k: str(v) for k, v in filters.items()},
        "items": matched[offset : offset + limit],
    }


# ---------------------------------------------------------------------------
# Single-day drill-down
# ---------------------------------------------------------------------------

_D1_ONE_SQL = text(
    """
    with d1 as (
        select b.ts, b.ts::date as d, b.open, b.high, b.low, b.close, b.volume,
               lag(b.close) over (order by b.ts) as prev_close
        from ohlcv_bars b
        join instruments i on i.id = b.instrument_id and i.contract_key = :ck
        where b.timeframe = 'D1'
    )
    select ts, open, high, low, close, volume, prev_close
    from d1 where d = :d
    """
)


def _intraday_sql(timeframe: str) -> text:
    return text(
        f"""
        select b.ts, b.open, b.high, b.low, b.close, b.volume
        from ohlcv_bars b
        join instruments i on i.id = b.instrument_id and i.contract_key = :ck
        where b.timeframe = '{timeframe}'
          and (b.ts at time zone 'Asia/Kolkata')::date = :d
        order by b.ts
        """
    )


_H1_SQL = _intraday_sql("H1")
_M15_SQL = _intraday_sql("M15")
_M5_SQL = _intraday_sql("M5")

_ADAY_SQL = text(
    """
    select weekday, day_name, weekday_lord, tithi, paksha,
           moon_nakshatra, moon_nakshatra_lord, moon_rashi, moon_rashi_index, moon_pada,
           lagna_longitude, lagna_rashi, lagna_rashi_index, lagna_nakshatra, lagna_pada,
           sun_rashi, sun_rashi_index,
           sunrise_ts, sunset_ts, ayanamsha
    from astro_days where as_of_date = :d
    """
)

# Whole-sign houses counted from a reference point (lagna / Moon / Sun), grouped
# into the four purushartha trikonas: 1·5·9 Dharma, 2·6·10 Artha, 3·7·11 Kama,
# 4·8·12 Moksha. The group index is simply (house - 1) % 4.
_HOUSE_GROUPS = ("Dharma", "Artha", "Kama", "Moksha")
_HOUSE_GROUP_TRIAD = {
    "Dharma": [1, 5, 9],
    "Artha": [2, 6, 10],
    "Kama": [3, 7, 11],
    "Moksha": [4, 8, 12],
}
#: (frame key, display name of the reference body)
_HOUSE_FRAMES = (("lagna", "Lagna"), ("moon", "Moon"), ("sun", "Sun"))


def _house_from(rashi_index: int, reference_rashi_index: int) -> int:
    return ((rashi_index - reference_rashi_index) % 12) + 1


def _house_from_deg(longitude: float, reference_longitude: float) -> int:
    """Equal house anchored on the exact ascendant degree: house 1 spans
    ``[lagna_lon, lagna_lon + 30°)``, house 2 the next 30°, … (Sripati-style)."""
    return int(((longitude - reference_longitude) % 360.0) // 30.0) + 1


def _house_group(house: int) -> str:
    return _HOUSE_GROUPS[(house - 1) % 4]


_POS_SQL = text(
    """
    select body, longitude, degree, rashi, rashi_index,
           nakshatra, nakshatra_index, pada, nakshatra_lord,
           retrograde, speed_longitude, dignity
    from astro_positions where as_of_date = :d
    order by case body
        when 'SUN' then 1 when 'MOON' then 2 when 'MARS' then 3
        when 'MERCURY' then 4 when 'JUPITER' then 5 when 'VENUS' then 6
        when 'SATURN' then 7 when 'RAHU' then 8 when 'KETU' then 9 else 99 end
    """
)

_SHAD_SQL = text(
    """
    select graha, sthana_bala, dig_bala, kala_bala, cheshta_bala,
           naisargika_bala, drik_bala, total_virupa, total_rupa,
           required_rupa, strength_ratio, rank, ishta_phala, kashta_phala,
           graha_yuddha
    from astro_shadbala where as_of_date = :d order by rank
    """
)


def _f(v: Any) -> float | None:
    return None if v is None else float(v)


def _iso(v: Any) -> str | None:
    return None if v is None else v.isoformat()


_MOON_LON_SQL = text(
    "select longitude from astro_positions where as_of_date = :d and body = 'MOON'"
)


def moon_dasha_for_day(
    session: Session,
    *,
    d: date,
    underlying: str = "NIFTY-INDEX",
    cycle_minutes: float = 390.0,
    levels: int = 2,
    session_open: str = "09:15",
) -> dict | None:
    """The Moon-anchored dasha timeline (docs/13 §5.6) for one date — reads the
    stored 09:00 IST sidereal Moon longitude and hands it to the pure engine.
    ``session_open`` anchors the wall clock (the sky is always the 09:00 IST
    snapshot; this only shifts where t=0 sits). ``None`` when no
    ``astro_positions`` row exists for the date."""
    lon = session.execute(_MOON_LON_SQL, {"d": d}).scalar()
    if lon is None:
        return None
    return {
        "date": d.isoformat(),
        "underlying": underlying,
        **moon_dasha(
            float(lon),
            cycle_minutes=cycle_minutes,
            levels=levels,
            session_open=session_open,
        ),
    }


def day_detail(session: Session, *, underlying: str = "NIFTY-INDEX", d: date) -> dict | None:
    d1 = session.execute(_D1_ONE_SQL, {"ck": underlying, "d": d}).mappings().first()
    aday = session.execute(_ADAY_SQL, {"d": d}).mappings().first()
    if d1 is None and aday is None:
        return None

    d1_out = None
    if d1 is not None:
        pc = _f(d1["prev_close"])
        open_, close, high, low = _f(d1["open"]), _f(d1["close"]), _f(d1["high"]), _f(d1["low"])
        d1_out = {
            "ts": _iso(d1["ts"]),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": _f(d1["volume"]),
            "prev_close": pc,
            # close-to-close: the overnight gap plus whatever happened intraday
            "ret_pct": (round((close - pc) / pc * 100.0, 3) if pc and close is not None else None),
            # today's own high-low spread only — can be much narrower than ret_pct
            # on a big-gap day, since it doesn't include the overnight move
            "range_pct": (
                round((high - low) / pc * 100.0, 3)
                if pc and high is not None and low is not None
                else None
            ),
            # the overnight move alone: open vs prior close
            "gap_pct": (round((open_ - pc) / pc * 100.0, 3) if pc and open_ is not None else None),
        }

    def _bars(sql) -> list[dict]:
        return [
            {
                "ts": _iso(m["ts"]),
                "open": _f(m["open"]),
                "high": _f(m["high"]),
                "low": _f(m["low"]),
                "close": _f(m["close"]),
                "volume": _f(m["volume"]),
            }
            for m in session.execute(sql, {"ck": underlying, "d": d}).mappings().all()
        ]

    hourly = _bars(_H1_SQL)
    m15 = _bars(_M15_SQL)
    m5 = _bars(_M5_SQL)

    lagna_ri = int(aday["lagna_rashi_index"]) if aday is not None else None

    day_out = None
    if aday is not None:
        day_out = {
            "weekday": int(aday["weekday"]),
            "day_name": aday["day_name"],
            "weekday_lord": aday["weekday_lord"].title(),
            "tithi": int(aday["tithi"]),
            "paksha": aday["paksha"],
            "moon_nakshatra": aday["moon_nakshatra"],
            "moon_nakshatra_lord": aday["moon_nakshatra_lord"].title(),
            "moon_rashi": aday["moon_rashi"],
            "moon_rashi_index": int(aday["moon_rashi_index"]),
            "moon_pada": int(aday["moon_pada"]),
            "lagna_longitude": _f(aday["lagna_longitude"]),
            "lagna_rashi": aday["lagna_rashi"],
            "lagna_rashi_index": lagna_ri,
            "lagna_nakshatra": aday["lagna_nakshatra"],
            "lagna_pada": int(aday["lagna_pada"]),
            "sun_rashi": aday["sun_rashi"],
            "sun_rashi_index": int(aday["sun_rashi_index"]),
            "sunrise_ts": _iso(aday["sunrise_ts"]),
            "sunset_ts": _iso(aday["sunset_ts"]),
            "ayanamsha": _f(aday["ayanamsha"]),
        }

    positions = [
        {
            "body": m["body"].title(),
            "longitude": _f(m["longitude"]),
            "degree": _f(m["degree"]),
            "rashi": m["rashi"],
            "rashi_index": int(m["rashi_index"]),
            "nakshatra": m["nakshatra"],
            "nakshatra_index": int(m["nakshatra_index"]),
            "pada": int(m["pada"]),
            "nakshatra_lord": m["nakshatra_lord"].title(),
            "retrograde": bool(m["retrograde"]),
            "speed_longitude": _f(m["speed_longitude"]),
            "dignity": m["dignity"],
            "house_from_lagna": None,
            "house_group_lagna": None,
            "house_from_lagna_deg": None,
            "house_group_lagna_deg": None,
            "house_from_naklord_deg": None,
            "house_group_naklord_deg": None,
            "house_from_moon": None,
            "house_group_moon": None,
            "house_from_sun": None,
            "house_group_sun": None,
            # diff vs the previous weekday (filled below)
            "prev_rashi": None,
            "prev_nakshatra": None,
            "prev_pada": None,
            "prev_retrograde": None,
            "changed_rashi": False,
            "changed_nakshatra": False,
            "changed_pada": False,
            "changed_retrograde": False,
        }
        for m in session.execute(_POS_SQL, {"d": d}).mappings().all()
    ]

    # the ascendant itself, as a first row (lives on astro_days, not astro_positions)
    lagna_lon = _f(aday["lagna_longitude"]) if aday is not None else None
    if lagna_lon is not None:
        lagna_lon = vedic.norm360(lagna_lon)
        _ni, _pd = vedic.nakshatra_pada(lagna_lon)
        positions.insert(
            0,
            {
                "body": "Lagna",
                "longitude": round(lagna_lon, 6),
                "degree": round(vedic.degree_in_sign(lagna_lon), 6),
                "rashi": vedic.rashi_name(lagna_lon),
                "rashi_index": vedic.rashi_index(lagna_lon),
                "nakshatra": vedic.NAKSHATRAS[_ni],
                "nakshatra_index": _ni,
                "pada": _pd,
                "nakshatra_lord": vedic.NAKSHATRA_LORDS[_ni].title(),
                "retrograde": False,
                "speed_longitude": None,  # the ascendant sweeps the whole zodiac each day
                "dignity": None,
                "house_from_lagna": None,
                "house_group_lagna": None,
                "house_from_lagna_deg": None,
                "house_group_lagna_deg": None,
                "house_from_naklord_deg": None,
                "house_group_naklord_deg": None,
                "house_from_moon": None,
                "house_group_moon": None,
                "house_from_sun": None,
                "house_group_sun": None,
                "prev_rashi": None,
                "prev_nakshatra": None,
                "prev_pada": None,
                "prev_retrograde": None,
                "changed_rashi": False,
                "changed_nakshatra": False,
                "changed_pada": False,
                "changed_retrograde": False,
            },
        )

    # what shifted since the previous weekday — sign (house), nakshatra, pada, retro
    prev_date = session.execute(
        text(
            "select as_of_date from astro_days where as_of_date < :d "
            "order by as_of_date desc limit 1"
        ),
        {"d": d},
    ).scalar()
    if prev_date is not None:
        prev_pos = {
            m["body"].title(): m
            for m in session.execute(_POS_SQL, {"d": prev_date}).mappings().all()
        }
        prev_lag = session.execute(
            text("select lagna_longitude from astro_days where as_of_date = :pd"),
            {"pd": prev_date},
        ).scalar()
        if prev_lag is not None:
            pl = vedic.norm360(float(prev_lag))
            p_ni, p_pd = vedic.nakshatra_pada(pl)
            prev_pos["Lagna"] = {
                "rashi": vedic.rashi_name(pl),
                "rashi_index": vedic.rashi_index(pl),
                "nakshatra": vedic.NAKSHATRAS[p_ni],
                "nakshatra_index": p_ni,
                "pada": p_pd,
                "retrograde": False,
            }
        for p in positions:
            pp = prev_pos.get(p["body"])
            if pp is None:
                continue
            p["prev_rashi"] = pp["rashi"]
            p["prev_nakshatra"] = pp["nakshatra"]
            p["prev_pada"] = int(pp["pada"])
            p["prev_retrograde"] = bool(pp["retrograde"])
            p["changed_rashi"] = int(pp["rashi_index"]) != p["rashi_index"]
            p["changed_nakshatra"] = int(pp["nakshatra_index"]) != p["nakshatra_index"]
            p["changed_pada"] = int(pp["pada"]) != p["pada"]
            p["changed_retrograde"] = bool(pp["retrograde"]) != p["retrograde"]

    # whole-sign house of each graha counted from the lagna / Moon / Sun, and its
    # trikona group, for each of the three reference frames
    by_body_ri = {p["body"]: p["rashi_index"] for p in positions}
    frame_ref = {
        "lagna": lagna_ri,
        "moon": by_body_ri.get("Moon"),
        "sun": by_body_ri.get("Sun"),
    }
    house_frames: list[dict] = []
    for frame_key, ref_name in _HOUSE_FRAMES:
        ref_ri = frame_ref.get(frame_key)
        if ref_ri is None:
            continue
        by_group: dict[str, list[str]] = {g: [] for g in _HOUSE_GROUPS}
        for p in positions:  # "Lagna" is a real position now — it lands in its own 1st house
            h = _house_from(p["rashi_index"], ref_ri)
            grp = _house_group(h)
            p[f"house_from_{frame_key}"] = h
            p[f"house_group_{frame_key}"] = grp
            by_group[grp].append(p["body"])
        house_frames.append(
            {
                "frame": frame_key,
                "reference": ref_name,
                "groups": [
                    {"group": g, "houses": _HOUSE_GROUP_TRIAD[g], "bodies": by_group[g]}
                    for g in _HOUSE_GROUPS
                ],
            }
        )

    # equal-house frame anchored on the exact lagna degree (Sripati-style):
    # a graha at 6° Tula with a 18° Tula lagna sits in the 12th, not the 1st.
    if lagna_lon is not None:
        by_group = {g: [] for g in _HOUSE_GROUPS}
        for p in positions:  # "Lagna" included — it resolves to its own 1st house
            if p["longitude"] is None:
                continue
            h = _house_from_deg(p["longitude"], lagna_lon)
            grp = _house_group(h)
            p["house_from_lagna_deg"] = h
            p["house_group_lagna_deg"] = grp
            by_group[grp].append(p["body"])
        house_frames.insert(
            1 if house_frames else 0,
            {
                "frame": "lagna_deg",
                "reference": "Lagna (by degree)",
                "groups": [
                    {"group": g, "houses": _HOUSE_GROUP_TRIAD[g], "bodies": by_group[g]}
                    for g in _HOUSE_GROUPS
                ],
            },
        )

    # equal-house frame anchored on the exact degree of the Moon's current
    # nakshatra-lord — the same Sripati-style math as lagna_deg, but the
    # reference graha itself changes as the Moon moves nakshatra to nakshatra
    # (e.g. Ashlesha/Ayilyam → Mercury; Ardra → Rahu; Moola → Ketu).
    if aday is not None:
        naklord = aday["moon_nakshatra_lord"].title()
        naklord_lon = next(
            (
                p["longitude"]
                for p in positions
                if p["body"] == naklord and p["longitude"] is not None
            ),
            None,
        )
        if naklord_lon is not None:
            by_group = {g: [] for g in _HOUSE_GROUPS}
            for p in positions:
                if p["longitude"] is None:
                    continue
                h = _house_from_deg(p["longitude"], naklord_lon)
                grp = _house_group(h)
                p["house_from_naklord_deg"] = h
                p["house_group_naklord_deg"] = grp
                by_group[grp].append(p["body"])
            house_frames.append(
                {
                    "frame": "naklord_deg",
                    "reference": "Moon's nakshatra-lord (by degree)",
                    "groups": [
                        {"group": g, "houses": _HOUSE_GROUP_TRIAD[g], "bodies": by_group[g]}
                        for g in _HOUSE_GROUPS
                    ],
                }
            )

    shadbala = [
        {
            "graha": m["graha"].title(),
            "sthana_bala": _f(m["sthana_bala"]),
            "dig_bala": _f(m["dig_bala"]),
            "kala_bala": _f(m["kala_bala"]),
            "cheshta_bala": _f(m["cheshta_bala"]),
            "naisargika_bala": _f(m["naisargika_bala"]),
            "drik_bala": _f(m["drik_bala"]),
            "total_virupa": _f(m["total_virupa"]),
            "total_rupa": _f(m["total_rupa"]),
            "required_rupa": _f(m["required_rupa"]),
            "strength_ratio": _f(m["strength_ratio"]),
            "rank": int(m["rank"]),
            "ishta_phala": _f(m["ishta_phala"]),
            "kashta_phala": _f(m["kashta_phala"]),
            "graha_yuddha": bool(m["graha_yuddha"]),
        }
        for m in session.execute(_SHAD_SQL, {"d": d}).mappings().all()
    ]

    # Moon-anchored dasha timeline for the day, on each session-length basis
    moon_lon = next(
        (p["longitude"] for p in positions if p["body"] == "Moon" and p["longitude"] is not None),
        None,
    )
    moon_dashas = (
        [moon_dasha(moon_lon, cycle_minutes=basis, levels=3) for basis in MOON_DASHA_BASES]
        if moon_lon is not None
        else []
    )

    # KP lord chain (sign → star → sub → sub-sub) for the two reference points
    kp_chains = {
        "lagna": kp_chain(lagna_lon) if lagna_lon is not None else None,
        "moon": kp_chain(moon_lon) if moon_lon is not None else None,
    }

    # Baadhagaadhipathi — the badhaka (obstruction) house + its lord, reckoned
    # from the Lagna, the Moon, and the Moon's current nakshatra-lord.
    sun_lon = next(
        (p["longitude"] for p in positions if p["body"] == "Sun" and p["longitude"] is not None),
        None,
    )
    naklord_name = aday["moon_nakshatra_lord"].title() if aday is not None else None
    badhaka_refs = (
        ("lagna", "Lagna", lagna_ri),
        ("moon", "Moon", by_body_ri.get("Moon")),
        (
            "naklord",
            f"Moon's nakshatra-lord ({naklord_name})" if naklord_name else "Moon's nakshatra-lord",
            by_body_ri.get(naklord_name) if naklord_name else None,
        ),
    )
    badhaka: list[dict] = []
    for frame_key, ref_name, ref_ri in badhaka_refs:
        if ref_ri is None:
            continue
        house, sign_i, lord = vedic.badhaka_from(ref_ri)
        lord_title = lord.title()
        lord_ri = by_body_ri.get(lord_title)
        badhaka.append(
            {
                "frame": frame_key,
                "reference": ref_name,
                "reference_sign": vedic.RASHIS[ref_ri],
                "movability": vedic.sign_movability(ref_ri),
                "badhaka_house": house,
                "badhaka_sign": vedic.RASHIS[sign_i],
                "badhaka_lord": lord_title,
                "badhaka_lord_house_from_ref": (
                    _house_from(lord_ri, ref_ri) if lord_ri is not None else None
                ),
            }
        )

    # Tithi Shunya — the void tithi(s) for this lunar month AND the rashi(s)
    # held void for today's tithi (a body / the lagna sitting in one is blunted).
    tithi_shoonya = None
    if aday is not None:
        masa = _chandra_masa(moon_lon, sun_lon, d)
        tithi_i = int(aday["tithi"])
        shoonya_list = list(vedic.shoonya_tithis_for_masa(masa)) if masa else []
        sh_ris = vedic.tithi_shoonya_rashis(tithi_i)
        shoonya_rashis = [{"index": ri, "name": vedic.RASHIS[ri]} for ri in sh_ris]
        bodies_in_shoonya = [
            {"body": p["body"], "rashi": p["rashi"]}
            for p in positions
            if p["rashi_index"] in sh_ris
        ]
        tithi_shoonya = {
            "chandra_masa": masa,
            "chandra_masa_approx": True,  # back-estimated new moon; no adhika-masa split
            "paksha": aday["paksha"],
            "tithi": tithi_i,
            "tithi_in_paksha": vedic.tithi_in_paksha(tithi_i),
            "tithi_name": vedic.tithi_name(tithi_i),
            "shoonya_tithis": shoonya_list,
            "is_shoonya": vedic.is_shoonya_tithi(masa, tithi_i) if masa else False,
            "shoonya_rashis": shoonya_rashis,
            "bodies_in_shoonya": bodies_in_shoonya,
        }
    if day_out is not None:
        day_out["chandra_masa"] = tithi_shoonya["chandra_masa"] if tithi_shoonya else None

    return {
        "date": d.isoformat(),
        "underlying": underlying,
        "market": {"d1": d1_out, "hourly": hourly, "m15": m15, "m5": m5},
        "astro": {
            "day": day_out,
            "positions": positions,
            "shadbala": shadbala,
            "house_frames": house_frames,
            "prev_date": prev_date.isoformat() if prev_date is not None else None,
            "moon_dasha": moon_dashas,
            "kp_chains": kp_chains,
            "badhaka": badhaka,
            "tithi_shoonya": tithi_shoonya,
        },
    }
