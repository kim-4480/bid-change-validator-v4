"""부적합은 공고가 분명히 말한 값으로만 낸다(2026-10-08, 표본 l 의 틀린 부적합)."""
from datetime import date

from bidengine.contracts import QualificationRequirement
from bidengine.judgment.rules import CompanyProfileSnapshot, ProfileIndustryFact, judge_requirements
from bidengine.requirements.legacy_slots import has_closed_value_text


def _req(key, type_, value, *, group=None, operator="ALL_OF", scope=None):
    return QualificationRequirement(
        requirement_key=key, requirement_group_key=group or f"{key}-G", group_operator=operator, notice_version_id="v",
        type=type_, operator="MATCH", value=value, raw=str(value), scope=scope or {},
    )


def _profile(size="SMALL", region="울산광역시 북구", codes=("1253",)):
    return CompanyProfileSnapshot(
        company_id="c", region_name=region, company_size=size,
        industries=[ProfileIndustryFact(code=code, name=code, verified=True) for code in codes],
        completeness={"region": True, "company_size": True, "industries": True},
    )


def _judge(reqs, profile):
    return judge_requirements(reqs, profile, preflight_case_id="c", reference_date=date(2026, 10, 8), coverage_complete=True)


def test_codes_inferred_from_a_family_name_never_make_a_company_ineligible():
    # '폐기물수집·운반업(건설폐기물)' 이 묶음 이름으로 풀려 생활·사업장폐기물 코드가 된 경우(747591).
    family = {"industry_name": "폐기물수집·운반업", "evidence": "family"}
    reqs = [_req(f"r{code}", "INDUSTRY", code, group="F", operator="ANY_OF", scope=family) for code in ("1224", "1226")]
    result = _judge(reqs, _profile())
    assert {j.status for j in result.judgments} == {"UNKNOWN"}
    assert result.overall_status == "needs_review"


def test_a_written_code_still_decides():
    result = _judge([_req("a", "INDUSTRY", "1224", scope={"industry_name": "업종코드 1224"})], _profile())
    assert result.overall_status == "core_unmet"


def test_two_disagreeing_sizes_do_not_make_a_company_ineligible():
    # 본문 '중소기업 또는 소상공인' 과 주석의 '소기업·소상공인 확인서' (740842).
    reqs = [_req("a", "COMPANY_SIZE", "중소기업"), _req("b", "COMPANY_SIZE", "소기업")]
    result = _judge(reqs, _profile(size="MEDIUM"))
    assert result.overall_status == "needs_review"
    # 둘 다 어긋나면 부적합이다.
    assert _judge(reqs, _profile(size="LARGE")).overall_status == "core_unmet"


def test_two_disjoint_regions_do_not_make_a_company_ineligible():
    reqs = [_req("a", "REGION", "경상남도"), _req("b", "REGION", "울산광역시")]
    assert _judge(reqs, _profile()).overall_status == "needs_review"
    assert _judge(reqs, _profile(region="부산광역시 중구")).overall_status == "core_unmet"


def test_nested_regions_are_both_required():
    reqs = [_req("a", "REGION", "경기도"), _req("b", "REGION", "경기도 시흥시")]
    assert _judge(reqs, _profile(region="경기도 수원시")).overall_status == "core_unmet"


def test_exclusions_are_not_softened():
    reqs = [_req("a", "COMPANY_SIZE", "중소기업"), _req("b", "COMPANY_SIZE", "대기업", scope={"restriction": "EXCLUDE"})]
    assert _judge(reqs, _profile(size="LARGE")).overall_status == "core_unmet"


def test_a_code_in_brackets_after_any_name_blocks_the_verdict():
    assert has_closed_value_text("- [출판사신고(1517)] 업종 또는 [인쇄사신고(1518)] 업종을 등록한 업체")
    assert not has_closed_value_text("과학기술정보통신부 공고(2026) 를 준수")
    assert not has_closed_value_text("제12조(경쟁입찰의 참가자격)")


def test_a_narrower_certificate_in_the_same_clause_keeps_a_medium_company_from_passing():
    from bidengine.labeling.closed_first import certificate_size

    assert certificate_size("중소기업자로서 “중·소기업, 소상공인 및 장애인기업 확인요령”에 따라 발급된 소기업 또는 소상공인 확인서를 소지한 업체") == "소기업"
    assert certificate_size("중소기업 또는 소상공인으로서 발급된 ‘중소기업․소상공인 확인서’를 소지한 자") == "중소기업"
    assert certificate_size("중소기업자 직접생산확인서") is None
    reqs = [_req("a", "COMPANY_SIZE", "중소기업", scope={"certificate_size": "소기업"})]
    assert _judge(reqs, _profile(size="MEDIUM")).overall_status == "needs_review"   # 748933, 748942
    assert _judge(reqs, _profile(size="SMALL")).overall_status == "core_met"
    assert _judge(reqs, _profile(size="LARGE")).overall_status == "core_unmet"
