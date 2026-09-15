"""Request dependencies — the single-user auth seam (docs/02 §6.6, docs/07 §2)
and a read-only DB session."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from fastapi import Header, HTTPException, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_sessionmaker


def get_db() -> Iterator[Session]:
    session = get_sessionmaker(get_settings())()
    try:
        yield session
    finally:
        session.close()


@dataclass(frozen=True, slots=True)
class Principal:
    username: str = "owner"


def get_current_principal(
    authorization: str | None = Header(default=None),
) -> Principal:
    settings = get_settings()
    if settings.local_api_token:
        expected = f"Bearer {settings.local_api_token}"
        if authorization != expected:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="missing or invalid bearer token",
            )
    return Principal()
