"""On-disk store for the runtime Upstox access token (docs/11 PV-1 fallback).

Upstox issues no refresh token and the access token expires daily at 03:30 IST
(PV-1). V1 accepts a fresh token once per day via the ``analytical-provider
set-token`` CLI; this module persists it locally so the worker/API can read it
without a redeploy.

Security:
  * The file lives under a git-ignored directory (default ``.secrets/``).
  * It is written with ``0600`` permissions (best-effort on Windows).
  * The token is **never** logged, printed, or included in a repr anywhere.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True, slots=True)
class StoredToken:
    access_token: str
    issued_at: datetime  # tz-aware, IST

    def __repr__(self) -> str:  # never leak the token
        return f"StoredToken(issued_at={self.issued_at.isoformat()}, access_token=***)"


def _path(token_file: str | Path) -> Path:
    return Path(token_file).expanduser()


def save(
    token_file: str | Path, access_token: str, *, issued_at: datetime | None = None
) -> StoredToken:
    if not access_token or not access_token.strip():
        raise ValueError("access_token is empty")
    issued = (issued_at or datetime.now(tz=IST)).astimezone(IST)
    p = _path(token_file)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"access_token": access_token.strip(), "issued_at": issued.isoformat()}
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    try:
        os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)  # 0600
    except OSError:  # pragma: no cover - platform dependent
        pass
    os.replace(tmp, p)
    return StoredToken(access_token=payload["access_token"], issued_at=issued)


def load(token_file: str | Path) -> StoredToken | None:
    p = _path(token_file)
    if not p.is_file():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        token = str(raw["access_token"])
        issued = datetime.fromisoformat(str(raw["issued_at"]))
    except (json.JSONDecodeError, KeyError, ValueError, OSError):
        return None
    if issued.tzinfo is None:
        issued = issued.replace(tzinfo=IST)
    return StoredToken(access_token=token, issued_at=issued.astimezone(IST))


def clear(token_file: str | Path) -> bool:
    p = _path(token_file)
    if p.is_file():
        p.unlink()
        return True
    return False
