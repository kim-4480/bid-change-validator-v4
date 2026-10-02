"""Build the standard-clause index that clause review compares notices against.

This is the one place where the two ownership boundaries meet on purpose:

- Backend owns document parsing (`app.services.document_extraction`).
- The AI package owns splitting legal text into clauses
  (`app.ai.clause_review.standards.index`) and never imports the ORM or a parser.

So this script does the wiring, and neither package has to depend on the other.

The original 예규 files stay in `data/standards/` untouched for audit; only the
derived index is written. Rebuild it whenever the rules are amended — the
comparison thresholds are read from this index, so rebuilding is what moves them.

    python scripts/build_standard_clauses.py
    python scripts/build_standard_clauses.py --data-dir data/standards --check
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from bidengine.clause_review.standards import build_clause_index  # noqa: E402
from bidengine.clause_review.standards.values import SPECS  # noqa: E402
from apps.api.app.services.document_extraction import (  # noqa: E402
    UnsupportedDocumentError,
    extract_document,
)


SUPPORTED_SUFFIXES = {".hwp", ".hwpx", ".hml", ".pdf", ".docx", ".txt"}
DEFAULT_DATA_DIR = REPO_ROOT / "data" / "standards"
INDEX_FILENAME = "clauses.json"

# 원본 예규(.hwp/.pdf)는 감사용으로 data/standards/ 에 남기고, 파생 인덱스만
# 패키지 안에 쓴다. Docker 이미지가 apps/api 만 복사하므로 리포 루트에 두면
# 컨테이너에서 표준 대조가 통째로 빠진다.
DEFAULT_OUT_PATH = (
    REPO_ROOT / "engine" / "bidengine" / "clause_review"
    / "standards" / "data" / INDEX_FILENAME
)


# ── HWPML, a format the extension does not admit to ──────────────────────
# 법제처 publishes 계약예규 as HWPML — an XML document — while still naming the
# file `.hwp`. Backend's extractor reads binary HWP (OLE2), HWPX, DOCX and PDF,
# so it rejects these files as "not an OLE2 structured storage file".
#
# The reader below is kept here, in a build script, rather than added to
# `app.services.document_extraction`, because that file belongs to Backend. It is
# a stopgap for building the standard-clause index. Notice attachments arriving
# in this same format are a production gap that belongs in Backend's extractor;
# once it is handled there, delete this and call `extract_document` for
# everything.
_HWPML_HINT = b"HWPML"


def _is_hwpml(head: bytes) -> bool:
    return head.lstrip().startswith(b"<?xml") and _HWPML_HINT in head


def _paragraph_own_text(element) -> str:
    """Text belonging to this paragraph, excluding paragraphs nested in tables.

    A table sits inside a paragraph, and its cells hold their own paragraphs.
    Collecting every descendant CHAR would emit the cell text twice — once for
    the cell's own paragraph and once for the enclosing one.
    """
    parts: list[str] = []
    for child in element:
        if child.tag == "P":
            continue
        if child.tag == "CHAR":
            if child.text:
                parts.append(child.text)
        else:
            parts.append(_paragraph_own_text(child))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)


def _extract_hwpml_text(path: Path) -> str:
    from xml.etree import ElementTree

    root = ElementTree.parse(path).getroot()
    return "\n".join(_paragraph_own_text(node) for node in root.iter("P"))


def extract_documents(data_dir: Path) -> tuple[list[tuple[str, str]], list[str]]:
    """Extract text from every rule document, reporting files that failed."""
    documents: list[tuple[str, str]] = []
    failures: list[str] = []

    for path in sorted(data_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        if path.name == INDEX_FILENAME:
            continue

        try:
            with path.open("rb") as handle:
                head = handle.read(4096)
            # The real format is decided by content, never by the extension.
            if _is_hwpml(head):
                text = _extract_hwpml_text(path)
            else:
                with path.open("rb") as handle:
                    text = extract_document(
                        handle, filename=path.name, content_type=None
                    ).text
        except (UnsupportedDocumentError, ValueError, OSError) as error:
            failures.append(f"{path.name}: {error}")
            continue
        except Exception as error:  # noqa: BLE001 - one bad file must not stop the build
            failures.append(f"{path.name}: {type(error).__name__}: {error}")
            continue

        if not (text or "").strip():
            failures.append(f"{path.name}: 본문 텍스트를 추출하지 못했습니다")
            continue
        documents.append((path.name, text))

    return documents, failures


def report_thresholds(clauses: list[dict]) -> int:
    """Print whether each rule's threshold is readable. Returns the failure count.

    A clause index that parses but yields no thresholds is worse than a missing
    one, because clause review would silently withhold every verdict. Surfacing
    it here means the problem is found at build time.
    """
    from bidengine.clause_review.standards import resolve_all

    resolved = resolve_all(clauses)
    unresolved = 0
    print("\n표준 기준값 추출 결과:")
    for rule_id in SPECS:
        item = resolved[rule_id]
        if item["status"] == "ok":
            value = item["raw"] or item["desc"]
            print(f"  [ok]   {rule_id:24s} {value}")
            if item["drift"]:
                print(f"         └ 개정 감지: {item['notes']}")
        else:
            unresolved += 1
            print(f"  [FAIL] {rule_id:24s} {item['status']} — {item['notes']}")
    return unresolved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--check",
        action="store_true",
        help="원본을 다시 읽어 기준값 추출만 확인하고 인덱스는 쓰지 않습니다",
    )
    args = parser.parse_args()

    data_dir: Path = args.data_dir
    if not data_dir.is_dir():
        print(f"표준 예규 디렉터리가 없습니다: {data_dir}", file=sys.stderr)
        return 2

    documents, failures = extract_documents(data_dir)
    for failure in failures:
        print(f"  [파싱 실패] {failure}", file=sys.stderr)
    if not documents:
        print(f"{data_dir} 에서 읽을 수 있는 예규 문서를 찾지 못했습니다", file=sys.stderr)
        return 2

    payload = build_clause_index(documents)
    print(f"문서 {len(documents)}건에서 조문 {len(payload['clauses'])}건 인덱싱")
    for source in payload["sources"]:
        print(f"  {source['file']} -> {source['source']}: {source['clause_count']}건")

    unresolved = report_thresholds(payload["clauses"])

    if args.check:
        print("\n--check 모드이므로 인덱스를 쓰지 않았습니다.")
        return 1 if unresolved else 0

    out_path: Path = args.out or DEFAULT_OUT_PATH
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n인덱스 저장 -> {out_path}")
    if unresolved:
        print(
            f"경고: 기준값 {unresolved}건을 원문에서 읽지 못했습니다. "
            f"해당 규칙은 판정하지 않고 '확인 불가'로 보고됩니다.",
            file=sys.stderr,
        )
    return 1 if unresolved else 0


if __name__ == "__main__":
    raise SystemExit(main())
