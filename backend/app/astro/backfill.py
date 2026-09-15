"""Generate the astro dataset — weekday sidereal positions (+ Shadbala) over a
date range and upsert into ``astro_positions`` / ``astro_shadbala`` (docs/13 §5).

Local, offline, deterministic. Idempotent per (date, body): re-running refreshes.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.astro.ephemeris import AstroEngine
from app.astro.shadbala import compute_shadbala
from app.db import models as m

IST = timezone(timedelta(hours=5, minutes=30))
_SOURCE = "swisseph:lahiri"


def weekdays(start: date, end: date) -> Iterator[date]:
    """Mon-Fri dates in [start, end] inclusive (Sat/Sun excluded)."""
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


@dataclass(slots=True)
class BuildReport:
    dates: int = 0
    positions_upserted: int = 0
    shadbala_upserted: int = 0
    days_upserted: int = 0
    first: date | None = None
    last: date | None = None

    def line(self) -> str:
        return (
            f"dates={self.dates} positions={self.positions_upserted} "
            f"shadbala={self.shadbala_upserted} days={self.days_upserted} "
            f"range={self.first}..{self.last}"
        )


def _pos_rows(engine: AstroEngine, d: date, hour_ist: float, ts: datetime) -> list[dict]:
    dt = datetime(d.year, d.month, d.day, tzinfo=IST) + timedelta(hours=hour_ist)
    ayan = round(engine.ayanamsha(dt), 6)
    rows = []
    for p in engine.positions(dt):
        rows.append(
            {
                "as_of_date": d,
                "as_of_ts": ts,
                "body": p.graha,
                "longitude": round(p.longitude, 6),
                "latitude": round(p.latitude, 6),
                "speed_longitude": round(p.speed_long, 6),
                "retrograde": p.retrograde,
                "rashi_index": p.rashi_index,
                "rashi": p.rashi,
                "degree": round(p.degree, 6),
                "nakshatra_index": p.nakshatra_index,
                "nakshatra": p.nakshatra,
                "pada": p.pada,
                "nakshatra_lord": p.nakshatra_lord,
                "dignity": p.dignity or None,
                "ayanamsha": ayan,
                "source": _SOURCE,
            }
        )
    return rows


def _sb_rows(
    engine: AstroEngine, d: date, hour_ist: float, ts: datetime, lat: float, lon: float
) -> list[dict]:
    dt = datetime(d.year, d.month, d.day, tzinfo=IST) + timedelta(hours=hour_ist)
    res = compute_shadbala(engine, dt, lat, lon)
    rows = []
    for g, r in res.items():
        rows.append(
            {
                "as_of_date": d,
                "as_of_ts": ts,
                "graha": g,
                "sthana_bala": round(r.sthana_total, 4),
                "dig_bala": round(r.dig, 4),
                "kala_bala": round(r.kala_total, 4),
                "cheshta_bala": round(r.cheshta, 4),
                "naisargika_bala": round(r.naisargika, 4),
                "drik_bala": round(r.drik, 4),
                "total_virupa": round(r.total_virupa, 4),
                "total_rupa": round(r.total_rupa, 4),
                "required_rupa": round(r.required_rupa, 3),
                "strength_ratio": round(r.ratio, 4),
                "rank": r.rank,
                "ishta_phala": round(r.ishta_phala, 4),
                "kashta_phala": round(r.kashta_phala, 4),
                "graha_yuddha": r.graha_yuddha,
                "components": {k: round(v, 4) for k, v in r.flat().items()},
                "source": _SOURCE,
            }
        )
    return rows


_KEY_COLS = {
    "astro_positions": ("as_of_date", "body"),
    "astro_shadbala": ("as_of_date", "graha"),
    "astro_days": ("as_of_date",),
}


def _upsert(session: Session, table, rows: list[dict], constraint: str) -> int:
    if not rows:
        return 0
    keys = _KEY_COLS[table.name]
    stmt = pg_insert(table).values(rows)
    update_cols = {c.name for c in table.columns} - {"id", "created_at", *keys}
    if table.name == "astro_days":
        stmt = stmt.on_conflict_do_update(
            index_elements=["as_of_date"],
            set_={c: getattr(stmt.excluded, c) for c in update_cols},
        )
    else:
        stmt = stmt.on_conflict_do_update(
            constraint=constraint,
            set_={c: getattr(stmt.excluded, c) for c in update_cols},
        )
    session.execute(stmt)
    return len(rows)


def _day_row(engine: AstroEngine, d: date, hour_ist: float, lat: float, lon: float) -> list[dict]:
    from app.astro.daily import compute_day_chart

    dt = datetime(d.year, d.month, d.day, tzinfo=IST) + timedelta(hours=hour_ist)
    c = compute_day_chart(engine, dt, lat, lon)
    return [
        {
            "as_of_date": c.as_of_date,
            "as_of_ts": c.as_of_ts,
            "weekday": c.weekday,
            "day_name": c.day_name,
            "weekday_lord": c.weekday_lord,
            "lagna_longitude": round(c.lagna_longitude, 6),
            "lagna_rashi_index": c.lagna_rashi_index,
            "lagna_rashi": c.lagna_rashi,
            "lagna_nakshatra_index": c.lagna_nakshatra_index,
            "lagna_nakshatra": c.lagna_nakshatra,
            "lagna_pada": c.lagna_pada,
            "moon_rashi_index": c.moon_rashi_index,
            "moon_rashi": c.moon_rashi,
            "moon_nakshatra_index": c.moon_nakshatra_index,
            "moon_nakshatra": c.moon_nakshatra,
            "moon_pada": c.moon_pada,
            "moon_nakshatra_lord": c.moon_nakshatra_lord,
            "sun_rashi_index": c.sun_rashi_index,
            "sun_rashi": c.sun_rashi,
            "tithi": c.tithi,
            "paksha": c.paksha,
            "sunrise_ts": c.sunrise_ts,
            "sunset_ts": c.sunset_ts,
            "ayanamsha": round(c.ayanamsha, 6),
            "source": _SOURCE,
        }
    ]


def last_built_date(session: Session) -> date | None:
    return session.execute(select(func.max(m.AstroPosition.as_of_date))).scalar_one_or_none()


def build(
    session: Session,
    *,
    start: date,
    end: date,
    latitude: float,
    longitude: float,
    hour_ist: float = 9.0,
    with_shadbala: bool = True,
    with_positions: bool = True,
    engine: AstroEngine | None = None,
    commit_every: int = 250,
) -> BuildReport:
    engine = engine or AstroEngine()
    rep = BuildReport()
    since_commit = 0
    for d in weekdays(start, end):
        ts = (datetime(d.year, d.month, d.day, tzinfo=IST) + timedelta(hours=hour_ist)).astimezone(
            UTC
        )
        if with_positions:
            rep.positions_upserted += _upsert(
                session,
                m.AstroPosition.__table__,
                _pos_rows(engine, d, hour_ist, ts),
                "astro_positions_identity",
            )
        if with_shadbala:
            rep.shadbala_upserted += _upsert(
                session,
                m.AstroShadbala.__table__,
                _sb_rows(engine, d, hour_ist, ts, latitude, longitude),
                "astro_shadbala_identity",
            )
        rep.days_upserted += _upsert(
            session,
            m.AstroDay.__table__,
            _day_row(engine, d, hour_ist, latitude, longitude),
            "pk_astro_days",
        )
        rep.dates += 1
        rep.first = rep.first or d
        rep.last = d
        since_commit += 1
        if since_commit >= commit_every:
            session.commit()
            since_commit = 0
    session.commit()
    return rep
