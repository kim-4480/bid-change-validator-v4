"""등록·면허 이름의 '또는' 을 ANY_OF 로 담는다 (docs/experiments/2026-09-30 실측 조항).

열어야 할 것: 진짜 대안, 괄호형 대안, 동의어 나열.
열면 안 되는 것: 배제 조건, 절차, 이름 말고 다른 조건이 섞인 대안.
"""
from __future__ import annotations

from datetime import date

import pytest

from bidengine.judgment.rules import (
    CompanyProfileSnapshot,
    ProfileCompleteness,
    ProfileIndustryFact,
    judge_requirements,
)
from bidengine.requirements.legacy_slots import (
    adapt_legacy_slot,
    labelled_industry_codes,
    registration_alternation,
    region_alternation,
    registration_alternation_with_region,
)

C04_ENGINEERING = ("1) 「건설기술진흥법」에 의한 건설엔지니어링업(종합) 또는 건설엔지니어링업(설계․사업관리-일반) "
                   "또는 건설엔지니어링업(설계․사업관리-건설사업관리)로 등록한 자")
C02_MEDICAL = "사업자등록증의 종목에 의료기기(또는 의료용기기, 의료용기구및기기)로 등록된 업체."
C02_MEDICAL_PDF = "사업자등록증의 종목에 의료기기 ( 또는 의료용기기 , 의료용기구및기기 ) 로 등록된 업체 ."
C03_BUILDING = "건설산업기본법령에 의한 건축(또는 토목건축)공사업 등록업체"

MASTER = {"건설엔지니어링업(종합)": "4966", "건설엔지니어링업(설계사업관리-일반)": "4967",
          "건설엔지니어링업(설계사업관리-건설사업관리)": "4969", "건축공사업": "0002", "토목건축공사업": "0003"}


class DictResolver:
    def code_for(self, name: str) -> str | None:
        return MASTER.get(name.replace("․", "").replace("·", "").replace(" ", ""))


@pytest.mark.parametrize(
    ("raw", "names"),
    [
        (C04_ENGINEERING, ["건설엔지니어링업(종합)", "건설엔지니어링업(설계․사업관리-일반)", "건설엔지니어링업(설계․사업관리-건설사업관리)"]),
        (C02_MEDICAL, ["의료기기", "의료용기기", "의료용기구및기기"]),
        (C02_MEDICAL_PDF, ["의료기기", "의료용기기", "의료용기구및기기"]),
        (C03_BUILDING, ["건축공사업", "토목건축공사업"]),
    ],
    ids=["c04-list", "c02-paren", "c02-pdf-spacing", "c03-paren"],
)
def test_real_alternatives_are_opened(raw, names):
    assert registration_alternation(raw) == names


@pytest.mark.parametrize(
    "raw",
    [
        # 배제 조건: 하나라도 해당하면 참가 불가. 대안으로 읽으면 뜻이 뒤집힌다.
        "마. 입찰일 현재 부정당업자 제재 중인 자와 부도(지급정지 포함) 또는 파산, 회생절차 중에 있는 자는 입찰에 참가할 수 없습니다.",
        # 절차: 납부 방법의 대안
        "가. 입찰금액의 5/100이상에 상당하는 금액을 현금 또는 농협 규정에 의한 보증보험증권 등으로 입찰참가등록 마감 전까지 농협에 납부하여야 합니다.",
        # 이름 말고 인원·확인 조건이 섞였다
        "3)「전력기술관리법」에 따라 종합설계업을 등록한 자 이거나 특급기술자 3인 이상을 보유한 전력시설물 설계업자로 "
        "시‧도지사에게 확인을 받은 자 또는 전력시설물 공사 감리업의 등록을 한 자",
        # 지역 조건 뒤에 다른 조건이 더 붙었다
        "건축(또는 토목건축)공사업 등록업체로서 주된 영업소의 소재지를 경상남도에 둔 업체로서 시공능력평가액 100억 이상인 업체",
        # 사람의 자격(대표자 또는 위임받은 자)
        "다. 참가자격 : 건설기술진흥법에 의한 건축분야 고급기술자 이상의 자격소지자로서 대표자 또는 대표자의 위임을 받은 자",
        # 예외 단서
        "건축공사업 또는 토목건축공사업으로 등록한 자. 다만 공동수급의 경우 구성원 모두 등록하여야 한다",
    ],
    ids=["exclusion", "payment", "staff-mixed", "region-plus-more", "person", "exception"],
)
def test_unsafe_or_is_not_opened(raw):
    assert registration_alternation(raw) is None


def _slot(raw):
    return {"유형": "등록요건", "raw": raw}


