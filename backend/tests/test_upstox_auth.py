"""Phase 2.1 — Upstox authentication seam (docs/11 PV-1).

Covers: token store round-trip + perms; auth_state OK/EXPIRED/UNKNOWN with the
03:30 IST daily-expiry rule; ensure_authenticated raises ProviderAuthError; the
token never appears in repr/str/logs; UpstoxProvider construction + capabilities;
registry wiring; and the worker degrades to SKIPPED (not crash) with no token.
"""

from __future__ import annotations

import json
import os
import stat
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
import structlog

from analytical_core.enums import (
    InstrumentPhaseOutcome,
    InstrumentType,
    ProviderAuthState,
    RunPhase,
    RunStatus,
    Timeframe,
)
from app.config import Settings
from app.db.repositories.memory import build_memory_repositories
from app.db.repositories.protocols import InstrumentView
from app.providers.base import (
    MarketDataProvider,
    ProviderAuthError,
    ProviderUnavailableCapabilityError,
)
from app.providers.capabilities import OIMode
from app.providers.upstox import UpstoxAuthProvider, UpstoxProvider, token_store
from app.providers.upstox.auth import _daily_expiry_after
from app.worker.cycle import run_cycle

IST = ZoneInfo("Asia/Kolkata")
SECRET = "tok_SUPER_SECRET_do_not_log_1234567890"


def _settings(tmp_path, *, env_token: str | None = None) -> Settings:
    return Settings(
        active_provider="upstox",
        upstox_token_file=str(tmp_path / ".secrets" / "upstox_token.json"),
        upstox_access_token=env_token,
    )


# --- token store ------------------------------------------------------


def test_token_store_round_trip_and_perms(tmp_path):
    path = tmp_path / ".secrets" / "t.json"
    stored = token_store.save(path, SECRET)
    assert path.is_file()
    loaded = token_store.load(path)
    assert loaded is not None
    assert loaded.access_token == SECRET
    assert loaded.issued_at.tzinfo is not None
    assert abs((loaded.issued_at - stored.issued_at).total_seconds()) < 2
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert token_store.clear(path) is True
    assert token_store.load(path) is None


def test_token_store_rejects_empty(tmp_path):
    with pytest.raises(ValueError):
        token_store.save(tmp_path / "t.json", "   ")


def test_token_store_ignores_corrupt_file(tmp_path):
    p = tmp_path / "t.json"
    p.write_text("{not json", encoding="utf-8")
    assert token_store.load(p) is None


def test_stored_token_repr_hides_secret(tmp_path):
    stored = token_store.save(tmp_path / "t.json", SECRET)
    assert SECRET not in repr(stored)
    assert "***" in repr(stored)


# --- daily-expiry rule (PV-1) ---------------------------------------


@pytest.mark.parametrize(
    ("issued", "expected_expiry"),
    [
        # issued 8 PM Tue -> expires 3:30 AM Wed
        ((2026, 3, 3, 20, 0), (2026, 3, 4, 3, 30)),
        # issued 2:30 AM Wed -> still expires 3:30 AM the SAME Wed
        ((2026, 3, 4, 2, 30), (2026, 3, 4, 3, 30)),
        # issued 4:00 AM Wed -> expires 3:30 AM Thu
        ((2026, 3, 4, 4, 0), (2026, 3, 5, 3, 30)),
        # issued exactly 3:30 -> next day (>= boundary)
        ((2026, 3, 4, 3, 30), (2026, 3, 5, 3, 30)),
    ],
)
def test_daily_expiry_after(issued, expected_expiry):
    got = _daily_expiry_after(datetime(*issued, tzinfo=IST))
    assert got == datetime(*expected_expiry, tzinfo=IST)


# --- UpstoxAuthProvider --------------------------------------------


def test_auth_state_unknown_without_token(tmp_path):
    auth = UpstoxAuthProvider(_settings(tmp_path))
    assert auth.auth_state() is ProviderAuthState.UNKNOWN
    with pytest.raises(ProviderAuthError):
        auth.ensure_authenticated()


def test_auth_state_ok_with_fresh_file_token(tmp_path):
    s = _settings(tmp_path)
    token_store.save(s.upstox_token_file, SECRET)
    auth = UpstoxAuthProvider(s)
    assert auth.auth_state() is ProviderAuthState.OK
    auth.ensure_authenticated()  # no raise
    assert auth.access_token() == SECRET


def test_auth_state_expired_after_daily_boundary(tmp_path):
    s = _settings(tmp_path)
    issued = datetime(2026, 3, 3, 20, 0, tzinfo=IST)
    token_store.save(s.upstox_token_file, SECRET, issued_at=issued)
    auth = UpstoxAuthProvider(s)
    # before boundary -> OK
    assert auth.auth_state(now=datetime(2026, 3, 4, 3, 0, tzinfo=IST)) is ProviderAuthState.OK
    # after 03:30 IST -> EXPIRED
    assert auth.auth_state(now=datetime(2026, 3, 4, 3, 31, tzinfo=IST)) is ProviderAuthState.EXPIRED
    assert auth.expires_at() == datetime(2026, 3, 4, 3, 30, tzinfo=IST)


