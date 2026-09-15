"""Upstox Market Data Feed v3 adapter (Phase S3, docs/11 §5).

The WebSocket is faked: ``connect_fn`` returns an object that records the
subscribe frame and iterates a queue of protobuf-encoded ``FeedResponse``
frames. The authorize call is an ``httpx.MockTransport``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from app.config import Settings
from app.providers.upstox import MarketDataFeed_pb2 as pb
from app.providers.upstox.feed import UpstoxMarketFeed, UpstoxStreamError, _to_tick
from app.providers.upstox.http import UpstoxHTTPClient

WSS = "wss://feed.example/upstox?requestId=abc&code=def"


def _authorize_client() -> UpstoxHTTPClient:
    def handle(req: httpx.Request) -> httpx.Response:
        assert "/v3/feed/market-data-feed/authorize" in str(req.url)
        return httpx.Response(
            200, json={"status": "success", "data": {"authorized_redirect_uri": WSS}}
        )

    return UpstoxHTTPClient(
        base_url="https://api.upstox.com",
        token_provider=lambda: "tok",
        transport=httpx.MockTransport(handle),
        max_rps=0,
        sleep_fn=lambda _s: None,
    )


class FakeWS:
    def __init__(self, frames: list[bytes]):
        self._frames = list(frames)
        self.sent: list[bytes] = []
        self.closed = False

    def send(self, data):
        self.sent.append(data)

    def __iter__(self):
        yield from self._frames

    def close(self):
        self.closed = True


def _feed(frames: list[bytes], *, enabled: bool = True):
    fake = FakeWS(frames)
    s = Settings(active_provider="upstox", upstox_access_token="tok", stream_enabled=enabled)
    f = UpstoxMarketFeed(s, http_client=_authorize_client(), connect_fn=lambda _uri, _tok: fake)
    return f, fake


# -- frame construction -------------------------------------------------


def test_sub_frame_is_binary_json_with_sub_method():
    raw = UpstoxMarketFeed._sub_frame(["NSE_INDEX|Nifty 50", "NSE_FO|68407"], "full")
    assert isinstance(raw, bytes)
    payload = json.loads(raw)
    assert payload["method"] == "sub"
    assert payload["data"] == {
        "mode": "full",
        "instrumentKeys": ["NSE_INDEX|Nifty 50", "NSE_FO|68407"],
    }
    assert payload["guid"]


# -- protobuf -> StreamTick -----------------------------------------


def _resp(**feeds) -> bytes:
    r = pb.FeedResponse()
    r.type = pb.Type.live_feed
    r.currentTs = 1_756_631_400_000
    for key, build in feeds.items():
        build(r.feeds[key])
    return r.SerializeToString()


def test_index_full_feed_maps_to_tick_with_no_volume_or_oi():
    def build(feed):
        feed.fullFeed.indexFF.ltpc.ltp = 24175.5
        feed.fullFeed.indexFF.ltpc.ltt = 1_756_631_400_000

    r = pb.FeedResponse()
    r.currentTs = 1_756_631_400_000
    build(r.feeds["NSE_INDEX|Nifty 50"])
    tick = _to_tick("NSE_INDEX|Nifty 50", r.feeds["NSE_INDEX|Nifty 50"], r.currentTs)
    assert tick.ltp == pytest.approx(24175.5)
    assert tick.cum_volume == 0 and tick.oi is None
    assert tick.ts == datetime.fromtimestamp(1_756_631_400_000 / 1000, tz=UTC)


def test_market_full_feed_carries_volume_and_oi():
    r = pb.FeedResponse()
    r.currentTs = 1_756_631_400_000
    m = r.feeds["NSE_FO|68407"].fullFeed.marketFF
    m.ltpc.ltp = 101.25
    m.ltpc.ltt = 1_756_631_400_000
    m.vtt = 55000
    m.oi = 250000
    tick = _to_tick("NSE_FO|68407", r.feeds["NSE_FO|68407"], r.currentTs)
    assert tick.cum_volume == 55000 and tick.oi == 250000


def test_ltp_zero_feed_is_dropped():
    r = pb.FeedResponse()
    r.feeds["X"].ltpc.ltp = 0.0
    assert _to_tick("X", r.feeds["X"], 0) is None


# -- subscribe loop -----------------------------------------------


def test_subscribe_yields_ticks_and_skips_market_info():
    info = pb.FeedResponse()
    info.type = pb.Type.market_info
    frame_info = info.SerializeToString()

    def idx(feed):
        feed.fullFeed.indexFF.ltpc.ltp = 100.0
        feed.fullFeed.indexFF.ltpc.ltt = 1_756_631_400_000

    def fut(feed):
        feed.fullFeed.marketFF.ltpc.ltp = 200.0
        feed.fullFeed.marketFF.ltpc.ltt = 1_756_631_400_000
        feed.fullFeed.marketFF.oi = 9000

    f, fake = _feed([frame_info, _resp(**{"NSE_INDEX|Nifty 50": idx, "NSE_FO|68407": fut})])
    ticks = list(f.subscribe(["NSE_INDEX|Nifty 50", "NSE_FO|68407"], mode="full"))
    assert {t.provider_symbol for t in ticks} == {"NSE_INDEX|Nifty 50", "NSE_FO|68407"}
    assert next(t for t in ticks if t.provider_symbol == "NSE_FO|68407").oi == 9000
    assert json.loads(fake.sent[0])["method"] == "sub"  # subscribed once
    assert fake.closed  # cleaned up on exit


def test_disabled_stream_refuses():
    f, _ = _feed([], enabled=False)
    with pytest.raises(UpstoxStreamError):
        list(f.subscribe(["NSE_INDEX|Nifty 50"]))


def test_unknown_mode_refuses():
    f, _ = _feed([])
    with pytest.raises(UpstoxStreamError):
        list(f.subscribe(["NSE_INDEX|Nifty 50"], mode="bogus"))
