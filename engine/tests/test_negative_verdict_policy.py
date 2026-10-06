"""미달은 닫힌 값 비교에서만 낸다 (ADR 0001 문제 4, docs/experiments/2026-09-30).

각 유형마다 (1) 닫힌 값이 안 맞으면 미달, (2) 자유 문자열만 안 맞으면 확인 필요 +
비교한 회사 쪽 표현이 근거로 남는지를 고정한다.
"""
from __future__ import annotations

from datetime import date

import pytest

from bidengine.contracts import QualificationRequirement
from bidengine.judgment.rules import (
    NEGATIVE_VERDICT_BASIS,
    CompanyProfileSnapshot,
    ProfileCertificationFact,
    ProfileCompleteness,
    ProfileIndustryFact,
    ProfilePerformanceFact,
    ProfileStaffFact,
    ProfileStaffRoleFact,
    judge_requirement,
)

REF = date(2026, 9, 1)
COMPLETE = ProfileCompleteness(
    region=True, company_size=True, industries=True, staff_total=True,
    staff_roles=True, performances=True, certifications=True,
)


def _req(type_: str, value=None, operator="MATCH", **extra) -> QualificationRequirement:
    return QualificationRequirement(
        requirement_key="R", notice_version_id="v", type=type_, operator=operator, value=value,
        raw=extra.pop("raw", "원문"), **extra,
    )


def _profile(**update) -> CompanyProfileSnapshot:
    base = CompanyProfileSnapshot(
        company_id="c", region_name="부산광역시", company_size="SMALL",
        industries=[ProfileIndustryFact(code="0036", name="정보통신공사업")],
        staff=ProfileStaffFact(total_count=10, roles=[ProfileStaffRoleFact(role_name="SW개발자", headcount=4)]),
        performances=[
            ProfilePerformanceFact(ref="p1", name="OO병원 집단급식소 운영", amount=500_000_000,
                                   completed_at=date(2026, 3, 31), fields=["집단급식소 운영"]),
        ],
        certifications=[ProfileCertificationFact(ref="c1", name="정보보호 관리체계 인증(ISMS)",
                                                 certification_code="C-100", issuer_name="한국인터넷진흥원")],
        completeness=COMPLETE,
    )
    return base.model_copy(update=update)


def _judge(req, profile=None):
    return judge_requirement(req, profile or _profile(), preflight_case_id="t", reference_date=REF)


def test_every_judged_type_declares_its_negative_basis():
    assert set(NEGATIVE_VERDICT_BASIS) == {
        "REGION", "COMPANY_SIZE", "INDUSTRY", "STAFF", "PERFORMANCE_AMOUNT",
        "PERFORMANCE_COUNT", "EXPERIENCE_FIELD", "REGISTRATION_CERTIFICATION",
    }


@pytest.mark.parametrize(
    "req",
    [
        _req("REGION", "서울특별시"),
        _req("COMPANY_SIZE", "중견기업"),
        _req("INDUSTRY", "0001"),
        _req("STAFF", 20, operator=">="),
        _req("PERFORMANCE_AMOUNT", 900_000_000, operator=">=", period_months=24,
             scope={"experience_field": "집단급식소 운영"}),
        _req("REGISTRATION_CERTIFICATION", "1257", scope={"kind": "REGISTRATION"}),
    ],
    ids=["region", "size-alias", "industry-code", "staff-total", "amount", "cert-code"],
)
def test_closed_value_mismatch_is_unsatisfied(req):
    assert _judge(req).status == "UNSATISFIED"


@pytest.mark.parametrize(
    ("req", "compared"),
    [
        (_req("COMPANY_SIZE", "벤처기업"), "SMALL"),
        (_req("STAFF", 2, operator=">=", scope={"role": "소프트웨어 개발"}), "SW개발자"),
        (_req("PERFORMANCE_COUNT", 1, operator=">=", period_months=24,
              scope={"experience_field": "단체급식 운영"}), "OO병원 집단급식소 운영"),
        (_req("EXPERIENCE_FIELD", "단체급식 운영", period_months=24), "OO병원 집단급식소 운영"),
        (_req("REGISTRATION_CERTIFICATION", "ISMS-P 인증", scope={"kind": "CERTIFICATION"}),
         "정보보호 관리체계 인증(ISMS)"),
        (_req("REGISTRATION_CERTIFICATION", "ISMS", scope={"kind": "CERTIFICATION", "issuer": "KISA"}),
         "한국인터넷진흥원"),
    ],
    ids=["size-free-text", "staff-role", "count-field", "experience-field", "cert-name", "cert-issuer"],
)
def test_free_text_mismatch_is_needs_review_with_compared_values(req, compared):
    judgment = _judge(req)
    assert judgment.status == "UNKNOWN"
    assert judgment.reason_code == "NEEDS_REVIEW"
    assert compared in {ref["value"] for ref in judgment.profile_refs}


def test_having_nothing_at_all_is_still_unsatisfied():
    """비교할 회사 쪽 값이 아예 없으면 어휘 문제가 아니다."""
    empty = _profile(
        performances=[], certifications=[],
        staff=ProfileStaffFact(total_count=10, roles=[]),
    )
    assert _judge(_req("EXPERIENCE_FIELD", "단체급식 운영", period_months=24), empty).status == "UNSATISFIED"
    # 등록·인증은 이름으로 요구하면 목록이 비어 있어도 확인 필요다(2026-10-06 정책 변경). 번호로 요구하면 미달이다.
    assert _judge(_req("REGISTRATION_CERTIFICATION", "ISMS-P 인증", scope={"kind": "CERTIFICATION"}), empty).status == "UNKNOWN"
    assert _judge(_req("REGISTRATION_CERTIFICATION", "4320140101", scope={"kind": "REGISTRATION"}), empty).status == "UNSATISFIED"
    assert _judge(_req("STAFF", 2, operator=">=", scope={"role": "소프트웨어 개발"}), empty).status == "UNSATISFIED"


def test_expired_certification_is_unsatisfied_even_when_named():
    expired = _profile(certifications=[ProfileCertificationFact(
        ref="c1", name="ISMS", expires_at=date(2025, 1, 1), issuer_name="한국인터넷진흥원")])
    assert _judge(_req("REGISTRATION_CERTIFICATION", "ISMS", scope={"kind": "CERTIFICATION"}), expired).status == "UNSATISFIED"
