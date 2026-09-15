"""Per-day chart scalars for the astro x market study (docs/13 §5).

One row of ``astro_days`` per date: weekday, lagna (ascendant), Moon nakshatra /
rashi / pada, Sun rashi, tithi + paksha, sunrise/sunset, ayanamsha. Everything
here is already derivable from ``astro_positions`` + the ephemeris, but is
denormalised so the study joins are one-liners.

:func:`run_catch_up` keeps the dataset current: it fills every missing weekday
from the last stored date up to today (IST). Offline, deterministic, idempotent
— the worker calls it on a slow timer (docs/13 §5.4) so the "today" astro row
is always present without a manual ``analytical-astro build``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone

import structlog
from sqlalchemy.orm import Session

from app.astro import vedic
from app.astro.ephemeris import AstroEngine

IST = timezone(timedelta(hours=5, minutes=30))
_LOG = structlog.get_logger("astro.daily")

_DAY_NAME = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_WEEKDAY_LORD = ("MOON", "MARS", "MERCURY", "JUPITER", "VENUS", "SATURN", "SUN")


@dataclass(frozen=True, slots=True)
class DayChart:
    as_of_date: object  # datetime.date
    as_of_ts: datetime
    weekday: int  # 0=Mon .. 6=Sun
    day_name: str
    weekday_lord: str
    lagna_longitude: float
    lagna_rashi_index: int
    lagna_rashi: str
    lagna_nakshatra_index: int
    lagna_nakshatra: str
    lagna_pada: int
    moon_rashi_index: int
    moon_rashi: str
    moon_nakshatra_index: int
    moon_nakshatra: str
    moon_pada: int
    moon_nakshatra_lord: str
    sun_rashi_index: int
    sun_rashi: str
    tithi: int  # 1..30
    paksha: str  # Shukla | Krishna
    sunrise_ts: datetime
    sunset_ts: datetime
    ayanamsha: float


def compute_day_chart(engine: AstroEngine, dt: datetime, lat: float, lon: float) -> DayChart:
    pos = {p.graha: p for p in engine.positions(dt)}
    moon, sun = pos["MOON"], pos["SUN"]
    lagna = engine.ascendant(dt, lat, lon)
    ni, pada = vedic.nakshatra_pada(lagna)
    phase = (moon.longitude - sun.longitude) % 360.0
    tithi = int(phase // 12.0) + 1
    d = dt.astimezone(IST).date()
    sr, ss = engine.sunrise_sunset(d, lat, lon)
    return DayChart(
        as_of_date=d,
        as_of_ts=dt.astimezone(UTC),
        weekday=d.weekday(),
        day_name=_DAY_NAME[d.weekday()],
        weekday_lord=_WEEKDAY_LORD[d.weekday()],
        lagna_longitude=lagna,
        lagna_rashi_index=vedic.rashi_index(lagna),
        lagna_rashi=vedic.rashi_name(lagna),
        lagna_nakshatra_index=ni,
        lagna_nakshatra=vedic.NAKSHATRAS[ni],
        lagna_pada=pada,
        moon_rashi_index=moon.rashi_index,
        moon_rashi=moon.rashi,
        moon_nakshatra_index=moon.nakshatra_index,
        moon_nakshatra=moon.nakshatra,
        moon_pada=moon.pada,
        moon_nakshatra_lord=moon.nakshatra_lord,
        sun_rashi_index=sun.rashi_index,
        sun_rashi=sun.rashi,
        tithi=tithi,
        paksha="Shukla" if tithi <= 15 else "Krishna",
        sunrise_ts=sr,
        sunset_ts=ss,
        ayanamsha=engine.ayanamsha(dt),
    )


def today_ist() -> date:
    return datetime.now(tz=IST).date()


def run_catch_up(session: Session, *, settings=None, today: date | None = None):
    """Fill missing weekday astro rows from the last stored date up to ``today`` (IST).

    Idempotent and offline — safe to call on a timer. Returns the
    :class:`~app.astro.backfill.BuildReport` (``dates == 0`` when already current).
    """
    from app.astro import backfill as bf
    from app.config import get_settings

    s = settings or get_settings()
    end = today or today_ist()
    last = bf.last_built_date(session)
    start = (last + timedelta(days=1)) if last else date.fromisoformat(s.astro_start_date)
    if start > end:
        _LOG.debug("astro catch-up: already current", last=str(last), today=str(end))
        return bf.BuildReport()
    _LOG.info("astro catch-up: building", start=str(start), end=str(end))
    rep = bf.build(
        session,
        start=start,
        end=end,
        latitude=s.astro_latitude,
        longitude=s.astro_longitude,
        hour_ist=s.astro_hour_ist,
    )
    _LOG.info(
        "astro catch-up: done",
        dates=rep.dates,
        positions=rep.positions_upserted,
        shadbala=rep.shadbala_upserted,
        days=rep.days_upserted,
        range=f"{rep.first}..{rep.last}",
    )
    return rep
