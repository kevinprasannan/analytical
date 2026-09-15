"""Phase 2.5 — backfill persistence against PostgreSQL (``@pytest.mark.db``)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from analytical_core.enums import (
    DataKind,
    InstrumentSegment,
    InstrumentType,
    Timeframe,
    WatermarkStatus,
)
from app.config import Settings
from app.db import models as md
from app.db.repositories.market_data import (
    OIRow,
    SaMarketDataRepository,
    WatermarkWrite,
)
from app.ingestion.backfill import BackfillService, BackfillTarget
from app.ingestion.budget import RequestBudget
from app.providers.base import OHLCVBar
from app.providers.upstox import UpstoxProvider
from app.providers.upstox.http import UpstoxHTTPClient

pytestmark = pytest.mark.db

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


@pytest.fixture()
def db_session(migrated_engine):
    with Session(migrated_engine) as s:
        yield s


def _instrument(db: Session, ck: str, itype: InstrumentType, seg: InstrumentSegment) -> int:
    row = md.Instrument(
        contract_key=ck, symbol=ck.split("-")[0], segment=seg, instrument_type=itype
    )
    db.add(row)
    db.flush()
    return int(row.id)


def _bar(ts: datetime, *, close=100, is_final=True, oi=None) -> OHLCVBar:
    return OHLCVBar(
        ts=ts,
        open=100,
        high=101,
        low=99,
        close=close,
        volume=10,
        is_final=is_final,
        source="upstox:v3/historical-candle",
        open_interest=oi,
    )


# ======================================================================================
# repository-level upsert semantics (docs/09 §2.8)
# ======================================================================================


def test_ohlcv_upsert_is_idempotent_and_tracks_is_final_transition(db_session):
    iid = _instrument(db_session, "NIFTY-FUT-2026-09", InstrumentType.FUTURE, InstrumentSegment.FUT)
    repo = SaMarketDataRepository(db_session)
    ts = datetime(2026, 8, 27, 3, 45, tzinfo=UTC)

    c1 = repo.upsert_ohlcv_bars(
        instrument_id=iid,
        timeframe=Timeframe.M1,
        provider="upstox",
        bars=[_bar(ts, is_final=False)],
    )
    assert (c1.inserted, c1.updated) == (1, 0)

    c2 = repo.upsert_ohlcv_bars(
        instrument_id=iid,
        timeframe=Timeframe.M1,
        provider="upstox",
        bars=[_bar(ts, close=200, is_final=True)],
    )
    assert (c2.inserted, c2.updated) == (0, 1)

    n = db_session.execute(select(func.count()).select_from(md.OhlcvBar)).scalar_one()
    assert n == 1
    row = db_session.execute(select(md.OhlcvBar)).scalar_one()
    assert row.is_final is True and int(row.close) == 200


def test_open_interest_upsert_is_idempotent(db_session):
    iid = _instrument(db_session, "NIFTY-FUT-2026-09", InstrumentType.FUTURE, InstrumentSegment.FUT)
    repo = SaMarketDataRepository(db_session)
    ts = datetime(2026, 8, 27, 3, 45, tzinfo=UTC)
    repo.upsert_open_interest(
        instrument_id=iid,
        timeframe=Timeframe.M1,
        provider="upstox",
        rows=[OIRow(ts=ts, oi=5000, is_final=True)],
    )
    c = repo.upsert_open_interest(
        instrument_id=iid,
        timeframe=Timeframe.M1,
        provider="upstox",
        rows=[OIRow(ts=ts, oi=5555, is_final=True)],
    )
    assert (c.inserted, c.updated) == (0, 1)
    assert db_session.execute(select(func.count()).select_from(md.OpenInterest)).scalar_one() == 1
    assert int(db_session.execute(select(md.OpenInterest.oi)).scalar_one()) == 5555


def test_watermark_roundtrip_and_verified_ts_is_preserved(db_session):
    iid = _instrument(db_session, "NIFTY-FUT-2026-09", InstrumentType.FUTURE, InstrumentSegment.FUT)
    repo = SaMarketDataRepository(db_session)
    t0 = datetime(2026, 8, 27, 4, 0, tzinfo=UTC)

    repo.upsert_watermark(
        WatermarkWrite(
            instrument_id=iid,
            timeframe=Timeframe.M1,
            data_kind=DataKind.OHLCV,
            provider="upstox",
            last_complete_ts=t0,
            last_attempt_at=t0,
            last_status=WatermarkStatus.OK,
            last_verified_ts=t0,
        )
    )
    # a later attempt that does NOT re-verify
    repo.upsert_watermark(
        WatermarkWrite(
            instrument_id=iid,
            timeframe=Timeframe.M1,
            data_kind=DataKind.OHLCV,
            provider="upstox",
            last_complete_ts=t0 + timedelta(minutes=5),
            last_attempt_at=t0 + timedelta(hours=1),
            last_status=WatermarkStatus.OK,
        )
    )
    wm = repo.get_watermark(
        instrument_id=iid, timeframe=Timeframe.M1, data_kind=DataKind.OHLCV, provider="upstox"
    )
    assert wm.last_complete_ts == t0 + timedelta(minutes=5)
    assert wm.last_verified_ts == t0  # preserved


def test_bar_open_timestamps_and_count(db_session):
    iid = _instrument(db_session, "NIFTY-FUT-2026-09", InstrumentType.FUTURE, InstrumentSegment.FUT)
    repo = SaMarketDataRepository(db_session)
    base = datetime(2026, 8, 27, 3, 45, tzinfo=UTC)
    repo.upsert_ohlcv_bars(
        instrument_id=iid,
        timeframe=Timeframe.M1,
        provider="upstox",
        bars=[_bar(base + timedelta(minutes=i)) for i in (0, 1, 2, 5)],
    )
    got = repo.bar_open_timestamps(
        instrument_id=iid,
        timeframe=Timeframe.M1,
        provider="upstox",
        start=base,
        end=base + timedelta(minutes=3),
    )
    assert got == [base, base + timedelta(minutes=1), base + timedelta(minutes=2)]
    assert repo.count_bars(instrument_id=iid, timeframe=Timeframe.M1, provider="upstox") == 4


# ======================================================================================
# full service against PostgreSQL
# ======================================================================================


def _m1_rows(n: int, *, start_min=555, oi_base=54000):
    rows = []
    for i in range(n):
        t = start_min + i
        rows.append(
            [
                f"2026-08-27T{t // 60:02d}:{t % 60:02d}:00+05:30",
                100,
                101,
                99,
                100 + i,
                10,
                oi_base + i,
            ]
        )
    rows.reverse()
    return rows


def _provider(m1_rows, d1_rows, budget):
    def handler(req: httpx.Request) -> httpx.Response:
        candles = d1_rows if "/days/1/" in str(req.url) else m1_rows
        return httpx.Response(200, json={"status": "success", "data": {"candles": candles}})

    client = UpstoxHTTPClient(
        base_url="https://api.upstox.com",
        token_provider=lambda: "tok",
        transport=httpx.MockTransport(handler),
        limiter=budget,
    )
    return UpstoxProvider(
        Settings(active_provider="upstox", upstox_access_token="x"), http_client=client
    )


def test_backfill_service_populates_all_tables(db_session):
    iid = _instrument(db_session, "NIFTY-FUT-2026-09", InstrumentType.FUTURE, InstrumentSegment.FUT)
    db_session.commit()
    budget = RequestBudget(max_rps=0, per_30min=0)
    provider = _provider(
        _m1_rows(60), [["2026-08-26T00:00:00+05:30", 100, 105, 95, 102, 5000, 0]], budget
    )
    svc = BackfillService(
        provider=provider,
        repo=SaMarketDataRepository(db_session),
        budget=budget,
        settings=Settings(),
        now_fn=lambda: NOW,
    )
    target = BackfillTarget(iid, "NSE_FO|68407", InstrumentType.FUTURE, "NIFTY-FUT-2026-09")
    report = svc.run([target])
    db_session.commit()

    assert report.instruments[0].status is WatermarkStatus.OK
    by_tf = dict(
        db_session.execute(
            select(md.OhlcvBar.timeframe, func.count()).group_by(md.OhlcvBar.timeframe)
        ).all()
    )
    assert by_tf[Timeframe.M1] == 60
    assert by_tf[Timeframe.D1] == 1
    assert by_tf[Timeframe.M5] == 12 and by_tf[Timeframe.M15] == 4 and by_tf[Timeframe.H1] == 1
    assert db_session.execute(select(func.count()).select_from(md.OpenInterest)).scalar_one() == 60
    # aggregated rows carry the ACTIVE provider, not the "aggregate:M1(...)" DTO source
    providers = set(
        db_session.execute(
            select(md.OhlcvBar.provider).where(md.OhlcvBar.timeframe == Timeframe.M5)
        ).scalars()
    )
    assert providers == {"upstox"}
    wms = db_session.execute(
        select(md.IngestionWatermark.timeframe, md.IngestionWatermark.data_kind)
    ).all()
    assert (Timeframe.M1, DataKind.OI) in wms and (Timeframe.H1, DataKind.OHLCV) in wms

    # resume: a second run upserts, no duplicate rows
    total_before = db_session.execute(select(func.count()).select_from(md.OhlcvBar)).scalar_one()
    assert total_before == 60 + 1 + 12 + 4 + 1  # M1 + D1 + M5 + M15 + H1
    svc.run([target])
    db_session.commit()
    assert (
        db_session.execute(select(func.count()).select_from(md.OhlcvBar)).scalar_one()
        == total_before
    )


def test_repo_error_mid_run_rolls_back_cleanly(db_session, monkeypatch):
    iid = _instrument(db_session, "NIFTY-FUT-2026-09", InstrumentType.FUTURE, InstrumentSegment.FUT)
    db_session.commit()
    budget = RequestBudget(max_rps=0, per_30min=0)
    provider = _provider(_m1_rows(30), [], budget)
    repo = SaMarketDataRepository(db_session)

    calls = {"n": 0}
    real = SaMarketDataRepository.upsert_ohlcv_bars

    def boom(self, **kw):
        calls["n"] += 1
        if calls["n"] == 2:  # after D1, during M1
            raise RuntimeError("simulated infra failure")
        return real(self, **kw)

    monkeypatch.setattr(SaMarketDataRepository, "upsert_ohlcv_bars", boom)
    svc = BackfillService(
        provider=provider, repo=repo, budget=budget, settings=Settings(), now_fn=lambda: NOW
    )
    with pytest.raises(RuntimeError):
        svc.run([BackfillTarget(iid, "NSE_FO|68407", InstrumentType.FUTURE, "NIFTY-FUT-2026-09")])
    db_session.rollback()
    assert db_session.execute(select(func.count()).select_from(md.OhlcvBar)).scalar_one() == 0
