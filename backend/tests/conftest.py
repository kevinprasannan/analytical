"""Shared fixtures.

DB-backed tests are marked ``@pytest.mark.db`` and skipped unless
``ANALYTICAL_TEST_DATABASE_URL`` points at a reachable PostgreSQL (docs/09 §2.8 —
never SQLite). Everything else runs with no database.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from analytical_core.enums import InstrumentType
from app.config import Settings
from app.db.repositories.memory import build_memory_repositories
from app.db.repositories.protocols import InstrumentView
from app.providers.stub import StubBehavior, StubProvider

# Tests assert on `Settings()` defaults; never let a local `.env` (e.g. one used
# to run a live instance) leak into the suite.
Settings.model_config["env_file"] = None

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "backend"
STATUS_YAML = REPO_ROOT / "docs" / "11-provider-validation.status.yaml"
DOCS_TABLE = REPO_ROOT / "docs" / "11-PROVIDER-VALIDATION.md"
UPSTOX_DIR = BACKEND / "app" / "providers" / "upstox"
FIXTURES = BACKEND / "tests" / "fixtures"
UPSTOX_MASTER_DIR = FIXTURES / "providers" / "upstox"


def _db_url() -> str | None:
    return os.environ.get("ANALYTICAL_TEST_DATABASE_URL")


@pytest.fixture(scope="session")
def db_url() -> str:
    url = _db_url()
    if not url:
        pytest.skip("ANALYTICAL_TEST_DATABASE_URL not set; DB-backed test skipped")
    return url


def _alembic(args: list[str], db_url: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "ANALYTICAL_DATABASE_URL": db_url}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
    )


@pytest.fixture()
def migrated_engine(db_url):
    """A fresh schema: ``downgrade base`` then ``upgrade head`` around each test."""
    from sqlalchemy import create_engine

    _alembic(["downgrade", "base"], db_url)
    up = _alembic(["upgrade", "head"], db_url)
    assert up.returncode == 0, up.stderr
    eng = create_engine(db_url, future=True)
    try:
        yield eng
    finally:
        eng.dispose()
        _alembic(["downgrade", "base"], db_url)


@pytest.fixture()
def sample_instruments() -> list[InstrumentView]:
    return [
        InstrumentView(1, "NIFTY-INDEX", InstrumentType.INDEX, True, False, "STUB:NIFTY-INDEX"),
        InstrumentView(
            2, "NIFTY-FUT-NEAR", InstrumentType.FUTURE, True, False, "STUB:NIFTY-FUT-NEAR"
        ),
        InstrumentView(
            3, "NIFTY-24000-CE", InstrumentType.OPTION, True, False, "STUB:NIFTY-OPT-24000-CE"
        ),
    ]


@pytest.fixture()
def memory_repos(sample_instruments):
    return build_memory_repositories(sample_instruments)


@pytest.fixture()
def stub_provider() -> StubProvider:
    return StubProvider(StubBehavior())


@pytest.fixture()
def status_yaml_path() -> Path:
    return STATUS_YAML
