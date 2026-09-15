"""``StubProvider`` — deterministic provider implementing every protocol.

Behaviour is configured up-front via ``StubBehavior`` so tests can exercise:
  * success
  * insufficient / no data           -> empty result, never a fabricated bar
  * unavailable capability           -> ProviderUnavailableCapabilityError
  * authentication failure           -> ProviderAuthError (worker -> SKIPPED)
  * rate limit / transient error     -> ProviderRateLimitError / ProviderError
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from analytical_core.enums import ProviderAuthState, Timeframe
from app.providers.base import (
    FullQuote,
    InstrumentRecord,
    LtpQuote,
    OhlcBucket,
    OhlcQuote,
    OHLCVBar,
    OIPoint,
    OISnapshot,
    OptionGreekQuote,
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
    ProviderUnavailableCapabilityError,
)
from app.providers.capabilities import ProviderCapabilities
from app.providers.stub import fixtures
from app.providers.stub.capabilities import STUB_CAPABILITIES


@dataclass(frozen=True, slots=True)
class StubBehavior:
    auth_state: ProviderAuthState = ProviderAuthState.OK
    empty_symbols: frozenset[str] = frozenset()  # return [] (no data) — NOT an error
    rate_limited_symbols: frozenset[str] = frozenset()
    error_symbols: frozenset[str] = frozenset()
    unavailable_capabilities: frozenset[str] = frozenset()  # e.g. {"oi_series"}
    capabilities: ProviderCapabilities = STUB_CAPABILITIES
    ohlcv_count: int = 12


class StubProvider:
    provider_id = "stub"

    def __init__(self, behavior: StubBehavior | None = None) -> None:
        self.behavior = behavior or StubBehavior()

    # --- auth ----------------------------------------------------------
    def auth_state(self) -> ProviderAuthState:
        return self.behavior.auth_state

    def ensure_authenticated(self) -> None:
        if self.behavior.auth_state is not ProviderAuthState.OK:
            raise ProviderAuthError(f"stub auth state is {self.behavior.auth_state.value}")

    # --- capability reporting ---------------------------------------
    def capabilities(self) -> ProviderCapabilities:
        return self.behavior.capabilities

    # --- instrument master ----------------------------------------
    def fetch_instrument_master(self) -> Sequence[InstrumentRecord]:
        self.ensure_authenticated()
        return fixtures.STUB_INSTRUMENTS

    # --- historical market data --------------------------------
    def fetch_ohlcv(
        self,
        provider_symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> Sequence[OHLCVBar]:
        self.ensure_authenticated()
        self._maybe_fail(provider_symbol)
        if provider_symbol in self.behavior.empty_symbols:
            return []  # no data — caller must NOT fabricate anything
        return fixtures.stub_ohlcv(
            provider_symbol, timeframe, start, end, count=self.behavior.ohlcv_count
        )

    # --- open interest ------------------------------------------
    def fetch_oi_snapshot(self, provider_symbols: Sequence[str]) -> Mapping[str, OISnapshot]:
        self.ensure_authenticated()
        if "oi_snapshot" in self.behavior.unavailable_capabilities:
            raise ProviderUnavailableCapabilityError("stub: oi_snapshot not offered")
        now = datetime.now(tz=UTC)
        out: dict[str, OISnapshot] = {}
        for sym in provider_symbols:
            self._maybe_fail(sym)
            if sym in self.behavior.empty_symbols:
                continue
            out[sym] = fixtures.stub_oi_snapshot(sym, now)
        return out

    def fetch_oi_series(
        self,
        provider_symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> Sequence[OIPoint]:
        self.ensure_authenticated()
        if "oi_series" in self.behavior.unavailable_capabilities:
            raise ProviderUnavailableCapabilityError("stub: per-candle OI (oi_series) not offered")
        self._maybe_fail(provider_symbol)
        if provider_symbol in self.behavior.empty_symbols:
            return []
        bars = fixtures.stub_ohlcv(
            provider_symbol, timeframe, start, end, count=self.behavior.ohlcv_count
        )
        return [
            OIPoint(ts=b.ts, oi=10_000 + i, provider_oi_change=None, source=b.source)
            for i, b in enumerate(bars)
        ]

    # --- realtime quotes (deterministic) ---------------------------
    @staticmethod
    def _base_price(symbol: str) -> Decimal:
        return Decimal(100 + (abs(hash(symbol)) % 9000))

    def fetch_ltp(self, provider_symbols: Sequence[str]) -> Mapping[str, LtpQuote]:
        self.ensure_authenticated()
        out: dict[str, LtpQuote] = {}
        for s in provider_symbols:
            if s in self.behavior.empty_symbols:
                continue
            self._maybe_fail(s)
            p = self._base_price(s)
            out[s] = LtpQuote(
                provider_symbol=s,
                last_price=p,
                last_qty=50,
                day_volume=100_000,
                prev_close=p - 1,
                source="STUB_FIXTURE",
            )
        return out

    def fetch_ohlc(
        self, provider_symbols: Sequence[str], *, interval: str = "1d"
    ) -> Mapping[str, OhlcQuote]:
        self.ensure_authenticated()
        out: dict[str, OhlcQuote] = {}
        for s in provider_symbols:
            if s in self.behavior.empty_symbols:
                continue
            self._maybe_fail(s)
            p = self._base_price(s)
            live = OhlcBucket(open=p, high=p + 5, low=p - 5, close=p + 1, volume=100_000, ts=None)
            out[s] = OhlcQuote(
                provider_symbol=s, last_price=p + 1, live=live, prev=None, source="STUB_FIXTURE"
            )
        return out

    def fetch_full_quote(self, provider_symbols: Sequence[str]) -> Mapping[str, FullQuote]:
        self.ensure_authenticated()
        out: dict[str, FullQuote] = {}
        for s in provider_symbols:
            if s in self.behavior.empty_symbols:
                continue
            self._maybe_fail(s)
            p = self._base_price(s)
            out[s] = FullQuote(
                provider_symbol=s,
                last_price=p + 1,
                open=p,
                high=p + 5,
                low=p - 5,
                close=p + 1,
                day_volume=100_000,
                average_price=p,
                oi=(25_000 if any(t in s for t in ("OPT", "FUT", "CE", "PE")) else None),
                net_change=Decimal(1),
                total_buy_qty=1000,
                total_sell_qty=900,
                lower_circuit=p * Decimal("0.9"),
                upper_circuit=p * Decimal("1.1"),
                ts=None,
                source="STUB_FIXTURE",
            )
        return out

    def fetch_option_greeks(
        self, provider_symbols: Sequence[str]
    ) -> Mapping[str, OptionGreekQuote]:
        self.ensure_authenticated()
        out: dict[str, OptionGreekQuote] = {}
        for s in provider_symbols:
            if s in self.behavior.empty_symbols:
                continue
            self._maybe_fail(s)
            out[s] = OptionGreekQuote(
                provider_symbol=s,
                last_price=self._base_price(s) + 1,
                iv=0.15,
                delta=0.5,
                gamma=0.01,
                theta=-0.4,
                vega=0.2,
                oi=25_000,
                day_volume=50_000,
                source="STUB_FIXTURE",
            )
        return out

    # --- internals ---------------------------------------------
    def _maybe_fail(self, symbol: str) -> None:
        if symbol in self.behavior.rate_limited_symbols:
            raise ProviderRateLimitError(f"stub: rate limited for {symbol}")
        if symbol in self.behavior.error_symbols:
            raise ProviderError(f"stub: transient error for {symbol}")