def test_master_names_become_industry_codes_and_others_stay_names():
    reqs, diags = adapt_legacy_slot(_slot(C04_ENGINEERING), notice_version_id="v", key_prefix="R",
                                    industry_resolver=DictResolver())
    assert [(r.type, r.value, r.group_operator) for r in reqs] == [
        ("INDUSTRY", "4966", "ANY_OF"), ("INDUSTRY", "4967", "ANY_OF"), ("INDUSTRY", "4969", "ANY_OF"),
    ]
    assert len({r.requirement_group_key for r in reqs}) == 1
    assert diags[0]["code"] == "REGISTRATION_ALTERNATION"

    medical, _ = adapt_legacy_slot(_slot(C02_MEDICAL), notice_version_id="v", key_prefix="M",
                                   industry_resolver=DictResolver())
    assert {(r.type, r.scope.get("kind")) for r in medical} == {("REGISTRATION_CERTIFICATION", "REGISTRATION")}


def test_without_resolver_alternatives_are_names():
    reqs, _ = adapt_legacy_slot(_slot(C03_BUILDING), notice_version_id="v", key_prefix="R")
    assert [r.value for r in reqs] == ["건축공사업", "토목건축공사업"]
    assert all(r.type == "REGISTRATION_CERTIFICATION" for r in reqs)


def _overall(reqs, industries, complete=True):
    profile = CompanyProfileSnapshot(
        company_id="c", industries=industries,
        completeness=ProfileCompleteness(industries=True, certifications=True),
    )
    return judge_requirements(reqs, profile, preflight_case_id="c", reference_date=date(2026, 9, 1),
                              coverage_complete=complete)


def test_any_alternative_held_is_eligible():
    reqs, _ = adapt_legacy_slot(_slot(C04_ENGINEERING), notice_version_id="v", key_prefix="R",
                                industry_resolver=DictResolver())
    held = [ProfileIndustryFact(code="4969", name="건설엔지니어링업(설계,사업관리-건설사업관리)")]
    assert _overall(reqs, held).overall_status == "eligible"


def test_no_alternative_held_is_ineligible_when_all_are_codes():
    reqs, _ = adapt_legacy_slot(_slot(C04_ENGINEERING), notice_version_id="v", key_prefix="R",
                                industry_resolver=DictResolver())
    held = [ProfileIndustryFact(code="0001", name="토목공사업")]
    assert _overall(reqs, held).overall_status == "ineligible"


def test_name_alternatives_are_matched_against_registered_industries():
    """업종으로 등록한 이름도 등록 요건을 충족한다. 이름이 다르면 미달이 아니라 확인 필요다."""
    reqs, _ = adapt_legacy_slot(_slot(C03_BUILDING), notice_version_id="v", key_prefix="R")
    assert _overall(reqs, [ProfileIndustryFact(code="0003", name="토목건축공사업")]).overall_status == "eligible"
    unrelated = _overall(reqs, [ProfileIndustryFact(code="0036", name="정보통신공사업")])
    assert unrelated.overall_status == "insufficient_data"
    assert {j.reason_code for j in unrelated.judgments} == {"NEEDS_REVIEW"}


def test_clauses_with_industry_codes_are_left_to_the_code_path():
    raw = "폐기물중간처분업(업종코드 : 1257) 또는 폐기물종합재활용업(업종코드 : 6786) 등록업체"
    assert registration_alternation(raw) is None



C03_WITH_REGION = ("가. 건설산업기본법령에 의한 건축(또는 토목건축)공사업 등록업체로서 입찰공고일 전일부터 "
                   "계약체결일까지 주된 영업소의 소재지를 경상남도에 둔 업체")


def test_attached_region_is_split_into_its_own_requirement():
    assert registration_alternation_with_region(C03_WITH_REGION) == (["건축공사업", "토목건축공사업"], ["경상남도"])
    reqs, _ = adapt_legacy_slot(_slot(C03_WITH_REGION), notice_version_id="v", key_prefix="R",
                                industry_resolver=DictResolver())
    alternatives = [r for r in reqs if r.group_operator == "ANY_OF"]
    region = [r for r in reqs if r.type == "REGION"]
    assert [r.value for r in alternatives] == ["0002", "0003"]
    assert [(r.value, r.group_operator) for r in region] == [("경상남도", "ALL_OF")]
    assert region[0].requirement_group_key != alternatives[0].requirement_group_key


def test_attached_region_alternatives_become_their_own_any_of_group():
    raw = "건축(또는 토목건축)공사업 등록업체로서 주된 영업소의 소재지를 경상남도 또는 부산광역시에 둔 업체"
    assert registration_alternation_with_region(raw) == (["건축공사업", "토목건축공사업"], ["경상남도", "부산광역시"])
    reqs, _ = adapt_legacy_slot(_slot(raw), notice_version_id="v", key_prefix="R", industry_resolver=DictResolver())
    groups = {}
    for r in reqs:
        groups.setdefault(r.requirement_group_key, []).append((r.type, r.value, r.group_operator))
    assert sorted(groups.values()) == [
        [("INDUSTRY", "0002", "ANY_OF"), ("INDUSTRY", "0003", "ANY_OF")],
        [("REGION", "경상남도", "ANY_OF"), ("REGION", "부산광역시", "ANY_OF")],
    ]


