"""Scoring — SCORE phase through ``run_cycle`` on PostgreSQL (``@pytest.mark.db``)."""

from __future__ import annotations

import math
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from analytical_core.enums import InstrumentSegment, InstrumentType
from app.config import Settings
from app.db import models as md
from app.db.repositories.sqlalchemy import build_sqlalchemy_repositories
from app.providers.upstox import UpstoxProvider
from app.providers.upstox.http import UpstoxHTTPClient
from app.worker.cycle import run_cycle

pytestmark = pytest.mark.db

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


@pytest.fixture()
def db_session(migrated_engine):
    with Session(migrated_engine) as s:
        yield s


def _m1(n, sm=555):
    rows = [
        [
            f"2026-08-27T{(sm + i) // 60:02d}:{(sm + i) % 60:02d}:00+05:30",
            100 + (i % 7),
            101 + (i % 7),
            99 + (i % 7),
            100 + (i % 5),
            10 + i,
            54000 + i,
        ]
        for i in range(n)
    ]
    rows.reverse()
    return rows


def _provider():
    def handler(req):
        c = (
            [["2026-08-25T00:00:00+05:30", 100, 105, 95, 102, 5000, 0]]
            if "/days/1/" in str(req.url)
            else _m1(200)
        )
        return httpx.Response(200, json={"status": "success", "data": {"candles": c}})

    cl = UpstoxHTTPClient(
        base_url="https://api.upstox.com",
        token_provider=lambda: "t",
        transport=httpx.MockTransport(handler),
        max_rps=0,
        max_retries=0,
        sleep_fn=lambda _s: None,
    )
    return UpstoxProvider(
        Settings(active_provider="upstox", upstox_access_token="x"), http_client=cl
    )


def _tracked(db, ck, itype, seg, psym):
    inst = md.Instrument(
        contract_key=ck,
        symbol=ck.split("-")[0],
        segment=seg,
        instrument_type=itype,
        is_tracked=True,
    )
    db.add(inst)
    db.flush()
    db.add(
        md.ProviderInstrumentMap(
            instrument_id=inst.id, provider="upstox", provider_symbol=psym, is_active=True
        )
    )
    db.flush()
    return int(inst.id)


def _run(db):
    return run_cycle(
        build_sqlalchemy_repositories(db),
        _provider(),
        settings=Settings(active_provider="upstox"),
        now_fn=lambda: NOW,
    )


def test_score_phase_writes_real_composites_and_linked_factors(db_session):
    fut = _tracked(
        db_session,
        "NIFTY-FUT-2026-09",
        InstrumentType.FUTURE,
        InstrumentSegment.FUT,
        "NSE_FO|68407",
    )
    db_session.commit()
    result = _run(db_session)
    db_session.commit()

    scores = (
        db_session.execute(select(md.SignalScore).where(md.SignalScore.run_id == result.run_id))
        .scalars()
        .all()
    )
    assert {s.timeframe.value for s in scores} == {"M5", "M15", "H1", "D1"}
    for s in scores:
        assert s.scoring_version == "1.0.0" and s.strategy == "weighted_v1"
        assert len(s.params_hash) == 16
        assert -100.0 <= float(s.composite_score) <= 100.0
        assert s.raw_label.value in {
            "STRONG_BEARISH",
            "BEARISH",
            "NEUTRAL",
            "BULLISH",
            "STRONG_BULLISH",
        }
        assert s.explanation

    m5 = next(s for s in scores if s.timeframe.value == "M5")
    factors = (
        db_session.execute(select(md.ScoreFactor).where(md.ScoreFactor.signal_score_id == m5.id))
        .scalars()
        .all()
    )
    assert factors  # RSI / Bollinger / EMA / Volume fed it
    assert abs(math.fsum(float(f.contribution) for f in factors) - float(m5.composite_score)) < 1e-3
    # every factor links back to its analysis_results row
    assert all(f.analysis_result_id is not None for f in factors)

    cur = (
        db_session.execute(
            select(md.CurrentSignalScore).where(md.CurrentSignalScore.instrument_id == fut)
        )
        .scalars()
        .all()
    )
    assert len(cur) == 4


def test_delta_vs_previous_is_zero_on_an_identical_second_cycle(db_session):
    _tracked(
        db_session,
        "NIFTY-FUT-2026-09",
        InstrumentType.FUTURE,
        InstrumentSegment.FUT,
        "NSE_FO|68407",
    )
    db_session.commit()
    _run(db_session)
    db_session.commit()
    _run(db_session)
    db_session.commit()

    deltas = db_session.execute(select(md.CurrentSignalScore.delta_vs_previous)).scalars().all()
    assert deltas and all(d is not None and abs(float(d)) < 1e-6 for d in deltas)
    assert db_session.execute(select(func.count()).select_from(md.SignalScore)).scalar_one() == 8


def test_golden_cross_absent_from_future_score_factors(db_session):
    _tracked(
        db_session,
        "NIFTY-FUT-2026-09",
        InstrumentType.FUTURE,
        InstrumentSegment.FUT,
        "NSE_FO|68407",
    )
    db_session.commit()
    result = _run(db_session)
    db_session.commit()
    keys = set(
        db_session.execute(
            select(md.ScoreFactor.analysis_key)
            .join(md.SignalScore, md.SignalScore.id == md.ScoreFactor.signal_score_id)
            .where(md.SignalScore.run_id == result.run_id)
        ).scalars()
    )
    assert "golden_cross" not in keys  # NOT_APPLICABLE -> no factor row (docs/06 §3.1)
    assert {"rsi", "ema7", "volume"} & keys
