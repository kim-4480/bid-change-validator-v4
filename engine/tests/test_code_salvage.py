"""모델이 업종코드 조항을 빠뜨려도 요건이 판정기에 닿는지.

[재현 2026-09-15] 같은 공고를 3회 돌리면 모델이 어떤 실행에서는 업종 조항을 아예 안 올린다.
구내식당은 "영업신고(업종코드 : 1450)" 슬롯이, 남원글로컬은 "(1257) 또는 (6770) 또는
(6786)" 조항이 통째로 빠졌다. 원문의 숫자는 그대로인데. 모델이 빠뜨린 것을 코드가 채운다.
"""

from __future__ import annotations

from bidengine.pipeline.analysis_pipeline import (
    QualificationAnalysisInput,
    QualificationDocumentInput,
    analyze_qualification_documents,
)
from bidengine.labeling.code_salvage import (
    exception_guarded_codes,
    industry_codes_in,
    salvage_missing_industry_slots,
)


CAFETERIA = (
    "3. 입찰 참가 자격\n"
    "가. 국가를 당사자로 하는 계약에 관한 법률 시행령 제12조에 의한 자격을 갖춘 업체\n"
    "나. 식품위생법에 의거 단체급식업 등록업체로서 식당허가 등에 결격사유가 없는 업체 "
    "식품위생법에 따른 인·허가를 득하고 동법 시행령에 따라 영업신고(업종코드 : 1450)를 하여 "
    "집단급식소 영업이 가능한 법인사업자\n"
    "다. 입찰 공고일 기준 2년 내에 2개 이상 각 단체급식소※(1일 평균 800식 이상)를 1년 이상 운영한 실적이 있는 업체"
)

WASTE = (
    "3. 입찰 참가 자격\n"
    "○ 입찰서 제출 마감일 전일까지 나라장터에 아래 업종 중 해당 자격을 등록한 업체이어야 한다.\n"
    "1) 「폐기물관리법」 제25조에 따른 폐기물중간처분업(1257) 또는 폐기물중간재활용업(6770) 또는 폐기물종합재활용업(6786) 등록업체\n"
    "2) 폐기물수집·운반업(1227) 등록업체"
)


def _input(text: str) -> QualificationAnalysisInput:
    return QualificationAnalysisInput(
        notice_id="notice-1",
        notice_version_id="version-1",
        documents=[QualificationDocumentInput(
            document_id="doc-1",
            extracted_blocks=[{"block_index": 0, "page": 1, "location": "p.1", "text": text}],
        )],
    )


def test_codes_are_read_only_in_industry_context() -> None:
    assert industry_codes_in("영업신고(업종코드 : 1450)를 한 업체") == {"1450"}
    assert industry_codes_in("폐기물수집·운반업(1227) 등록업체") == {"1227"}
    assert industry_codes_in("2024년 6월 30일까지 (2026) 1500제곱미터") == set()


def test_exception_guarded_codes_reads_only_the_immediate_next_line() -> None:
    chunks = [{"chunk_id": "A", "text": (
        "1)「폐기물관리법」 제25조에 따른 폐기물중간처분업(1257) 등록업체\n"
        "2)「폐기물관리법」 제25조에 따른 폐기물수집·운반업(1227) 등록업체\n"
        "※ 단, 처분 허가를 보유한 경우 수집·운반업 등록을 갈음할 수 있다"
    )}]

    assert exception_guarded_codes(chunks) == {"1227"}


