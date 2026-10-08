"""공백(확인 필요) 가려내기 — 2026-10-07 표본 h·g 의 실제 공고 문장."""
from types import SimpleNamespace as NS

import pytest

from bidengine.pipeline.gap_triage import classify_gap, triage_gaps


@pytest.mark.parametrize("raw, reason", [
    ("-" * 60 + " 아래의 입찰참가자격을 모두 갖춘 자이어야 합니다.", "LIST_INTRO"),
    ("※ 입찰참가자격 공지사항 ◐ 다음 중 어느 하나에 해당하는 자는 입찰참가자격이 없음", "LIST_INTRO"),
    ("4. 입찰참가자격", "HEADING"),
    ("6 . 예정가격 및 낙찰자 결정방법", "HEADING"),
    ("이어야 합니다 .", "FRAGMENT_OF_CLAUSE"),
    ("② 입 찰 참 가 자 격 제 한 기 간 중 에 있 는 자 ( 법 제 3 1 조 제 5 항 에 해 당 되 는 경 우 예 외 )", "COMMON_DISQUALIFICATION"),
    ("1 . 지 방 자 치 단 체 의 장 또 는 지 방 의 회 의 원 의 배 우 자 인 사 업 자", "COMMON_DISQUALIFICATION"),
    ("1 . 경쟁입찰에 있어서 특정인의 낙찰을 위하여 담합을 주도한 자는 부산광역시에서 발주하는 입찰에 입찰 참가자격제한 처분을 받은 날부터 1 년동안 참가하지 못한다 .",
     "COMMON_DISQUALIFICATION"),
    ("※ 지방자치단체를 당사자로 하는 계약에 관한 법률 제33조에 해당되는 자 또는 지방자치단체 수의계약운영요령(행정안전부 예규)",
     "COMMON_DISQUALIFICATION"),
    ("가. 「국가를 당사자로 하는 계약에 관한 법률 시행령」 제12조의 규정에 의한 요건을 갖춘 자로서", "STATUTE_BASELINE"),
    ("나. 『지방자치단체를 당사자로 하는 계약에 관한 법률시행령』제13조의 자격 요건을 구비하고 조달청에 입찰 참가자격이 등록된 업체이어야 합니다.",
     "STATUTE_BASELINE"),
    ("마. 공동수급이 허용되지 않습니다.", "JOINT_CONTRACT_NOTE"),
    ("- 공동수급체 구성원은 대표사를 포함하여 5개사 이하로 구성하여야 하며, 구성원별 계약참여 최소지분율은 10% 이상으로 하여야 합니다.",
     "JOINT_CONTRACT_NOTE"),
    ("○ (입찰보증금 납부) 입찰참가자는 반드시 이 건 입찰공고의 입찰보증금 내용을 숙지하시기 바랍니다.", "PROCEDURE"),
])
def test_noise_is_moved_with_a_reason(raw, reason):
    assert classify_gap(raw) == reason


@pytest.mark.parametrize("raw", [
    "다. 납품할 종자를 생산할 수 있는 생산시설(친어지, 부화지, 치어사육지)을 갖춘 자로서 납품할 종자를 직접 자가생산하며",
    "※ 본 과업과 관련된 행사기획 및 대행서비스에 해당하는 직접생산확인증명서에 한함.",
    "○ 단일 급식장* 기준 1일 평균 700명 이상의 집단급식(장) 운영실적이 있는 자",
    "제조사 기술지원 확약서 1부",
    # 닫힌 값(지역)이 있으면 공통 결격 낱말이 있어도 남긴다 — 실제 지역 자격일 수 있다.
    "제92조에 해당되지 않으며, 법인등기부상 소재지가 전주시인 업체",
    # 공동수급 조건이라도 지역이 걸리면 실제 자격이다.
    "공동수급체 구성원 중 1개사 이상은 본점 소재지가 강원특별자치도인 업체이어야 함",
])
def test_real_conditions_stay(raw):
    assert classify_gap(raw) is None


def test_structural_reasons_are_not_second_guessed():
    assert classify_gap("A 또는 B 등록", reason="ALTERNATIVE_OR_EXCEPTION_RULE") is None
    assert classify_gap("A 또는 B 등록") == "HEADING"


def test_duplicates_and_pdf_fragments_are_merged():
    full = "가. 「지방자치단체를 당사자로 하는 계약에 관한 법률 시행령」 제13조 및 동법률 시행규칙 제14조의 규정에 의한 자격을 갖추고, 주된 영업소의 소재지가 강원특별자치도에 있는 업체"
    gaps = [
        NS(kind="UNCLASSIFIED", raw="다. 생산시설을 갖춘 자", reason=None),
        NS(kind="UNCLASSIFIED", raw="다 . 생산시설을 갖춘 자", reason=None),
        NS(kind="UNREPRESENTABLE", raw="가 . 「 지방자치단체를 당사자로 하는 계약에 관한 법률 시행령 」 제 13 조 및 동법률 시행규칙", reason="X"),
        NS(kind="DROPPED", raw="가. 【전문소방시설공사업】또는【일반소방시설공사업】 면허", reason=None),
        NS(kind="DROPPED", raw="가 . 【 전문소방시설공사업 】 또는 【 일반소방시설공사업 】 면허", reason=None),
    ]
    kept, moved = triage_gaps(gaps, [NS(raw=full, type="REGION")])
    assert [g.raw for g in kept] == ["다. 생산시설을 갖춘 자", "가. 【전문소방시설공사업】또는【일반소방시설공사업】 면허"]
    assert sorted(reason for _gap, reason in moved) == ["DUPLICATE", "DUPLICATE", "FRAGMENT_OF_CLAUSE"]


@pytest.mark.parametrize("raw, reason", [
    ("다. 「지방자치단체를 당사자로 하는 계약에 관한 법률」 제31조의5 및 같은 법 시행령", "STATUTE_FRAGMENT"),
    ("① 우리 의학원 계약업무요령 제16조(참가자격), 제26조(입찰참가제한)의 규정에 의한 입찰참가자격요건을 갖춘 업체.", "STATUTE_BASELINE"),
    ("7. 입찰참가 신청자로서 정당한 사유 없이 입찰에 불참한 자", "COMMON_DISQUALIFICATION"),
    ("○ 입찰참가자격등록증상의 상호 및 대표자가 법인등기부등본상의 상호, 대표자와 다른 경우 변경등록하고 입찰에 참여하여야 합니다.", "PROCEDURE"),
])
def test_more_noise_found_on_unused_notices(raw, reason):
    """2026-10-08 표본 j 에서 쓸모없는 확인 문장이 붙었던 공백."""
    assert classify_gap(raw) == reason


def test_joint_contract_sentences_anywhere_in_the_documents_become_notes():
    from bidengine.pipeline.analysis_pipeline import with_document_notes
    from bidengine.pipeline.analysis_result import AnalysisCoverage, CoverageGap, RequirementAnalysisResult

    result = RequirementAnalysisResult(status="SUCCEEDED", notice_id="n", notice_version_id="v",
                                       coverage=AnalysisCoverage(section_selection="anchored"))
    chunks = [{"text": "2. 견적서 제출 및 계약방식\n라. 공동도급은 허용하지 않습니다.\n마. 노무비 구분관리 대상 공사입니다."},
              {"text": "라 . 공동도급은 허용하지 않습니다 ."}]          # PDF 사본 — 한 번만
    notes = with_document_notes(result, chunks).coverage.notes
    assert [gap.raw for gap in notes] == ["라. 공동도급은 허용하지 않습니다."]
