"""The ``run-completed`` hook point (docs/02 §3.7).

A process-local registry of callables invoked once per cycle, after the run is
finalised. V1 ships a single structured-log sink; the alert seam (docs/10) is a
future subscriber that registers here without touching the cycle body.

A hook must never break a cycle: :func:`fire_run_completed` isolates each call.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:  # avoid a runtime import cycle with cycle.py
    from app.worker.cycle import CycleResult

_LOG = structlog.get_logger("worker.hooks")

RunCompletedHook = Callable[["CycleResult"], None]

_HOOKS: list[RunCompletedHook] = []


def register_run_completed(hook: RunCompletedHook) -> RunCompletedHook:
    """Register a ``run-completed`` subscriber. Returns ``hook`` (usable as a decorator)."""
    if hook not in _HOOKS:
        _HOOKS.append(hook)
    return hook


def unregister_run_completed(hook: RunCompletedHook) -> None:
    if hook in _HOOKS:
        _HOOKS.remove(hook)


def registered_hooks() -> tuple[RunCompletedHook, ...]:
    return tuple(_HOOKS)


def fire_run_completed(result: CycleResult) -> None:
    for hook in tuple(_HOOKS):
        try:
            hook(result)
        except Exception as exc:  # pragma: no cover - defensive; a hook must not break a cycle
            name = getattr(hook, "__name__", repr(hook))
            _LOG.error("run-completed hook raised", hook=name, error=repr(exc))


def default_log_sink(result: CycleResult) -> None:
    """The always-on sink: one structured line summarising the finished cycle."""
    _LOG.info(
        "run-completed",
        run_id=result.run_id,
        cycle_seq=result.cycle_seq,
        status=result.status.value,
        crashed=result.crashed,
        phases={p.value: po.status.value for p, po in result.phases.items()},
    )


register_run_completed(default_log_sink)