def test_exception_guarded_codes_joins_a_two_line_hint() -> None:
    """[재현 2026-09-15, 라이브 검수] J14 실제 DB 원문 그대로. "갈음"이 아니라 "요구하지
    않을 수 있다"로 적혀 있고, 단서 문장이 두 줄에 걸쳐 있다 — 첫 시도(갈음만 잡음, 한 줄만
    봄)는 이 원문에서 실패했다(라이브 5/5 로 1227 이 그대로 남음)."""
    chunks = [{"chunk_id": "A", "text": (
        "3 참가자격\n"
        "○ 「국가를 당사자로 하는 계약에 관한 법률 시행령」 제12조 및 같은 법 시행규칙 제14조에 따른\n"
        "자격을 갖추고, 국가종합전자조달시스템 입찰참가자격 등록을 마친 업체이어야 한다.\n"
        "※ 국가계약법 시행령 제12조는 경쟁입찰 참가자격에 관한 기본 조항입니다.\n"
        "○ 입찰서 제출 마감일 전일까지 나라장터에 아래 업종 중 해당 자격을 등록한 업체이어야 한다.\n"
        "1)「폐기물관리법 」 제25조에 따른 폐기물중간처분업 (1257) 또는 폐기물중간재활용업\n"
        "(6770)또는 폐기물종합재활용업(6786) 등록업체\n"
        "2)「폐기물관리법」 제25조에 따른 폐기물수집·운반업(1227) 등록업체\n"
        "※ 단, 처분 또는 재활용업 허가를 받은 업체가 관계 법령상 해당 폐기물을 직접 수집·운반할 수 있는\n"
        "장비·허가 조건을 갖춘 경우에는 수집·운반업 등록을 별도로 요구하지 않을 수 있다.\n"
        "※ 최종 공고 전 나라장터 업종코드는 계약담당부서에서 반드시 재확인하여 기재한다.\n"
        "※ 「폐기물관리법」 제25조는 폐기물의 수집·운반, 재활용 또는 처분을 업으로 하려는 경우 폐\n"
        "기물처리업 관련 절차를 두고 있습니다."
    )}]

    guarded = exception_guarded_codes(chunks)

    # 1227 만 걸린다 — 1)의 대안 코드(1257/6770/6786)는 다음 줄이 단서가 아니라 걸리지 않고,
    # "국가종합전자조달시스템 입찰참가자격 등록" 뒤의 순수 설명 각주도 안 걸린다.
    assert guarded == {"1227"}


def test_a_code_after_a_second_parenthetical_is_read_and_a_mixed_sentence_keeps_it() -> None:
    """[재현 2026-09-15, 골든 J20 01684825] "기타자유업(행사대행업)(9901)" — 업종명 뒤에 설명
    괄호가 하나 더 있다. 같은 문장에 나라장터 절차 문구가 붙어 있어 문장 전체가 절차로
    막혔고 salvage 도 이 괄호 모양을 못 읽어 0건이 됐다. 골든은 INDUSTRY 9901 을 기대한다."""
    real = (
        "가. 국가종합전자조달시스템입찰참가자격등록규정에 따라 반드시 전자입찰서 제출마감일 전일까지 "
        "나라장터(G2B시스템)에 아래의 사항을 입찰참가자격으로 등록한 자\n"
        "-[기타자유업(행사대행업)(9901)] 업종을 등록한 업체"
    )
    assert industry_codes_in(real) == {"9901"}

    result = analyze_qualification_documents(_input(real), structured_extract=lambda *a: {"requirements": []})

    assert [(i.type, i.value) for i in result.requirements if i.type == "INDUSTRY"] == [("INDUSTRY", "9901")]


def test_a_continuation_line_without_exception_words_does_not_guard() -> None:
    """단서 줄이라고 다 예외는 아니다 — "관공서와 기업체에 한함" 처럼 대상을 좁히는 것뿐인
    단서는 갈음·대체가 아니다. 코드를 억지로 막지 않는다."""
    chunks = [{"chunk_id": "A", "text": (
        "가. 영업신고(업종코드 : 1450)를 하여 집단급식소 영업이 가능한 법인사업자\n"
        "※ 관공서와 기업체에 한함(병원, 학교, 군부대, 사회복지시설 등 제외)"
    )}]

    assert exception_guarded_codes(chunks) == set()


def test_the_omitted_cafeteria_code_is_filled_from_source() -> None:
    """구내식당 run2 그대로 — 모델이 '나.' 조항의 1450 슬롯을 안 냈다."""
    def model_omits_industry(system, body, schema):
        return {"requirements": [{
            "유형": "실적요건",
            "raw": "다. 입찰 공고일 기준 2년 내에 2개 이상 각 단체급식소※(1일 평균 800식 이상)를 1년 이상 운영한 실적이 있는 업체",
            "경험분야_raw": "각 단체급식소※(1일 평균 800식 이상)를 1년 이상 운영",
            "근거조항": "다",
        }]}

    result = analyze_qualification_documents(_input(CAFETERIA), structured_extract=model_omits_industry)

    industries = [item for item in result.requirements if item.type == "INDUSTRY"]
    assert [item.value for item in industries] == ["1450"]
    assert "영업신고(업종코드 : 1450)" in industries[0].raw
    # 빠뜨렸다는 사실은 남고, 분석 상태를 PARTIAL 로 끌어내리지는 않는다.
    assert any(d.code == "INDUSTRY_CODE_SALVAGED_FROM_SOURCE" for d in result.diagnostics)
    assert result.status == "SUCCEEDED"


