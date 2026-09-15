"""Phase 2.6 — INGEST persistence through a full ``run_cycle`` against PostgreSQL."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from analytical_core.enums import (
    InstrumentPhaseOutcome,
    InstrumentSegment,
    InstrumentType,
    RunPhase,
    RunStatus,
    Timeframe,
)
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


def _tracked(db: Session, ck: str, itype: InstrumentType, seg: InstrumentSegment, psym: str) -> int:
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
            100,
            101,
            99,
            100 + i,
            10,
            54000 + i,
        ]
        for i in range(n)
    ]
    rows.reverse()
    return rows


def _upstox(err_symbol: str | None = None) -> UpstoxProvider:
    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        if err_symbol and err_symbol in url:
            return httpx.Response(500, text="boom")
        candles = (
            [["2026-08-27T00:00:00+05:30", 1, 1, 1, 1, 9, 0]] if "/days/1/" in url else _m1_rows(45)
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


def _run(db_session, provider):
    repos = build_sqlalchemy_repositories(db_session)
    return run_cycle(
        repos,
        provider,
        settings=Settings(active_provider="upstox"),
        now_fn=lambda: NOW,
    )


def test_full_cycle_persists_ingested_bars_and_run_model(db_session):
    fut = _tracked(
        db_session,
        "NIFTY-FUT-2026-09",
        InstrumentType.FUTURE,
        InstrumentSegment.FUT,
        "NSE_FO|68407",
    )
    idx = _tracked(
        db_session,
        "NIFTY-INDEX",
        InstrumentType.INDEX,
        InstrumentSegment.INDEX,
        "NSE_INDEX|Nifty 50",
    )
    db_session.commit()

    result = _run(db_session, _upstox())
    db_session.commit()

    # --- run model ------------------------------------------------------
    assert db_session.execute(select(func.count()).select_from(md.AnalysisRun)).scalar_one() == 1
    phases = set(
        db_session.execute(
            select(md.RunPhaseStatus.phase).where(md.RunPhaseStatus.run_id == result.run_id)
        ).scalars()
    )
    assert phases == {RunPhase.INGEST, RunPhase.ANALYZE, RunPhase.SCORE}
    inst_status = db_session.execute(
        select(md.RunInstrumentStatus.instrument_id, md.RunInstrumentStatus.phase).where(
            md.RunInstrumentStatus.run_id == result.run_id
        )
    ).all()
    assert (fut, RunPhase.INGEST) in inst_status and (idx, RunPhase.INGEST) in inst_status

    # --- INGEST actually wrote market data ---------------------------
    by_tf = dict(
        db_session.execute(
            select(md.OhlcvBar.timeframe, func.count())
            .where(md.OhlcvBar.instrument_id == fut)
            .group_by(md.OhlcvBar.timeframe)
        ).all()
    )
    assert by_tf[Timeframe.M1] == 45
    assert by_tf[Timeframe.M5] == 9 and by_tf[Timeframe.M15] == 3 and by_tf[Timeframe.H1] == 1
    assert by_tf[Timeframe.D1] == 1
    assert (
        db_session.execute(
            select(func.count())
            .select_from(md.OpenInterest)
            .where(md.OpenInterest.instrument_id == fut)
        ).scalar_one()
        == 45
    )
    assert (
        db_session.execute(
            select(func.count())
            .select_from(md.OpenInterest)
            .where(md.OpenInterest.instrument_id == idx)
        ).scalar_one()
        == 0
    )
    assert (
        db_session.execute(select(func.count()).select_from(md.IngestionWatermark)).scalar_one() > 0
    )

    # --- placeholder ANALYZE / SCORE still ran under the one run -----
    assert all(
        r == result.run_id
        for r in db_session.execute(select(md.AnalysisResultRow.run_id)).scalars()
    )
    assert (
        db_session.execute(select(func.count()).select_from(md.CurrentSignalScore)).scalar_one() > 0
    )


def test_second_cycle_adds_no_duplicate_bars(db_session):
    _tracked(
        db_session,
        "NIFTY-FUT-2026-09",
        InstrumentType.FUTURE,
        InstrumentSegment.FUT,
        "NSE_FO|68407",
    )
    db_session.commit()
    _run(db_session, _upstox())
    db_session.commit()
    n1 = db_session.execute(select(func.count()).select_from(md.OhlcvBar)).scalar_one()

    _run(db_session, _upstox())
    db_session.commit()
    n2 = db_session.execute(select(func.count()).select_from(md.OhlcvBar)).scalar_one()
    assert n1 == n2 > 0
    assert db_session.execute(select(func.count()).select_from(md.AnalysisRun)).scalar_one() == 2


def test_partial_ingest_failure_degrades_the_run_not_crashes(db_session):
    ok = _tracked(
        db_session,
        "NIFTY-FUT-2026-09",
        InstrumentType.FUTURE,
        InstrumentSegment.FUT,
        "NSE_FO|68407",
    )
    bad = _tracked(
        db_session,
        "BANKNIFTY-FUT-2026-09",
        InstrumentType.FUTURE,
        InstrumentSegment.FUT,
        "NSE_FO|99999",
    )
    db_session.commit()

    result = _run(db_session, _upstox(err_symbol="99999"))
    db_session.commit()

    assert result.crashed is False
    assert result.status is RunStatus.PARTIAL
    outcomes = dict(
        db_session.execute(
            select(md.RunInstrumentStatus.instrument_id, md.RunInstrumentStatus.outcome).where(
                md.RunInstrumentStatus.run_id == result.run_id,
                md.RunInstrumentStatus.phase == RunPhase.INGEST,
            )
        ).all()
    )
    assert outcomes[bad] is InstrumentPhaseOutcome.ERROR
    assert outcomes[ok] is InstrumentPhaseOutcome.OK
    # the good instrument still got bars; the bad one did not
    assert (
        db_session.execute(
            select(func.count()).select_from(md.OhlcvBar).where(md.OhlcvBar.instrument_id == ok)
        ).scalar_one()
        > 0
    )
    assert (
        db_session.execute(
            select(func.count()).select_from(md.OhlcvBar).where(md.OhlcvBar.instrument_id == bad)
        ).scalar_one()
        == 0
    )


# ======================================================================================
# single-flight advisory lock
# ======================================================================================


def test_worker_context_is_single_flight(db_session, db_url):
    from sqlalchemy import create_engine as _ce

    from app.db.session import reset_engine
    from app.worker.deps import CYCLE_ADVISORY_LOCK_KEY, SingleFlightBusy, worker_context

    holder_engine = _ce(db_url, future=True)
    holder = holder_engine.connect()
    assert holder.execute(select(func.pg_try_advisory_lock(CYCLE_ADVISORY_LOCK_KEY))).scalar_one()
    try:
        reset_engine()
        settings = Settings(database_url=db_url, active_provider="stub")
        with pytest.raises(SingleFlightBusy):
            with worker_context(settings):
                pass  # pragma: no cover
    finally:
        holder.execute(select(func.pg_advisory_unlock(CYCLE_ADVISORY_LOCK_KEY)))
        holder.close()
        holder_engine.dispose()
        reset_engine()


def test_worker_context_releases_the_lock_after_use(db_session, db_url):
    from app.db.session import reset_engine
    from app.worker.deps import CYCLE_ADVISORY_LOCK_KEY, worker_context

    reset_engine()
    settings = Settings(database_url=db_url, active_provider="stub")
    with worker_context(settings):
        pass
    reset_engine()

    probe_engine = create_engine(db_url, future=True)
    with probe_engine.connect() as c:
        # lock is free again -> a fresh connection can take it
        assert c.execute(select(func.pg_try_advisory_lock(CYCLE_ADVISORY_LOCK_KEY))).scalar_one()
        c.execute(select(func.pg_advisory_unlock(CYCLE_ADVISORY_LOCK_KEY)))
    probe_engine.dispose()
