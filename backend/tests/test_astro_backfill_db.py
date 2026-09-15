"""Astro backfill -> astro_positions / astro_shadbala (docs/13 §5). Needs PG."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.astro import backfill as bf

pytestmark = pytest.mark.db


@pytest.fixture()
def session(migrated_engine):
    with Session(migrated_engine) as s:
        yield s


def test_weekdays_excludes_weekend():
    ds = list(bf.weekdays(date(2024, 1, 1), date(2024, 1, 14)))
    assert date(2024, 1, 6) not in ds and date(2024, 1, 7) not in ds  # Sat/Sun
    assert ds[0] == date(2024, 1, 1) and ds[-1] == date(2024, 1, 12)
    assert len(ds) == 10


def test_build_one_week_positions_and_shadbala(session):
    rep = bf.build(
        session,
        start=date(2024, 1, 1),
        end=date(2024, 1, 7),  # 5 weekdays (Mon-Fri), Sat/Sun dropped
        latitude=19.076090,
        longitude=72.877426,
    )
    assert rep.dates == 5
    n_pos = session.execute(text("select count(*) from astro_positions")).scalar_one()
    n_sb = session.execute(text("select count(*) from astro_shadbala")).scalar_one()
    assert n_pos == 5 * 9  # 9 bodies
    assert n_sb == 5 * 7  # 7 grahas

    row = session.execute(
        text(
            "select longitude, rashi, nakshatra, pada, retrograde "
            "from astro_positions where as_of_date='2024-01-01' and body='MERCURY'"
        )
    ).one()
    assert row.rashi == "Vrischika" and row.retrograde is True

    sb_row = session.execute(
        text(
            "select total_rupa, required_rupa, rank, components "
            "from astro_shadbala where as_of_date='2024-01-01' and graha='JUPITER'"
        )
    ).one()
    assert 3.0 < float(sb_row.total_rupa) < 12.0
    assert sb_row.rank == 1  # Jupiter strongest on this date
    assert "sthana_uccha" in sb_row.components


def test_build_is_idempotent(session):
    kw = dict(start=date(2024, 2, 1), end=date(2024, 2, 2), latitude=19.07609, longitude=72.877426)
    bf.build(session, **kw)
    first = session.execute(
        text(
            "select body, longitude from astro_positions where as_of_date='2024-02-01' order by body"
        )
    ).all()
    bf.build(session, **kw)  # re-run
    again = session.execute(
        text(
            "select body, longitude from astro_positions where as_of_date='2024-02-01' order by body"
        )
    ).all()
    assert first == again
    n = session.execute(
        text("select count(*) from astro_positions where as_of_date='2024-02-01'")
    ).scalar_one()
    assert n == 9  # no duplicates


def test_no_shadbala_flag(session):
    bf.build(
        session,
        start=date(2024, 3, 1),
        end=date(2024, 3, 1),
        latitude=19.07609,
        longitude=72.877426,
        with_shadbala=False,
    )
    assert (
        session.execute(
            text("select count(*) from astro_positions where as_of_date='2024-03-01'")
        ).scalar_one()
        == 9
    )
    assert (
        session.execute(
            text("select count(*) from astro_shadbala where as_of_date='2024-03-01'")
        ).scalar_one()
        == 0
    )


def test_run_catch_up_fills_gap_then_is_noop(session):
    from app.astro.daily import run_catch_up

    bf.build(
        session,
        start=date(2024, 4, 1),
        end=date(2024, 4, 1),
        latitude=19.07609,
        longitude=72.877426,
    )
    # last stored = 2024-04-01; ask for catch-up through Fri 2024-04-05
    rep = run_catch_up(session, today=date(2024, 4, 5))
    assert rep.dates == 4  # Apr 2,3,4,5 (all weekdays)
    assert rep.first == date(2024, 4, 2) and rep.last == date(2024, 4, 5)
    n_days = session.execute(
        text("select count(*) from astro_days where as_of_date between '2024-04-01' and '2024-04-05'")
    ).scalar_one()
    assert n_days == 5

    again = run_catch_up(session, today=date(2024, 4, 5))
    assert again.dates == 0  # already current — no-op