def test_the_omitted_alternation_clause_becomes_an_any_of_group() -> None:
    """남원글로컬 run0 그대로 — 업종 조항이 통째로 없다. '또는' 관계까지 살아야 한다."""
    def model_omits_everything_industrial(system, body, schema):
        return {"requirements": []}

    result = analyze_qualification_documents(_input(WASTE), structured_extract=model_omits_everything_industrial)

    by_value = {item.value: item for item in result.requirements if item.type == "INDUSTRY"}
    assert set(by_value) == {"1257", "6770", "6786", "1227"}
    assert {by_value[c].group_operator for c in ("1257", "6770", "6786")} == {"ANY_OF"}
    assert by_value["1227"].group_operator == "ALL_OF"


def test_nothing_is_added_when_the_model_already_covered_the_code() -> None:
    """모델이 냈으면 코드는 가만히 있는다. 두 번 만들면 중복이고 개수가 부푼다."""
    def model_covers(system, body, schema):
        return {"requirements": [{
            "유형": "업종요건",
            "raw": "식품위생법에 따른 인·허가를 득하고 동법 시행령에 따라 영업신고(업종코드 : 1450)를 하여 집단급식소 영업이 가능한 법인사업자",
            "업종_raw": "집단급식소",
            "근거조항": "나",
        }]}

    result = analyze_qualification_documents(_input(CAFETERIA), structured_extract=model_covers)

    assert [item.value for item in result.requirements if item.type == "INDUSTRY"] == ["1450"]
    assert not any(d.code == "INDUSTRY_CODE_SALVAGED_FROM_SOURCE" for d in result.diagnostics)


def test_a_duplicated_clause_across_documents_is_salvaged_once() -> None:
    chunks = [
        {"chunk_id": "A", "text": "나. 영업신고(업종코드 : 1450)를 한 업체", "source_blocks": [], "clause_label": "나"},
        {"chunk_id": "B", "text": "나. 영업신고(업종코드 : 1450)를 한 업체", "source_blocks": [], "clause_label": "나"},
    ]

    salvaged = salvage_missing_industry_slots(set(), chunks)

    assert len(salvaged) == 1
    assert salvaged[0]["_salvaged_codes"] == ["1450"]


def test_a_clause_the_model_emitted_but_mapping_could_not_use_is_still_filled() -> None:
    """[재현 2026-09-15 J14 run0] 모델이 "○ … 1) A(1257) 또는 B(6770) 또는 C(6786) 등록업체
    2) D(1227) 등록업체" 문단을 통째로 한 슬롯에 담았다. 마지막 조각에 코드가 둘이라 ANY_OF 로
    못 풀려 UNMAPPED. 모델이 냈다는 이유로 건너뛰면 네 코드가 영영 안 채워진다."""
    def model_emits_whole_paragraph(system, body, schema):
        return {"requirements": [{
            "유형": "등록요건",
            "raw": ("○ 입찰서 제출 마감일 전일까지 나라장터에 아래 업종 중 해당 자격을 등록한 업체이어야 한다.\n"
                    "1) 「폐기물관리법」 제25조에 따른 폐기물중간처분업(1257) 또는 폐기물중간재활용업(6770) 또는 폐기물종합재활용업(6786) 등록업체\n"
                    "2) 폐기물수집·운반업(1227) 등록업체"),
            "등록인증_raw": None,
            "근거조항": None,
        }]}

    result = analyze_qualification_documents(_input(WASTE), structured_extract=model_emits_whole_paragraph)

    by_value = {item.value: item for item in result.requirements if item.type == "INDUSTRY"}
    assert set(by_value) == {"1257", "6770", "6786", "1227"}
    # 모델 슬롯은 못 썼고 코드가 채웠다. 그 사실이 상태와 진단에 남는다.
    assert result.status == "PARTIAL"
    assert any(d.code == "INDUSTRY_CODE_SALVAGED_FROM_SOURCE" for d in result.diagnostics)


