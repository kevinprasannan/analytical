"""Resolve the single active provider from settings (docs/02 §3.2).

  * ``stub``   -> ``StubProvider`` (deterministic, synthetic; the default; also
                  the docs/09 ``MockProvider`` role)
  * ``upstox`` -> ``UpstoxProvider`` (real adapter). Phase 2.1 provides auth +
                  capabilities; data-fetch methods raise ``NotImplementedError``
                  until Phases 2.2–2.3. Construction re-runs the PV gate.

A documented "preferred source order" exists in the design but has exactly one
entry in V1 (review M18).
"""

from __future__ import annotations

from app.config import Settings, get_settings
from app.providers.base import MarketDataProvider
from app.providers.stub import StubProvider

_KNOWN = ("stub", "upstox")


def get_provider(settings: Settings | None = None) -> MarketDataProvider:
    settings = settings or get_settings()
    name = settings.active_provider
    if name == "stub":
        return StubProvider()  # type: ignore[return-value]
    if name == "upstox":
        from app.providers.upstox import UpstoxProvider

        return UpstoxProvider(settings)  # type: ignore[return-value]
    raise ValueError(f"unknown ACTIVE_PROVIDER {name!r}; known: {_KNOWN}")
