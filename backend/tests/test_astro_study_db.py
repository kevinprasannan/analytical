"""Astro x market cross-check study (docs/13 §5). Needs PostgreSQL."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.astro import backfill as bf
from app.astro.study import result_to_dict, run_study

pytestmark = pytest.mark.db
IST = timezone(timedelta(hours=5, minutes=30))


@pytest.fixture()
def session(migrated_engine):
    with Session(migrated_engine) as s:
        yield s


def _seed_nifty_d1(session: Session, closes: list[float], start: date) -> None:
    session.execute(
        text(
            "INSERT INTO instruments (id,contract_key,symbol,segment,instrument_type,"
            "is_active,is_tracked) VALUES (1,'NIFTY-INDEX','NIFTY','INDEX','INDEX',true,true)"
        )
    )
    d = start
    for c in closes:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        ts = datetime(d.year, d.month, d.day, tzinfo=IST) + timedelta(hours=3, minutes=45)
        session.execute(
            text(
                "INSERT INTO ohlcv_bars (instrument_id,timeframe,ts,open,high,low,close,"
                "volume,provider,is_final) VALUES "
                "(1,'D1',:ts,:o,:h,:l,:c,0,'test',true)"
            ),
            {"ts": ts, "o": c, "h": c * 1.01, "l": c * 0.99, "c": c},
        )
        d += timedelta(days=1)
    session.commit()


def test_study_shapes_and_math(session):
    closes = [100, 101, 102, 101, 103, 104, 103, 105, 106, 107, 108, 107]
    _seed_nifty_d1(session, closes, date(2024, 1, 1))
    bf.build(
        session,
        start=date(2024, 1, 1),
        end=date(2024, 1, 19),
        latitude=19.076090,
        longitude=72.877426,
        with_shadbala=False,
    )

    res = run_study(session)
    assert res.underlying == "NIFTY-INDEX"
    assert res.n_days == len(closes) - 1  # first bar has no prev_close

    # baseline mean return matches a hand calc over the close series
    rets = [(closes[i] - closes[i - 1]) / closes[i - 1] * 100 for i in range(1, len(closes))]
    assert res.baseline.mean_ret == pytest.approx(sum(rets) / len(rets), abs=1e-6)
    assert res.baseline.n == len(rets)
    assert 0 <= res.baseline.pct_up <= 100

    # every grouping partitions the same N days
    for group in (res.by_weekday, res.by_moon_nakshatra, res.by_lagna_rashi, res.by_paksha):
        assert sum(b.n for b in group) == res.n_days

    d = result_to_dict(res)
    assert set(d) >= {"by_weekday", "by_moon_nakshatra", "by_lagna_rashi", "by_tithi", "baseline"}
    assert d["by_weekday"][0]["key"] in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")


def test_study_respects_date_window(session):
    _seed_nifty_d1(session, [100 + i for i in range(15)], date(2024, 2, 1))
    bf.build(
        session,
        start=date(2024, 2, 1),
        end=date(2024, 2, 29),
        latitude=19.076090,
        longitude=72.877426,
        with_shadbala=False,
    )
    full = run_study(session)
    windowed = run_study(session, start=date(2024, 2, 10))
    assert windowed.n_days < full.n_days
    assert windowed.first >= date(2024, 2, 10)
