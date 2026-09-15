"""run-completed hook registry (docs/02 §3.7)."""

from __future__ import annotations

import pytest

from app.db.repositories.memory import build_memory_repositories
from app.providers.stub import StubBehavior, StubProvider
from app.worker import hooks
from app.worker.cycle import run_cycle


@pytest.fixture(autouse=True)
def _isolate_registry():
    saved = hooks.registered_hooks()
    yield
    for h in hooks.registered_hooks():
        hooks.unregister_run_completed(h)
    for h in saved:
        hooks.register_run_completed(h)


def test_default_log_sink_is_registered():
    assert hooks.default_log_sink in hooks.registered_hooks()


def test_register_is_idempotent_and_returns_the_hook():
    calls: list = []

    def sink(result):
        calls.append(result)

    assert hooks.register_run_completed(sink) is sink
    hooks.register_run_completed(sink)
    assert hooks.registered_hooks().count(sink) == 1


def test_fire_invokes_hooks_and_isolates_a_raising_one():
    seen: list = []
    hooks.register_run_completed(lambda r: (_ for _ in ()).throw(RuntimeError("boom")))
    hooks.register_run_completed(lambda r: seen.append(r))
    hooks.fire_run_completed(object())  # must not raise
    assert len(seen) == 1


def test_run_cycle_fires_registered_hooks(sample_instruments):
    repos, _store = build_memory_repositories(sample_instruments)
    got: list = []
    hooks.register_run_completed(lambda r: got.append(r))

    result = run_cycle(repos, StubProvider(StubBehavior()))

    assert len(got) == 1
    assert got[0].run_id == result.run_id
    assert got[0].status is result.status
