"""Provider protocols, DTOs and exceptions (docs/02 §3.2, task E/F).

Separated capability areas:
  * authentication            -> ``AuthProvider``
  * instrument master         -> ``InstrumentMasterProvider``
  * historical market data    -> ``HistoricalMarketDataProvider``
  * open interest             -> ``OpenInterestProvider``
  * capability reporting      -> ``CapabilityReportingProvider``

``MarketDataProvider`` is the structural union of all five.

Every data DTO carries a ``source`` string. A stub/synthetic provider MUST set
``source="STUB_FIXTURE"`` and callers MUST NOT treat such rows as real market
data (task E, docs/09 §2.5 "no fabricated bars/data").
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

from analytical_core.enums import (
    InstrumentSegment,
    InstrumentType,
    OptionType,
    ProviderAuthState,
    Timeframe,
)
from app.providers.capabilities import ProviderCapabilities

# --------------------------------------------------------------------------------------
# Exceptions
# --------------------------------------------------------------------------------------


class ProviderError(Exception):
    """Base class for all provider-layer failures."""


class ProviderAuthError(ProviderError):
    """Authentication is missing, expired, or rejected. -> instrument SKIPPED."""


class ProviderRateLimitError(ProviderError):
    """Provider throttled the request. -> instrument DEGRADED, retried next cycle."""


class ProviderUnavailableCapabilityError(ProviderError):
    """A capability the caller asked for is not offered by this provider."""


class ProviderValidationGateError(ProviderError):
    """A provider refused to operate because the docs/11 PV gate is not cleared."""


class InsufficientProviderDataError(ProviderError):
    """Provider legitimately has no / not enough data for the request window."""


# --------------------------------------------------------------------------------------
# DTOs (provider-neutral shapes; normalisation to canonical rows is Phase 2)
# --------------------------------------------------------------------------------------

STUB_SOURCE = "STUB_FIXTURE"


@dataclass(frozen=True, slots=True)
class InstrumentRecord:
    """One normalised row of a provider instrument master (provider-neutral).

    The provider adapter maps its raw master rows onto this shape; the
    ``app/instruments`` layer validates and turns accepted records into canonical
    ``instruments`` + ``provider_instrument_map`` rows.
    """

    provider: str
    provider_symbol: str  # the provider's stable-per-cycle instrument key/token
    instrument_type: InstrumentType
    underlying_symbol: str | None  # short token, e.g. "NIFTY" (None for INDEX)
    exchange: str
    expiry_date: date | None = None
    strike_price: Decimal | None = None
    option_type: OptionType | None = None
    lot_size: int | None = None
    tick_size: Decimal | None = None
    display_name: str | None = None
    #: provider segment as reported (e.g. Upstox "NSE_FO"), mapped to the
    #: canonical enum during validation.
    segment: InstrumentSegment | None = None
    #: the provider's key for the *underlying* (e.g. Upstox "NSE_INDEX|Nifty 50");
    #: used to resolve ``underlying_id`` via ``provider_instrument_map``.
    underlying_provider_key: str | None = None
    #: the provider's authoritative weekly-vs-monthly flag (docs/11 PV-6). ``None``
    #: on a derivative row is unclassifiable and is quarantined (not guessed).
    weekly: bool | None = None
    #: the provider's human-readable trading symbol / display name.
    trading_symbol: str | None = None
    name: str | None = None
    source: str = ""
    raw: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OHLCVBar:
    ts: datetime  # bar-open, tz-aware UTC (docs/03 §2)
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    is_final: bool
    source: str
    #: per-candle Open Interest (docs/11 PV-4 branch A — v3 candle element 7).
    #: ``None`` when the provider row carries no OI (e.g. an INDEX candle, or a
    #: 6-element row). Never fabricated or zero-filled at parse time.
    open_interest: int | None = None


@dataclass(frozen=True, slots=True)
class OIPoint:
    ts: datetime  # bar-open, tz-aware UTC (branch A)
    oi: int
    provider_oi_change: int | None
    source: str


@dataclass(frozen=True, slots=True)
class StreamTick:
    """One decoded message from a streaming market-data feed (docs/02 §3.4).

    Provider-shaped (`provider_symbol`); the streamer maps it to an instrument
    and hands it to the pure ``analytical_core.streaming`` M1 builder.
    """

    provider_symbol: str
    ts: datetime  # tz-aware; exchange time
    ltp: float
    cum_volume: int  # cumulative session traded volume
    oi: int | None = None


@dataclass(frozen=True, slots=True)
class OISnapshot:
    snapshot_ts: datetime  # poll instant, tz-aware UTC (branch B)
    oi: int
    provider_oi_change: int | None
    day_volume: int | None
    instrument_price: Decimal | None
    source: str


# --------------------------------------------------------------------------------------
# Realtime quote DTOs (docs/07 §4.10) — REST snapshots, read-only. Never an input
# to the deterministic engine; the engine runs on ``ohlcv_bars`` (decision 13).
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OhlcBucket:
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int | None
    ts: datetime | None  # candle-start


@dataclass(frozen=True, slots=True)
class LtpQuote:
    provider_symbol: str
    last_price: Decimal
    last_qty: int | None
    day_volume: int | None
    prev_close: Decimal | None
    source: str


@dataclass(frozen=True, slots=True)
class OhlcQuote:
    provider_symbol: str
    last_price: Decimal | None
    live: OhlcBucket | None
    prev: OhlcBucket | None
    source: str


@dataclass(frozen=True, slots=True)
class FullQuote:
    provider_symbol: str
    last_price: Decimal | None
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    day_volume: int | None
    average_price: Decimal | None
    oi: int | None
    net_change: Decimal | None
    total_buy_qty: int | None
    total_sell_qty: int | None
    lower_circuit: Decimal | None
    upper_circuit: Decimal | None
    ts: datetime | None
    source: str


@dataclass(frozen=True, slots=True)
class OptionGreekQuote:
    provider_symbol: str
    last_price: Decimal | None
    iv: float | None  # annualised fraction
    delta: float | None
    gamma: float | None
    theta: float | None
    vega: float | None
    oi: int | None
    day_volume: int | None
    source: str


# --------------------------------------------------------------------------------------
# Protocols
# --------------------------------------------------------------------------------------


@runtime_checkable
class AuthProvider(Protocol):
    def auth_state(self) -> ProviderAuthState: ...

    def ensure_authenticated(self) -> None:
        """Raise :class:`ProviderAuthError` unless the auth state is OK."""


@runtime_checkable
class InstrumentMasterProvider(Protocol):
    def fetch_instrument_master(self) -> Sequence[InstrumentRecord]: ...


@runtime_checkable
class HistoricalMarketDataProvider(Protocol):
    def fetch_ohlcv(
        self,
        provider_symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> Sequence[OHLCVBar]: ...


@runtime_checkable
class OpenInterestProvider(Protocol):
    def fetch_oi_snapshot(self, provider_symbols: Sequence[str]) -> Mapping[str, OISnapshot]: ...

    def fetch_oi_series(
        self,
        provider_symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> Sequence[OIPoint]: ...


@runtime_checkable
class CapabilityReportingProvider(Protocol):
    def capabilities(self) -> ProviderCapabilities: ...


@runtime_checkable
class RealtimeQuoteProvider(Protocol):
    """REST snapshot quotes (docs/07 §4.10). Read-only — never an engine input.
    Every method returns a map keyed by ``provider_symbol``; symbols the provider
    has no quote for are simply absent."""

    def fetch_ltp(self, provider_symbols: Sequence[str]) -> Mapping[str, LtpQuote]: ...

    def fetch_ohlc(
        self, provider_symbols: Sequence[str], *, interval: str = "1d"
    ) -> Mapping[str, OhlcQuote]: ...

    def fetch_full_quote(self, provider_symbols: Sequence[str]) -> Mapping[str, FullQuote]: ...

    def fetch_option_greeks(
        self, provider_symbols: Sequence[str]
    ) -> Mapping[str, OptionGreekQuote]: ...


@runtime_checkable
class StreamingMarketDataProvider(Protocol):
    """A push feed for the forming M1 bar + live OI (docs/02 §3.4). Optional —
    not part of :class:`MarketDataProvider`; a streamer wires it separately."""

    def subscribe(
        self, provider_symbols: Sequence[str], *, mode: str = "full"
    ) -> Iterator[StreamTick]:
        """Blocking iterator of ticks; ends on :meth:`close` or feed close."""

    def close(self) -> None: ...


@runtime_checkable
class MarketDataProvider(
    AuthProvider,
    InstrumentMasterProvider,
    HistoricalMarketDataProvider,
    OpenInterestProvider,
    CapabilityReportingProvider,
    RealtimeQuoteProvider,
    Protocol,
):
    """Structural union of every provider capability area."""


PROVIDER_PROTOCOLS: tuple[type, ...] = (
    AuthProvider,
    InstrumentMasterProvider,
    HistoricalMarketDataProvider,
    OpenInterestProvider,
    CapabilityReportingProvider,
    RealtimeQuoteProvider,
    MarketDataProvider,
)
