"""Astro x market cross-check (docs/07 §4.9, docs/13 §5).

``GET /astro/study`` — descriptive statistics of daily index return grouped by
weekday / Moon nakshatra / lagna rashi / tithi / paksha, against an "all days"
baseline.

``GET /astro/days`` — the individual trading days behind those buckets:
filterable (weekday + tithi + nakshatra + …), sortable and paginated, with a
``summary`` bucket for the filtered set so a chosen combination reads as one
market-performance report.

``GET /astro/almanac`` — every ``astro_days`` row (past **or future**) with its
panchang scalars and, where a candle exists, that day's return; the way to reach
days the market hasn't traded yet.

Read-only, computed on request from ``astro_days`` (inner-joined to
``ohlcv_bars`` for study/day-log, left-joined for the almanac). Exploratory
research — no forecast, no execution label.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.errors import ApiError, not_found
from app.api.schemas.astro import (
    AlmanacResponse,
    AstroStudyResponse,
    DashaResponse,
    DayDetailResponse,
    DayLogResponse,
    KpTimelineResponse,
    MoonDashaResponse,
)
from app.astro.dasha import vimshottari_grid
from app.astro.daylog import day_detail, moon_dasha_for_day, run_almanac, run_daylog
from app.astro.study import result_to_dict, run_study

router = APIRouter(prefix="/api/v1", tags=["astro"])


@router.get("/astro/study", response_model=AstroStudyResponse)
def astro_study(
    underlying: str = Query("NIFTY-INDEX", description="instrument contract_key"),
    start: date | None = Query(None, description="ISO date, inclusive"),
    end: date | None = Query(None, description="ISO date, inclusive"),
    db: Session = Depends(get_db),
) -> AstroStudyResponse:
    try:
        res = run_study(db, underlying=underlying, start=start, end=end)
    except ValueError as exc:
        raise not_found(f"astro study for {underlying} ({exc})") from exc
    return AstroStudyResponse(**result_to_dict(res))


@router.get("/astro/days", response_model=DayLogResponse)
def astro_days(
    underlying: str = Query("NIFTY-INDEX", description="instrument contract_key"),
    start: date | None = Query(None, description="ISO date, inclusive"),
    end: date | None = Query(None, description="ISO date, inclusive"),
    sort: str = Query(
        "-ret", description="d | ret | range | gap | close | tithi | pada; '-' = desc"
    ),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    weekday: str | None = Query(None, description="0-4 or a day name (Monday…Friday)"),
    weekday_lord: str | None = Query(None),
    month: int | None = Query(None, ge=1, le=12, description="calendar month, 1-12"),
    day: int | None = Query(
        None, ge=1, le=31, description="day of month — pair with month for e.g. 8 Sep every year"
    ),
    tithi: int | None = Query(None, ge=1, le=30),
    paksha: str | None = Query(None, description="Shukla | Krishna"),
    moon_nakshatra: str | None = Query(None),
    moon_nakshatra_lord: str | None = Query(None),
    moon_rashi: str | None = Query(None),
    moon_pada: int | None = Query(None, ge=1, le=4),
    lagna_rashi: str | None = Query(None),
    sun_rashi: str | None = Query(None),
    db: Session = Depends(get_db),
) -> DayLogResponse:
    wd: str | int | None = weekday
    if weekday is not None and weekday.isdigit():
        wd = int(weekday)
    filters = {
        "weekday": wd,
        "weekday_lord": weekday_lord,
        "month": month,
        "day": day,
        "tithi": tithi,
        "paksha": paksha,
        "moon_nakshatra": moon_nakshatra,
        "moon_nakshatra_lord": moon_nakshatra_lord,
        "moon_rashi": moon_rashi,
        "moon_pada": moon_pada,
        "lagna_rashi": lagna_rashi,
        "sun_rashi": sun_rashi,
    }
    try:
        res = run_daylog(
            db,
            underlying=underlying,
            start=start,
            end=end,
            filters=filters,
            sort=sort,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise not_found(f"astro day log for {underlying} ({exc})") from exc
    return DayLogResponse(**res)


@router.get("/astro/almanac", response_model=AlmanacResponse)
def astro_almanac(
    underlying: str = Query("NIFTY-INDEX", description="instrument contract_key"),
    start: date | None = Query(None, description="ISO date, inclusive (default: today IST)"),
    end: date | None = Query(None, description="ISO date, inclusive"),
    sort: str = Query("d", description="d | tithi | pada; '-' prefix = desc"),
    limit: int = Query(60, ge=1, le=500),
    offset: int = Query(0, ge=0),
    weekday: str | None = Query(None, description="0-4 or a day name"),
    weekday_lord: str | None = Query(None),
    month: int | None = Query(None, ge=1, le=12),
    day: int | None = Query(None, ge=1, le=31, description="day of month"),
    tithi: int | None = Query(None, ge=1, le=30),
    paksha: str | None = Query(None, description="Shukla | Krishna"),
    moon_nakshatra: str | None = Query(None),
    moon_rashi: str | None = Query(None),
    lagna_rashi: str | None = Query(None),
    sun_rashi: str | None = Query(None),
    db: Session = Depends(get_db),
) -> AlmanacResponse:
    """Every ``astro_days`` row (past **or future**) with its panchang scalars —
    and, where a D1 candle exists, that day's return. Use it to browse the sky
    for days the market hasn't traded yet; each date opens the day screen."""
    wd: str | int | None = weekday
    if weekday is not None and weekday.isdigit():
        wd = int(weekday)
    filters = {
        "weekday": wd,
        "weekday_lord": weekday_lord,
        "month": month,
        "day": day,
        "tithi": tithi,
        "paksha": paksha,
        "moon_nakshatra": moon_nakshatra,
        "moon_rashi": moon_rashi,
        "lagna_rashi": lagna_rashi,
        "sun_rashi": sun_rashi,
    }
    try:
        res = run_almanac(
            db,
            underlying=underlying,
            start=start,
            end=end,
            filters=filters,
            sort=sort,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise not_found(f"astro almanac ({exc})") from exc
    return AlmanacResponse(**res)


@router.get("/astro/dasha", response_model=DashaResponse)
def astro_dasha(
    minutes: float | None = Query(
        390.0,
        gt=0,
        le=100_000,
        description="session length (minutes) to scale the 120y cycle onto",
    ),
    start_lord: str = Query(
        "Ketu",
        description="mahadasha anchor: Ketu|Venus|Sun|Moon|Mars|Rahu|Jupiter|Saturn|Mercury",
    ),
) -> DashaResponse:
    """The Vimshottari 9x9 mahadasha x antardasha table (docs/13 §5.6).

    Pure arithmetic — the nine lords in fixed 7·20·6·10·7·18·16·19·17 proportion
    (120 years), every cell shown both in years and, when ``minutes`` is given,
    scaled to ``H:MM:SS`` of that session. No chart lookup, no forecast."""
    try:
        return DashaResponse(**vimshottari_grid(minutes, start_lord=start_lord))
    except ValueError as exc:
        raise ApiError(422, "Unprocessable Entity", str(exc)) from exc


@router.get("/astro/dasha/moon", response_model=MoonDashaResponse)
def astro_dasha_moon(
    d: date,
    minutes: float = Query(
        390.0, gt=0, le=100_000, description="session length; replaces the 120-year cycle"
    ),
    levels: int = Query(2, ge=1, le=3, description="1 mahadasha · 2 +antardasha · 3 +pratyantar"),
    session_open: str = Query(
        "09:15",
        pattern=r"^\d{2}:\d{2}$",
        description="IST wall-clock anchor for t=0 (e.g. 09:00 or 09:15)",
    ),
    underlying: str = Query(
        "NIFTY-INDEX", description="echoed back; astro data is not per-underlying"
    ),
    db: Session = Depends(get_db),
) -> MoonDashaResponse:
    """The **Moon-anchored** dasha timeline for one date (`docs/13` §5.6).

    Standard balance-of-dasha math — the Moon's exact sidereal longitude at
    09:00 IST → nakshatra → lord → un-elapsed fraction → the first mahadasha is
    cut to that balance, full periods follow, wrapping to tile the whole
    session — only with ``minutes`` standing in for 120 years. ``session_open``
    just shifts where t=0 sits on the clock. Not the abstract grid
    (`/astro/dasha`); not a different dasha school."""
    try:
        res = moon_dasha_for_day(
            db,
            d=d,
            underlying=underlying,
            cycle_minutes=minutes,
            levels=levels,
            session_open=session_open,
        )
    except ValueError as exc:
        raise ApiError(422, "Unprocessable Entity", str(exc)) from exc
    if res is None:
        raise not_found(f"astro Moon position for {d.isoformat()}")
    return MoonDashaResponse(**res)


@router.get("/astro/days/{d}", response_model=DayDetailResponse)
def astro_day_detail(
    d: date,
    underlying: str = Query("NIFTY-INDEX", description="instrument contract_key"),
    db: Session = Depends(get_db),
) -> DayDetailResponse:
    """One date, everything: D1 OHLC, the H1 (hourly) bars for the session, and
    the full 09:00 IST chart (panchang + sidereal positions + Shadbala)."""
    res = day_detail(db, underlying=underlying, d=d)
    if res is None:
        raise not_found(f"astro day {d.isoformat()} for {underlying}")
    return DayDetailResponse(**res)


@router.get("/astro/days/{d}/kp-timeline", response_model=KpTimelineResponse)
def astro_kp_timeline(
    d: date,
    end: str = Query("15:40", pattern=r"^\d{2}:\d{2}$", description="session end, IST HH:MM"),
    level: str = Query(
        "sub", pattern=r"^(sub|sub_sub)$", description="bracket on 'sub' | 'sub_sub'"
    ),
    underlying: str = Query("NIFTY-INDEX", description="instrument contract_key for the M1 bars"),
    db: Session = Depends(get_db),
) -> KpTimelineResponse:
    """KP lord chain **change brackets** for the **Lagna** and the **Moon**,
    09:00 IST → ``end`` (`docs/13` §5.6.1) — a new row whenever either chain's
    lord changes at ``level`` (sub lord, or every sub-sub turn). Each row carries
    both chains, the Parashari natural relation star↔sub within each and Lagna-sub
    ↔ Moon-sub, the sub-lord **house relation** (1-7 / 1-5-9 / …), and — when M1
    bars exist for ``underlying`` on ``d`` — that bracket's open→close market
    move. Sky computed live from the ephemeris; nothing stored."""
    from datetime import UTC, datetime, time, timedelta

    from sqlalchemy import select

    from analytical_core.enums import Timeframe
    from app.astro.kp_timeline import IST, kp_session_timeline
    from app.config import get_settings
    from app.db import models as m

    s = get_settings()
    day_start = datetime.combine(d, time.min, IST).astimezone(UTC)
    day_end = day_start + timedelta(days=1)
    bars: dict[int, tuple[float, float]] = {}
    for ts, o, c in db.execute(
        select(m.OhlcvBar.ts, m.OhlcvBar.open, m.OhlcvBar.close)
        .join(m.Instrument, m.Instrument.id == m.OhlcvBar.instrument_id)
        .where(
            m.Instrument.contract_key == underlying,
            m.OhlcvBar.timeframe == Timeframe.M1,
            m.OhlcvBar.ts >= day_start,
            m.OhlcvBar.ts < day_end,
        )
    ):
        ist = ts.astimezone(IST)
        bars[ist.hour * 60 + ist.minute] = (float(o), float(c))

    try:
        res = kp_session_timeline(
            _kp_engine(),
            d=d,
            lat=s.astro_latitude,
            lon=s.astro_longitude,
            end=end,
            level=level,
            bars=bars or None,
        )
    except ValueError as exc:
        raise ApiError(422, "Unprocessable Entity", str(exc)) from exc
    return KpTimelineResponse(**res)


_KP_ENGINE: object | None = None


def _kp_engine():
    """One shared ephemeris engine for the KP-timeline endpoint (loading the
    Swiss Ephemeris data is not free; reuse it across requests)."""
    global _KP_ENGINE
    if _KP_ENGINE is None:
        from app.astro.ephemeris import AstroEngine

        _KP_ENGINE = AstroEngine()
    return _KP_ENGINE
