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


def test_sme_company_is_not_a_conglomerate_affiliate():
    """'대기업 및 중견기업 … 상호출자제한기업집단에 속하는 기업도 참여 불가' — 중소기업 이하로 확인된 회사는 소속일 수 없다."""
    from bidengine.judgment.rules import ProfileCompleteness, judge_requirement

    req = _req("S", "COMPANY_SIZE", "대기업 및 중견기업").model_copy(update={
        "scope": {"restriction": "EXCLUDE"},
        "raw": "대기업 및 중견기업인 소프트웨어 사업자는 참여할 수 없으며, 상호출자제한기업집단에 속하는 기업도 입찰에 참여할 수 없습니다.",
    })
    small = CompanyProfileSnapshot(company_id="c", company_size="SMALL", completeness=ProfileCompleteness(company_size=True))
    assert judge_requirement(req, small, preflight_case_id="c", reference_date=date(2026, 10, 8)).status == "SATISFIED"
    unconfirmed = small.model_copy(update={"completeness": ProfileCompleteness(company_size=False)})
    assert judge_requirement(req, unconfirmed, preflight_case_id="c", reference_date=date(2026, 10, 8)).status == "UNKNOWN"
    mid = CompanyProfileSnapshot(company_id="c", company_size="MID_SIZED", completeness=ProfileCompleteness(company_size=True))
    assert judge_requirement(req, mid, preflight_case_id="c", reference_date=date(2026, 10, 8)).status == "UNSATISFIED"


def test_large_company_is_excluded_even_if_it_says_it_is_not_an_affiliate():
    """'대기업 및 중견기업인 … 참여할 수 없으며, 상호출자제한기업집단 … 도' — 규모 배제가 계열회사 답에 묻히면 안 된다."""
    from bidengine.judgment.rules import ProfileCompleteness, judge_requirement

    req = _req("S", "COMPANY_SIZE", "대기업 및 중견기업").model_copy(update={
        "scope": {"restriction": "EXCLUDE"},
        "raw": "대기업 및 중견기업인 소프트웨어 사업자는 본 입찰에 참여할 수 없으며, 상호출자제한기업집단에 속하는 기업도 입찰에 참여할 수 없습니다.",
    })
    large = CompanyProfileSnapshot(company_id="c", company_size="LARGE", completeness=ProfileCompleteness(company_size=True),
                                   extensions={"conglomerate_affiliate": {"is_affiliate": False}})
    assert judge_requirement(req, large, preflight_case_id="c", reference_date=date(2026, 10, 8)).status == "UNSATISFIED"


def test_three_fixes_from_sample_k():
    """2026-10-08 표본 k: 공동도급 역할 조항, '(지점 투찰 불허)' 덧말, HWP·PDF 사본의 규모 차이."""
    from bidengine.labeling.closed_first import _BRANCH_REMARK_RE, _PARTY_CLAUSE_RE
    from bidengine.pipeline.analysis_pipeline import drop_narrower_copy_sizes

    assert _PARTY_CLAUSE_RE.search("3.2.1. 주계약자(대표사) : 「건설산업기본법령」에 의한 건축공사업과 토목공사업을 동시에 등록업체")
    assert _PARTY_CLAUSE_RE.search("3.2.3. 부계약자 : 「건설산업기본법령」에 의한 전문건설업 중 기계설비·가스공사업")
    assert not _PARTY_CLAUSE_RE.search("가. 건축공사업을 등록한 업체")
    blocked = CoverageGap(kind="UNREPRESENTABLE", reason="COMPOSITE_PARTY_RULE",
                          raw="3.2.3. 부계약자 : 전문건설업 중 기계설비·가스공사업으로 주력분야를 기계설비공사로 등록한 업체")
    assert gap_blocks_verdict(blocked)

    text = "다. 주된 영업소의 소재지를 계속 경상남도 또는 울산광역시에 둔 사업자이어야 합니다. (지점 투찰 불허)"
    assert "불허" not in _BRANCH_REMARK_RE.sub(" ", text)

    raw = "마. 「중소기업기본법」 제2조 제2항에 따른 중기업, 소기업 또는 소상공인으로서 … 발급된 소기업 또는 소상공인 확인서"
    pdf = "마 . 「 중소기업기본법 」 제 2 조 제 2 항에 따른 중기업 , 소기업 또는 소상공인으로서 … 발급된 소기업 또는 소상공인 확인서"
    wide = _req("A", "COMPANY_SIZE", "중소기업").model_copy(update={"raw": raw})
    narrow = _req("B", "COMPANY_SIZE", "소기업").model_copy(update={"raw": pdf})
    other_clause = _req("C", "COMPANY_SIZE", "소기업").model_copy(update={"raw": "라. 소기업 또는 소상공인 간 제한경쟁입찰"})
    kept, dropped = drop_narrower_copy_sizes([wide, narrow, other_clause])
    assert [r.requirement_key for r in kept] == ["A", "C"] and [r.requirement_key for r in dropped] == ["B"]
