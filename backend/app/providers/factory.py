"""Build a live provider adapter wired for real HTTP (Phase 2.5 / 2.6).

For ``upstox`` this attaches an ``UpstoxHTTPClient`` whose rate limiting can be a
shared thread-safe :class:`~app.ingestion.budget.RequestBudget` (needed when a
backfill or the live INGEST phase fetches several instruments concurrently,
docs/02 §6.7). For ``stub`` it just returns the registry default.

Returns ``(provider, close)`` — call ``close()`` when done to release the HTTP
connection pool.
"""

from __future__ import annotations

from collections.abc import Callable

from app.config import Settings, get_settings
from app.providers.base import MarketDataProvider, StreamingMarketDataProvider


def build_live_provider(
    settings: Settings | None = None,
    *,
    budget=None,
) -> tuple[MarketDataProvider, Callable[[], None]]:
    settings = settings or get_settings()
    if settings.active_provider == "upstox":
        from app.providers.upstox import UpstoxProvider
        from app.providers.upstox.auth import UpstoxAuthProvider
        from app.providers.upstox.http import UpstoxHTTPClient

        auth = UpstoxAuthProvider(settings)
        client = UpstoxHTTPClient(
            base_url=settings.upstox_base_url,
            token_provider=auth.access_token,
            timeout=settings.provider_http_timeout_seconds,
            max_retries=settings.provider_max_retries,
            backoff_base=settings.provider_backoff_base_seconds,
            max_rps=settings.provider_max_rps,
            limiter=budget,
        )
        return UpstoxProvider(settings, http_client=client), client.close  # type: ignore[return-value]

    from app.providers.registry import get_provider

    return get_provider(settings), (lambda: None)


def build_streaming_provider(
    settings: Settings | None = None,
) -> tuple[StreamingMarketDataProvider, Callable[[], None]]:
    """The push feed for the streaming ingestor (docs/02 §3.4, Phase S).

    Returns ``(feed, close)``. ``upstox`` uses the real Market Data Feed v3
    WebSocket (Phase S3, docs/11 §5); it carries its own ``stream_enabled``
    guard. Any other provider gets the deterministic ``StubMarketFeed``.
    """
    settings = settings or get_settings()
    if settings.active_provider == "upstox":
        from app.providers.upstox.feed import UpstoxMarketFeed

        feed = UpstoxMarketFeed(settings)
        return feed, feed.close

    from app.providers.stub.feed import StubMarketFeed

    feed = StubMarketFeed()
    return feed, feed.close
