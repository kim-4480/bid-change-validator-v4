from datetime import date

from bidengine.contracts import QualificationRequirement
from bidengine.contracts import Judgment
from bidengine.judgment.rules import (
    CompanyProfileSnapshot,
    ProfileCertificationFact,
    ProfileCompleteness,
    ProfilePerformanceFact,
    ProfileStaffFact,
    ProfileStaffRoleFact,
    judge_requirements,
)

REFERENCE_DATE = date(2026, 9, 7)


def _requirement(key: str, req_type: str, *, operator: str = "MATCH", value=None, scope=None, period_months=None, group_key=None, group_operator="ALL_OF"):
    return QualificationRequirement(requirement_key=key, requirement_group_key=group_key or f"{key}-GROUP", group_operator=group_operator, notice_version_id="version-1", type=req_type, operator=operator, value=value, scope=scope or {}, period_months=period_months, raw=f"raw:{key}")


def _profile(*, completeness: ProfileCompleteness | None = None, certifications=None):
    return CompanyProfileSnapshot(
        company_id="company-1",
        region_code="11",
        region_name="서울특별시",
        company_size="SMALL",
        staff=ProfileStaffFact(total_count=8, verified=True, roles=[ProfileStaffRoleFact(role_name="개발", headcount=5, verified=True)]),
        performances=[ProfilePerformanceFact(ref="performance-1", name="공공기관 정보시스템 구축", client_name="데모 공공기관", amount=500_000_000, completed_at=date(2026, 6, 30), fields=["공공기관 정보시스템 구축"], verified=True)],
        certifications=list(certifications or []),
        completeness=completeness or ProfileCompleteness(),
    )


def test_golden_baseline_keeps_missing_registration_unknown():
    requirements = [
        _requirement("REQ-REGION", "REGION", value="서울특별시"),
        _requirement("REQ-STAFF", "STAFF", operator=">=", value=5, scope={"role": "개발"}),
        _requirement("REQ-PERFORMANCE", "PERFORMANCE_AMOUNT", operator=">=", value=400_000_000, period_months=36, scope={"client_requirement": "공공기관", "aggregation": "UNSPECIFIED"}),
        _requirement("REQ-REGISTRATION", "REGISTRATION_CERTIFICATION", value="정보통신공사업", scope={"kind": "REGISTRATION"}),
    ]
    profile = _profile(completeness=ProfileCompleteness(staff_roles=True, performances=True, certifications=False))
    result = judge_requirements(requirements, profile, preflight_case_id="case-1", reference_date=REFERENCE_DATE)
    by_key = {item.requirement_key: item for item in result.judgments}
    assert by_key["REQ-REGION"].status == "SATISFIED"
    assert by_key["REQ-STAFF"].status == "SATISFIED"
    assert by_key["REQ-PERFORMANCE"].status == "SATISFIED"
    assert by_key["REQ-REGISTRATION"].status == "UNKNOWN"
    assert result.overall_status == "insufficient_data"


def test_changed_performance_threshold_becomes_unsatisfied_when_profile_is_complete():
    requirement = _requirement("REQ-PERFORMANCE", "PERFORMANCE_AMOUNT", operator=">=", value=600_000_000, period_months=36, scope={"client_requirement": "공공기관", "aggregation": "UNSPECIFIED"})
    result = judge_requirements([requirement], _profile(completeness=ProfileCompleteness(staff_roles=True, performances=True)), preflight_case_id="case-1", reference_date=REFERENCE_DATE)
    assert result.judgments[0].status == "UNSATISFIED"
    assert result.overall_status == "ineligible"


def test_changed_performance_threshold_stays_unknown_when_profile_is_incomplete():
    requirement = _requirement("REQ-PERFORMANCE", "PERFORMANCE_AMOUNT", operator=">=", value=600_000_000, period_months=36)
    result = judge_requirements([requirement], _profile(completeness=ProfileCompleteness(performances=False)), preflight_case_id="case-1", reference_date=REFERENCE_DATE)
    assert result.judgments[0].status == "UNKNOWN"
    assert result.overall_status == "insufficient_data"


