"""``GET /instruments/{underlying_id}/option-chain`` (docs/07 §4.4) — end to end
on PostgreSQL: a seeded NIFTY index + a few CE/PE strikes, one cycle, then the
chain assembled on read."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from analytical_core.enums import (
    ExpiryKind,
    InstrumentSegment,
    InstrumentType,
    OptionType,
)
from app.api.deps import get_db
from app.api.main import create_app
from app.config import Settings, get_settings
from app.db import models as md
from app.db.repositories.sqlalchemy import build_sqlalchemy_repositories
from app.providers.upstox import UpstoxProvider
from app.providers.upstox.http import UpstoxHTTPClient
from app.worker.cycle import run_cycle

pytestmark = pytest.mark.db

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
EXPIRY = date(2026, 9, 29)


def _m1(n, base):
    rows = [
        [
            f"2026-08-27T{(555 + i) // 60:02d}:{(555 + i) % 60:02d}:00+05:30",
            base + (i % 5),
            base + 4 + (i % 5),
            base - 2 + (i % 5),
            base + (i % 3),
            10 + i,
            50000 + 20 * i,
        ]
        for i in range(n)
    ]
    rows.reverse()
    return rows


def _provider():
    def handler(req):
        u = str(req.url)
        base = 24100 if "Nifty%2050" in u or "Nifty 50" in u else (150 if "CE" in u else 130)
        c = (
            [["2026-08-25T00:00:00+05:30", base, base + 50, base - 50, base + 10, 5000, 40000]]
            if "/days/1/" in u
            else _m1(200, base)
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


@pytest.fixture()
def client(migrated_engine, monkeypatch):
    monkeypatch.setenv("ANALYTICAL_ACTIVE_PROVIDER", "upstox")
    get_settings.cache_clear()
    with Session(migrated_engine) as seed:
        idx = md.Instrument(
            contract_key="NIFTY-INDEX",
            symbol="NIFTY",
            segment=InstrumentSegment.INDEX,
            instrument_type=InstrumentType.INDEX,
            is_tracked=True,
        )
        seed.add(idx)
        seed.flush()
        seed.add(
            md.ProviderInstrumentMap(
                instrument_id=idx.id,
                provider="upstox",
                provider_symbol="NSE_INDEX|Nifty 50",
                is_active=True,
            )
        )
        for strike in (24000, 24100, 24200):
            for ot in ("CE", "PE"):
                o = md.Instrument(
                    contract_key=f"NIFTY-{strike}-{ot}-2026-09",
                    symbol="NIFTY",
                    segment=InstrumentSegment.OPT,
                    instrument_type=InstrumentType.OPTION,
                    is_tracked=True,
                    underlying_id=idx.id,
                    expiry_date=EXPIRY,
                    expiry_kind=ExpiryKind.MONTHLY,
                    strike_price=Decimal(strike),
                    option_type=OptionType(ot),
                )
                seed.add(o)
                seed.flush()
                seed.add(
                    md.ProviderInstrumentMap(
                        instrument_id=o.id,
                        provider="upstox",
                        provider_symbol=f"NSE_FO|{strike}{ot}",
                        is_active=True,
                    )
                )
        seed.commit()
        idx_id = idx.id
        run_cycle(
            build_sqlalchemy_repositories(seed),
            _provider(),
            settings=Settings(active_provider="upstox"),
            now_fn=lambda: NOW,
        )
        seed.commit()

    app = create_app()

    def _override():
        s = Session(migrated_engine)
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _override
    c = TestClient(app)
    c.idx_id = idx_id
    yield c
    get_settings.cache_clear()


def test_option_chain_assembled_from_ingested_data(client):
    r = client.get(f"/api/v1/instruments/{client.idx_id}/option-chain")
    assert r.status_code == 200, r.text
    ch = r.json()
    assert ch["underlying_symbol"] == "NIFTY"
    assert ch["expiry"] == "2026-09-29"
    assert ch["expiries"] == ["2026-09-29"]
    assert ch["spot"] > 0
    assert ch["algo_version"].startswith("3.")
    assert [row["strike"] for row in ch["rows"]] == [24000.0, 24100.0, 24200.0]
    assert ch["atm_strike"] in (24000.0, 24100.0, 24200.0)
    assert ch["total_call_oi"] > 0 and ch["total_put_oi"] > 0
    assert ch["pcr_oi"] is not None and ch["max_pain_strike"] in (24000.0, 24100.0, 24200.0)

    mid = next(row for row in ch["rows"] if row["strike"] == 24100.0)
    assert mid["call"] is not None and mid["put"] is not None
    assert mid["call"]["ltp"] is not None and mid["call"]["oi"] is not None
    # premiums are well inside the no-arb band -> IV + greeks solve
    assert mid["call"]["iv"] is not None and 0.0 < mid["call"]["delta"] < 1.0
    assert mid["put"]["iv"] is not None and mid["put"]["delta"] < 0.0


def test_unknown_expiry_is_404(client):
    r = client.get(f"/api/v1/instruments/{client.idx_id}/option-chain?expiry=2099-01-01")
    assert r.status_code == 404


def test_non_underlying_instrument_has_no_chain(client):
    # the index has options; a strike itself has none -> 404
    opt = client.get("/api/v1/instruments?instrument_type=OPTION&limit=1").json()["items"][0]
    r = client.get(f"/api/v1/instruments/{opt['id']}/option-chain")
    assert r.status_code == 404
