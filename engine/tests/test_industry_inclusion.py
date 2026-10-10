"""포함 면허: 상위 면허를 가진 회사는 하위 업종 요건을 충족한다(2026-10-10)."""
from datetime import date

from bidengine.contracts import QualificationRequirement
from bidengine.judgment.rules import CompanyProfileSnapshot, ProfileIndustryFact, judge_requirements
from bidengine.normalization.industry_inclusion import inclusion_index
from bidengine.pipeline.notice_limits import mark_accepted_licences

MASTER = [
    ("0002", "[1^0002^건축공사업^0003^토목건축공사업]"),
    ("0003", "[1^0002^건축공사업^0003^토목건축공사업],[2^0001^토목공사업^0003^토목건축공사업]"),
    ("0037", ""), ("9999", "[형식이 다른 항목]"), ("0040", None),
]


class Resolver:
    def including_codes(self, code):
        return inclusion_index(MASTER).get(code, [])


def _req(value, **scope):
    return QualificationRequirement(requirement_key=f"r{value}", notice_version_id="v", type="INDUSTRY", operator="MATCH",
                                    value=value, raw="건축공사업을 등록한 자", scope=scope)


def _overall(reqs, codes):
    profile = CompanyProfileSnapshot(
        company_id="c", region_name="대전광역시 서구", company_size="SMALL",
        industries=[ProfileIndustryFact(code=code, name=code, verified=True) for code in codes],
        completeness={"region": True, "company_size": True, "industries": True},
    )
    return judge_requirements(reqs, profile, preflight_case_id="c", reference_date=date(2026, 10, 10), coverage_complete=True).overall_status


def test_the_master_lists_which_licence_includes_which():
    assert inclusion_index(MASTER) == {"0002": ["0003"], "0001": ["0003"]}


def test_a_company_with_the_including_licence_meets_the_requirement():
    plain = [_req("0002")]
    assert _overall(plain, ["0003"]) == "core_unmet"          # 포함 관계를 모르면 틀린 부적합
    marked = mark_accepted_licences(plain, Resolver())
    assert marked[0].scope["accepted_by"] == {"0002": ["0003"]}
    assert _overall(marked, ["0003"]) == "core_met"
    assert _overall(marked, ["0002"]) == "core_met"
    assert _overall(marked, ["0037"]) == "core_unmet"         # 관계없는 업종은 그대로 미달
    assert _overall(marked, ["0001"]) == "core_unmet"         # 거꾸로는 안 된다 — 하위 면허가 상위를 대신하지 않는다


def test_inclusion_applies_inside_a_licence_group_too():
    grouped = mark_accepted_licences([_req("0001", with_codes=["0002"])], Resolver())
    assert _overall(grouped, ["0003"]) == "core_met"
    assert _overall(grouped, ["0001"]) == "core_unmet"


def test_requirements_without_an_including_licence_are_untouched():
    reqs = [_req("0037")]
    assert mark_accepted_licences(reqs, Resolver()) == reqs
    assert mark_accepted_licences(reqs, None) == reqs
