"""Clause review against the real 계약예규 corpus, not a fixture.

The unit tests use a trimmed stand-in so they stay readable. These run the same
code against the actual published rules in `data/standards/`, which is what
catches an anchor that quietly stops matching after the rules are amended.

Skipped when the index has not been built, so a fresh clone still runs green:

    python scripts/build_standard_clauses.py
"""

from pathlib import Path

import pytest

from bidengine.clause_review import detect_patterns, detect_standard_diff
from bidengine.clause_review.standards import load_clauses, resolve_all


REPO_ROOT = Path(__file__).resolve().parents[2]
# 인덱스는 패키지에 함께 배포된다. 리포 루트 data/ 를 보면 Docker 이미지와
# 경로가 어긋나 CI 에서만 조용히 skip 되고, 예규 대조 검증이 통째로 빠진다.
from bidengine.clause_review.standards.index import BUNDLED_CLAUSE_INDEX as INDEX_PATH

pytestmark = pytest.mark.skipif(
    not INDEX_PATH.exists(),
    reason="표준 조문 인덱스 없음 — scripts/build_standard_clauses.py 실행 필요",
)


@pytest.fixture(scope="module")
def clauses() -> list[dict]:
    return load_clauses(INDEX_PATH)


def test_the_corpus_holds_the_clauses_the_rules_depend_on(clauses) -> None:
    by_source: dict[str, set[str]] = {}
    for clause in clauses:
        by_source.setdefault(clause["source"], set()).add(clause["clause_no"])

    assert {"18조", "20조", "31조", "56조", "58조", "59조"} <= by_source["용역계약일반조건"]
    # 용역계약일반조건 제55조 delegates the liquidated-damages rate here, so the
    # delegated text has to be in the corpus for that rule to become possible.
    assert "75조" in by_source["국가계약법 시행규칙"]


def test_every_threshold_is_readable_from_the_published_rules(clauses) -> None:
    resolved = resolve_all(clauses)

    unresolved = {
        rule_id: item["status"]
        for rule_id, item in resolved.items()
        if item["status"] != "ok"
    }
    assert unresolved == {}, (
        f"예규 원문에서 기준값을 읽지 못했습니다: {unresolved}. "
        f"예규가 개정되었다면 values.py의 anchor를 갱신해야 합니다."
    )


def test_recorded_values_still_agree_with_the_published_rules(clauses) -> None:
    drifted = {
        rule_id: item["drift"]
        for rule_id, item in resolve_all(clauses).items()
        if item["drift"]
    }
    # Drift is not a code failure — the extracted value is what gets used. It
    # means the rules were amended and the tripwire in values.py needs updating.
    assert drifted == {}, f"예규 개정 감지: {drifted} — values.py의 recorded를 갱신하세요"


def test_a_realistic_notice_is_reviewed_end_to_end(clauses) -> None:
    chunks = [
        # The notice says what kind of contract it is, which is what decides
        # whether the 소프트웨어용역 chapter's standards apply to it at all.
        {
            "chunk_id": "CHUNK-0000",
            "clause_label": "1.1",
            "text": (
                "1. 사업 개요\n1.1 사업명: 통합정보시스템 구축 소프트웨어 개발 용역\n"
                "1.2 본 사업은 정보시스템 고도화를 위한 소프트웨어 개발을 목적으로 한다."
            ),
        },
        {
            "chunk_id": "CHUNK-0001",
            "clause_label": "3.5",
            "text": "3. 과업 내용\n3.1 시스템 분석 및 설계\n3.5 기타 발주기관이 필요하다고 인정하여 요구하는 사항",
        },
        {
            "chunk_id": "CHUNK-0002",
            "clause_label": "5.1",
            "text": "5.1 계약상대자는 인수 확인 후 36개월간 무상으로 하자를 보수하여야 한다.",
        },
        {
            "chunk_id": "CHUNK-0003",
            "clause_label": "6.1",
            "text": "6.1 지체상금의 총액은 계약금액의 100분의 50을 한도로 한다.",
        },
        {
            "chunk_id": "CHUNK-0004",
            "clause_label": "9.1",
            "text": "9.1 본 용역의 모든 산출물에 대한 저작재산권은 발주기관에 귀속한다.",
        },
    ]

    findings = detect_standard_diff(chunks, clauses, notice_version_id="nv-001")
    findings += detect_patterns(chunks, notice_version_id="nv-001")
    by_rule = {finding.rule_id: finding for finding in findings}

    flagged = {
        rule_id for rule_id, finding in by_rule.items() if finding.verdict == "NEEDS_REVIEW"
    }
    assert {"warranty_period", "penalty_cap", "ip_ownership", "open_ended_scope"} <= flagged

    # Each flagged term carries the standard it was measured against, read from
    # the published rules rather than from a constant in the codebase.
    warranty = by_rule["warranty_period"]
    assert warranty.notice_value == 36
    assert warranty.standard is not None
    assert warranty.standard.value == 12
    assert warranty.standard.value_raw == "1년"
    assert warranty.standard.source == "용역계약일반조건"
    assert warranty.standard.text_excerpt


def test_a_compliant_notice_produces_no_flags(clauses) -> None:
    chunks = [
        {
            "chunk_id": "CHUNK-0000",
            "clause_label": "1.1",
            "text": (
                "1.1 사업명: 정보시스템 유지관리 소프트웨어 용역\n"
                "1.2 본 소프트웨어 사업의 과업은 아래와 같다."
            ),
        },
        {
            "chunk_id": "CHUNK-0001",
            "clause_label": "5.1",
            "text": "5.1 계약상대자는 인수 확인 후 12개월간 하자보수 책임을 진다.",
        },
        {
            "chunk_id": "CHUNK-0002",
            "clause_label": "6.1",
            "text": "6.1 지체상금의 총액은 계약금액의 100분의 30을 초과하지 아니한다.",
        },
        {
            "chunk_id": "CHUNK-0003",
            "clause_label": "9.1",
            "text": (
                "9.1 산출물의 지식재산권은 발주기관과 계약상대자가 공동으로 소유하며 "
                "지분은 균등한 것으로 한다."
            ),
        },
    ]

    findings = detect_standard_diff(chunks, clauses)
    findings += detect_patterns(chunks)

    flagged = [finding for finding in findings if finding.verdict == "NEEDS_REVIEW"]
    assert flagged == [], [
        (finding.rule_id, finding.reason, finding.matched_text) for finding in flagged
    ]
