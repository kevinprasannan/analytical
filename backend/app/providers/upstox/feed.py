"""``UpstoxMarketFeed`` — the real streaming feed (Phase S3, docs/11 §5).

Authorises the Upstox **Market Data Feed v3** WebSocket, subscribes to a set of
instrument keys in ``full`` mode, decodes the protobuf frames
(``MarketDataFeed.proto`` v3 -> ``MarketDataFeed_pb2``) and yields
:class:`~app.providers.base.StreamTick` — LTP + cumulative session volume + OI —
for the pure ``analytical_core.streaming`` M1 builder.

Bounded scope (decision 3 / §3b): this supplies only the forming M1 bar + live
OI. History / backfill / disconnect gap-fill stay on the REST cycle. Carries its
own ``stream_enabled`` guard (decision 3.1).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime

from app.config import Settings, get_settings
from app.providers.base import ProviderError, StreamTick
from app.providers.upstox import MarketDataFeed_pb2 as pb
from app.providers.upstox.auth import UpstoxAuthProvider
from app.providers.upstox.http import UpstoxHTTPClient

_AUTHORIZE_PATH = "/v3/feed/market-data-feed/authorize"
_MODES = {"ltpc", "full", "option_greeks", "full_d30"}


class UpstoxStreamError(ProviderError):
    """The Upstox market-data-feed WebSocket could not be established or decoded."""


def _to_tick(key: str, feed, current_ts: int) -> StreamTick | None:
    """One ``Feed`` -> a StreamTick, or ``None`` if it carries no usable LTP."""
    which = feed.WhichOneof("FeedUnion")
    ltpc = None
    vtt = 0
    oi: int | None = None
    if which == "ltpc":
        ltpc = feed.ltpc
    elif which == "firstLevelWithGreeks":
        g = feed.firstLevelWithGreeks
        ltpc, vtt, oi = g.ltpc, g.vtt, (int(g.oi) if g.oi else None)
    elif which == "fullFeed":
        inner = feed.fullFeed.WhichOneof("FullFeedUnion")
        if inner == "marketFF":
            m = feed.fullFeed.marketFF
            ltpc, vtt, oi = m.ltpc, m.vtt, (int(m.oi) if m.oi else None)
        elif inner == "indexFF":
            ltpc = feed.fullFeed.indexFF.ltpc  # index: no volume / OI
    if ltpc is None or not ltpc.ltp:
        return None
    ltt = ltpc.ltt or current_ts
    ts = datetime.fromtimestamp(ltt / 1000.0, tz=UTC) if ltt else datetime.now(tz=UTC)
    return StreamTick(
        provider_symbol=key,
        ts=ts,
        ltp=float(ltpc.ltp),
        cum_volume=int(vtt or 0),
        oi=oi,
    )


class UpstoxMarketFeed:
    provider_id = "upstox"

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        http_client: UpstoxHTTPClient | None = None,
        connect_fn=None,
    ) -> None:
        self._settings = settings or get_settings()
        self._auth = UpstoxAuthProvider(self._settings)
        self._http = http_client
        # injectable for tests; defaults to websockets.sync.client.connect
        self._connect_fn = connect_fn
        self._ws = None
        self._closed = False

    # -- internals -------------------------------------------------------
    def _client(self) -> UpstoxHTTPClient:
        if self._http is None:
            self._http = UpstoxHTTPClient(
                base_url=self._settings.upstox_base_url,
                token_provider=self._auth.access_token,
                timeout=self._settings.provider_http_timeout_seconds,
                max_retries=self._settings.provider_max_retries,
                backoff_base=self._settings.provider_backoff_base_seconds,
                max_rps=self._settings.provider_max_rps,
            )
        return self._http

    def _authorize(self) -> str:
        body = self._client().get_json(_AUTHORIZE_PATH)
        uri = (body.get("data") or {}).get("authorized_redirect_uri") or (
            body.get("data") or {}
        ).get("authorizedRedirectUri")
        if not uri:
            raise UpstoxStreamError(f"authorize response has no redirect uri: {body!r}")
        return uri

    @staticmethod
    def _sub_frame(provider_symbols: Sequence[str], mode: str) -> bytes:
        payload = {
            "guid": str(uuid.uuid4()),
            "method": "sub",
            "data": {"mode": mode, "instrumentKeys": list(provider_symbols)},
        }
        return json.dumps(payload).encode("utf-8")  # sent as a BINARY frame

    def _connect(self, uri: str):
        if self._connect_fn is not None:
            return self._connect_fn(uri, self._auth.access_token())
        from websockets.sync.client import connect

        return connect(
            uri, additional_headers={"Authorization": f"Bearer {self._auth.access_token()}"}
        )

    # -- StreamingMarketDataProvider ----------------------------------
    def subscribe(
        self, provider_symbols: Sequence[str], *, mode: str = "full"
    ) -> Iterator[StreamTick]:
        if not self._settings.stream_enabled:
            raise UpstoxStreamError(
                "stream_enabled is false — the Upstox market feed is opt-in "
                "(ANALYTICAL_STREAM_ENABLED=true)."
            )
        if mode not in _MODES:
            raise UpstoxStreamError(f"unknown feed mode {mode!r}; expected one of {sorted(_MODES)}")
        self._auth.ensure_authenticated()
        uri = self._authorize()
        self._ws = self._connect(uri)
        try:
            self._ws.send(self._sub_frame(provider_symbols, mode))
            for raw in self._ws:
                if self._closed:
                    break
                if isinstance(raw, str):
                    continue  # control / non-protobuf text; ignore
                try:
                    resp = pb.FeedResponse.FromString(raw)
                except Exception as exc:  # noqa: BLE001 - malformed frame, keep the stream
                    raise UpstoxStreamError(f"undecodable feed frame: {exc}") from exc
                if resp.type == pb.Type.market_info:
                    continue  # first message = segment status
                cur = resp.currentTs
                for key, feed in resp.feeds.items():
                    tick = _to_tick(key, feed, cur)
                    if tick is not None:
                        yield tick
        finally:
            self._safe_close_ws()

    def close(self) -> None:
        self._closed = True
        self._safe_close_ws()

    def _safe_close_ws(self) -> None:
        ws, self._ws = self._ws, None
        if ws is not None:
            try:
                ws.close()
            except Exception:  # noqa: BLE001 - already closing
                pass
