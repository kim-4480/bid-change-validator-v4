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
    assert _overall(merged, codes=["1253"]) == "core_met"
    assert _overall(merged, codes=["6728"]) == "needs_review"                      # 못 맞춰도 부적합은 아니다
    assert _overall(merged, codes=[]) == "needs_review"


def test_a_group_of_several_licences_is_not_met_by_one_of_them():
    # 748606: (건축공사업) 또는 (전문 3종 모두)
    merged, _ = merge_notice_limits(
        [], _limits(("1", "0002"), ("2", "4989"), ("2", "4991"), ("2", "4992")), notice_version_id="v")
    assert _overall(merged, codes=["0002"]) == "core_met"
    assert _overall(merged, codes=["4989", "4991", "4992"]) == "core_met"
    assert _overall(merged, codes=["4991"]) == "needs_review"


def test_a_licence_documents_missed_is_added_but_never_makes_a_company_ineligible():
    merged, _ = merge_notice_limits([_req("r", "REGION", "경기도 양평군")], _limits(("1", "5611")), notice_version_id="v")
    assert _overall(merged, codes=["5611"]) == "core_met"
    assert _overall(merged, codes=[]) == "needs_review"


def test_required_in_documents_but_alternative_in_limits_follows_the_limits():
    reqs = [_req("a", "INDUSTRY", "1475"), _req("b", "INDUSTRY", "4119")]
    merged, diagnostics = merge_notice_limits(reqs, _limits(("1", "1475"), ("2", "4119")), notice_version_id="v")
    assert _overall(reqs, codes=["1475"]) == "core_unmet"            # 보강 전: 문서만 믿으면 틀린 부적합
    assert _overall(merged, codes=["1475"]) == "core_met"
    assert _overall(merged, codes=[]) == "needs_review"
    assert [d["reason"] for d in diagnostics] == ["REPLACED_BY_NOTICE_LIMITS"] * 2
    # 747591: 문서가 1253 과 6728 을 둘 다 필수로 읽었다. 1253 은 모든 묶음에 있으니 남고, 6728 은 묶음이 대신한다.
    both = [_req("a", "INDUSTRY", "1253"), _req("b", "INDUSTRY", "6728")]
    merged, _ = merge_notice_limits(both, _limits(("1", "1253"), ("1", "6728"), ("2", "1253")), notice_version_id="v")
    assert _overall(merged, codes=["1253"]) == "core_met"
    assert _overall(merged, codes=["6728"]) == "core_unmet"          # 1253 은 문서에 분명히 적힌 필수다


def test_a_region_documents_missed_is_added():
    merged, _ = merge_notice_limits([], _limits(regions=["부산광역시"]), notice_version_id="v")
    assert _overall(merged, region="부산광역시 중구") == "core_met"
    assert _overall(merged, region="경기도 양평군") == "needs_review"
    # 문서가 같은 시·도를 이미 요구하면 더하지 않는다(시·군 22곳을 나열한 전남 공고).
    reqs = [_req("r", "REGION", "전라남도")]
    merged, _ = merge_notice_limits(reqs, _limits(regions=["전남광주통합특별시 목포시", "전남광주통합특별시 여수시"]), notice_version_id="v")
    assert merged == reqs
    assert merge_notice_limits([], _limits(regions=["전국"]), notice_version_id="v")[0] == []


def test_no_restriction_is_only_stated_by_an_open_tender_with_nothing_set():
    open_tender = {"flags": {"cntrctCnclsMthdNm": "일반경쟁", "indstrytyLmtYn": "N", "prdctClsfcLmtYn": "N", "cmmnSpldmdCorpRgnLmtYn": "Y"}}
    assert NoticeLimits.from_collected(open_tender).no_restriction_stated      # 공동수급 지역 표시는 참가 제한이 아니다
    for changed in ({"cntrctCnclsMthdNm": "제한경쟁"}, {"cntrctCnclsMthdNm": "수의계약"}, {"indstrytyLmtYn": "Y"}, {"cntrctCnclsMthdNm": ""}):
        assert not NoticeLimits.from_collected({"flags": {**open_tender["flags"], **changed}}).no_restriction_stated
    assert not NoticeLimits.from_collected({**open_tender, "regions": ["부산광역시"]}).no_restriction_stated
    assert not NoticeLimits.from_collected({**open_tender, "licenses": [{"group": "1", "name": "x", "code": "0037"}]}).no_restriction_stated
    assert not NoticeLimits().no_restriction_stated


def test_a_notice_without_requirements_is_met_only_when_the_tender_is_stated_open():
    def overall(reqs, *, complete=True, stated=False):
        profile = CompanyProfileSnapshot(company_id="c", region_name="서울특별시 중구", company_size="SMALL")
        return judge_requirements(reqs, profile, preflight_case_id="c", reference_date=date(2026, 10, 10),
                                  coverage_complete=complete, no_restriction_stated=stated).overall_status

    assert overall([]) == "needs_review"                        # 요건이 없다 — 추출 실패일 수 있다
    assert overall([], stated=True) == "core_met"
    assert overall([], stated=True, complete=False) == "needs_review"   # 놓친 조항이 있으면 확정하지 않는다
    # 요건이 있는 공고에는 영향이 없다.
    assert overall([_req("a", "INDUSTRY", "0037")], stated=True) == "core_unmet"
