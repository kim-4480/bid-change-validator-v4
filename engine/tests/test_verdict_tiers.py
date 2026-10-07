"""판정 대상(닫힌 값)과 확인 항목을 나눈다 — 2026-10-07 사용자 결정."""
from datetime import date

from bidengine.contracts import QualificationRequirement
from bidengine.judgment.rules import CompanyProfileSnapshot, ProfileIndustryFact, judge_requirements, requirement_tier
from bidengine.pipeline.analysis_result import AnalysisCoverage, CoverageGap, gap_blocks_verdict


def _req(key, type_, value, *, group=None, operator="ALL_OF"):
    return QualificationRequirement(
        requirement_key=key, requirement_group_key=group or f"{key}-G", group_operator=operator, notice_version_id="v",
        type=type_, operator="MATCH", value=value, raw=str(value),
    )


PROFILE = CompanyProfileSnapshot(company_id="c", region_name="강원특별자치도 강릉시", company_size="SMALL",
                                 industries=[ProfileIndustryFact(code="0040", name="전문소방시설공사업", verified=True)])


def _overall(reqs, coverage=True):
    return judge_requirements(reqs, PROFILE, preflight_case_id="c", reference_date=date(2026, 10, 7),
                              coverage_complete=coverage).overall_status


def test_tiers():
    assert requirement_tier(_req("a", "INDUSTRY", "0040")) == "VERDICT"
    assert requirement_tier(_req("b", "REGION", "강릉시")) == "VERDICT"
    assert requirement_tier(_req("c", "REGISTRATION_CERTIFICATION", "4615171502")) == "VERDICT"
    assert requirement_tier(_req("d", "REGISTRATION_CERTIFICATION", "Solar A Mark 인증서")) == "CHECKLIST"
    assert requirement_tier(_req("e", "REGISTRATION_CERTIFICATION", "수산종자생산업")) == "VERDICT"  # 업종 이름


def test_checklist_items_do_not_decide_the_verdict():
    reqs = [_req("a", "INDUSTRY", "0040"), _req("b", "REGION", "강릉시"), _req("c", "REGISTRATION_CERTIFICATION", "Solar A Mark 인증서")]
    assert _overall(reqs) == "eligible"            # 인증서는 확인 항목 — 확인 필요여도 핵심 자격은 충족
    assert _overall(reqs[:2] + [_req("d", "REGION", "부산광역시")]) == "ineligible"


def test_any_of_with_a_verdict_member_is_judged_as_a_whole():
    reqs = [_req("a", "INDUSTRY", "1468", group="G", operator="ANY_OF"),
            _req("b", "REGISTRATION_CERTIFICATION", "OO 인증서", group="G", operator="ANY_OF")]
    assert _overall(reqs) == "insufficient_data"   # 1468 은 없지만 OO 인증을 확인해야 한다


def test_only_closed_value_gaps_block_the_verdict():
    assert gap_blocks_verdict(CoverageGap(kind="UNREPRESENTABLE", raw="가. 산림조합 …", reason="UNMAPPED_INDUSTRY/ALTERNATIVE_UNRESOLVED"))
    assert gap_blocks_verdict(CoverageGap(kind="UNCLASSIFIED", raw="본점 소재지가 곡성군인 업체 중 …"))
    assert not gap_blocks_verdict(CoverageGap(kind="UNCLASSIFIED", raw="다. 납품할 종자를 생산할 수 있는 생산시설을 갖춘 자"))
    coverage = AnalysisCoverage(section_selection="anchored", unclassified=1,
                                gaps=[CoverageGap(kind="UNCLASSIFIED", raw="다. 생산시설을 갖춘 자")],
                                ignored=[CoverageGap(kind="IGNORED", raw="공동수급 불가", reason="GAP_JOINT_CONTRACT_NOTE")],
                                unclassified_blocks_eligibility=True)
    assert coverage.verdict_complete and not coverage.complete
    assert [g.raw for g in coverage.checklist_gaps] == ["다. 생산시설을 갖춘 자"]
    assert [g.raw for g in coverage.notes] == ["공동수급 불가"]


def test_gap_repeating_extracted_closed_values_is_a_checklist_item():
    from types import SimpleNamespace as NS

    from bidengine.pipeline.gap_triage import closed_values_covered

    reqs = [NS(type="INDUSTRY", value="1264"), NS(type="REGION", value="부산광역시"), NS(type="COMPANY_SIZE", value="소기업")]
    hotel = CoverageGap(kind="UNREPRESENTABLE", reason="UNMAPPED_REGISTRATION_CERTIFICATION",
                        raw="아. ‘관광호텔업(업종코드1264)’ 분야의 등록을 필한 5성급 호텔로 다음 조건을 충족하여야 함.")
    assert closed_values_covered(hotel, reqs)
    assert closed_values_covered(CoverageGap(kind="UNREPRESENTABLE", raw="* 소기업‧소상공인 확인서 제출"), reqs)
    # 담기지 않은 값(다른 지역)이 있으면 판정을 막는다.
    assert not closed_values_covered(CoverageGap(kind="UNCLASSIFIED", raw="공동수급체 구성원 중 1인은 경상남도 업체"), reqs)
    # (가)·(나) 공백은 담긴 값과 상관없이 막는다 — "산림조합" 을 놓친 조항에 곡성군이 담겨 있어도 그렇다.
    forest = CoverageGap(kind="UNREPRESENTABLE", raw="산림사업법인 또는 산림조합으로 본점이 곡성군",
                         reason="UNMAPPED_INDUSTRY/ALTERNATIVE_UNRESOLVED")
    assert not closed_values_covered(forest, [NS(type="REGION", value="곡성군")])
