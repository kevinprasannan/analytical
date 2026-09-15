"""``UpstoxAuthProvider`` — the ``AuthProvider`` implementation for Upstox.

docs/11 PV-1 (CONFIRMED 2026-08-27): OAuth 2.0 authorization-code flow; the
``access_token`` is valid **until 03:30 AM IST the following day, regardless of
when it was generated**; there is **no refresh token** and no unattended renewal.
So this provider does not perform any OAuth round-trip — a human supplies a fresh
token once per day (env var or ``analytical-provider set-token``), and this class
reports OK / EXPIRED / UNKNOWN from that token's issue time.

The token is never logged, printed, or reprd.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from analytical_core.enums import ProviderAuthState
from app.config import Settings, get_settings
from app.providers.base import ProviderAuthError
from app.providers.upstox import token_store
from app.providers.upstox.token_store import StoredToken

IST = ZoneInfo("Asia/Kolkata")
_EXPIRY_HOUR = 3
_EXPIRY_MINUTE = 30


def _daily_expiry_after(issued_ist: datetime) -> datetime:
    """The next 03:30 IST that is strictly after ``issued_ist`` (PV-1)."""
    boundary = issued_ist.replace(hour=_EXPIRY_HOUR, minute=_EXPIRY_MINUTE, second=0, microsecond=0)
    if issued_ist >= boundary:
        boundary = boundary + timedelta(days=1)
    return boundary


class UpstoxAuthProvider:
    """Reads the current access token from settings (env) or the token file."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    # --- token resolution (never exposed) -----------------------------
    def _resolve(self) -> tuple[str, datetime | None] | None:
        env_token = self._settings.upstox_access_token
        if env_token is not None:
            value = env_token.get_secret_value().strip()
            if value:
                # env-supplied token carries no issue time -> trust the operator
                return value, None
        stored: StoredToken | None = token_store.load(self._settings.upstox_token_file)
        if stored is not None:
            return stored.access_token, stored.issued_at
        return None

    def access_token(self) -> str:
        """The raw token, for the HTTP client only. Raises if unavailable/expired."""
        self.ensure_authenticated()
        resolved = self._resolve()
        assert resolved is not None  # ensured by ensure_authenticated
        return resolved[0]

    # --- AuthProvider protocol ---------------------------------------
    def auth_state(self, *, now: datetime | None = None) -> ProviderAuthState:
        resolved = self._resolve()
        if resolved is None:
            return ProviderAuthState.UNKNOWN
        _token, issued_at = resolved
        if issued_at is None:
            return ProviderAuthState.OK  # env token, no issue time known
        now_ist = (now or datetime.now(tz=IST)).astimezone(IST)
        if now_ist >= _daily_expiry_after(issued_at.astimezone(IST)):
            return ProviderAuthState.EXPIRED
        return ProviderAuthState.OK

    def ensure_authenticated(self) -> None:
        state = self.auth_state()
        if state is not ProviderAuthState.OK:
            raise ProviderAuthError(
                f"Upstox access token is {state.value}. Supply a fresh token "
                "(ANALYTICAL_UPSTOX_ACCESS_TOKEN or `analytical-provider set-token`); "
                "tokens expire daily at 03:30 IST (docs/11 PV-1)."
            )

    def expires_at(self) -> datetime | None:
        resolved = self._resolve()
        if resolved is None or resolved[1] is None:
            return None
        return _daily_expiry_after(resolved[1].astimezone(IST))

    def __repr__(self) -> str:
        return f"UpstoxAuthProvider(state={self.auth_state().value}, token=***)"
