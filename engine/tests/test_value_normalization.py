"""추출 값의 표기 정규화 (docs/experiments/2026-10-01 모델 비교의 표기 흔들림)."""
from __future__ import annotations

from datetime import date

import pytest

from bidengine.contracts import QualificationRequirement
from bidengine.judgment.rules import CompanyProfileSnapshot, judge_requirement
from bidengine.requirements.legacy_slots import adapt_legacy_slot, normalize_value_text


@pytest.mark.parametrize(
    ("value", "req_type", "expected"),
    [
        ("직접생산확인증명서 ( 세부품명 : 정보시스템개발서비스 , 세부품명번호 : 8111159901)", "REGISTRATION_CERTIFICATION",
         "직접생산확인증명서(세부품명: 정보시스템개발서비스, 세부품명번호: 8111159901)"),
        ("직접생산확인증명서(세부품명 : 정보시스템개발서비스, 세부품명번호 : 8111159901)", "REGISTRATION_CERTIFICATION",
         "직접생산확인증명서(세부품명: 정보시스템개발서비스, 세부품명번호: 8111159901)"),
        ("정보통신부문의 정보통신분야에 엔지니어링 사업자", "REGISTRATION_CERTIFICATION", "정보통신부문의정보통신분야에엔지니어링사업자"),
        ("정보통신부문의 정보통신분야에엔지니어링사업자", "REGISTRATION_CERTIFICATION", "정보통신부문의정보통신분야에엔지니어링사업자"),
        ("ISO / IEC 27001", "REGISTRATION_CERTIFICATION", "ISO / IEC 27001"),
        ("경상남도  ", "REGION", "경상남도"),
    ],
)
def test_same_value_in_different_spacing_normalizes_to_one_form(value, req_type, expected):
    assert normalize_value_text(value, req_type=req_type) == expected


def test_generic_word_is_not_a_registration_requirement():
    slot = {"유형": "등록요건", "raw": "소프트웨어사업자로 신고 및 실적이 등록되어 있는 자", "등록인증_raw": "실적"}
    reqs, diags = adapt_legacy_slot(slot, notice_version_id="v", key_prefix="R")
    assert reqs == []
    assert [d["code"] for d in diags] == ["UNMAPPED_REGISTRATION_CERTIFICATION"]


@pytest.mark.parametrize("raw_value", ["대기업 및 중견기업 참여 제한", "대기업 및 중견기업"])
def test_size_restriction_tail_is_removed_from_value(raw_value):
    slot = {"유형": "기업규모요건", "raw": "대기업 및 중견기업 참여 제한", "기업규모_raw": raw_value}
    reqs, _ = adapt_legacy_slot(slot, notice_version_id="v", key_prefix="R")
    assert [(r.value, r.scope.get("restriction")) for r in reqs] == [("대기업 및 중견기업", "EXCLUDE")]


@pytest.mark.parametrize(
    ("size", "expected"),
    [("SMALL", "SATISFIED"), ("MEDIUM", "SATISFIED"), ("MID_SIZED", "UNSATISFIED"), ("LARGE", "UNSATISFIED")],
)
def test_size_conjunction_is_a_closed_set_under_exclusion(size, expected):
    """전: "대기업 및 중견기업" 은 문자열 비교로 떨어져 중견기업 회사가 충족이었다."""
    req = QualificationRequirement(
        requirement_key="R", notice_version_id="v", type="COMPANY_SIZE", operator="MATCH",
        value="대기업 및 중견기업", scope={"restriction": "EXCLUDE"}, raw="대기업 및 중견기업 참여 제한",
    )
    profile = CompanyProfileSnapshot(company_id="c", company_size=size)
    assert judge_requirement(req, profile, preflight_case_id="c", reference_date=date(2026, 9, 1)).status == expected
