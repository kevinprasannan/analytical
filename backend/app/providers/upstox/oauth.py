"""Upstox OAuth2 authorization-code helper (docs/11 PV-1).

Turns an Upstox app (API key + secret + redirect URI) plus a one-time ``code``
into a **daily** access token. There is no refresh token — this runs once each
morning (`analytical-provider login`). The token itself is never returned in a
log line; callers hand it straight to ``token_store.save``.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlencode, urlparse

import httpx

_DIALOG_PATH = "/v2/login/authorization/dialog"
_TOKEN_PATH = "/v2/login/authorization/token"


class UpstoxOAuthError(Exception):
    """The Upstox login dialog or token exchange failed."""


def authorize_url(
    *,
    api_key: str,
    redirect_uri: str,
    base_url: str = "https://api.upstox.com",
    state: str | None = None,
) -> str:
    """The URL the user opens in a browser to log in and approve."""
    query = {"response_type": "code", "client_id": api_key, "redirect_uri": redirect_uri}
    if state:
        query["state"] = state
    return f"{base_url}{_DIALOG_PATH}?{urlencode(query)}"


def code_from_redirect(pasted: str) -> str:
    """Accept either a bare ``code`` or the full redirected URL and return the code."""
    pasted = (pasted or "").strip()
    if pasted.startswith("http") or "?" in pasted:
        qs = parse_qs(urlparse(pasted).query)
        if qs.get("code"):
            return qs["code"][0]
    return pasted


def exchange_code(
    *,
    code: str,
    api_key: str,
    api_secret: str,
    redirect_uri: str,
    base_url: str = "https://api.upstox.com",
    client: httpx.Client | None = None,
) -> str:
    """POST the one-time ``code`` to the token endpoint; return the access token."""
    data = {
        "code": code,
        "client_id": api_key,
        "client_secret": api_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    own = client is None
    c = client or httpx.Client(timeout=15.0)
    try:
        resp = c.post(
            f"{base_url}{_TOKEN_PATH}",
            data=data,
            headers={"Accept": "application/json"},
        )
    finally:
        if own:
            c.close()

    if resp.status_code != 200:
        raise UpstoxOAuthError(
            f"token exchange failed: HTTP {resp.status_code} — {resp.text[:300]}"
        )
    try:
        body = resp.json()
    except ValueError as exc:
        raise UpstoxOAuthError("token endpoint returned non-JSON") from exc
    token = body.get("access_token")
    if not token:
        raise UpstoxOAuthError(f"no access_token in response ({sorted(body)})")
    return str(token)