def test_env_token_takes_precedence_and_is_ok(tmp_path):
    auth = UpstoxAuthProvider(_settings(tmp_path, env_token="env_tok_value_abc"))
    assert auth.auth_state() is ProviderAuthState.OK
    assert auth.access_token() == "env_tok_value_abc"
    assert auth.expires_at() is None  # env token has no issue time


def test_auth_repr_and_str_never_leak_token(tmp_path):
    s = _settings(tmp_path)
    token_store.save(s.upstox_token_file, SECRET)
    auth = UpstoxAuthProvider(s)
    assert SECRET not in repr(auth)
    assert SECRET not in str(auth)
    assert SECRET not in repr(s)  # SecretStr in Settings
    assert SECRET not in str(s)


def test_token_never_written_to_logs(tmp_path):
    cap = structlog.testing.LogCapture()
    structlog.configure(processors=[cap], cache_logger_on_first_use=False)
    try:
        s = _settings(tmp_path)
        token_store.save(s.upstox_token_file, SECRET)
        auth = UpstoxAuthProvider(s)
        auth.ensure_authenticated()
        _ = auth.access_token()
        _ = auth.auth_state()
        blob = json.dumps(cap.entries)
        assert SECRET not in blob
    finally:
        structlog.reset_defaults()


# --- UpstoxProvider + registry -----------------------------------


def test_upstox_provider_constructs_and_reports_capabilities(tmp_path):
    p = UpstoxProvider(_settings(tmp_path))
    caps = p.capabilities()
    assert caps.provider == "upstox"
    assert caps.oi_mode is OIMode.PER_TIMEFRAME
    assert {tf.value for tf in caps.native_timeframes} == {"M1", "D1"}
    assert caps.requests_per_30min == 2000
    assert caps.auth_kind == "oauth-daily-manual"
    assert isinstance(p, MarketDataProvider)


def test_upstox_provider_auth_delegates(tmp_path):
    s = _settings(tmp_path)
    p = UpstoxProvider(s)
    assert p.auth_state() is ProviderAuthState.UNKNOWN
    with pytest.raises(ProviderAuthError):
        p.ensure_authenticated()
    token_store.save(s.upstox_token_file, SECRET)
    assert UpstoxProvider(s).auth_state() is ProviderAuthState.OK


def test_upstox_candle_methods_require_auth(tmp_path):
    # Phase 2.3: fetch_ohlcv / fetch_oi_series are implemented; with no token they
    # fail the auth gate before any HTTP (detailed behaviour: test_upstox_candles).
    p = UpstoxProvider(_settings(tmp_path))
    now = datetime.now(tz=IST)
    with pytest.raises(ProviderAuthError):
        p.fetch_ohlcv("X", Timeframe.M1, now, now)
    with pytest.raises(ProviderAuthError):
        p.fetch_oi_series("X", Timeframe.M1, now, now)


def test_upstox_oi_snapshot_stays_not_implemented(tmp_path):
    # branch-B fallback only (docs/11 PV-4); branch A_PER_CANDLE is active in V1.
    with pytest.raises(NotImplementedError):
        UpstoxProvider(_settings(tmp_path)).fetch_oi_snapshot(["X"])


def test_upstox_instrument_master_requires_configured_file(tmp_path):
    # Phase 2.2: no automatic download; an unconfigured master file is a
    # capability error, not a silent empty result.
    p = UpstoxProvider(_settings(tmp_path))
    with pytest.raises(ProviderUnavailableCapabilityError):
        p.fetch_instrument_master()


def test_upstox_instrument_master_reads_configured_fixture(tmp_path):
    from tests.conftest import UPSTOX_MASTER_DIR

    s = _settings(tmp_path)
    s = s.model_copy(
        update={"upstox_instrument_master_file": str(UPSTOX_MASTER_DIR / "nse_master_sample.json")}
    )
    records = UpstoxProvider(s).fetch_instrument_master()
    assert records and all(r.provider == "upstox" for r in records)


def test_upstox_provider_repr_hides_token(tmp_path):
    s = _settings(tmp_path)
    token_store.save(s.upstox_token_file, SECRET)
    assert SECRET not in repr(UpstoxProvider(s))


def test_registry_returns_upstox_provider(tmp_path):
    from app.providers.registry import get_provider

    p = get_provider(_settings(tmp_path))
    assert isinstance(p, UpstoxProvider)


# --- worker degrades (no crash) with no token --------------------


def test_worker_cycle_skips_all_instruments_without_a_token(tmp_path):
    instruments = [InstrumentView(1, "K", InstrumentType.INDEX, True, False, "SYM")]
    repos, store = build_memory_repositories(instruments)
    provider = UpstoxProvider(_settings(tmp_path))  # no token

    result = run_cycle(repos, provider)

    assert result.crashed is False
    assert result.status is RunStatus.PARTIAL
    ingest = store.phase_status[(result.run_id, RunPhase.INGEST)]
    assert ingest["status"].value == "SKIPPED"
    assert store.instrument_status[(result.run_id, 1, RunPhase.INGEST)]["outcome"] is (
        InstrumentPhaseOutcome.SKIPPED
    )
    assert store.results == [] and store.scores == []
