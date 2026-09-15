"""``app.ops.backup`` — the SQLAlchemy-URL → pg_dump-args parsing (pure)."""

from __future__ import annotations

from app.ops.backup import _pg_conn


def test_pg_conn_parses_url_and_hides_password():
    args, env = _pg_conn("postgresql+psycopg://analytical:s3cr%40t@127.0.0.1:5432/analytical")
    assert args == ["-h", "127.0.0.1", "-p", "5432", "-U", "analytical", "-d", "analytical"]
    assert env == {"PGPASSWORD": "s3cr@t"}  # %40 -> @, and it's in env, never in args
    assert not any("s3cr" in a for a in args)


def test_pg_conn_without_password_or_port():
    args, env = _pg_conn("postgresql://user@dbhost/mydb")
    assert args == ["-h", "dbhost", "-U", "user", "-d", "mydb"]
    assert env == {}
