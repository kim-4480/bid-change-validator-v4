"""회사 규모 조건이 어떤 모양으로 와도 같은 COMPANY_SIZE 가 되는지.

[재현 2026-09-15, 골든 17개 실측] 같은 사실이 실행마다 세 모양으로 갈렸다 —

    COMPANY_SIZE "중·소기업·소상공인"                 (규모 요건)
    REGISTRATION_CERTIFICATION "중·소기업·소상공인확인서"  (증빙 서류를 인증으로)
    DETAIL_NOT_FOUND_IN_SOURCE 기업규모_raw            (법령 인용 사이의 값을 못 찾음)

7개 공고가 이것으로 흔들렸다. 게다가 첫째 모양조차 판정기의 alias 표("소기업"·"중소기업"…
다섯 낱말)에 없는 값이라 문자열 비교로 떨어져 **SMALL 회사가 UNSATISFIED** 를 받았다.
둘째는 회사 인증 목록과 대조되니 같은 틀린 미달이다. 골든셋은 전부 COMPANY_SIZE 로 본다.

규모 낱말은 다섯 개뿐인 닫힌 어휘다. 이어 붙인 값은 허용 집합의 합집합이고, 그것이 정확히
한 낱말의 집합이면 그 낱말로 정규화한다. 판정 코드는 손대지 않는다.
"""

from __future__ import annotations

from datetime import date

import pytest

from bidengine.requirements.legacy_slots import adapt_legacy_slot
from bidengine.requirements.legacy_slots import company_size_alias
from bidengine.requirements.legacy_slots import is_company_size_certificate_name
from bidengine.labeling.requirement_extraction import validate_extracted_slot
from bidengine.judgment.rules import CompanyProfileSnapshot
from bidengine.judgment.rules import judge_requirement


def _small_company() -> CompanyProfileSnapshot:
    return CompanyProfileSnapshot.model_validate({
        "company_id": "C-1", "company_size": "SMALL", "industries": [], "certifications": [],
        "completeness": {
            "certifications": True, "company_size": True, "industries": True,
            "performances": True, "region": True, "staff_roles": True, "staff_total": True,
        },
    })


@pytest.mark.parametrize("text, expected", [
    ("중·소기업·소상공인", "중소기업"),          # 01685616 — 골든 allowed [MICRO, SMALL, MEDIUM]
    ("중소기업자 및 소상공인", "중소기업"),        # 01626459
    ("소기업·소상공인", "소기업"),               # 01634767·01699215 — 골든 allowed [MICRO, SMALL]
    ("중소기업.소상공인확인서", "중소기업"),       # 01699574
    ("「중소기업기본법」 제2조에 따른 소상공인", "소상공인"),  # 법령명 안의 '중소기업' 은 안 센다
    ("대기업", "대기업"),
    ("대기업 및 중견기업", None),               # 어느 한 낱말의 집합과도 안 맞음 — 손대지 않는다
    ("ISO 9001", None),
])
def test_joined_size_words_normalize_to_the_single_alias_with_the_same_allowed_set(text, expected) -> None:
    assert company_size_alias(text) == expected


def test_a_size_certificate_name_is_recognized_but_a_real_certification_is_not() -> None:
    assert is_company_size_certificate_name("소기업·소상공인확인서")
    assert is_company_size_certificate_name("중·소기업·소상공인확인서")
    assert not is_company_size_certificate_name("ISO 9001")
    assert not is_company_size_certificate_name("직접생산확인증명서")
    assert not is_company_size_certificate_name("소기업 및 ISO 9001 인증")


def test_the_size_requirement_value_is_normalized_so_the_judge_can_read_it() -> None:
    """정규화 전에는 SMALL 회사가 UNSATISFIED 를 받았다(2026-09-15 실행으로 확인)."""
    requirements, _ = adapt_legacy_slot(
        {"유형": "기업규모요건", "raw": "◦ 중·소기업·소상공인으로서 확인서를 소지한 자", "기업규모_raw": "중·소기업·소상공인"},
        notice_version_id="NV-1", key_prefix="R",
    )

    assert [(i.type, i.value) for i in requirements] == [("COMPANY_SIZE", "중소기업")]
    judged = judge_requirement(requirements[0], _small_company(), preflight_case_id="X", reference_date=date(2026, 9, 15))
    assert judged.status == "SATISFIED"


