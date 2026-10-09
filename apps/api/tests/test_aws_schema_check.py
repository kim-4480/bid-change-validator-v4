"""Isolated AWS release gate tests; no AWS or DB access."""
from pathlib import Path

import pytest

from apps.api.app.aws_schema_check import expected_revision, verify_connection


API_DIR = Path(__file__).resolve().parents[1]


class FakeConnection:
    def __init__(self, revision="025_analysis_input_fingerprint", role="bidcheck_app", tls=True, rls=True):
        self.responses = iter([revision, role, tls, rls])
        self.statements = []

    def execute(self, statement):
        sql = str(statement)
        self.statements.append(sql)
        if sql == "SET TRANSACTION READ ONLY":
            return None
        class Result:
            def __init__(self, value):
                self.value = value
            def scalar_one(self):
                return self.value
        return Result(next(self.responses))


def test_api_image_alembic_head_detected(monkeypatch):
    monkeypatch.chdir(API_DIR)
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    assert expected_revision() == ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()


def test_schema_gate_accepts_matching_revision_with_security_flags(capsys):
    conn = FakeConnection()
    verify_connection(conn, "025_analysis_input_fingerprint")
    assert conn.statements[0] == "SET TRANSACTION READ ONLY"
    assert "AWS_SCHEMA_CHECK_OK" in capsys.readouterr().out


@pytest.mark.parametrize("change", [
    {"revision": "024_analysis_run_coverage"},
    {"role": "postgres"},
    {"tls": False},
    {"rls": False},
])
def test_schema_gate_blocks_older_revision_or_weaker_security(change):
    conn = FakeConnection(**change)
    with pytest.raises(RuntimeError, match="AWS schema gate blocked"):
        verify_connection(conn, "025_analysis_input_fingerprint")
    assert conn.statements[0] == "SET TRANSACTION READ ONLY"