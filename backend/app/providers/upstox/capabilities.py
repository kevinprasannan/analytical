"""Upstox provider capabilities — populated strictly from CONFIRMED docs/11 §4.

Every value here traces to the Phase 1.5 validation evidence (2026-08-27):
  * PV-2 → M5/M15/H1 are NOT listed as native; they are aggregated from M1
    (``AGGREGATE_FROM_M1``). D1 is native. So ``native_timeframes = {M1, D1}``.
  * PV-3 → daily from Jan 2000 (1 decade/request); minutes 1-15 from Jan 2022
    (1 month/request); >15min & hours from Jan 2022 (1 quarter/request).
  * PV-4 → per-candle OI (candle element 7): ``oi_mode = PER_TIMEFRAME``.
  * PV-5 → 50 req/s, 500 req/min, 2000 req/30min ("Other Standard APIs").
  * PV-1 → OAuth 2.0 authorization-code, daily 03:30 IST expiry, no refresh
    token: ``auth_kind = "oauth-daily-manual"``.
"""

from __future__ import annotations

from datetime import date

from analytical_core.enums import Timeframe
from app.providers.capabilities import OIMode, ProviderCapabilities

_SINCE_2022 = date(2022, 1, 1)

UPSTOX_CAPABILITIES = ProviderCapabilities(
    provider="upstox",
    auth_kind="oauth-daily-manual",
    supports_instrument_master=True,
    # M5/M15/H1 are deliberately excluded so resolve_timeframe_plan forces
    # aggregation from M1 (docs/11 PV-2: H1 session-anchoring is undocumented).
    native_timeframes=frozenset({Timeframe.M1, Timeframe.D1}),
    aggregatable_from=Timeframe.M1,
    oi_mode=OIMode.PER_TIMEFRAME,
    rate_limit_per_sec=50,
    requests_per_minute=500,
    requests_per_30min=2000,
    historical_since={
        Timeframe.D1.value: date(2000, 1, 1),
        Timeframe.H1.value: _SINCE_2022,
        Timeframe.M15.value: _SINCE_2022,
        Timeframe.M5.value: _SINCE_2022,
        Timeframe.M1.value: _SINCE_2022,
    },
    max_range_days={
        Timeframe.D1.value: 3650,  # 1 decade / request
        Timeframe.H1.value: 92,  # 1 quarter / request
        Timeframe.M15.value: 92,
        Timeframe.M5.value: 31,  # 1 month / request
        # Upstox 400s on ~29-31d M1 windows for 2022-era history; 25 is safe for
        # the full 2022->now backfill (observed 2026-08-30 deep backfill).
        Timeframe.M1.value: 25,
    },
    notes=(
        "Upstox v3. Values CONFIRMED in docs/11 §4 (2026-08-27). "
        "M5/M15/H1 aggregated from M1 (PV-2). OI = candle element 7 (PV-4 branch A). "
        "Daily-manual access token, 03:30 IST expiry, no refresh token (PV-1). "
        "Current trading day comes from the intraday candle endpoint, prior days "
        "from historical (PV-2, 2026-08-31)."
    ),
)


def capabilities() -> ProviderCapabilities:
    return UPSTOX_CAPABILITIES