def test_a_size_certificate_classified_as_certification_becomes_a_size_requirement() -> None:
    """01634767 run — "소기업·소상공인확인서" 를 인증요건으로 냈다. 인증 목록과 대조하면 미달이다."""
    requirements, diagnostics = adapt_legacy_slot(
        {
            "유형": "인증요건",
            "raw": "「중·소기업·소상공인 및 장애인기업 확인요령」에 따라 발급된 소기업·소상공인확인서를 소지한 자",
            "등록인증_raw": "소기업·소상공인확인서",
        },
        notice_version_id="NV-1", key_prefix="R",
    )

    assert [(i.type, i.value) for i in requirements] == [("COMPANY_SIZE", "소기업")]
    assert [d["code"] for d in diagnostics] == ["COMPANY_SIZE_FROM_CERTIFICATE"]
    judged = judge_requirement(requirements[0], _small_company(), preflight_case_id="X", reference_date=date(2026, 9, 15))
    assert judged.status == "SATISFIED"


def test_a_real_certification_is_still_a_certification() -> None:
    requirements, _ = adapt_legacy_slot(
        {"유형": "인증요건", "raw": "ISO 9001 인증을 보유한 업체", "등록인증_raw": "ISO 9001"},
        notice_version_id="NV-1", key_prefix="R",
    )
    assert [(i.type, i.value) for i in requirements] == [("REGISTRATION_CERTIFICATION", "ISO 9001")]


def test_a_large_business_exclusion_keeps_its_exclude_scope_and_raw_value() -> None:
    """참여 제한 조항은 기존 EXCLUDE 경로 그대로. "대기업 및 중견기업" 은 한 낱말로 안 줄어든다."""
    requirements, _ = adapt_legacy_slot(
        {"유형": "기업규모요건", "raw": "대기업 및 중견기업 참여 제한", "기업규모_raw": "대기업 및 중견기업"},
        notice_version_id="NV-1", key_prefix="R",
    )
    assert requirements[0].value == "대기업 및 중견기업"
    assert requirements[0].scope.get("restriction") == "EXCLUDE"


def test_both_shapes_from_one_notice_collapse_into_one_size_requirement() -> None:
    """01685616 — 규모 요건과 확인서 인증이 둘 다 나왔다. 정규화되면 값이 같아 하나로 접힌다."""
    from bidengine.requirements.canonicalize import canonicalize_validated_slots

    blocks = [{"document_id": "doc", "block_index": 0, "page": 1, "location": "p.1"}]
    result = canonicalize_validated_slots([
        {"유형": "기업규모요건", "raw": "중·소기업·소상공인으로서", "기업규모_raw": "중·소기업·소상공인",
         "_source_blocks": blocks, "_source_chunk_id": "C1"},
        {"유형": "인증요건", "raw": "중·소기업·소상공인확인서를 소지한 자", "등록인증_raw": "중·소기업·소상공인확인서",
         "_source_blocks": blocks, "_source_chunk_id": "C1"},
    ], notice_version_id="NV-1")

    assert [(i.type, i.value) for i in result["requirements"]] == [("COMPANY_SIZE", "중소기업")]


def test_a_size_detail_split_by_a_statute_citation_is_still_found_in_source() -> None:
    """01694234 — 원문은 "「중소기업기본법」 제2조에 따른 중·소기업자 또는 「소상공인…법률」 제2조에
    따른 소상공인" 인데 모델은 "중·소기업자 또는 소상공인" 으로 적는다. 이어붙인 문자열은 원문에
    없지만 조각은 다 있다. 규모 필드는 '또는' 로도 쪼개 조각마다 확인한다."""
    source = (
        "바. 「중소기업기본법」 제2조에 따른 중·소기업자 또는 「소상공인 보호 및 지원에 관한 법률」 "
        "제2조에 따른 소상공인으로서 「중소기업 범위 및 확인에 관한 규정」에 따라 확인서를 제출한 자"
    )
    chunks = [{"chunk_id": "A", "text": source, "source_blocks": [], "clause_label": "바"}]
    slot = {"유형": "기업규모요건", "raw": source, "기업규모_raw": "중·소기업자 또는 소상공인"}

    ok, reason, _ = validate_extracted_slot(slot, chunks)

    assert ok, reason
