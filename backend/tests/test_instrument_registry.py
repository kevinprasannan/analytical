"""Phase 2.2 — canonical registry sync: idempotency, remapping, absent contracts,
underlying resolution, provider mapping, DB persistence (§5–§9, §11)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from analytical_core.enums import InstrumentSegment, InstrumentType, OptionType
from app.db.repositories.instrument_registry import (
    MemoryInstrumentRegistryRepository,
    SaInstrumentRegistryRepository,
)
from app.instruments.registry import sync_instruments
from app.providers.base import InstrumentRecord
from app.providers.upstox.instrument_master import records_from_master
from tests.conftest import UPSTOX_MASTER_DIR

BASE = UPSTOX_MASTER_DIR / "nse_master_sample.json"
REMAPPED = UPSTOX_MASTER_DIR / "nse_master_remapped.json"
EXPIRED = UPSTOX_MASTER_DIR / "nse_master_expired_subset.json"


def _sync_file(path, repo):
    records, norm_rej = records_from_master(path)
    return sync_instruments(records, provider="upstox", repo=repo, extra_rejections=norm_rej)


# ======================================================================================
# In-memory
# ======================================================================================


def test_sync_creates_registry_with_correct_underlyings():
    repo = MemoryInstrumentRegistryRepository()
    rep = _sync_file(BASE, repo)
    assert rep.created == 10 and rep.accepted == 11
    nifty_idx = repo.get_instrument_by_contract_key("NIFTY-INDEX")
    bank_idx = repo.get_instrument_by_contract_key("BANKNIFTY-INDEX")
    assert nifty_idx.instrument_type is InstrumentType.INDEX
    # derivative -> INDEX underlying_id
    nifty_fut = repo._inst[repo._by_ck["NIFTY-FUT-2026-09"]]
    assert nifty_fut["underlying_id"] == nifty_idx.id
    bank_opt = repo._inst[repo._by_ck["BANKNIFTY-OPT-2026-09-54000-CE"]]
    assert bank_opt["underlying_id"] == bank_idx.id
    # index rows have no underlying
    assert repo._inst[nifty_idx.id]["underlying_id"] is None


def test_sync_is_idempotent():
    repo = MemoryInstrumentRegistryRepository()
    _sync_file(BASE, repo)
    ids1 = dict(repo._by_ck)
    r2 = _sync_file(BASE, repo)
    assert dict(repo._by_ck) == ids1  # same canonical identities
    assert r2.created == 0 and r2.remapped == 0 and r2.updated == 0
    assert r2.unchanged == 10
    assert len(repo._maps) == 10  # no duplicate mappings


def test_provider_key_remapping_keeps_canonical_identity():
    repo = MemoryInstrumentRegistryRepository()
    _sync_file(BASE, repo)
    id_before = repo.get_instrument_by_contract_key("NIFTY-FUT-2026-09").id
    r = _sync_file(REMAPPED, repo)
    assert r.remapped == 1 and r.created == 0
    assert repo.get_instrument_by_contract_key("NIFTY-FUT-2026-09").id == id_before
    assert repo.get_instrument_id_by_provider_symbol("upstox", "NSE_FO|68407") is None
    assert repo.get_instrument_id_by_provider_symbol("upstox", "NSE_FO|99999") == id_before


def test_absent_contract_is_deactivated_not_deleted_then_reactivated():
    repo = MemoryInstrumentRegistryRepository()
    _sync_file(BASE, repo)
    oct_id = repo._by_ck["NIFTY-FUT-2026-10"]
    r = _sync_file(EXPIRED, repo)
    assert r.deactivated == 1
    assert oct_id in repo._inst  # retained
    assert repo._inst[oct_id]["is_active"] is False
    assert repo._maps[("upstox", oct_id)]["is_active"] is False
    # it comes back in the full master
    r2 = _sync_file(BASE, repo)
    assert repo._inst[oct_id]["is_active"] is True
    assert r2.updated == 1  # reactivation counts as an update


def test_unresolved_underlying_quarantined_no_fake_underlying():
    repo = MemoryInstrumentRegistryRepository()
    rep = _sync_file(BASE, repo)
    assert any(
        q.stage == "resolve" and "unresolved underlying" in q.reason for q in rep.quarantined
    )
    # the stock future was NOT persisted and no HDFCBANK underlying was invented
    assert repo.get_instrument_by_contract_key("HDFCBANK-FUT-2026-09") is None
    assert repo.get_instrument_by_contract_key("HDFCBANK-INDEX") is None


def test_weekly_null_row_quarantined():
    repo = MemoryInstrumentRegistryRepository()
    rep = _sync_file(BASE, repo)
    assert any("cannot classify expiry_kind" in q.reason for q in rep.quarantined)


def test_underlying_that_is_not_an_index_is_quarantined():
    records, _ = records_from_master(BASE)
    rogue = InstrumentRecord(
        provider="upstox",
        provider_symbol="NSE_FO|ROGUE",
        instrument_type=InstrumentType.OPTION,
        underlying_symbol="NIFTY",
        exchange="NSE",
        segment=InstrumentSegment.OPT,
        underlying_provider_key="NSE_FO|68407",  # -> the NIFTY FUTURE, not an index
        expiry_date=date(2026, 9, 4),
        weekly=True,
        option_type=OptionType.CE,
        strike_price=Decimal("77777"),
        lot_size=65,
        tick_size=Decimal("5"),
        trading_symbol="ROGUE",
    )
    repo = MemoryInstrumentRegistryRepository()
    rep = sync_instruments([*records, rogue], provider="upstox", repo=repo)
    assert any("is not an INDEX" in q.reason for q in rep.quarantined)
    assert repo.get_instrument_by_contract_key("NIFTY-OPT-2026-09-04-77777-CE") is None


def test_cross_sync_provider_symbol_collision_quarantined():
    repo = MemoryInstrumentRegistryRepository()
    _sync_file(BASE, repo)  # maps NSE_FO|68407 -> NIFTY-FUT-2026-09
    # a new contract that (wrongly) reuses an existing provider key
    clash = InstrumentRecord(
        provider="upstox",
        provider_symbol="NSE_FO|68407",
        instrument_type=InstrumentType.FUTURE,
        underlying_symbol="NIFTY",
        exchange="NSE",
        segment=InstrumentSegment.FUT,
        underlying_provider_key="NSE_INDEX|Nifty 50",
        expiry_date=date(2026, 11, 24),
        weekly=False,
        lot_size=65,
        tick_size=Decimal("10"),
        trading_symbol="NIFTY FUT NOV",
    )
    rep = sync_instruments([clash], provider="upstox", repo=repo)
    assert any("already mapped to instrument" in q.reason for q in rep.quarantined)
    assert repo.get_instrument_by_contract_key("NIFTY-FUT-2026-11") is None


def test_no_strike_ladder_invention():
    repo = MemoryInstrumentRegistryRepository()
    _sync_file(BASE, repo)
    option_ids = [
        i for i, row in repo._inst.items() if row["instrument_type"] is InstrumentType.OPTION
    ]
    assert len(option_ids) == 5  # exactly the CE/PE rows in the fixture, no extras


# ======================================================================================
# DB-backed
# ======================================================================================


@pytest.fixture()
def db_session(migrated_engine):
    from sqlalchemy.orm import Session

    with Session(migrated_engine) as s:
        yield s


@pytest.mark.db
def test_db_sync_persists_with_correct_fk(db_session):
    from sqlalchemy import select

    from app.db import models as md

    _sync_file(BASE, SaInstrumentRegistryRepository(db_session))
    db_session.commit()

    rows = db_session.execute(select(md.Instrument)).scalars().all()
    by_ck = {r.contract_key: r for r in rows}
    assert set(by_ck) == {
        "NIFTY-INDEX",
        "BANKNIFTY-INDEX",
        "NIFTY-FUT-2026-09",
        "NIFTY-FUT-2026-10",
        "BANKNIFTY-FUT-2026-09",
        "NIFTY-OPT-2026-09-04-24000-CE",
        "NIFTY-OPT-2026-09-04-24000-PE",
        "NIFTY-OPT-2026-09-04-24050-CE",
        "NIFTY-OPT-2026-09-24000-CE",
        "BANKNIFTY-OPT-2026-09-54000-CE",
    }
    assert by_ck["NIFTY-INDEX"].underlying_id is None
    assert by_ck["NIFTY-FUT-2026-09"].underlying_id == by_ck["NIFTY-INDEX"].id
    assert by_ck["BANKNIFTY-OPT-2026-09-54000-CE"].underlying_id == by_ck["BANKNIFTY-INDEX"].id
    assert by_ck["NIFTY-FUT-2026-09"].has_intraday_oi is True
    assert by_ck["NIFTY-INDEX"].has_intraday_oi is False
    assert all(r.is_tracked is False for r in rows)  # 2.2 tracks nothing

    maps = db_session.execute(select(md.ProviderInstrumentMap)).scalars().all()
    assert len(maps) == 10
    assert {mp.provider for mp in maps} == {"upstox"}


@pytest.mark.db
def test_db_idempotent_no_duplicates(db_session):
    from sqlalchemy import func, select

    from app.db import models as md

    _sync_file(BASE, SaInstrumentRegistryRepository(db_session))
    db_session.commit()
    n1 = db_session.execute(select(func.count()).select_from(md.Instrument)).scalar()
    r2 = _sync_file(BASE, SaInstrumentRegistryRepository(db_session))
    db_session.commit()
    n2 = db_session.execute(select(func.count()).select_from(md.Instrument)).scalar()
    assert n1 == n2 == 10
    assert r2.unchanged == 10 and r2.created == 0
    n_maps = db_session.execute(select(func.count()).select_from(md.ProviderInstrumentMap)).scalar()
    assert n_maps == 10


@pytest.mark.db
def test_db_remap_preserves_historical_market_data_identity(db_session):
    from sqlalchemy import select, text

    from app.db import models as md

    _sync_file(BASE, SaInstrumentRegistryRepository(db_session))
    db_session.commit()
    fut_id = db_session.execute(
        select(md.Instrument.id).where(md.Instrument.contract_key == "NIFTY-FUT-2026-09")
    ).scalar_one()
    # seed a historical bar for that instrument
    db_session.execute(
        text(
            "INSERT INTO ohlcv_bars (instrument_id,timeframe,ts,open,high,low,close,volume,"
            "provider,is_final) VALUES (:i,'M1',now(),1,1,1,1,0,'upstox',true)"
        ).bindparams(i=fut_id)
    )
    db_session.commit()

    _sync_file(REMAPPED, SaInstrumentRegistryRepository(db_session))
    db_session.commit()

    # canonical identity unchanged; provider_symbol updated; bar untouched
    assert (
        db_session.execute(
            select(md.Instrument.id).where(md.Instrument.contract_key == "NIFTY-FUT-2026-09")
        ).scalar_one()
        == fut_id
    )
    ps = db_session.execute(
        select(md.ProviderInstrumentMap.provider_symbol).where(
            md.ProviderInstrumentMap.instrument_id == fut_id
        )
    ).scalar_one()
    assert ps == "NSE_FO|99999"
    bar_iid = db_session.execute(
        select(md.OhlcvBar.instrument_id).where(md.OhlcvBar.provider == "upstox")
    ).scalar_one()
    assert bar_iid == fut_id


@pytest.mark.db
def test_db_absent_contract_retained_inactive(db_session):
    from sqlalchemy import select

    from app.db import models as md

    _sync_file(BASE, SaInstrumentRegistryRepository(db_session))
    db_session.commit()
    r = _sync_file(EXPIRED, SaInstrumentRegistryRepository(db_session))
    db_session.commit()
    assert r.deactivated == 1
    row = db_session.execute(
        select(md.Instrument).where(md.Instrument.contract_key == "NIFTY-FUT-2026-10")
    ).scalar_one()
    assert row.is_active is False
    mp = db_session.execute(
        select(md.ProviderInstrumentMap).where(md.ProviderInstrumentMap.instrument_id == row.id)
    ).scalar_one()
    assert mp.is_active is False


@pytest.mark.db
def test_db_transaction_rolls_back_on_error(db_session, monkeypatch):
    from sqlalchemy import func, select

    from app.db import models as md

    calls = {"n": 0}
    real = SaInstrumentRegistryRepository.upsert_provider_map

    def boom(self, *a, **k):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("simulated infra failure")
        return real(self, *a, **k)

    monkeypatch.setattr(SaInstrumentRegistryRepository, "upsert_provider_map", boom)
    with pytest.raises(RuntimeError):
        _sync_file(BASE, SaInstrumentRegistryRepository(db_session))
        db_session.commit()
    db_session.rollback()
    assert db_session.execute(select(func.count()).select_from(md.Instrument)).scalar() == 0
