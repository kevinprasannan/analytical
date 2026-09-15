"""Upstox OAuth2 authorization-code helper (docs/11 PV-1). No live call."""

from __future__ import annotations

import httpx
import pytest

from app.providers.upstox import oauth


def test_authorize_url_shape():
    url = oauth.authorize_url(api_key="KEY123", redirect_uri="http://localhost", state="xy")
    assert url.startswith("https://api.upstox.com/v2/login/authorization/dialog?")
    assert "response_type=code" in url
    assert "client_id=KEY123" in url
    assert "redirect_uri=http%3A%2F%2Flocalhost" in url
    assert "state=xy" in url


def test_code_from_redirect_accepts_bare_code_and_full_url():
    assert oauth.code_from_redirect("abc123") == "abc123"
    assert oauth.code_from_redirect("  abc123  ") == "abc123"
    assert oauth.code_from_redirect("http://localhost/?code=abc123&state=xy") == "abc123"
    assert oauth.code_from_redirect("https://127.0.0.1?state=z&code=deadbeef") == "deadbeef"


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_exchange_code_posts_form_and_returns_token():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["body"] = req.content.decode()
        return httpx.Response(200, json={"access_token": "eyJ0.OKTOKEN", "email": "x@y.z"})

    tok = oauth.exchange_code(
        code="CODE",
        api_key="KEY",
        api_secret="SECRET",
        redirect_uri="http://localhost",
        client=_client(handler),
    )
    assert tok == "eyJ0.OKTOKEN"
    assert seen["url"].endswith("/v2/login/authorization/token")
    assert "grant_type=authorization_code" in seen["body"]
    assert "client_secret=SECRET" in seen["body"]


def test_exchange_code_raises_on_http_error():
    def handler(_req):
        return httpx.Response(400, json={"errors": [{"message": "invalid code"}]})

    with pytest.raises(oauth.UpstoxOAuthError, match="HTTP 400"):
        oauth.exchange_code(
            code="BAD",
            api_key="K",
            api_secret="S",
            redirect_uri="http://localhost",
            client=_client(handler),
        )


def test_exchange_code_raises_when_no_token_in_body():
    def handler(_req):
        return httpx.Response(200, json={"email": "x@y.z"})

    with pytest.raises(oauth.UpstoxOAuthError, match="no access_token"):
        oauth.exchange_code(
            code="C",
            api_key="K",
            api_secret="S",
            redirect_uri="http://localhost",
            client=_client(handler),
        )


# -- `analytical-provider login` CLI ----------------------------------


def test_login_cli_errors_without_app_credentials(monkeypatch, tmp_path, capsys):
    from app.config import get_settings
    from app.providers.upstox import cli

    monkeypatch.delenv("ANALYTICAL_UPSTOX_API_KEY", raising=False)
    monkeypatch.delenv("ANALYTICAL_UPSTOX_API_SECRET", raising=False)
    get_settings.cache_clear()
    rc = cli.main(["login", "--code", "x"])
    get_settings.cache_clear()
    assert rc == 2
    assert "ANALYTICAL_UPSTOX_API_KEY" in capsys.readouterr().err


def test_login_cli_happy_path_stores_token(monkeypatch, tmp_path, capsys):
    from app.config import get_settings
    from app.providers.upstox import cli, oauth, token_store

    tf = tmp_path / "tok.json"
    monkeypatch.setenv("ANALYTICAL_UPSTOX_API_KEY", "KEY")
    monkeypatch.setenv("ANALYTICAL_UPSTOX_API_SECRET", "SECRET")
    monkeypatch.setenv("ANALYTICAL_UPSTOX_TOKEN_FILE", str(tf))
    get_settings.cache_clear()
    monkeypatch.setattr(oauth, "exchange_code", lambda **_kw: "eyJ0.LIVE")

    rc = cli.main(["login", "--code", "http://localhost/?code=abc123&state=z", "--no-browser"])
    get_settings.cache_clear()
    assert rc == 0
    assert token_store.load(str(tf)).access_token == "eyJ0.LIVE"
    assert "token stored" in capsys.readouterr().out
