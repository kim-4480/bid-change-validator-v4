"""Fail-closed AWS read-only schema gate tied to the API image migration head."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text


def expected_revision(config_path: str | Path = "alembic.ini") -> str:
    heads = ScriptDirectory.from_config(Config(str(config_path))).get_heads()
    if len(heads) != 1:
        raise RuntimeError(f"Expected one Alembic head in this API image, got {heads!r}")
    return heads[0]


def verify_connection(connection, revision: str) -> None:
    connection.execute(text("SET TRANSACTION READ ONLY"))
    actual = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    user = connection.execute(text("SELECT current_user")).scalar_one()
    tls = connection.execute(text("SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()")).scalar_one()
    rls = connection.execute(text("SELECT row_security_active('public.qualification_graph_runs'::regclass)")).scalar_one()
    if (actual, user, tls, rls) != (revision, "bidcheck_app", True, True):
        raise RuntimeError(
            f"AWS schema gate blocked: revision={actual!r} expected={revision!r} "
            f"role={user!r} tls={tls!r} rls={rls!r}"
        )
    print("AWS_SCHEMA_CHECK_OK", actual, user, "TLS", tls, "RLS", rls)


def main() -> None:
    from app.database import engine

    revision = expected_revision()
    with engine.connect() as connection:
        verify_connection(connection, revision)


if __name__ == "__main__":
    main()