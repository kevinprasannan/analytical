"""Phase 2.5 — thread-safe provider request budget (docs/02 §6.7)."""

from __future__ import annotations

import threading

import pytest

from app.ingestion.budget import RequestBudget


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0
        self.slept: list[float] = []

    def time(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.slept.append(s)
        self.t += s


def test_rps_spacing_is_enforced():
    clk = FakeClock()
    b = RequestBudget(max_rps=4.0, per_30min=0, time_fn=clk.time, sleep_fn=clk.sleep)  # 0.25s apart
    b.acquire()  # free
    b.acquire()  # waits 0.25
    clk.t += 0.10
    b.acquire()  # 0.10 elapsed -> waits 0.15
    assert clk.slept == [pytest.approx(0.25), pytest.approx(0.15)]
    assert b.granted == 3


def test_30min_quota_blocks_until_oldest_falls_out_of_window():
    clk = FakeClock()
    b = RequestBudget(
        max_rps=0, per_30min=3, window_seconds=1800, time_fn=clk.time, sleep_fn=clk.sleep
    )
    for _ in range(3):
        b.acquire()
    assert clk.slept == []
    b.acquire()  # 4th must wait until the 1st (t=0) leaves the 1800s window
    assert clk.slept == [pytest.approx(1800.0)]
    assert b.granted == 4


def test_quota_window_slides():
    clk = FakeClock()
    b = RequestBudget(
        max_rps=0, per_30min=2, window_seconds=100, time_fn=clk.time, sleep_fn=clk.sleep
    )
    b.acquire()  # t=0
    clk.t = 60
    b.acquire()  # t=60
    b.acquire()  # waits until t=100 (first leaves), then granted
    assert clk.slept == [pytest.approx(40.0)]


def test_disabled_when_both_limits_zero():
    b = RequestBudget(max_rps=0, per_30min=0, sleep_fn=lambda _s: pytest.fail("should not sleep"))
    for _ in range(50):
        b.acquire()
    assert b.granted == 50


def test_thread_safe_grant_count():
    # real clock, tiny spacing; many threads hammering acquire()
    b = RequestBudget(max_rps=2000.0, per_30min=0)
    n = 200

    def worker() -> None:
        for _ in range(10):
            b.acquire()

    threads = [threading.Thread(target=worker) for _ in range(n // 10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert b.granted == n


def test_snapshot_reports_progress():
    b = RequestBudget(max_rps=0, per_30min=1800)
    for _ in range(5):
        b.acquire()
    snap = b.snapshot()
    assert snap["granted"] == 5 and snap["in_window"] == 5 and snap["budget_30min"] == 1800
