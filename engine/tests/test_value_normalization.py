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


@pytest.mark.parametrize(
    ("value", "req_type", "expected"),
    [
        # 조항 단위 추출에서 같은 조항의 값이 이렇게 갈렸다(2026-10-01 실측)
        ("소프트웨어사업자로 신고 및 실적이 등록되어 있는 자", "REGISTRATION_CERTIFICATION", "소프트웨어사업자"),
        ("소프트웨어사업자로 신고 및 실적이 등록", "REGISTRATION_CERTIFICATION", "소프트웨어사업자"),
        ("건설기술진흥법에 의한 건축분야 고급기술자 이상의 자격소지자", "STAFF", "건축분야 고급기술자 이상의 자격소지자"),
        # 이름 자체는 건드리지 않는다
        ("소프트웨어사업", "REGISTRATION_CERTIFICATION", "소프트웨어사업"),
        ("ISO 9001", "REGISTRATION_CERTIFICATION", "ISO 9001"),
    ],
)
def test_statute_prefix_and_registration_predicate_are_not_part_of_the_name(value, req_type, expected):
    assert normalize_value_text(value, req_type=req_type) == expected


def test_staff_role_in_scope_is_normalized_with_the_value():
    slot = {"유형": "인력요건", "raw": "건설기술진흥법에 의한 건축분야 고급기술자 이상의 자격소지자",
            "인력역할_raw": "건설기술진흥법에 의한 건축분야 고급기술자 이상의 자격소지자"}
    reqs, _ = adapt_legacy_slot(slot, notice_version_id="v", key_prefix="R")
    assert {(r.value, r.scope.get("role")) for r in reqs} == {
        ("건축분야 고급기술자 이상의 자격소지자", "건축분야 고급기술자 이상의 자격소지자")
    }


@pytest.mark.parametrize(
    ("value", "req_type", "expected"),
    [
        # 이름 값에 조사와 서술이 딸려 왔다(2026-10-06 세 번째 표본 실측). 공백을 없애기 전에 걷는다.
        ("「철근·콘크리트공사업」면허를 보유한", "REGISTRATION_CERTIFICATION", "「철근·콘크리트공사업」면허"),
        ("직접생산확인증명서는", "REGISTRATION_CERTIFICATION", "직접생산확인증명서"),
        ("전기중형승합차(세부품명번호: 2510152103)로 입찰참가 등록", "REGISTRATION_CERTIFICATION", "전기중형승합차(세부품명번호: 2510152103)"),
        ("사업관리자(PM)는 공고일 이전부터 제안서 평가일까지 계속 재직자", "STAFF", "사업관리자(PM)"),
        ("병의원에 청소 용역 실적이 있는 업체", "EXPERIENCE_FIELD", "병의원 청소 용역 실적"),
        # 이름 글자인 '가'·'을'·'에' 는 건드리지 않는다
        ("전문가 보유", "STAFF", "전문가 보유"),
        ("마을기업", "REGISTRATION_CERTIFICATION", "마을기업"),
        ("에너지 진단", "EXPERIENCE_FIELD", "에너지 진단"),
    ],
)
def test_particles_and_predicates_after_a_name_are_removed(value, req_type, expected):
    assert normalize_value_text(value, req_type=req_type) == expected
