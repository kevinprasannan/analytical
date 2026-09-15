"""``UpstoxProvider`` — the real provider adapter.

Delivered so far:
  * Phase 2.1 — authentication seam + capabilities.
  * Phase 2.2 — ``fetch_instrument_master`` (local file, no network).
  * Phase 2.3 — ``fetch_ohlcv`` / ``fetch_oi_series`` for **M1 + D1** via the
    Upstox v3 historical candle endpoint. M5/M15/H1 are aggregated from M1
    (docs/11 PV-2) and raise ``ProviderUnavailableCapabilityError`` here.

Still stubbed:
  * ``fetch_oi_snapshot``  -> branch-B fallback only (docs/11 PV-4), not V1.

Construction re-runs the provider-validation gate as defense-in-depth: if a
blocking PV row is ever re-opened, the adapter refuses to exist
(``ProviderValidationGateError``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

from analytical_core.enums import ProviderAuthState, Timeframe
from app.config import Settings, get_settings
from app.providers.base import (
    FullQuote,
    InstrumentRecord,
    LtpQuote,
    OhlcQuote,
    OHLCVBar,
    OIPoint,
    OISnapshot,
    OptionGreekQuote,
    ProviderUnavailableCapabilityError,
)
from app.providers.capabilities import ProviderCapabilities
from app.providers.upstox import candles, quotes
from app.providers.upstox.auth import UpstoxAuthProvider
from app.providers.upstox.capabilities import UPSTOX_CAPABILITIES
from app.providers.upstox.gate import assert_gate_clear
from app.providers.upstox.http import UpstoxHTTPClient


class UpstoxProvider:
    provider_id = "upstox"

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        http_client: UpstoxHTTPClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        assert_gate_clear()  # defense-in-depth (docs/02 §3.2)
        self._auth = UpstoxAuthProvider(self._settings)
        self._http_client = http_client  # injected in tests; built lazily otherwise

    # --- auth (Phase 2.1) ------------------------------------------
    def auth_state(self) -> ProviderAuthState:
        return self._auth.auth_state()

    def ensure_authenticated(self) -> None:
        self._auth.ensure_authenticated()

    # --- capability reporting (Phase 2.1) ----------------------
    def capabilities(self) -> ProviderCapabilities:
        return UPSTOX_CAPABILITIES

    # --- instrument master (Phase 2.2 — local file only, no network) -----
    def fetch_instrument_master(self) -> Sequence[InstrumentRecord]:
        path = self._settings.upstox_instrument_master_file
        if not path:
            raise ProviderUnavailableCapabilityError(
                "upstox_instrument_master_file is not configured; Phase 2.2 reads a "
                "local Upstox NSE master file (no automatic download)."
            )
        from app.providers.upstox.instrument_master import records_from_master

        records, _rejected = records_from_master(path)
        return records

    # --- candles / OI (Phase 2.3 — M1 + D1) --------------------------
    @property
    def _source(self) -> str:
        return f"upstox:{self._settings.upstox_api_version}/historical-candle"

    def _client(self) -> UpstoxHTTPClient:
        if self._http_client is None:
            self._http_client = UpstoxHTTPClient(
                base_url=self._settings.upstox_base_url,
                token_provider=self._auth.access_token,
                timeout=self._settings.provider_http_timeout_seconds,
                max_retries=self._settings.provider_max_retries,
                backoff_base=self._settings.provider_backoff_base_seconds,
                max_rps=self._settings.provider_max_rps,
            )
        return self._http_client

    def fetch_ohlcv(
        self, provider_symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> Sequence[OHLCVBar]:
        self.ensure_authenticated()
        return candles.fetch_candles(
            self._client(),
            instrument_key=provider_symbol,
            timeframe=timeframe,
            start=start,
            end=end,
            api_version=self._settings.upstox_api_version,
            is_bar_close=self._settings.upstox_candle_ts_is_bar_close,
            source=self._source,
        )

    def fetch_oi_series(
        self, provider_symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> Sequence[OIPoint]:
        self.ensure_authenticated()
        return candles.fetch_oi_points(
            self._client(),
            instrument_key=provider_symbol,
            timeframe=timeframe,
            start=start,
            end=end,
            api_version=self._settings.upstox_api_version,
            is_bar_close=self._settings.upstox_candle_ts_is_bar_close,
            source=self._source,
        )

    def fetch_oi_snapshot(self, provider_symbols: Sequence[str]) -> Mapping[str, OISnapshot]:
        raise NotImplementedError(
            "UpstoxProvider.fetch_oi_snapshot is the docs/11 PV-4 branch-B fallback "
            "(oi_mode=SNAPSHOT) and is not part of V1 (branch A_PER_CANDLE is active)."
        )

    # --- realtime quotes (docs/07 §4.10) -----------------------------
    @property
    def _quote_source(self) -> str:
        return f"upstox:{self._settings.upstox_api_version}/market-quote"

    def fetch_ltp(self, provider_symbols: Sequence[str]) -> Mapping[str, LtpQuote]:
        self.ensure_authenticated()
        return quotes.fetch_ltp(self._client(), provider_symbols, source=self._quote_source)

    def fetch_ohlc(
        self, provider_symbols: Sequence[str], *, interval: str = "1d"
    ) -> Mapping[str, OhlcQuote]:
        self.ensure_authenticated()
        return quotes.fetch_ohlc(
            self._client(), provider_symbols, interval=interval, source=self._quote_source
        )

    def fetch_full_quote(self, provider_symbols: Sequence[str]) -> Mapping[str, FullQuote]:
        self.ensure_authenticated()
        return quotes.fetch_full_quote(self._client(), provider_symbols, source=self._quote_source)

    def fetch_option_greeks(
        self, provider_symbols: Sequence[str]
    ) -> Mapping[str, OptionGreekQuote]:
        self.ensure_authenticated()
        return quotes.fetch_option_greeks(
            self._client(), provider_symbols, source=self._quote_source
        )

    def __repr__(self) -> str:
        return f"UpstoxProvider(auth={self._auth!r})"
