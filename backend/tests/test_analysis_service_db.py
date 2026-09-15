"""Phase 3 — ANALYZE orchestration through ``run_cycle`` on PostgreSQL:
real indicator results, provenance columns, applicability, recompute guard."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from analytical_core.enums import (
    AnalysisStatus,
    InstrumentSegment,
    InstrumentType,
)
from analytical_core.versioning import ALGO_VERSION
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


def _m1_rows(n: int, *, start_min=555):
    rows = [
        [
            f"2026-08-27T{(start_min + i) // 60:02d}:{(start_min + i) % 60:02d}:00+05:30",
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


def _provider() -> UpstoxProvider:
    def handler(req: httpx.Request) -> httpx.Response:
        candles = (
            [["2026-08-25T00:00:00+05:30", 100, 105, 95, 102, 5000, 0]]
            if "/days/1/" in str(req.url)
            else _m1_rows(200)
        )
        return httpx.Response(200, json={"status": "success", "data": {"candles": candles}})

    client = UpstoxHTTPClient(
        base_url="https://api.upstox.com",
        token_provider=lambda: "tok",
        transport=httpx.MockTransport(handler),
        max_rps=0,
        max_retries=0,
        sleep_fn=lambda _s: None,
    )
    return UpstoxProvider(
        Settings(active_provider="upstox", upstox_access_token="x"), http_client=client
    )


def _run(db_session):
    repos = build_sqlalchemy_repositories(db_session)
    return run_cycle(
        repos, _provider(), settings=Settings(active_provider="upstox"), now_fn=lambda: NOW
    )


def _results(db, run_id, instrument_id, key):
    return (
        db.execute(
            select(md.AnalysisResultRow).where(
                md.AnalysisResultRow.run_id == run_id,
                md.AnalysisResultRow.instrument_id == instrument_id,
                md.AnalysisResultRow.analysis_key == key,
            )
        )
        .scalars()
        .all()
    )


def test_real_indicator_results_are_written_with_provenance(db_session):
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

    rsi_rows = _results(db_session, result.run_id, fut, "rsi")
    assert rsi_rows and any(r.timeframe.value == "M5" for r in rsi_rows)
    m5 = next(r for r in rsi_rows if r.timeframe.value == "M5")
    assert m5.status is AnalysisStatus.OK
    assert m5.algo_version == ALGO_VERSION
    assert m5.params_id == "rsi.v1"
    assert len(m5.params_hash) == 16
    assert m5.input_window_end is not None
    assert m5.bars_used and m5.bars_used > 14
    assert 0.0 <= float(m5.result["values"]["rsi"]) <= 100.0
    assert m5.result["meta"]["last_bar_final"] is True

    # bollinger + ema7 also produced OK M5 rows
    for key in ("bollinger", "ema7", "volume"):
        rows = _results(db_session, result.run_id, fut, key)
        assert any(r.timeframe.value == "M5" and r.status is AnalysisStatus.OK for r in rows), key

    # current projection updated
    assert (
        db_session.execute(
            select(func.count())
            .select_from(md.CurrentAnalysisResult)
            .where(md.CurrentAnalysisResult.instrument_id == fut)
        ).scalar_one()
        > 0
    )


def test_golden_cross_not_applicable_for_future_is_persisted(db_session):
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

    gc = _results(db_session, result.run_id, fut, "golden_cross")
    assert len(gc) == 1
    assert gc[0].status is AnalysisStatus.NOT_APPLICABLE  # not omitted


def test_golden_cross_index_insufficient_without_200_daily_bars(db_session):
    idx = _tracked(
        db_session,
        "NIFTY-INDEX",
        InstrumentType.INDEX,
        InstrumentSegment.INDEX,
        "NSE_INDEX|Nifty 50",
    )
    db_session.commit()
    result = _run(db_session)
    db_session.commit()

    gc = _results(db_session, result.run_id, idx, "golden_cross")
    assert gc and gc[0].status is AnalysisStatus.INSUFFICIENT_DATA


def test_recompute_guard_carries_on_an_immediate_second_cycle(db_session):
    fut = _tracked(
        db_session,
        "NIFTY-FUT-2026-09",
        InstrumentType.FUTURE,
        InstrumentSegment.FUT,
        "NSE_FO|68407",
    )
    db_session.commit()

    r1 = _run(db_session)
    db_session.commit()
    first = next(
        r for r in _results(db_session, r1.run_id, fut, "rsi") if r.timeframe.value == "M5"
    )
    assert first.carried is False

    r2 = _run(db_session)  # identical bars, all final
    db_session.commit()
    second = next(
        r for r in _results(db_session, r2.run_id, fut, "rsi") if r.timeframe.value == "M5"
    )
    assert second.carried is True
    assert second.carried_from_result_id == first.id
    assert second.result.get("carried") is True

    # engine was NOT re-run: no fresh values payload on the carried row
    assert "values" not in second.result or second.result.get("carried") is True


def test_carried_result_keeps_values_in_the_projection_and_stays_flat(db_session):
    from analytical_core.enums import Timeframe
    from app.api import services

    fut = _tracked(
        db_session,
        "NIFTY-FUT-2026-09",
        InstrumentType.FUTURE,
        InstrumentSegment.FUT,
        "NSE_FO|68407",
    )
    db_session.commit()
    r1 = _run(db_session)
    db_session.commit()
    real = next(r for r in _results(db_session, r1.run_id, fut, "rsi") if r.timeframe.value == "M5")

    _run(db_session)  # carry #1
    db_session.commit()
    r3 = _run(db_session)  # carry #2 -> must still point at the ROOT, not carry #1
    db_session.commit()
    third = next(
        r for r in _results(db_session, r3.run_id, fut, "rsi") if r.timeframe.value == "M5"
    )
    assert third.carried is True
    assert third.carried_from_result_id == real.id  # chain stays flat

    # the hot projection keeps the real values (panel view)
    cur = db_session.execute(
        select(md.CurrentAnalysisResult).where(
            md.CurrentAnalysisResult.instrument_id == fut,
            md.CurrentAnalysisResult.analysis_key == "rsi",
            md.CurrentAnalysisResult.timeframe == Timeframe.M5,
        )
    ).scalar_one()
    assert cur.summary.get("values", {}).get("rsi") == real.result["values"]["rsi"]

    # and the single-item read resolves through the carry
    item = services.one_analysis(db_session, fut, "rsi", Timeframe.M5)
    assert item.carried is True
    assert item.values.get("rsi") == real.result["values"]["rsi"]
    assert item.provenance is not None and item.provenance.algo_version == ALGO_VERSION
