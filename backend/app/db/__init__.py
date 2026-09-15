"""Persistence layer: declarative models, engine/session, repositories.

Phase 1 targets PostgreSQL 16 only. Enum types are created by the Alembic
baseline migration from ``analytical_core.enums`` (``emit_sql``); models
reference them with ``create_type=False``. DB-backed tests run via
``alembic upgrade head`` (never ``create_all``, never SQLite — docs/09 §2.8).
"""
