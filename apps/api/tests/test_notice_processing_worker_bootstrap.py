"""The standalone worker must register every model referenced by its jobs."""

import os
import subprocess
import sys
from pathlib import Path


def test_standalone_worker_registers_auth_foreign_key_table():
    repo_root = Path(__file__).resolve().parents[3]
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(repo_root / "apps" / "api"), str(repo_root / "engine")))
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.workers import notice_processing; "
            "from app.models import Base; "
            "assert 'app_users' in Base.metadata.tables; "
            "Base.metadata.sorted_tables",
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
