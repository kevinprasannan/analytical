"""Alembic environment.

Target DB URL resolution, in order:
  1. ``ANALYTICAL_DATABASE_URL`` (explicit — the production / deploy URL).
  2. **``ANALYTICAL_TEST_DATABASE_URL``** when set and (1) is not — so running
     ``alembic ...`` in a shell that only has the *test* URL exported can never
     hit production. (The pytest helper always passes an explicit URL; this guard
     protects manual invocations.)
  3. ``alembic.ini``'s ``sqlalchemy.url``.

A bare ``alembic downgrade base`` against production is destructive; this
ordering makes the common "I set the test var" mistake harmless.
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import models as _models  # noqa: E402,F401  (populates Base.metadata)
from app.db.base import Base  # noqa: E402

config = context.config

_env_url = os.environ.get("ANALYTICAL_DATABASE_URL") or os.environ.get(
    "ANALYTICAL_TEST_DATABASE_URL"
)
if _env_url:
    config.set_main_option("sqlalchemy.url", _env_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
