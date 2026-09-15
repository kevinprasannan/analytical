"""KP-lord change brackets across one trading session (docs/13 §5.6.1).

For a date, sample the sky minute by minute from 09:00 IST to an end time
(default 15:40) and, whenever the **KP lord chain** (sign → star → sub →
sub-sub) of the **Lagna** *or* the **Moon** changes at the chosen level, close
the current bracket and open a new one. The Lagna moves ~1°/4min so its sub /
sub-sub lord turn over many times through the session; the Moon barely moves.

Each bracket carries: the Parashari natural relation star↔sub within each
chain; `lagna_houses` — the whole-sign house **from the Lagna** (ascendant =
house 1) of the Lagna chain's sign / star / sub lord grahas, e.g. `11-9-10`;
and, when M1 bars are supplied, that bracket's **open→close** market move.

Descriptive research — no forecast, no execution label.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.astro import vedic
from app.astro.dasha import kp_chain
from app.astro.ephemeris import AstroEngine

IST = timezone(timedelta(hours=5, minutes=30))
_START_MIN = 9 * 60  # 09:00 IST


def _parse_hm(hm: str) -> int:
    try:
        h, m = (int(x) for x in hm.split(":"))
    except ValueError:
        raise ValueError(f"end must be 'HH:MM', got {hm!r}") from None
    v = h * 60 + m
    if not (_START_MIN < v <= 23 * 60 + 59):
        raise ValueError(f"end must be after 09:00 and a valid clock time, got {hm!r}")
    return v


def _clock(mins: int) -> str:
    return f"{mins // 60:02d}:{mins % 60:02d}"


def _point(lon: float) -> dict:
    c = kp_chain(lon)
    return {
        "longitude": round(lon % 360.0, 4),
        **c,
        "star_sub_relation": vedic.natural_relation(c["star_lord"], c["sub_lord"]),
    }


def _chain_key(p: dict, *, deep: bool) -> tuple:
    k = (p["sign_lord"], p["star_lord"], p["sub_lord"])
    return (*k, p["sub_sub_lord"]) if deep else k


def _house_from_lagna(lagna_lon: float, lord: str, rashi_of: dict[str, int]) -> int | None:
    """Whole-sign house of ``lord``'s graha counted from the Lagna sign
    (ascendant = house 1). ``None`` if the graha's rashi is unknown."""
    r = rashi_of.get(lord.upper())
    if r is None:
        return None
    lr = int(lagna_lon % 360.0 // 30.0)
    return ((r - lr) % 12) + 1


def _bracket_market(
    bars: dict[int, tuple[float, float]] | None, start_min: int, end_min: int
) -> dict | None:
    """Open of the first M1 bar ≥ ``start_min`` → close of the last M1 bar
    ``< end_min``; the change between them. ``None`` when no bars land in the
    bracket (or none were supplied)."""
    if not bars:
        return None
    inside = sorted(m for m in bars if start_min <= m < end_min)
    if not inside:
        return None
    o = bars[inside[0]][0]
    c = bars[inside[-1]][1]
    chg = c - o
    return {
        "open": round(o, 2),
        "close": round(c, 2),
        "change": round(chg, 2),
        "change_pct": round(chg / o * 100.0, 3) if o else None,
    }


def kp_session_timeline(
    engine: AstroEngine,
    *,
    d: date,
    lat: float,
    lon: float,
    end: str = "15:40",
    level: str = "sub",
    bars: dict[int, tuple[float, float]] | None = None,
) -> dict:
    """Lagna + Moon KP-chain **change brackets** for ``d``, 09:00 IST → ``end``.

    One row per stretch during which neither chain's lord changes at ``level``
    (``"sub"`` — the KP-decisive sub lord, the default; or ``"sub_sub"`` — every
    sub-sub-lord turn). Each row: ``start`` / ``end`` (IST ``HH:MM``), both
    chains at the bracket's start, each chain's star↔sub naisargika relation,
    ``lagna_houses`` (the whole-sign house from the Lagna of the sign / star /
    sub lord grahas of the Lagna's chain), and — when ``bars``
    (``{minute_of_day: (open, close)}`` M1) is given — the bracket's ``market``
    open→close move.
    """
    if level not in ("sub", "sub_sub"):
        raise ValueError(f"level must be 'sub' or 'sub_sub', got {level!r}")
    deep = level == "sub_sub"
    end_min = _parse_hm(end)
    midnight = datetime.combine(d, datetime.min.time(), IST)

    # graha rashis for the day (they barely move intraday — one 09:00 snapshot)
    rashi_of = {
        p.graha: p.rashi_index for p in engine.positions(midnight + timedelta(minutes=_START_MIN))
    }

    raw: list[dict] = []
    cur: dict | None = None
    prev_key: tuple | None = None

    for mins in range(_START_MIN, end_min + 1):
        dt = midnight + timedelta(minutes=mins)
        lagna = _point(engine.ascendant(dt, lat, lon))
        moon = _point(engine.position(dt, "MOON").longitude)
        key = (_chain_key(lagna, deep=deep), _chain_key(moon, deep=deep))
        if key != prev_key:
            if cur is not None:
                cur["_end_min"] = mins
                raw.append(cur)
            cur = {
                "_start_min": mins,
                "_end_min": end_min,
                "lagna": lagna,
                "moon": moon,
                # whole-sign house from the Lagna of the sign / star / sub lord
                # grahas of the Lagna's chain (docs/13 §5.6.1)
                "lagna_houses": {
                    "sign": _house_from_lagna(lagna["longitude"], lagna["sign_lord"], rashi_of),
                    "star": _house_from_lagna(lagna["longitude"], lagna["star_lord"], rashi_of),
                    "sub": _house_from_lagna(lagna["longitude"], lagna["sub_lord"], rashi_of),
                },
            }
            prev_key = key
    if cur is not None:
        cur["_end_min"] = end_min
        raw.append(cur)

    rows = []
    for r in raw:
        s, e = r.pop("_start_min"), r.pop("_end_min")
        rows.append(
            {
                "start": _clock(s),
                "end": _clock(e),
                **r,
                "market": _bracket_market(bars, s, e),
            }
        )

    return {"date": d.isoformat(), "end": _clock(end_min), "level": level, "rows": rows}
