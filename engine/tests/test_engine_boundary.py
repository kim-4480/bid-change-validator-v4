"""엔진 경계: bidengine은 API·DB 계층을 import하지 않는다 (ADR 0001)."""
from __future__ import annotations

import ast
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1] / "bidengine"
FORBIDDEN = ("apps", "app", "sqlalchemy", "fastapi", "psycopg", "alembic", "bideval")


def _imported_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_engine_does_not_import_api_or_db_layers() -> None:
    violations = [
        f"{path.relative_to(ENGINE.parent)}: {root}"
        for path in sorted(ENGINE.rglob("*.py"))
        for root in sorted(_imported_roots(path) & set(FORBIDDEN))
    ]
    assert violations == []


def test_engine_uses_absolute_imports_only_within_package() -> None:
    # 상대 import가 패키지 밖(..을 넘어서)으로 나가지 않는지 확인한다.
    for path in ENGINE.rglob("*.py"):
        depth = len(path.relative_to(ENGINE).parts) - 1
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.level:
                assert node.level - 1 <= depth, f"{path}: relative import escapes bidengine"
