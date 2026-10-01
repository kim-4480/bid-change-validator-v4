"""분석 커버리지와 적합 판정의 관계 (docs/experiments/2026-09-30 실측 발견 2)."""
from __future__ import annotations

from datetime import date

from bidengine.contracts import QualificationRequirement
from bidengine.judgment.rules import CompanyProfileSnapshot, judge_requirements
from bidengine.labeling.requirement_extraction import select_eligibility_chunks_with_mode
from bidengine.pipeline.analysis_result import build_requirement_analysis_result

REQ = QualificationRequirement(
    requirement_key="R1", notice_version_id="v", type="REGION", operator="MATCH",
    value="서울특별시", raw="본점 소재지가 서울특별시인 업체",
)
SEOUL = CompanyProfileSnapshot(company_id="c", region_name="서울특별시")


def _result(diagnostics, *, dropped=None, selection="anchored", requirements=(REQ,)):
    return build_requirement_analysis_result(
        notice_id="n", notice_version_id="v", document_ids=["d"],
        canonicalized={"requirements": list(requirements), "evidence": [], "diagnostics": diagnostics},
        extraction_dropped_requirements=dropped, section_selection=selection, candidate_count=5,
    )


def test_procedural_clauses_are_not_gaps():
    result = _result([{"code": "UNMAPPED_REQUIREMENT", "raw": "나라장터 이용자 등록", "reason": "LEGAL_PROCEDURAL_RULE"}])
    assert result.status == "SUCCEEDED"
    assert result.coverage.procedural == 1
    assert result.coverage.complete


def test_unrepresentable_alternative_blocks_completeness_even_when_status_succeeded():
    """C04 실측: 등록 요건 4개가 '또는' 때문에 빠졌는데 상태는 SUCCEEDED 였다."""
    result = _result([{
        "code": "UNMAPPED_REQUIREMENT", "reason": "ALTERNATIVE_OR_EXCEPTION_RULE",
        "raw": "건설엔지니어링업(종합) 또는 건설엔지니어링업(설계·사업관리-일반)으로 등록한 자",
    }])
    assert result.status == "SUCCEEDED"
    assert result.coverage.unrepresentable == 1
    assert not result.coverage.complete
    assert result.coverage.gaps[0].raw.startswith("건설엔지니어링업")
    assert "complete" in result.model_dump()["coverage"]


def test_unclassified_other_is_listed_but_does_not_block_by_default():
    result = _result([{"code": "UNMAPPED_REQUIREMENT", "raw": "제조사 기술지원 확약서 1부"}])
    assert result.coverage.unclassified == 1
    assert result.coverage.complete
    assert [gap.kind for gap in result.coverage.gaps] == ["UNCLASSIFIED"]


def test_dropped_candidates_and_missing_section_block_completeness():
    assert not _result([], dropped=[{"raw": "x", "reason_code": "RAW_NOT_FOUND_IN_SOURCE"}]).coverage.complete
    assert not _result([], selection="keyword_fallback").coverage.complete


def test_eligible_requires_complete_coverage():
    complete = _result([])
    incomplete = _result([{"code": "UNMAPPED_REQUIREMENT", "raw": "A 또는 B 등록", "reason": "ALTERNATIVE_OR_EXCEPTION_RULE"}])

    def overall(result):
        return judge_requirements(
            result.requirements, SEOUL, preflight_case_id="c", reference_date=date(2026, 9, 1),
            analysis_status=result.status, coverage_complete=result.coverage.complete,
        ).overall_status

    assert overall(complete) == "eligible"
    assert overall(incomplete) == "insufficient_data"


def test_coverage_overrides_partial_status_but_absence_keeps_old_behaviour():
    """PARTIAL 은 파이프라인 사정을 섞어 쓴다. 커버리지가 있으면 그것이 우선이다."""
    kwargs = dict(preflight_case_id="c", reference_date=date(2026, 9, 1), analysis_status="PARTIAL")
    assert judge_requirements([REQ], SEOUL, **kwargs).overall_status == "insufficient_data"
    assert judge_requirements([REQ], SEOUL, coverage_complete=True, **kwargs).overall_status == "eligible"