def test_none_company_size_means_unknown_not_large_company_mismatch():
    requirement = _requirement("REQ-SIZE", "COMPANY_SIZE", value="중소기업")
    profile = _profile().model_copy(update={"company_size": "NONE"})

    result = judge_requirements(
        [requirement],
        profile,
        preflight_case_id="case-1",
        reference_date=REFERENCE_DATE,
    )

    assert result.judgments[0].status == "UNKNOWN"
    assert result.overall_status == "insufficient_data"


def test_complete_missing_certification_is_unsatisfied():
    """번호로 요구한 등록이 목록에 없으면 미달이다. 이름으로 요구한 것은 표기가 갈려 확인 필요다."""
    requirement = _requirement("REQ-CERT", "REGISTRATION_CERTIFICATION", value="4321150102")
    result = judge_requirements([requirement], _profile(completeness=ProfileCompleteness(certifications=True)), preflight_case_id="case-1", reference_date=REFERENCE_DATE)
    assert result.judgments[0].status == "UNSATISFIED"
    assert result.overall_status == "ineligible"

    named = _requirement("REQ-CERT", "REGISTRATION_CERTIFICATION", value="정보통신공사업")
    result = judge_requirements([named], _profile(completeness=ProfileCompleteness(certifications=True)), preflight_case_id="case-1", reference_date=REFERENCE_DATE)
    assert result.judgments[0].status == "UNKNOWN"


def test_present_valid_certification_is_satisfied_even_before_collection_is_complete():
    requirement = _requirement("REQ-CERT", "REGISTRATION_CERTIFICATION", value="정보통신공사업")
    profile = _profile(certifications=[ProfileCertificationFact(ref="cert-1", name="정보통신공사업", expires_at=date(2027, 12, 31), verified=True)], completeness=ProfileCompleteness(certifications=False))
    result = judge_requirements([requirement], profile, preflight_case_id="case-1", reference_date=REFERENCE_DATE)
    assert result.judgments[0].status == "SATISFIED"
    assert result.judgments[0].evidence_held is True


def test_certification_code_can_match_canonical_requirement_value():
    requirement = _requirement(
        "REQ-CERT-CODE", "REGISTRATION_CERTIFICATION", value="ISO27001"
    )
    profile = _profile(
        certifications=[
            ProfileCertificationFact(
                ref="cert-iso",
                name="정보보호 경영시스템 인증",
                certification_code="ISO27001",
                verified=True,
            )
        ]
    )

    result = judge_requirements(
        [requirement],
        profile,
        preflight_case_id="case-1",
        reference_date=REFERENCE_DATE,
    )

    assert result.judgments[0].status == "SATISFIED"


def test_year_only_performance_near_period_boundary_returns_unknown():
    requirement = _requirement(
        "REQ-PERFORMANCE-YEAR",
        "PERFORMANCE_AMOUNT",
        operator=">=",
        value=400_000_000,
        period_months=12,
    )
    profile = _profile(completeness=ProfileCompleteness(performances=True))
    profile = profile.model_copy(
        update={
            "performances": [
                ProfilePerformanceFact(
                    ref="performance-year",
                    name="연도만 확인된 실적",
                    amount=500_000_000,
                    completed_year=2025,
                    verified=True,
                )
            ]
        }
    )

    result = judge_requirements(
        [requirement],
        profile,
        preflight_case_id="case-1",
        reference_date=REFERENCE_DATE,
    )

    assert result.judgments[0].status == "UNKNOWN"


def test_any_of_group_does_not_make_one_failed_alternative_ineligible():
    requirements = [
        _requirement("REQ-ALT-SEOUL", "REGION", value="서울특별시", group_key="REQ-ALT", group_operator="ANY_OF"),
        _requirement("REQ-ALT-BUSAN", "REGION", value="부산광역시", group_key="REQ-ALT", group_operator="ANY_OF"),
    ]
    result = judge_requirements(requirements, _profile(), preflight_case_id="case-1", reference_date=REFERENCE_DATE)
    assert result.overall_status == "eligible"


def test_industry_identifiers_require_exact_match():
    from bidengine.judgment.rules import ProfileIndustryFact
    profile = _profile().model_copy(update={"industries": [ProfileIndustryFact(code="11426", name="다른 업종")]})
    req = _requirement("industry", "INDUSTRY", value="1426")
    assert judge_requirements([req], profile, preflight_case_id="c", reference_date=REFERENCE_DATE).overall_status == "ineligible"


