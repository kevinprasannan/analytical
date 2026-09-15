"""Explicit (fictional) capabilities of the stub provider.

These are declared, not inferred. They are NOT Upstox's capabilities — see the
``notes`` field. Phase-1 code branches on this object exactly as it would on a
real provider's ``capabilities()``.
"""

from __future__ import annotations

from analytical_core.enums import Timeframe
from app.providers.capabilities import OIMode, ProviderCapabilities

STUB_CAPABILITIES = ProviderCapabilities(
    provider="stub",
    auth_kind="static-token",
    supports_instrument_master=True,
    native_timeframes=frozenset(
        {Timeframe.M1, Timeframe.M5, Timeframe.M15, Timeframe.H1, Timeframe.D1}
    ),
    aggregatable_from=Timeframe.M1,
    oi_mode=OIMode.SNAPSHOT,
    max_history_days={"D1": 400, "H1": 400, "M15": 400, "M5": 180, "M1": 10},
    rate_limit_per_sec=10,
    notes="SYNTHETIC PHASE-1 STUB — capabilities are fictional and are NOT Upstox's.",
)
