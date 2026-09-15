"""Upstox adapter.

Phase 2.1: authentication seam + capabilities (``UpstoxProvider``,
``UpstoxAuthProvider``). Data fetch (instrument master, candles, OI) is added in
Phases 2.2–2.3. Construction still runs the provider-validation gate as
defense-in-depth (``gate.assert_gate_clear``).
"""

from app.providers.upstox.auth import UpstoxAuthProvider
from app.providers.upstox.provider import UpstoxProvider

__all__ = ["UpstoxAuthProvider", "UpstoxProvider"]
