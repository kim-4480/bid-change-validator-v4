"""확인할 항목의 소음 — 2026-10-08 g·h·i·j 측정에서 모은 이름."""
import pytest

from bidengine.contracts import QualificationRequirement
from bidengine.labeling.closed_first import open_condition_is_noise, open_name_is_noise
from bidengine.pipeline.analysis_pipeline import drop_checklist_duplicates, drop_checklist_fragments


@pytest.mark.parametrize("name, reason", [
    ("업종", "FRAGMENT"),
    ("지도기관", "FRAGMENT"),
    ("등록기준(기술능력, 자본금, 시설·장비·사무실등)", "FRAGMENT"),
    ("고용노동부장관의지정", "AUTHORITY_ONLY"),
    ("식품의약품안전처장의허가, 인증, 신고", "AUTHORITY_ONLY"),
    ("「건설산업기본법」에의한", "STATUTE_OR_PROCEDURE"),
    ("「건설산업기본법」에따른종합건설", "STATUTE_OR_PROCEDURE"),
])
def test_fragment_names_are_noise(name, reason):
    assert open_name_is_noise(name, "", []) == reason


@pytest.mark.parametrize("name", [
    "수산종자생산업허가", "종자생산확인서", "규격적합확인서", "5성급호텔", "위탁급식영업신고",
    "마이크로소프트사의교육기관용 MS OVS-ES 공식총판사의파트너사", "품목허가(신고)확인및 GMP/GIP적합인증서",
])
def test_real_check_items_stay(name):
    assert open_name_is_noise(name, "", []) is None


def test_staff_procedure_is_noise_but_real_roles_stay():
    assert open_condition_is_noise({"유형": "인력요건", "인력역할_raw": "입찰대리인은 입찰 당시 반드시 입찰참가업체에 재직 중인 임‧직원"})
    assert open_condition_is_noise({"유형": "인력요건", "인력역할_raw": "기술능력"})
    assert open_condition_is_noise({"유형": "인력요건", "인력역할_raw": "정보처리기사"}) is None
    assert open_condition_is_noise({"유형": "인력요건", "인력역할_raw": "건설기술인 3명"}) is None
    # 사람·자격이 아닌 것을 인력으로 올린 경우(2026-10-08 수산종자 공고)
    assert open_condition_is_noise({"유형": "인력요건", "인력역할_raw": "생산시설(친어지, 부화지, 치어사육지)"}) == "STAFF_NOT_PERSON"
    assert open_condition_is_noise({"유형": "인력요건", "인력역할_raw": "관리 상태가 양호하고"}) == "STAFF_NOT_PERSON"


def _req(key, type_, value):
    return QualificationRequirement(requirement_key=key, requirement_group_key=f"{key}-G", group_operator="ALL_OF",
                                    notice_version_id="v", type=type_, operator="MATCH", value=value, raw=str(value))


def test_checklist_duplicates_are_dropped_once():
    reqs = [
        _req("A", "EXPERIENCE_FIELD", "○ 단일 급식장* 기준 1일 평균 700명 이상의 집단급식(장) 운영실적"),
        _req("B", "EXPERIENCE_FIELD", "단일 급식당* 기준 1일 평균 700명 이상의 집단급식(장) 운영실적"),   # PDF OCR 차이
        _req("C", "REGISTRATION_CERTIFICATION", "8111179901"),
        _req("D", "REGISTRATION_CERTIFICATION", "직접생산확인증명서"),                                 # 품명번호 요건과 같다
        _req("E", "REGISTRATION_CERTIFICATION", "종자생산확인서"),
    ]
    kept, dropped = drop_checklist_duplicates(reqs)
    assert [r.requirement_key for r in kept] == ["A", "C", "E"]
    assert [r.requirement_key for r in dropped] == ["B", "D"]


def test_fragment_names_left_after_adaptation_are_dropped():
    reqs = [_req("A", "REGISTRATION_CERTIFICATION", "고용노동부장관의지정"), _req("B", "REGISTRATION_CERTIFICATION", "업종"),
            _req("C", "REGISTRATION_CERTIFICATION", "규격적합확인서"), _req("D", "INDUSTRY", "5612")]
    kept, dropped = drop_checklist_fragments(reqs)
    assert [r.requirement_key for r in kept] == ["C", "D"] and [r.requirement_key for r in dropped] == ["A", "B"]


def test_mutual_market_allowance_softens_specialty_industry_mismatch_for_general_contractors():
    """'전문공사로 상호시장 진출 허용에 따라 종합건설업자의 참여를 허용' — 조경공사업(종합)만 가진 회사는 미달이 아니라 확인 필요."""
    from datetime import date

    from bidengine.judgment.rules import CompanyProfileSnapshot, ProfileCompleteness, ProfileIndustryFact, judge_requirement
    from bidengine.pipeline.analysis_pipeline import mark_general_contractor_allowed
    from bidengine.pipeline.gap_triage import classify_gap

    allow = "※ 본 공사는 전문공사로 건설업역간 상호시장 진출 허용에 따라 종합건설업자의 참여를 허용합니다."
    reqs = mark_general_contractor_allowed([_req("A", "INDUSTRY", "4993"), _req("B", "REGION", "강릉시")], [allow])
    assert reqs[0].scope.get("general_contractor_allowed") and not reqs[1].scope.get("general_contractor_allowed")
    deny = "본공사는 종합공사의 시공자격업체로 제한함(상호시장 진출을 허용하지 않음)"
    assert not mark_general_contractor_allowed([_req("A", "INDUSTRY", "4993")], [deny])[0].scope.get("general_contractor_allowed")

    general = CompanyProfileSnapshot(company_id="c", industries=[ProfileIndustryFact(code="0005", name="조경공사업", verified=True)],
                                     completeness=ProfileCompleteness(industries=True))
    other = general.model_copy(update={"industries": [ProfileIndustryFact(code="0036", name="정보통신공사업", verified=True)]})
    judge = lambda req, company: judge_requirement(req, company, preflight_case_id="c", reference_date=date(2026, 10, 8)).status
    assert judge(reqs[0], general) == "UNKNOWN"
    assert judge(reqs[0], other) == "UNSATISFIED"
    assert classify_gap(allow) == "MUTUAL_MARKET_NOTE"
