"""Nightly PostgreSQL backup — ``pg_dump`` to a local directory, pruned.

Run by the worker's daily job (``app.worker.scheduler.run_db_backup``) or by
hand: ``python -m app.ops.backup``. Writes a custom-format dump
(``analytical-YYYY-MM-DD-HHMMSS.dump``, restore with ``pg_restore``) and keeps
the newest ``db_backup_keep`` files.

Needs ``pg_dump`` on PATH (or ``ANALYTICAL_PG_DUMP_PATH`` pointing at it). The
connection is taken from ``database_url``; the password is passed to the child
via ``PGPASSWORD``, never on the command line.
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

import structlog

from app.config import Settings, get_settings

_LOG = structlog.get_logger("ops.backup")


def _resolve_pg_dump(configured: str) -> str:
    """The configured value if it resolves, else a common Windows PostgreSQL
    install path, else the configured value (let the failure surface)."""
    if os.path.isabs(configured) and os.path.exists(configured):
        return configured
    on_path = shutil.which(configured)
    if on_path:
        return on_path
    for pat in (
        r"C:\Program Files\PostgreSQL\*\bin\pg_dump.exe",
        r"C:\Program Files (x86)\PostgreSQL\*\bin\pg_dump.exe",
    ):
        hits = sorted(glob.glob(pat), reverse=True)  # newest major version first
        if hits:
            return hits[0]
    return configured


def _pg_conn(database_url: str) -> tuple[list[str], dict[str, str]]:
    """(pg_dump connection args, extra env) from a SQLAlchemy URL."""
    # strip the SQLAlchemy driver suffix: postgresql+psycopg:// -> postgresql://
    u = urlparse(database_url.replace("+psycopg", "").replace("+psycopg2", ""))
    args: list[str] = []
    if u.hostname:
        args += ["-h", u.hostname]
    if u.port:
        args += ["-p", str(u.port)]
    if u.username:
        args += ["-U", unquote(u.username)]
    db = (u.path or "/").lstrip("/")
    if db:
        args += ["-d", db]
    env = {"PGPASSWORD": unquote(u.password)} if u.password else {}
    return args, env


def run_backup(settings: Settings | None = None, *, now: datetime | None = None) -> Path:
    """Take one dump and prune old ones. Returns the dump path. Raises on failure."""
    s = settings or get_settings()
    now = now or datetime.now(tz=UTC)
    out_dir = Path(s.db_backup_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"analytical-{now:%Y-%m-%d-%H%M%S}.dump"

    conn_args, extra_env = _pg_conn(s.database_url)
    pg_dump = _resolve_pg_dump(s.pg_dump_path)
    cmd = [pg_dump, *conn_args, "-Fc", "--no-owner", "--no-privileges", "-f", str(dest)]
    _LOG.info("db backup starting", dest=str(dest))
    proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
        cmd,
        env={**os.environ, **extra_env},
        capture_output=True,
        text=True,
        timeout=s.db_backup_timeout_seconds,
        check=False,
    )
    if proc.returncode != 0 or not dest.exists():
        dest.unlink(missing_ok=True)
        raise RuntimeError(f"pg_dump failed (rc={proc.returncode}): {proc.stderr.strip()[:500]}")

    kept = _prune(out_dir, keep=s.db_backup_keep)
    _LOG.info("db backup done", dest=str(dest), bytes=dest.stat().st_size, kept=kept)
    return dest


def _prune(out_dir: Path, *, keep: int) -> int:
    dumps = sorted(out_dir.glob("analytical-*.dump"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in dumps[max(keep, 1) :]:
        old.unlink(missing_ok=True)
        _LOG.info("db backup pruned", path=str(old))
    return min(len(dumps), max(keep, 1))


if __name__ == "__main__":  # pragma: no cover
    p = run_backup()
    print(f"wrote {p} ({p.stat().st_size:,} bytes)")