def test_a_code_at_the_start_of_a_wrapped_line_is_not_a_new_item() -> None:
    """실제 J14 원문 그대로. "(6770)" 이 줄머리에 오고 "※ 단, …또는…" 단서가 따라온다.
    네 자리를 항목 기호로 보면 '또는' 조항이 두 동강 나고, 단서를 붙이면 가드에 막힌다.

    [검수 3차 2026-09-15] 1227 은 이제 요건으로 안 나온다 — 바로 다음 줄의 "갈음" 단서 때문에
    무조건 필수가 아니라 대안이 있는 조건이다(골든셋 J13/J14/J15/J16 이 그렇게 본다).
    """
    real = (
        "3 참가자격\n"
        "○ 입찰서 제출 마감일 전일까지 나라장터에 아래 업종 중 해당 자격을 등록한 업체이어야 한다.\n"
        "1)「폐기물관리법 」 제25조에 따른 폐기물중간처분업 (1257) 또는 폐기물중간재활용업\n"
        "(6770)또는 폐기물종합재활용업(6786) 등록업체\n"
        "2)「폐기물관리법」 제25조에 따른 폐기물수집·운반업(1227) 등록업체\n"
        "※ 단, 처분 또는 재활용업 허가를 보유한 경우 수집·운반업 등록을 갈음할 수 있다"
    )

    result = analyze_qualification_documents(_input(real), structured_extract=lambda *a: {"requirements": []})

    by_value = {item.value: item for item in result.requirements if item.type == "INDUSTRY"}
    assert set(by_value) == {"1257", "6770", "6786", "1227"}
    assert {by_value[c].group_operator for c in ("1257", "6770", "6786")} == {"ANY_OF"}
    # 1227 은 지워지지 않고 구조에 새겨진다 — composite(확인 필요) + 사유. 판정기는 이 행을
    # UNKNOWN 으로 둔다. 분석 상태는 PARTIAL 로 안 내린다(불확실성은 행이 들고 있다).
    assert by_value["1227"].condition_complexity == "composite"
    assert by_value["1227"].scope.get("guard_reason") == "EXCEPTION_UNRESOLVED"
    assert {by_value[c].condition_complexity for c in ("1257", "6770", "6786")} == {"simple"}
    assert any(
        d.code == "INDUSTRY_CODE_EXCEPTION_UNRESOLVED" and d.details.get("value") == "1227"
        for d in result.diagnostics
    )
    assert result.status == "SUCCEEDED"


def test_the_exception_hint_is_caught_regardless_of_what_the_model_raw_contains() -> None:
    """[재현 2026-09-15, 검수 3차] 코덱스가 이 단서를 모델 raw 에 다시 붙이는 실험을 했을 때,
    모델이 그 줄을 raw 에 담았는지 여부에 실행 결과가 갈렸다(5/5 → 4/5). 여기서는 모델이
    1227 을 "단서 없는 깨끗한 raw" 로 직접 냈다고 가정해도 — 원문 청크에 단서가 있으면
    코드가 걸러낸다. 모델 출력과 무관하게 매번 같다."""
    real = (
        "3 참가자격\n"
        "1)「폐기물관리법」 제25조에 따른 폐기물중간처분업(1257) 등록업체\n"
        "2)「폐기물관리법」 제25조에 따른 폐기물수집·운반업(1227) 등록업체\n"
        "※ 단, 처분 허가를 보유한 경우 수집·운반업 등록을 갈음할 수 있다"
    )

    def model_emits_plain_1227(system, body, schema):
        return {"requirements": [{
            "유형": "업종요건",
            "raw": "2)「폐기물관리법」 제25조에 따른 폐기물수집·운반업(1227) 등록업체",
            "업종_raw": "폐기물수집·운반업",
            "근거조항": "2",
        }]}

    result = analyze_qualification_documents(_input(real), structured_extract=model_emits_plain_1227)

    row = next(item for item in result.requirements if item.type == "INDUSTRY" and item.value == "1227")
    assert row.condition_complexity == "composite"
    assert any(d.code == "INDUSTRY_CODE_EXCEPTION_UNRESOLVED" for d in result.diagnostics)