def test_composite_clause_abstains_even_with_matching_company_certification():
    req = _requirement("cert", "REGISTRATION_CERTIFICATION", value="정보통신공사업").model_copy(update={"raw": "공동수급체 구성원 모두 정보통신공사업 등록업체이어야 한다."})
    profile = _profile(certifications=[ProfileCertificationFact(ref="c", name="정보통신공사업")])
    assert judge_requirements([req], profile, preflight_case_id="c", reference_date=REFERENCE_DATE).judgments[0].status == "UNKNOWN"


def test_partial_policy_keeps_any_of_logic_and_never_promotes_to_eligible():
    reqs = [_requirement("a", "REGION", value="서울특별시", group_key="either", group_operator="ANY_OF"), _requirement("b", "REGION", value="부산광역시", group_key="either", group_operator="ANY_OF")]
    assert judge_requirements(reqs, _profile(), preflight_case_id="c", reference_date=REFERENCE_DATE, analysis_status="PARTIAL").overall_status == "insufficient_data"


def test_performance_amount_cannot_use_unrelated_field_or_future_work():
    req = _requirement("amount", "PERFORMANCE_AMOUNT", operator=">=", value=100, scope={"experience_field": "해외진출"})
    profile = _profile(completeness=ProfileCompleteness(performances=True))
    # 분야 이름은 통제 어휘가 없어 "다르다"를 확정할 수 없다(ADR 0001 문제 4). 충족으로 쓰지는 않되
    # 미달로 단정하지도 않는다.
    result = judge_requirements([req], profile, preflight_case_id="c", reference_date=REFERENCE_DATE)
    assert result.judgments[0].status == "UNKNOWN"
    assert result.overall_status == "insufficient_data"
    future = profile.performances[0].model_copy(update={"completed_at": date(2027, 1, 1), "fields": ["해외진출"]})
    profile = profile.model_copy(update={"performances": [future]})
    assert judge_requirements([req], profile, preflight_case_id="c", reference_date=REFERENCE_DATE).overall_status == "ineligible"


def test_judgment_exposes_human_readable_reason() -> None:
    judgment = Judgment(
        judgment_key="JUDG:CASE:REQ",
        preflight_case_id="CASE",
        notice_version_id="VERSION",
        requirement_key="REQ",
        status="UNKNOWN",
        basis_type="NONE",
        reason_code="INSUFFICIENT_DATA",
    )
    assert judgment.reason == "판정에 필요한 회사 정보가 부족합니다."


def test_open_vocabulary_mismatch_is_unknown_not_unsatisfied():
    """같은 실적을 다른 말로 적은 회사를 미달로 판정하지 않는다 (골든 J06 조항)."""
    req = _requirement(
        "count", "PERFORMANCE_COUNT", operator=">=", value=2, period_months=24,
        scope={"experience_field": "단체급식 운영"},
    )
    work = [
        ProfilePerformanceFact(ref=f"p{i}", name=f"기관{i} 단체급식소 위탁운영", amount=1, completed_at=day,
                               fields=["단체급식소 위탁운영"], verified=True)
        for i, day in enumerate([date(2025, 6, 30), date(2026, 3, 31)])
    ]
    profile = _profile(completeness=ProfileCompleteness(performances=True)).model_copy(update={"performances": work})
    judgment = judge_requirements([req], profile, preflight_case_id="c", reference_date=REFERENCE_DATE).judgments[0]
    assert judgment.status == "UNKNOWN"


def test_no_performance_in_period_is_still_unsatisfied():
    """분야를 따지기 전에 기간 안 실적 자체가 없으면 미달이다 — 어휘 문제가 아니다."""
    req = _requirement(
        "count", "PERFORMANCE_COUNT", operator=">=", value=1, period_months=12,
        scope={"experience_field": "단체급식 운영"},
    )
    old = ProfilePerformanceFact(ref="p", name="단체급식 운영", amount=1, completed_at=date(2020, 1, 1),
                                 fields=["단체급식 운영"], verified=True)
    profile = _profile(completeness=ProfileCompleteness(performances=True)).model_copy(update={"performances": [old]})
    judgment = judge_requirements([req], profile, preflight_case_id="c", reference_date=REFERENCE_DATE).judgments[0]
    assert judgment.status == "UNSATISFIED"
