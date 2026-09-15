"""``analytical-provider`` — manage the runtime Upstox access token (docs/11 PV-1).

    analytical-provider login              # daily OAuth: prints the login URL,
                                           #   exchanges the pasted code for a token
    analytical-provider login --code ...   # skip the prompt (code / redirected URL)
    analytical-provider set-token          # store a token you already have (STDIN)
    analytical-provider show               # auth state + issue/expiry time (no token)
    analytical-provider clear              # delete the stored token

The token is never echoed, logged, or printed back.
"""

from __future__ import annotations

import argparse
import sys

from app.config import get_settings
from app.providers.upstox import token_store
from app.providers.upstox.auth import UpstoxAuthProvider


def _login(args: argparse.Namespace) -> int:
    from app.providers.upstox import oauth

    settings = get_settings()
    api_key = settings.upstox_api_key.get_secret_value() if settings.upstox_api_key else None
    api_secret = (
        settings.upstox_api_secret.get_secret_value() if settings.upstox_api_secret else None
    )
    redirect = settings.upstox_redirect_uri
    if not api_key or not api_secret:
        sys.stderr.write(
            "error: set ANALYTICAL_UPSTOX_API_KEY and ANALYTICAL_UPSTOX_API_SECRET "
            "(deploy/.env) — from developer.upstox.com > My Apps.\n"
        )
        return 2

    if args.code:
        code = oauth.code_from_redirect(args.code)
    else:
        url = oauth.authorize_url(
            api_key=api_key, redirect_uri=redirect, base_url=settings.upstox_base_url
        )
        sys.stderr.write(f"\n1. Open this URL, log in to Upstox, approve:\n\n   {url}\n\n")
        if not args.no_browser:
            try:
                import webbrowser

                webbrowser.open(url)
            except Exception:  # noqa: BLE001 - headless / no browser is fine
                pass
        sys.stderr.write(
            f"2. You are redirected to {redirect}?code=...  — paste that whole URL "
            "(or just the code), then Enter:\n"
        )
        code = oauth.code_from_redirect(sys.stdin.readline())

    if not code:
        sys.stderr.write("error: no authorization code\n")
        return 2
    try:
        token = oauth.exchange_code(
            code=code,
            api_key=api_key,
            api_secret=api_secret,
            redirect_uri=redirect,
            base_url=settings.upstox_base_url,
        )
    except oauth.UpstoxOAuthError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1

    stored = token_store.save(settings.upstox_token_file, token)
    state = UpstoxAuthProvider(settings).auth_state()
    sys.stdout.write(
        f"token stored at {settings.upstox_token_file} "
        f"(issued {stored.issued_at.isoformat()}); auth_state={state.value}\n"
    )
    return 0


def _set_token() -> int:
    sys.stderr.write("Paste the Upstox access token, then press Enter:\n")
    token = sys.stdin.readline().strip()
    if not token:
        sys.stderr.write("error: no token on STDIN\n")
        return 2
    settings = get_settings()
    stored = token_store.save(settings.upstox_token_file, token)
    state = UpstoxAuthProvider(settings).auth_state()
    sys.stdout.write(
        f"token stored at {settings.upstox_token_file} "
        f"(issued {stored.issued_at.isoformat()}); auth_state={state.value}\n"
    )
    return 0


def _show() -> int:
    settings = get_settings()
    auth = UpstoxAuthProvider(settings)
    stored = token_store.load(settings.upstox_token_file)
    exp = auth.expires_at()
    sys.stdout.write(
        f"token_present={stored is not None} "
        f"issued_at={stored.issued_at.isoformat() if stored else None} "
        f"expires_at={exp.isoformat() if exp else None} "
        f"auth_state={auth.auth_state().value}\n"
    )
    return 0


def _clear() -> int:
    settings = get_settings()
    removed = token_store.clear(settings.upstox_token_file)
    sys.stdout.write(f"token {'removed' if removed else 'not present'}\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="analytical-provider")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_login = sub.add_parser("login", help="daily OAuth: get + store an access token")
    p_login.add_argument("--code", help="authorization code or the full redirected URL")
    p_login.add_argument("--no-browser", action="store_true", help="do not auto-open the login URL")
    sub.add_parser("set-token", help="store an Upstox access token read from STDIN")
    sub.add_parser("show", help="print auth state (never the token)")
    sub.add_parser("clear", help="delete the stored token")
    args = parser.parse_args(argv)
    if args.cmd == "login":
        return _login(args)
    return {"set-token": _set_token, "show": _show, "clear": _clear}[args.cmd]()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