@pytest.mark.parametrize(
    ("region", "industries", "expected"),
    [
        ("경상남도", [ProfileIndustryFact(code="0003", name="토목건축공사업")], "eligible"),
        ("부산광역시", [ProfileIndustryFact(code="0003", name="토목건축공사업")], "ineligible"),
        ("경상남도", [ProfileIndustryFact(code="0001", name="토목공사업")], "ineligible"),
    ],
    ids=["both-held", "wrong-region", "no-alternative"],
)
def test_alternatives_and_region_are_both_required(region, industries, expected):
    reqs, _ = adapt_legacy_slot(_slot(C03_WITH_REGION), notice_version_id="v", key_prefix="R",
                                industry_resolver=DictResolver())
    profile = CompanyProfileSnapshot(
        company_id="c", region_name=region, industries=industries,
        completeness=ProfileCompleteness(industries=True, certifications=True),
    )
    result = judge_requirements(reqs, profile, preflight_case_id="c", reference_date=date(2026, 9, 1),
                                coverage_complete=True)
    assert result.overall_status == expected


# ── PDF 의 벌어진 업종코드 ─────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("text", "codes"),
    [
        ("업종코드 : 1 4 6 8 )", {"1468"}),
        ("업종코드: 1468", {"1468"}),
        ("업종코드: 14 68", {"1468"}),
        ("업\n종코드: 5898", {"5898"}),
        ("업종코드 : 1 4 6 8 0", set()),   # 다섯 자리
        ("업종코드 : 1-4-6-8", set()),     # 숫자 사이에 다른 글자
        ("업종코드 : 1.4.6.8", set()),
        ("2026년 1 4 6 8", set()),         # 라벨 없음
    ],
)
def test_spaced_digits_after_label_are_one_code_only_when_separated_by_spaces(text, codes):
    assert labelled_industry_codes(text) == codes


def test_code_in_registration_name_field_becomes_industry_code():
    """C01 실측: 코드가 raw 가 아니라 등록 이름 필드에, 그것도 벌어진 채로 왔다."""
    slot = {
        "유형": "등록요건",
        "raw": "ㅇ 「 국가종합전자조달시스템 입찰참가자격등록규정 」 에 의하여 나라장터 (G2B) 에 다음 분야의 입찰참가자격을 전자입찰서 제출마감일 전일까지 등록한 자",
        "등록인증_raw": "소프트웨어사업 ( 컴퓨터관련서비스사업 , 업종코드 : 1 4 6 8 )",
    }
    reqs, _ = adapt_legacy_slot(slot, notice_version_id="v", key_prefix="R")
    assert [(r.type, r.value) for r in reqs] == [("INDUSTRY", "1468")]



# ── 지역 단독 문장의 '또는' ───────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("raw", "regions"),
    [
        ("본점 소재지가 서울특별시 또는 경기도에 있는 업체", ["서울특별시", "경기도"]),
        ("주된 영업소의 소재지를 부산광역시, 울산광역시 또는 경상남도에 둔 업체", ["부산광역시", "울산광역시", "경상남도"]),
        ("입찰공고일 전일부터 계약체결일까지 본점 소재지가 전라남도 또는 광주광역시에 소재한 자", ["전라남도", "광주광역시"]),
    ],
)
def test_region_only_alternatives(raw, regions):
    assert region_alternation(raw) == regions


@pytest.mark.parametrize(
    "raw",
    [
        "본점 소재지가 서울특별시에 있는 업체",  # 하나뿐 — 기존 지역 경로의 몫
        "서울특별시 또는 경기도에 소재한 업체는 참가할 수 없음",  # 배제
        "본점이 서울특별시 또는 경기도에 있는 업체로서 시공능력평가액 100억 이상",  # 다른 조건
    ],
)
def test_region_only_is_not_opened_when_unsafe_or_single(raw):
    assert region_alternation(raw) is None


@pytest.mark.parametrize(
    ("company_region", "expected"),
    [("경기도", "SATISFIED"), ("서울특별시", "SATISFIED"), ("인천광역시", "UNSATISFIED")],
)
def test_region_any_of_is_satisfied_by_one_region(company_region, expected):
    slot = {"유형": "지역요건", "raw": "본점 소재지가 서울특별시 또는 경기도에 있는 업체", "지역_raw": "서울특별시 또는 경기도"}
    reqs, diags = adapt_legacy_slot(slot, notice_version_id="v", key_prefix="R")
    assert [d["code"] for d in diags] == ["REGION_ALTERNATION"]
    profile = CompanyProfileSnapshot(company_id="c", region_name=company_region)
    result = judge_requirements(reqs, profile, preflight_case_id="c", reference_date=date(2026, 9, 1),
                                coverage_complete=True)
    group = "SATISFIED" if result.overall_status == "eligible" else "UNSATISFIED"
    assert group == expected
