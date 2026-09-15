"""Scheduler loop — job config, session gate, single-flight skip, error isolation
(docs/02 §3.7)."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, date, datetime, time, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from analytical_core.enums import RunTrigger
from app.config import Settings
from app.db import models as m
from app.worker import scheduler as sched
from app.worker.calendar_gate import GateDecision, evaluate_gate

# 09:15 IST = 03:45 UTC ; 15:30 IST = 10:00 UTC
MID_SESSION = datetime(2026, 8, 27, 6, 30, tzinfo=UTC)  # 12:00 IST


class _Row:
    def __init__(self, *, trading=True, o=time(9, 15), c=time(15, 30)):
        self.is_trading_day = trading
        self.session_open_ist = o
        self.session_close_ist = c


class _FakeSession:
    def __init__(self, row):
        self._row = row

    def execute(self, *_a, **_k):
        return SimpleNamespace(scalar_one_or_none=lambda: self._row)


@contextmanager
def _fake_scope(*_a, **_k):
    yield object()


# --------------------------------------------------------------------------- gate


def test_gate_open_mid_session():
    d = evaluate_gate(_FakeSession(_Row()), MID_SESSION, Settings())
    assert d.should_run and d.reason == "session live"


def test_gate_closed_before_warmup():
    s = Settings(scheduler_warmup_seconds=300)
    # 03:40 UTC = 09:10 IST, 5 min before open, warmup window starts 03:40 -> still closed at 03:39
    d = evaluate_gate(_FakeSession(_Row()), datetime(2026, 8, 27, 3, 39, tzinfo=UTC), s)
    assert not d.should_run and "warmup" in d.reason


def test_gate_open_inside_warmup():
    s = Settings(scheduler_warmup_seconds=600)
    d = evaluate_gate(_FakeSession(_Row()), datetime(2026, 8, 27, 3, 40, tzinfo=UTC), s)
    assert d.should_run


def test_gate_open_inside_cooldown_then_closed_after():
    s = Settings(scheduler_cooldown_seconds=300)
    inside = evaluate_gate(_FakeSession(_Row()), datetime(2026, 8, 27, 10, 3, tzinfo=UTC), s)
    after = evaluate_gate(_FakeSession(_Row()), datetime(2026, 8, 27, 10, 6, tzinfo=UTC), s)
    assert inside.should_run
    assert not after.should_run and "cooldown" in after.reason


def test_gate_closed_on_holiday_and_missing_row():
    assert not evaluate_gate(_FakeSession(_Row(trading=False)), MID_SESSION, Settings()).should_run
    assert not evaluate_gate(_FakeSession(None), MID_SESSION, Settings()).should_run


def test_gate_disabled_always_runs():
    s = Settings(scheduler_session_only=False)
    d = evaluate_gate(_FakeSession(None), MID_SESSION, s)
    assert d.should_run and "disabled" in d.reason


# ----------------------------------------------------------------- build_scheduler


def test_build_scheduler_job_is_single_flight():
    scheduler = sched.build_scheduler(lambda: None, Settings(cycle_interval_seconds=90))
    job = scheduler.get_job("analytical-cycle")
    assert job.max_instances == 1
    assert job.coalesce is True
    assert job.trigger.interval == timedelta(seconds=90)


def test_astro_catchup_job_present_by_default_and_toggleable():
    on = sched.build_scheduler(
        lambda: None, Settings(astro_daily_catchup=True, astro_catchup_interval_seconds=1234)
    )
    job = on.get_job("analytical-astro-catchup")
    assert job is not None and job.coalesce is True
    assert job.trigger.interval == timedelta(seconds=1234)

    off = sched.build_scheduler(lambda: None, Settings(astro_daily_catchup=False))
    assert off.get_job("analytical-astro-catchup") is None


def test_universe_roll_and_backup_jobs_present_by_default_and_toggleable():
    on = sched.build_scheduler(
        lambda: None,
        Settings(
            universe_daily_roll=True,
            universe_roll_interval_seconds=4321,
            db_backup_enabled=True,
            db_backup_interval_seconds=9999,
        ),
    )
    roll = on.get_job("analytical-universe-roll")
    assert roll is not None and roll.coalesce is True
    assert roll.trigger.interval == timedelta(seconds=4321)
    bkp = on.get_job("analytical-db-backup")
    assert bkp is not None and bkp.trigger.interval == timedelta(seconds=9999)

    off = sched.build_scheduler(
        lambda: None, Settings(universe_daily_roll=False, db_backup_enabled=False)
    )
    assert off.get_job("analytical-universe-roll") is None
    assert off.get_job("analytical-db-backup") is None


def test_tick_skips_when_gate_closed(monkeypatch):
    monkeypatch.setattr(sched, "session_scope", _fake_scope)
    monkeypatch.setattr(sched, "evaluate_gate", lambda *a, **k: GateDecision(False, "holiday"))
    called: list[int] = []
    monkeypatch.setattr("app.worker.cycle.run_cycle", lambda *a, **k: called.append(1))
    sched.run_scheduled_cycle(Settings())
    assert not called


def test_tick_runs_cycle_with_scheduled_trigger_and_app_settings(monkeypatch):
    monkeypatch.setattr(sched, "session_scope", _fake_scope)
    monkeypatch.setattr(sched, "evaluate_gate", lambda *a, **k: GateDecision(True, "session live"))

    @contextmanager
    def _ctx(_settings):
        yield ("repos", "provider", {"scoring.min_confidence": 0.5})

    monkeypatch.setattr("app.worker.deps.worker_context", _ctx)
    seen: dict = {}

    def _run_cycle(repos, provider, *, trigger, settings, app_settings):
        seen.update(repos=repos, trigger=trigger, app_settings=app_settings)
        return SimpleNamespace(run_id=7, cycle_seq=7, status=SimpleNamespace(value="SUCCEEDED"))

    monkeypatch.setattr("app.worker.cycle.run_cycle", _run_cycle)
    sched.run_scheduled_cycle(Settings())
    assert seen["trigger"] is RunTrigger.SCHEDULED
    assert seen["app_settings"] == {"scoring.min_confidence": 0.5}


def test_tick_swallows_single_flight_busy(monkeypatch):
    monkeypatch.setattr(sched, "session_scope", _fake_scope)
    monkeypatch.setattr(sched, "evaluate_gate", lambda *a, **k: GateDecision(True, "live"))
    from app.worker.deps import SingleFlightBusy

    @contextmanager
    def _ctx(_settings):
        raise SingleFlightBusy("busy")
        yield  # pragma: no cover

    monkeypatch.setattr("app.worker.deps.worker_context", _ctx)
    sched.run_scheduled_cycle(Settings())  # must not raise


def test_tick_never_raises_on_unexpected_error(monkeypatch):
    def _boom(*_a, **_k):
        raise RuntimeError("db down")

    monkeypatch.setattr(sched, "session_scope", _boom)
    sched.run_scheduled_cycle(Settings())  # must not raise


# --------------------------------------------------------------------------- DB


@pytest.mark.db
def test_evaluate_gate_against_seeded_calendar(migrated_engine):
    with Session(migrated_engine) as db:
        db.add(
            m.MarketCalendar(
                exchange="NSE",
                segment="FO",
                calendar_date=date(2026, 8, 27),
                is_trading_day=True,
                session_open_ist=time(9, 15),
                session_close_ist=time(15, 30),
                session_type="NORMAL",
            )
        )
        db.commit()
        s = Settings()
        assert evaluate_gate(db, MID_SESSION, s).should_run
        assert not evaluate_gate(db, datetime(2026, 8, 27, 2, 0, tzinfo=UTC), s).should_run
        # a date with no row
        assert not evaluate_gate(db, datetime(2026, 8, 28, 6, 30, tzinfo=UTC), s).should_run
