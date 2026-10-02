"""PDF 가 남긴 쪽 번호·줄바꿈이 대조와 저장 값을 흔들지 않는지.

[재현 2026-09-15]
- 우치공원 1/5 PARTIAL: 중대재해처벌법 조항 한가운데 쪽 번호 "- 4 -" 가 끼어 대조 본문이
  "종사자의-4-안전" 이 됐고, 모델은 마커 없이 인용하니 RAW_NOT_FOUND 로 버려졌다.
- REGION 값 "전북특⏎별자치도", raw "…재활용업⏎(6770)또는…" — 낱말 안 줄바꿈이 값에 남아
  화면에 그대로 보이고, 같은 조항의 raw 지문이 실행마다 줄바꿈 위치만 달랐다.
쪽 번호는 공고의 말이 아니고, 줄바꿈은 종이의 사정이다. 둘 다 걷어낸다.
"""

from __future__ import annotations

from bidengine.labeling.requirement_extraction import (
    _squash,
    join_wrapped_lines,
    snap_to_source_span,
    validate_extracted_slot,
)


SAFETY_CLAUSE = (
    "가. 본 입찰에 참가하고자 하는 자는 「중대재해처벌 등에 관한 법률」에 따라 종사자의\n"
    "- 4 -\n"
    "안전‧보건상 유해 또는 위험을 방지하고 그 이용자 또는 그 밖의 사람의 생명‧신체의 안전을 위해 "
    "해당 사업의 특성 및 규모 등을 고려하여 다음과 같이 조치사항을 이행하여야 합니다."
)


def test_a_page_number_line_is_not_part_of_the_text_for_comparison() -> None:
    assert "-4-" not in _squash(SAFETY_CLAUSE)
    # 날짜 같은 하이픈 숫자는 줄 전체가 아니라 그대로 남는다.
    assert "2026-09-15" in _squash("제출기한 2026-09-15 까지")


def test_a_quote_that_skips_the_page_number_is_still_found_in_source() -> None:
    """우치공원 run — 모델은 쪽 번호 없이 인용했다. 전에는 RAW_NOT_FOUND 였다."""
    model_raw = (
        "가. 본 입찰에 참가하고자 하는 자는 「중대재해처벌 등에 관한 법률」에 따라 종사자의 "
        "안전‧보건상 유해 또는 위험을 방지하고 그 이용자 또는 그 밖의 사람의 생명‧신체의 안전을 위해 "
        "해당 사업의 특성 및 규모 등을 고려하여 다음과 같이 조치사항을 이행하여야 합니다."
    )
    chunks = [{"chunk_id": "A", "text": SAFETY_CLAUSE, "source_blocks": [], "clause_label": "가"}]
    slot = {"유형": "기타요건", "raw": model_raw}

    ok, reason, _ = validate_extracted_slot(slot, chunks)

    assert ok, reason
    assert "- 4 -" not in slot["raw"] and "\n" not in slot["raw"]


def test_a_value_wrapped_inside_a_word_is_joined_without_a_space() -> None:
    source = "주된 영업소의 소재지가 전북특\n별자치도에 있는 업체만 참가할 수 있다."
    assert snap_to_source_span("전북특별자치도", source) == "전북특별자치도"
    # 원래 띄어쓰기는 남고, 줄바꿈만 사라진다.
    assert join_wrapped_lines("폐기물중간재활용업\n(6770)또는 폐기물종합재활용업(6786) 등록업체") == (
        "폐기물중간재활용업(6770)또는 폐기물종합재활용업(6786) 등록업체"
    )


def test_stored_raw_is_single_line_after_validation() -> None:
    source = "1)「폐기물관리법」 제25조에 따른 폐기물중간처분업 (1257) 또는 폐기물중간재활용업\n(6770)또는 폐기물종합재활용업(6786) 등록업체"
    chunks = [{"chunk_id": "A", "text": source, "source_blocks": [], "clause_label": "1"}]
    slot = {"유형": "업종요건", "raw": source, "업종_raw": "폐기물중간처분업"}

    ok, reason, _ = validate_extracted_slot(slot, chunks)

    assert ok, reason
    assert "\n" not in slot["raw"]
    assert slot["raw"].endswith("폐기물중간재활용업(6770)또는 폐기물종합재활용업(6786) 등록업체")


def test_a_region_value_loses_its_descriptive_tail() -> None:
    """우치공원 1/5 — 모델이 지역값을 "전남광주통합특별시에 소재한 업체" 로 냈다. 값이 달라져
    지문이 갈렸다. 지역명은 행정구역 이름이지 문장이 아니다."""
    from bidengine.requirements.legacy_slots import adapt_legacy_slot

    for tail in ("전남광주통합특별시에 소재한 업체", "전남광주통합특별시 소재 업체", "전남광주통합특별시에 있는 자", "전남광주통합특별시"):
        requirements, _ = adapt_legacy_slot(
            {"유형": "지역요건", "raw": f"본점소재지를 {tail}", "지역_raw": tail},
            notice_version_id="NV-1", key_prefix="R",
        )
        assert [(i.type, i.value) for i in requirements] == [("REGION", "전남광주통합특별시")], tail


def test_the_e_bidding_certificate_is_a_procedure() -> None:
    from bidengine.judgment.clause_safety import unsafe_clause_reason

    raw = ("라. 본 입찰은 신원확인 입찰이 적용되므로 전자입찰자는 개인인증수단과 지정 전자서명인증자로부터 "
           "발급받은 사업자용 인증서를 이용하여 전자조달시스템에 접속하여야 하며")
    assert unsafe_clause_reason(raw) == "LEGAL_PROCEDURAL_RULE"
    # 진짜 인증은 그대로.
    assert unsafe_clause_reason("ISO 9001 인증서를 보유한 업체") is None
