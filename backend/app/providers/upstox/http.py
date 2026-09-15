"""Thin HTTP layer for the Upstox adapter (Phase 2.3).

Responsibilities kept here so the candle/OI code stays about *shapes*, not
sockets:

* one ``httpx.Client`` (a ``transport`` may be injected in tests — **CI makes no
  live Upstox call, ever**, docs/09 §2.9);
* a client-side request-rate ceiling (``PROVIDER_MAX_RPS``, docs/02 §6.7);
* exponential backoff on a throttle response (HTTP 429/503, honouring
  ``Retry-After``) → :class:`ProviderRateLimitError` once retries are spent;
* status → exception mapping (401/403 → :class:`ProviderAuthError`, other non-2xx
  → :class:`ProviderError`).

The access token is injected per request via ``token_provider`` and never
logged, stored, or placed in an exception message.
"""

from __future__ import annotations

import time as _time
from collections.abc import Callable, Mapping
from typing import Protocol

import httpx

from app.providers.base import ProviderAuthError, ProviderError, ProviderRateLimitError

_THROTTLE_STATUS = frozenset({429, 503})
_AUTH_STATUS = frozenset({401, 403})


class Limiter(Protocol):
    """Anything that blocks until one request is allowed (``RateLimiter`` here;
    a thread-safe ``RequestBudget`` during a concurrent backfill)."""

    def acquire(self) -> None: ...


class RateLimiter:
    """Minimum-spacing limiter: at most ``max_rps`` acquisitions per second."""

    def __init__(
        self,
        max_rps: float,
        *,
        time_fn: Callable[[], float] = _time.monotonic,
        sleep_fn: Callable[[float], None] = _time.sleep,
    ) -> None:
        self._min_interval = 1.0 / max_rps if max_rps > 0 else 0.0
        self._time = time_fn
        self._sleep = sleep_fn
        self._last: float | None = None

    def acquire(self) -> None:
        if self._min_interval <= 0.0:
            return
        now = self._time()
        if self._last is not None:
            wait = self._min_interval - (now - self._last)
            if wait > 0:
                self._sleep(wait)
                now = self._time()
        self._last = now


def _retry_after_seconds(resp: httpx.Response) -> float | None:
    raw = resp.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None


class UpstoxHTTPClient:
    def __init__(
        self,
        *,
        base_url: str,
        token_provider: Callable[[], str],
        timeout: float = 10.0,
        max_retries: int = 4,
        backoff_base: float = 0.5,
        max_rps: float = 8.0,
        limiter: Limiter | None = None,
        transport: httpx.BaseTransport | None = None,
        time_fn: Callable[[], float] = _time.monotonic,
        sleep_fn: Callable[[float], None] = _time.sleep,
    ) -> None:
        self._token_provider = token_provider
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._sleep = sleep_fn
        # a caller-supplied limiter (e.g. a shared thread-safe RequestBudget for a
        # concurrent backfill) overrides the per-client rps ceiling.
        self._limiter: Limiter = limiter or RateLimiter(max_rps, time_fn=time_fn, sleep_fn=sleep_fn)
        self._client = httpx.Client(base_url=base_url, timeout=timeout, transport=transport)

    # -- lifecycle ----------------------------------------------------------
    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> UpstoxHTTPClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # -- the one call the adapter needs -----------------------------------
    def get_json(self, path: str, params: Mapping[str, str] | None = None) -> dict:
        last_status: int | None = None
        for attempt in range(self._max_retries + 1):
            self._limiter.acquire()
            token = self._token_provider()  # may raise ProviderAuthError
            resp = self._client.get(
                path,
                params=dict(params or {}),
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
            status = resp.status_code
            if status == 200:
                return _parse_success_body(resp, path)
            if status in _AUTH_STATUS:
                raise ProviderAuthError(f"Upstox rejected the access token (HTTP {status}).")
            if status in _THROTTLE_STATUS:
                last_status = status
                if attempt < self._max_retries:
                    delay = _retry_after_seconds(resp)
                    if delay is None:
                        delay = self._backoff_base * (2**attempt)
                    self._sleep(delay)
                    continue
                raise ProviderRateLimitError(
                    f"Upstox throttled the request (HTTP {status}) after "
                    f"{self._max_retries} retries."
                )
            raise ProviderError(f"Upstox HTTP {status} for {path}.")
        # unreachable: the loop either returns or raises
        raise ProviderRateLimitError(  # pragma: no cover
            f"Upstox throttled the request (HTTP {last_status})."
        )


def _parse_success_body(resp: httpx.Response, path: str) -> dict:
    try:
        body = resp.json()
    except ValueError as exc:
        raise ProviderError(f"Upstox returned a non-JSON 200 for {path}.") from exc
    if not isinstance(body, dict):
        raise ProviderError(f"Upstox 200 body for {path} is not a JSON object.")
    if body.get("status") != "success":
        raise ProviderError(f"Upstox reported status={body.get('status')!r} for {path}.")
    return body
