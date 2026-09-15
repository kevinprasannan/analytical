"""Declarative base, constraint naming convention, and the PG-enum helper."""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import Enum as SAEnum
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def pg_enum(enum_cls: type[StrEnum], name: str) -> SAEnum:
    """Native PostgreSQL ENUM bound to an ``analytical_core`` enum.

    ``values_callable`` makes the stored labels the enum *values* (e.g. ``"rsi"``,
    ``"M5"``) taken straight from ``analytical_core.enums`` — the single source of
    truth (docs/12). The baseline migration emits ``CREATE TYPE`` for these via
    ``metadata.create_all`` (documented choice — see the migration docstring);
    ``analytical_core.enums.emit_sql()`` remains the human-inspection / contract
    -test rendering of the same list.
    """
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=True,
        values_callable=lambda e: [m.value for m in e],
    )
