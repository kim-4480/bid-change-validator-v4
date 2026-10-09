"""나라장터가 구조화해 둔 면허제한·참가가능지역으로 문서 요건을 보강한다(2026-10-10)."""
from datetime import date

from bidengine.contracts import QualificationRequirement
from bidengine.judgment.rules import CompanyProfileSnapshot, ProfileIndustryFact, judge_requirements
from bidengine.pipeline.notice_limits import NoticeLimits, merge_notice_limits


def _req(key, type_, value, *, group=None, operator="ALL_OF", scope=None):
    return QualificationRequirement(
        requirement_key=key, requirement_group_key=group or f"{key}-G", group_operator=operator, notice_version_id="v",
        type=type_, operator="MATCH", value=value, raw=str(value), scope=scope or {},
    )


def _limits(*licenses, regions=()):
    return NoticeLimits.from_collected({
        "licenses": [{"group": group, "name": f"업종{code}", "code": code} for group, code in licenses], "regions": list(regions),
    })


def _overall(reqs, codes=(), region="경기도 양평군"):
    profile = CompanyProfileSnapshot(
        company_id="c", region_name=region, company_size="SMALL",
        industries=[ProfileIndustryFact(code=code, name=code, verified=True) for code in codes],
        completeness={"region": True, "company_size": True, "industries": True},
    )
    return judge_requirements(reqs, profile, preflight_case_id="c", reference_date=date(2026, 10, 10), coverage_complete=True).overall_status


def test_nothing_changes_without_limits():
    reqs = [_req("a", "INDUSTRY", "1253")]
    assert merge_notice_limits(reqs, None, notice_version_id="v") == (reqs, [])
    assert merge_notice_limits(reqs, NoticeLimits(), notice_version_id="v") == (reqs, [])


def test_nothing_is_added_when_documents_already_say_the_same():
    reqs = [_req("a", "INDUSTRY", "0040"), _req("r", "REGION", "서울특별시")]
    merged, _ = merge_notice_limits(reqs, _limits(("1", "0040"), regions=["서울특별시"]), notice_version_id="v")
    assert merged == reqs
    alternatives = [_req("a", "INDUSTRY", "1475", group="G", operator="ANY_OF"), _req("b", "INDUSTRY", "4119", group="G", operator="ANY_OF")]
    merged, _ = merge_notice_limits(alternatives, _limits(("1", "1475"), ("2", "4119")), notice_version_id="v")
    assert merged == alternatives


def test_groups_are_alternatives_and_a_group_needs_all_its_licences():
    # 747591: (1253 과 6728) 또는 (1253). 문서에서는 묶음 이름으로 추론한 코드만 나왔다.
    inferred = [_req(f"f{code}", "INDUSTRY", code, group="F", operator="ANY_OF", scope={"evidence": "family"}) for code in ("1224", "1226")]
    merged, diagnostics = merge_notice_limits(
        inferred, _limits(("1", "1253"), ("1", "6728"), ("2", "1253")), notice_version_id="v")
    assert [r.value for r in merged if r.scope.get("evidence") == "family"] == []       # 추론한 코드는 버린다
    assert {d["reason"] for d in diagnostics} == {"INFERRED_CODE_NOT_IN_NOTICE_LIMITS"}
    assert _overall(merged, codes=["1253"]) == "eligible"
    assert _overall(merged, codes=["6728"]) == "insufficient_data"                      # 못 맞춰도 부적합은 아니다
    assert _overall(merged, codes=[]) == "insufficient_data"


def test_a_group_of_several_licences_is_not_met_by_one_of_them():
    # 748606: (건축공사업) 또는 (전문 3종 모두)
    merged, _ = merge_notice_limits(
        [], _limits(("1", "0002"), ("2", "4989"), ("2", "4991"), ("2", "4992")), notice_version_id="v")
    assert _overall(merged, codes=["0002"]) == "eligible"
    assert _overall(merged, codes=["4989", "4991", "4992"]) == "eligible"
    assert _overall(merged, codes=["4991"]) == "insufficient_data"


def test_a_licence_documents_missed_is_added_but_never_makes_a_company_ineligible():
    merged, _ = merge_notice_limits([_req("r", "REGION", "경기도 양평군")], _limits(("1", "5611")), notice_version_id="v")
    assert _overall(merged, codes=["5611"]) == "eligible"
    assert _overall(merged, codes=[]) == "insufficient_data"


def test_required_in_documents_but_alternative_in_limits_is_not_a_firm_miss():
    reqs = [_req("a", "INDUSTRY", "1475"), _req("b", "INDUSTRY", "4119")]
    merged, _ = merge_notice_limits(reqs, _limits(("1", "1475"), ("2", "4119")), notice_version_id="v")
    assert _overall(reqs, codes=["1475"]) == "ineligible"            # 보강 전: 문서만 믿으면 틀린 부적합
    assert _overall(merged, codes=["1475"]) == "insufficient_data"


def test_a_region_documents_missed_is_added():
    merged, _ = merge_notice_limits([], _limits(regions=["부산광역시"]), notice_version_id="v")
    assert _overall(merged, region="부산광역시 중구") == "eligible"
    assert _overall(merged, region="경기도 양평군") == "insufficient_data"
    # 문서가 같은 시·도를 이미 요구하면 더하지 않는다(시·군 22곳을 나열한 전남 공고).
    reqs = [_req("r", "REGION", "전라남도")]
    merged, _ = merge_notice_limits(reqs, _limits(regions=["전남광주통합특별시 목포시", "전남광주통합특별시 여수시"]), notice_version_id="v")
    assert merged == reqs
    assert merge_notice_limits([], _limits(regions=["전국"]), notice_version_id="v")[0] == []
