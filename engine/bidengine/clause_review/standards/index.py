"""Indexing the published government contract rules into individual clauses.

The rules arrive as HWP files. **Extracting text from them is Backend's job**, not
this package's: `app.services.document_extraction` already does it, and importing
it here would tie the AI package to the ORM and to file storage. So this module
takes text that has already been extracted and only does the part that is
specific to legal documents — cutting a document into clauses.

`scripts/build_standard_clauses.py` wires the Backend extractor to this function
and writes the index. The original HWP files stay untouched for audit.

Two details that a naive split gets wrong:

- Branch numbering (제35조의2) must not be read as 제35조.
- Chapter membership matters. 제4장 소프트웨어용역 계약조건 applies only to
  software service contracts, so a clause has to remember which chapter it is in.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


# 제58조(하자보수 등), 제35조의2(...) — branch numbers must be covered.
CLAUSE_HEADER_RE = re.compile(r"제(\d+)조(의\d+)?\(([^)]+)\)")
CHAPTER_RE = re.compile(r"^\s*제(\d+)장\s+(.+?)\s*$", re.MULTILINE)

# Filename keyword -> the source name clause rules refer to.
_SOURCE_NAMES = [
    ("용역계약일반조건", "용역계약일반조건"),
    ("공사계약일반조건", "공사계약일반조건"),
    # 물품구매(제조)계약일반조건 — matched on the distinctive prefix so the
    # published filename's 예규 번호 and date do not have to be tracked.
    ("물품구매", "물품구매(제조)계약일반조건"),
    ("집행기준", "정부 입찰·계약 집행기준"),
    # 용역계약일반조건 제55조 delegates the liquidated-damages rate to
    # 시행규칙 제75조, so that text has to be indexed for the rate to be checkable.
    ("법률 시행규칙", "국가계약법 시행규칙"),
    ("법률 시행령", "국가계약법 시행령"),
]


def source_name(filename: str) -> str:
    for keyword, name in _SOURCE_NAMES:
        if keyword in filename:
            return name
    return Path(filename).stem


def split_clauses(source: str, text: str) -> list[dict[str, Any]]:
    """Cut one document into clauses, tagging each with the chapter it sits in."""
    chapters = [
        (match.start(), f"제{match.group(1)}장 {match.group(2)}")
        for match in CHAPTER_RE.finditer(text)
    ]

    def chapter_at(position: int) -> str | None:
        current = None
        for chapter_position, chapter_name in chapters:
            if chapter_position <= position:
                current = chapter_name
            else:
                break
        return current

    def starts_a_line(position: int) -> bool:
        """A clause header opens a line; mid-line it is a cross-reference.

        Without this, "제21조 및 제22조의 인수" inside the body of another clause
        would start a new clause and truncate the one being read.
        """
        line_start = text.rfind("\n", 0, position) + 1
        return not text[line_start:position].strip()

    headers = [match for match in CLAUSE_HEADER_RE.finditer(text)]
    clauses: list[dict[str, Any]] = []

    for index, match in enumerate(headers):
        if not starts_a_line(match.start()):
            continue
        end = len(text)
        for following in headers[index + 1 :]:
            if starts_a_line(following.start()):
                end = following.start()
                break

        branch = match.group(2) or ""
        clauses.append(
            {
                "source": source,
                "chapter": chapter_at(match.start()),
                "clause_no": f"{match.group(1)}조{branch}",
                "title": f"제{match.group(1)}조{branch}({match.group(3)})",
                "text": text[match.start() : end].strip(),
            }
        )
    return clauses


def build_clause_index(documents: list[tuple[str, str]]) -> dict[str, Any]:
    """Build the index payload from `(filename, extracted_text)` pairs."""
    clauses: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []

    for filename, text in documents:
        name = source_name(filename)
        document_clauses = split_clauses(name, text or "")
        sources.append(
            {"file": filename, "source": name, "clause_count": len(document_clauses)}
        )
        clauses.extend(document_clauses)

    return {"sources": sources, "clauses": clauses}


# 인덱스는 패키지 안에 산다. 리포 루트 `data/` 에 두면 Docker 이미지가
# `apps/api` 만 복사하므로 컨테이너에서 조용히 사라진다 — 로컬에서는 동작하고
# 배포에서만 표준 대조가 통째로 빠지는, 발견이 가장 늦는 종류의 고장이다.
BUNDLED_CLAUSE_INDEX = Path(__file__).with_name("data") / "clauses.json"


def load_clauses(path: str | Path | None = None) -> list[dict[str, Any]]:
    """Read a previously built index. Missing index is an error, not an empty list.

    Returning [] would let every rule silently report "standard clause missing",
    which reads like the rules changed rather than like the index was never built.

    `path` 를 주지 않으면 패키지에 함께 배포되는 인덱스를 쓴다.
    """
    index_path = Path(path) if path is not None else BUNDLED_CLAUSE_INDEX
    if not index_path.exists():
        raise FileNotFoundError(
            f"표준 조문 인덱스가 없습니다: {index_path} "
            f"— scripts/build_standard_clauses.py 를 먼저 실행하세요"
        )
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    return list(payload.get("clauses") or [])


def find_clause(
    clauses: list[dict[str, Any]], source: str, clause_no: str
) -> dict[str, Any] | None:
    for clause in clauses:
        if clause.get("source") == source and clause.get("clause_no") == clause_no:
            return clause
    return None