def test_ineligible_does_not_depend_on_coverage():
    busan = CompanyProfileSnapshot(company_id="c", region_name="부산광역시")
    result = judge_requirements([REQ], busan, preflight_case_id="c", reference_date=date(2026, 9, 1),
                                coverage_complete=False)
    assert result.overall_status == "ineligible"


def test_selection_mode_reports_how_the_section_was_found():
    anchored = [{"chunk_id": "0", "clause_label": "3.", "text": "3. 입찰참가자격\n가. 업종", "source_blocks": []}]
    assert select_eligibility_chunks_with_mode(anchored)[1] == "anchored"
    plain = [{"chunk_id": "0", "clause_label": None, "text": "본문", "source_blocks": []}]
    assert select_eligibility_chunks_with_mode(plain)[1] == "whole_document"


def test_body_item_that_mentions_the_keyword_is_not_a_section_heading():
    """본문 항목이 '입찰참가자격' 을 품었다고 제목이 되면, 그 항목만 절이 되고 나머지 요건이 빠진다."""
    def chunk(index, label, text):
        return {"chunk_id": str(index), "clause_label": label, "text": text, "source_blocks": []}

    body_only = [
        chunk(0, "1", "1. 지방계약 관계 법령과 국가종합전자조달시스템 입찰참가자격등록규정에 따라 전자입찰 참가등록을 완료한 자"),
        chunk(1, "2", "2. 입찰공고일 전일부터 본점 소재지가 경상남도에 있는 자"),
        chunk(2, "4", "4. 최근 5년 이내 설치 완료실적 누계가 400,000,000원 이상인 자"),
        chunk(3, "5", "5. 지방계약 관계 법령에 따른 입찰참가자격 제한 또는 부정당업자 제재 중이 아닌 자"),
    ]
    selected, mode = select_eligibility_chunks_with_mode(body_only)
    assert mode == "keyword_fallback"
    assert [c["chunk_id"] for c in selected] == ["0", "1", "2", "3"]

    with_colon = [chunk(0, "3", "3. 입찰 참가자격 : 다음 조건을 모두 충족하는 자로서 아래 각 호에 해당하는 업체"), chunk(1, "가", "가. 업종")]
    assert select_eligibility_chunks_with_mode(with_colon)[1] == "anchored"


def test_statute_citation_at_line_start_does_not_end_the_section():
    """PDF 가 "…시행령｣⏎제12조 및 동법 …" 으로 줄을 바꾸면 인용이 조문 제목처럼 보인다. 절은 이어져야 한다."""
    def chunk(index, label, text):
        return {"chunk_id": str(index), "clause_label": label, "text": text, "source_blocks": []}

    chunks = [
        chunk(0, "2", "2. 입찰참가자격"),
        chunk(1, "가", "가. ｢국가를 당사자로 하는 계약에 관한 법률 시행령｣"),
        chunk(2, "제12조", "제12조 및 동법 시행규칙 제14조의 요건을 갖추고 소프트웨어사업자(업종코드:1468)로 등록한자"),
        chunk(3, "나", "나. 중ㆍ소기업 또는 소상공인으로서 확인서를 소지한 자"),
        chunk(4, "3", "3. 입찰 진행사항"),
    ]
    selected, mode = select_eligibility_chunks_with_mode(chunks)
    assert mode == "anchored"
    assert [c["chunk_id"] for c in selected] == ["0", "1", "2", "3"]
    real_article = [chunk(0, "2", "2. 입찰참가자격"), chunk(1, "가", "가. 업종"), chunk(2, "제5조", "제5조(입찰보증금) 면제")]
    assert [c["chunk_id"] for c in select_eligibility_chunks_with_mode(real_article)[0]] == ["0", "1"]


def test_same_unmapped_clause_counts_once():
    clause = {"code": "UNMAPPED_REQUIREMENT", "raw": "건축(또는 토목건축)공사업 등록업체", "reason": "ALTERNATIVE_OR_EXCEPTION_RULE"}
    result = _result([clause, dict(clause, raw="건축(또는 토목건축)공사업  등록업체")])
    assert result.coverage.unrepresentable == 1
    assert len(result.coverage.gaps) == 1
