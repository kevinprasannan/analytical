"""Per-day astro × market log (docs/13 §5.2). Needs PostgreSQL."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.main import create_app
from app.astro import backfill as bf
from app.astro.daylog import day_detail, run_almanac, run_daylog

pytestmark = pytest.mark.db
IST = timezone(timedelta(hours=5, minutes=30))


def _seed(session: Session, closes: list[float], start: date) -> None:
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
                "volume,provider,is_final) VALUES (1,'D1',:ts,:o,:h,:l,:c,0,'test',true)"
            ),
            {"ts": ts, "o": c, "h": c * 1.02, "l": c * 0.98, "c": c},
        )
        d += timedelta(days=1)
    session.commit()
    bf.build(
        session,
        start=start,
        end=start + timedelta(days=len(closes) + 10),
        latitude=19.076090,
        longitude=72.877426,
        with_shadbala=False,
    )


@pytest.fixture()
def session(migrated_engine):
    with Session(migrated_engine) as s:
        _seed(s, [100, 102, 101, 103, 105, 104, 106, 108, 107, 110, 109, 112], date(2024, 1, 1))
        yield s


@pytest.fixture()
def client(session, migrated_engine):
    app = create_app()

    def _override():
        s = Session(migrated_engine)
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _override
    return TestClient(app)


def test_daylog_sorts_by_return_desc_by_default(session):
    res = run_daylog(session)
    rets = [r["ret_pct"] for r in res["items"]]
    assert rets == sorted(rets, reverse=True)
    assert res["total"] == 11  # 12 closes, first has no prev_close
    assert res["summary"]["n"] == 11
    assert res["items"][0]["ret_pct"] >= res["items"][-1]["ret_pct"]


def test_daylog_pagination_is_stable(session):
    p1 = run_daylog(session, limit=4, offset=0)
    p2 = run_daylog(session, limit=4, offset=4)
    assert len(p1["items"]) == 4 and len(p2["items"]) == 4
    assert {r["d"] for r in p1["items"]}.isdisjoint({r["d"] for r in p2["items"]})
    assert p1["total"] == p2["total"] == 11


def test_daylog_ascending_and_date_sort(session):
    asc = run_daylog(session, sort="ret")
    rets = [r["ret_pct"] for r in asc["items"]]
    assert rets == sorted(rets)
    by_date = run_daylog(session, sort="d")
    ds = [r["d"] for r in by_date["items"]]
    assert ds == sorted(ds)


def test_daylog_combination_filter_narrows_and_summarises(session):
    full = run_daylog(session)
    sample = full["items"][0]
    combo = run_daylog(
        session,
        filters={
            "weekday": sample["weekday"],
            "tithi": sample["tithi"],
            "moon_nakshatra": sample["moon_nakshatra"],
        },
    )
    assert 1 <= combo["total"] <= full["total"]
    assert combo["summary"]["n"] == combo["total"]
    for r in combo["items"]:
        assert r["weekday"] == sample["weekday"]
        assert r["tithi"] == sample["tithi"]
        assert r["moon_nakshatra"] == sample["moon_nakshatra"]
    assert combo["filters"]["tithi"] == str(sample["tithi"])


def test_daylog_month_filter(session):
    jan = run_daylog(session, filters={"month": 1})
    assert jan["total"] >= 1
    assert all(r["month"] == 1 for r in jan["items"])
    assert all(r["d"][5:7] == "01" for r in jan["items"])
    assert run_daylog(session, filters={"month": 7})["total"] == 0  # seed is Jan 2024 only


def test_daylog_empty_combo_returns_zeroed_summary_not_error(session):
    res = run_daylog(session, filters={"paksha": "Shukla", "weekday_lord": "Saturn"})
    assert res["total"] == 0
    assert res["items"] == []
    assert res["summary"]["n"] == 0
    assert res["first"] is None and res["last"] is None


def test_daylog_bad_sort_key_raises(session):
    with pytest.raises(ValueError, match="unknown sort key"):
        run_daylog(session, sort="wat")


def test_almanac_includes_days_without_a_candle(session):
    # _seed builds astro_days a few days past the 12 candles → some rows have no D1
    res = run_almanac(session, start=date(2024, 1, 1), end=date(2024, 1, 31), sort="d")
    assert res["total"] > res["with_candle"] >= 1
    by_date = {r["d"]: r for r in res["items"]}
    traded = [r for r in res["items"] if r["has_candle"]]
    untraded = [r for r in res["items"] if not r["has_candle"]]
    assert traded and untraded
    # every row carries the panchang; only traded rows carry a return
    for r in res["items"]:
        assert r["moon_nakshatra"] and r["lagna_rashi"] and r["sun_rashi"]
        if not r["has_candle"]:
            assert r["close"] is None and r["ret_pct"] is None
    # dates are chronological, and the day screen resolves for an untraded one
    assert list(by_date) == sorted(by_date)
    assert day_detail(session, d=date.fromisoformat(untraded[0]["d"])) is not None


def test_almanac_default_start_is_today(session):
    # seed is Jan 2024 → default (today) window returns nothing, but never errors
    res = run_almanac(session)
    assert res["total"] == 0 and res["items"] == []


def test_day_detail_has_market_and_astro(session):
    log = run_daylog(session, sort="d")
    day = log["items"][3]["d"]  # a mid-series day → has prev_close
    det = day_detail(session, d=date.fromisoformat(day))
    assert det is not None
    assert det["date"] == day
    d1 = det["market"]["d1"]
    assert d1["high"] >= d1["close"] >= 0
    assert d1["low"] <= d1["close"]
    assert d1["ret_pct"] is not None and d1["range_pct"] is not None
    assert det["market"]["hourly"] == []  # none seeded
    assert det["astro"]["day"]["day_name"] in (
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
    )
    bodies = [p["body"] for p in det["astro"]["positions"]]
    # the ascendant leads, then Sun→Ketu
    assert bodies[:3] == ["Lagna", "Sun", "Moon"] and len(bodies) == 10
    lagna = next(p for p in det["astro"]["positions"] if p["body"] == "Lagna")
    assert lagna["retrograde"] is False and lagna["speed_longitude"] is None
    assert lagna["house_from_lagna"] == 1 and lagna["house_from_lagna_deg"] == 1
    assert 0.0 <= lagna["degree"] < 30.0 and 0 <= lagna["rashi_index"] <= 11
    assert det["astro"]["shadbala"] == []  # fixture built with_shadbala=False

    # diff vs the previous weekday
    a = det["astro"]
    assert a["prev_date"] is not None and a["prev_date"] < day
    moon = next(p for p in a["positions"] if p["body"] == "Moon")
    # the Moon moves ~13°/day → its nakshatra and/or pada always shift day-to-day
    assert moon["changed_nakshatra"] or moon["changed_pada"]
    assert moon["prev_nakshatra"] and moon["prev_pada"] is not None
    for p in a["positions"]:
        # a flag is only true when it disagrees with the stated prev_* value
        if p["changed_pada"]:
            assert p["prev_pada"] != p["pada"]
        if p["changed_rashi"]:
            assert p["prev_rashi"] != p["rashi"]
        if not p["changed_retrograde"]:
            assert p["prev_retrograde"] in (p["retrograde"], None)

    # the earliest astro_days row has no predecessor → no diff, flags all False
    first_day = run_daylog(session, sort="d")["items"][0]["d"]
    first = day_detail(session, d=date.fromisoformat(first_day))["astro"]
    if first["prev_date"] is None:
        assert all(not p["changed_pada"] and not p["changed_rashi"] for p in first["positions"])


def test_day_detail_unknown_date_is_none(session):
    assert day_detail(session, d=date(1990, 1, 1)) is None


def test_day_detail_house_frames_lagna_moon_sun(session):
    day = run_daylog(session, sort="d")["items"][3]["d"]
    det = day_detail(session, d=date.fromisoformat(day))
    a = det["astro"]
    triads = {"Dharma": {1, 5, 9}, "Artha": {2, 6, 10}, "Kama": {3, 7, 11}, "Moksha": {4, 8, 12}}

    refs = {
        "lagna": a["day"]["lagna_rashi_index"],
        "moon": next(p["rashi_index"] for p in a["positions"] if p["body"] == "Moon"),
        "sun": next(p["rashi_index"] for p in a["positions"] if p["body"] == "Sun"),
    }
    for fr, ref_ri in refs.items():
        assert 0 <= ref_ri <= 11
        for p in a["positions"]:
            h = p[f"house_from_{fr}"]
            g = p[f"house_group_{fr}"]
            assert 1 <= h <= 12
            assert h == ((p["rashi_index"] - ref_ri) % 12) + 1
            assert h in triads[g]

    # the reference body always sits in its own 1st house → Dharma
    moon = next(p for p in a["positions"] if p["body"] == "Moon")
    assert moon["house_from_moon"] == 1 and moon["house_group_moon"] == "Dharma"
    sun = next(p for p in a["positions"] if p["body"] == "Sun")
    assert sun["house_from_sun"] == 1

    frames = a["house_frames"]
    assert [f["frame"] for f in frames] == ["lagna", "lagna_deg", "moon", "sun"]
    for f in frames:
        assert [g["group"] for g in f["groups"]] == ["Dharma", "Artha", "Kama", "Moksha"]
        assert f["groups"][0]["houses"] == [1, 5, 9]
        placed = sum(len(g["bodies"]) for g in f["groups"])
        # "Lagna" is a real position now — every frame places exactly the positions
        assert placed == len(a["positions"])
    assert "Lagna" in frames[0]["groups"][0]["bodies"]
    assert "Lagna" in frames[1]["groups"][0]["bodies"]  # lagna_deg 1st house too
    # no duplicates
    for f in frames:
        allb = [b for g in f["groups"] for b in g["bodies"]]
        assert len(allb) == len(set(allb))
    assert "Moon" in next(g["bodies"] for g in frames[2]["groups"] if g["group"] == "Dharma")

    # degree-based lagna house = floor((lon - lagna_lon) mod 360 / 30) + 1
    lag = a["day"]["lagna_longitude"]
    assert lag is not None
    for p in a["positions"]:
        hd = p["house_from_lagna_deg"]
        assert 1 <= hd <= 12
        assert hd == int(((p["longitude"] - lag) % 360.0) // 30.0) + 1
        assert hd in triads[p["house_group_lagna_deg"]]


def test_day_detail_includes_hourly_and_shadbala(migrated_engine):
    with Session(migrated_engine) as s:
        s.execute(
            text(
                "INSERT INTO instruments (id,contract_key,symbol,segment,instrument_type,"
                "is_active,is_tracked) VALUES (1,'NIFTY-INDEX','NIFTY','INDEX','INDEX',true,true)"
            )
        )
        d1_day = date(2024, 3, 4)  # a Monday
        ts_d1 = datetime(2024, 3, 4, tzinfo=IST) + timedelta(hours=3, minutes=45)
        s.execute(
            text(
                "INSERT INTO ohlcv_bars (instrument_id,timeframe,ts,open,high,low,close,"
                "volume,provider,is_final) VALUES (1,'D1',:ts,100,104,99,103,0,'test',true)"
            ),
            {"ts": ts_d1},
        )
        for h in range(4):  # 09:15..12:15 IST hourly bars
            hts = datetime(2024, 3, 4, 9, 15, tzinfo=IST) + timedelta(hours=h)
            s.execute(
                text(
                    "INSERT INTO ohlcv_bars (instrument_id,timeframe,ts,open,high,low,close,"
                    "volume,provider,is_final) VALUES (1,'H1',:ts,:o,:hi,:lo,:c,1000,'test',true)"
                ),
                {"ts": hts, "o": 100 + h, "hi": 101 + h, "lo": 99 + h, "c": 100.5 + h},
            )
        for f in range(3):  # 09:15..09:25 IST 5-min bars
            fts = datetime(2024, 3, 4, 9, 15, tzinfo=IST) + timedelta(minutes=5 * f)
            s.execute(
                text(
                    "INSERT INTO ohlcv_bars (instrument_id,timeframe,ts,open,high,low,close,"
                    "volume,provider,is_final) VALUES (1,'M5',:ts,:o,:hi,:lo,:c,200,'test',true)"
                ),
                {"ts": fts, "o": 100 + f, "hi": 100.5 + f, "lo": 99.5 + f, "c": 100.2 + f},
            )
        s.commit()
        bf.build(
            s,
            start=d1_day,
            end=d1_day + timedelta(days=1),
            latitude=19.076090,
            longitude=72.877426,
            with_shadbala=True,
        )
        det = day_detail(s, d=d1_day)

    assert det["market"]["d1"]["close"] == 103.0
    hourly = det["market"]["hourly"]
    assert len(hourly) == 4
    assert [h["open"] for h in hourly] == [100.0, 101.0, 102.0, 103.0]
    assert hourly == sorted(hourly, key=lambda h: h["ts"])
    m5 = det["market"]["m5"]
    assert len(m5) == 3
    assert [b["open"] for b in m5] == [100.0, 101.0, 102.0]
    assert m5 == sorted(m5, key=lambda b: b["ts"])
    shad = det["astro"]["shadbala"]
    assert len(shad) == 7
    assert [x["rank"] for x in shad] == sorted(x["rank"] for x in shad)
    assert all(x["total_rupa"] > 0 for x in shad)


def test_api_astro_day_detail_endpoint(client):
    log = client.get("/api/v1/astro/days", params={"sort": "d", "limit": 5}).json()
    day = log["items"][2]["d"]
    r = client.get(f"/api/v1/astro/days/{day}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["date"] == day
    assert body["market"]["d1"]["open"] is not None
    assert len(body["astro"]["positions"]) == 9

    assert client.get("/api/v1/astro/days/1985-06-01").status_code == 404


def test_api_astro_days_endpoint(client):
    r = client.get("/api/v1/astro/days", params={"limit": 5, "sort": "-ret"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["underlying"] == "NIFTY-INDEX"
    assert len(body["items"]) == 5
    assert body["total"] == 11
    assert body["summary"]["n"] == 11
    rets = [x["ret_pct"] for x in body["items"]]
    assert rets == sorted(rets, reverse=True)

    day = body["items"][0]
    combo = client.get(
        "/api/v1/astro/days",
        params={"weekday": day["day_name"], "tithi": day["tithi"]},
    )
    assert combo.status_code == 200, combo.text
    cb = combo.json()
    assert cb["total"] >= 1
    assert all(x["tithi"] == day["tithi"] for x in cb["items"])
    assert cb["filters"]["weekday"] == day["day_name"]
