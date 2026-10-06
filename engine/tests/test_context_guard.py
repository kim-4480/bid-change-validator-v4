"""맥락 가드: 조항의 극성(모델)과 닫힌 값의 개수(코드)로 낱말 가드를 다시 판단한다 (2026-10-02)."""
from __future__ import annotations

import pytest

from bidengine.judgment.context_guard import decide
from bidengine.labeling.clause_polarity import POLARITY_KEY, attach_clause_polarity
from bidengine.requirements.legacy_slots import adapt_legacy_slot, sido_names, value_name_alternatives

REGION_CLAUSE = (
    "2. 입찰공고일 전일부터 입찰일까지 법인등기부상 본점 소재지 또는 개인사업자의 사업자등록상 사\n"
    "업장 소재지가 경상남도에 있고, 낙찰자는 계약체결일까지 해당 소재지 요건을 유지하는 자"
)
TWO_REGION_CLAUSE = "마. 본 입찰은 지역제한 입찰이며, 본점 소재지가 [충청남도] 또는 [세종특별시]에 있는 업체여야 합니다."
INDUSTRY_CLAUSE = (
    "3.1. 건축공사업(또는 토목건축공사업)을 등록한 자로서 입찰일(다만 낙찰자는 계약체결일)까지 "
    "본점 소재지(개인사업자인 경우에는 사업자등록증 또는 관련 서류에 기재된 사업장의 소재지)를 계속 서울특별시에 둔 자"
)


class Resolver:
    def code_for(self, name):
        return {"건축공사업": "0002", "토목건축공사업": "0003"}.get(name)


def _adapt(slot, polarity=None):
    if polarity is not None:
        slot = {**slot, POLARITY_KEY: polarity}
    return adapt_legacy_slot(slot, notice_version_id="v", key_prefix="REQ-001", industry_resolver=Resolver())


def test_without_polarity_the_word_guard_is_unchanged():
    assert decide(REGION_CLAUSE, None).action == "DEFAULT"
    requirements, diagnostics = _adapt({"유형": "지역요건", "raw": REGION_CLAUSE, "지역_raw": "경상남도"})
    assert requirements == []
    assert diagnostics[0]["reason"] == "ALTERNATIVE_OR_EXCEPTION_RULE"


def test_positive_clause_with_one_region_becomes_a_region_requirement():
    requirements, _ = _adapt({"유형": "지역요건", "raw": REGION_CLAUSE, "지역_raw": "경상남도에 있고"}, "POSITIVE")
    assert [(r.type, r.value, r.condition_complexity) for r in requirements] == [("REGION", "경상남도", "simple")]
    assert requirements[0].scope["guard_basis"] == "model_polarity"


def test_only_positive_lifts_the_guard():
    for polarity in ("EXCLUSION", "EXCEPTION", "NOT_REQUIREMENT", "UNSURE"):
        requirements, diagnostics = _adapt({"유형": "지역요건", "raw": REGION_CLAUSE, "지역_raw": "경상남도"}, polarity)
        assert requirements == []
        assert diagnostics[0]["reason"] == f"MODEL_POLARITY_{polarity}"


def test_exclusion_without_any_guard_word_is_no_longer_confirmed():
    raw = "경기도에 본점을 둔 업체는 본 입찰 대상이 아님"
    assert _adapt({"유형": "지역요건", "raw": raw, "지역_raw": "경기도"})[0] != []          # 예전: 요구로 확정
    assert _adapt({"유형": "지역요건", "raw": raw, "지역_raw": "경기도"}, "EXCLUSION")[0] == []


def test_negation_words_veto_a_positive_answer():
    raw = "본점 소재지가 경기도인 업체는 참가할 수 없습니다"
    decision = decide(raw, "POSITIVE")
    assert (decision.action, decision.reason) == ("ABSTAIN", "POLARITY_DISAGREEMENT")


def test_hard_reasons_are_left_to_the_old_guard():
    assert decide("공동수급체를 구성하지 않고 단독으로 전체 계약을 이행하는 자", "POSITIVE").action == "DEFAULT"


def test_size_exclusion_stays_representable():
    raw = "대기업 및 중견기업 참여 제한"
    requirements, _ = _adapt({"유형": "기업규모요건", "raw": raw, "기업규모_raw": "대기업 및 중견기업"}, "EXCLUSION")
    assert requirements and requirements[0].scope.get("restriction") == "EXCLUDE"


def test_excluded_large_companies_are_captured_whatever_type_the_model_gave():
    raw = "바. 본 사업은 20억원 미만인 사업으로 「소프트웨어 진흥법」 제48조에 따라 대기업 및 중견기업은 입찰 참가 불가"
    requirements, _ = _adapt({"유형": "기타요건", "raw": raw}, "EXCLUSION")
    assert [(r.type, r.scope.get("restriction")) for r in requirements] == [("COMPANY_SIZE", "EXCLUDE")]
    assert "대기업" in str(requirements[0].value) and "중견기업" in str(requirements[0].value)
    mixed = "「중소기업기본법」에 따른 중소기업이 아닌 자는 참여할 수 없음"
    assert _adapt({"유형": "기타요건", "raw": mixed}, "EXCLUSION")[0] == []   # 무엇을 막는지 낱말만으로 알 수 없다


def test_size_certificate_names_are_company_size_not_name_alternatives():
    raw = "마. 소기업 및 소상공인으로서 「중소기업 범위 및 확인에 관한 규정」에 따라 발급된 소기업 또는 소상공인확인서를 소지한 업체이어야 합니다."
    requirements, _ = _adapt({"유형": "인증요건", "raw": raw, "등록인증_raw": "소기업 또는 소상공인확인서"}, "POSITIVE")
    assert [(r.type, r.value) for r in requirements] == [("COMPANY_SIZE", "소기업")]


def test_large_company_is_never_a_positive_size_requirement():
    raw = "< 대기업인 소프트웨어 사업자의 참여가능 사업금액의 하한 > 매출액 8천억원 이상인 대기업 80억원 이상"
    for polarity in (None, "POSITIVE"):
        requirements, diagnostics = _adapt({"유형": "기업규모요건", "raw": raw, "기업규모_raw": "대기업"}, polarity)
        assert requirements == []
        assert diagnostics[0]["reason"] == "LARGE_ONLY_SIZE_REQUIREMENT"


def test_size_words_in_one_clause_are_a_union_not_two_requirements():
    raw = "나. 중소기업 및 소상공인으로서 확인서를 소지한 자"
    for span in ("중소기업", "소상공인"):
        requirements, _ = _adapt({"유형": "기업규모요건", "raw": raw, "기업규모_raw": span})
        assert [(r.type, r.value) for r in requirements] == [("COMPANY_SIZE", "중소기업")]


def test_two_regions_in_the_value_span_are_alternatives():
    requirements, _ = _adapt(
        {"유형": "지역요건", "raw": TWO_REGION_CLAUSE, "지역_raw": "[충청남도] 또는 [세종특별시]"}, "POSITIVE"
    )
    assert [(r.value, r.group_operator) for r in requirements] == [("충청남도", "ANY_OF"), ("세종특별자치시", "ANY_OF")]


def test_one_region_in_the_span_but_two_in_the_clause_is_not_confirmed():
    requirements, diagnostics = _adapt({"유형": "지역요건", "raw": TWO_REGION_CLAUSE, "지역_raw": "충청남도"}, "POSITIVE")
    assert requirements == []
    assert diagnostics[0] == {"code": "UNMAPPED_REGION", "raw": TWO_REGION_CLAUSE, "reason": "REGION_RELATION_UNCLEAR"}


def test_name_alternatives_inside_the_value_span_become_any_of():
    requirements, _ = _adapt(
        {"유형": "업종요건", "raw": INDUSTRY_CLAUSE, "업종_raw": "건축공사업(또는 토목건축공사업)"}, "POSITIVE"
    )
    assert [(r.type, r.value, r.group_operator) for r in requirements] == [
        ("INDUSTRY", "0002", "ANY_OF"), ("INDUSTRY", "0003", "ANY_OF"),
    ]
    region, _ = _adapt({"유형": "지역요건", "raw": INDUSTRY_CLAUSE, "지역_raw": "서울특별시"}, "POSITIVE")
    assert [(r.type, r.value) for r in region] == [("REGION", "서울특별시")]


def test_sido_names_are_a_closed_vocabulary():
    assert sido_names("해당 연도 제도 정도 [충청남도] 또는 [세 종특별시] 강원도") == ["충청남도", "세종특별자치시", "강원특별자치도"]
    assert value_name_alternatives("정보통신공사업") is None
    assert value_name_alternatives("진공또는원심농축기 세부품명번호 4110481601") is None   # 품명 안의 '또는'
    assert value_name_alternatives("진공또는원심농축기") is None


def test_polarity_is_asked_once_per_clause_and_remembered():
    calls = []

    def extractor(_system, body, _schema):
        calls.append(body)
        return {"clauses": [{"clause_id": "P001", "polarity": "POSITIVE"}]}

    memory: dict[str, str] = {}
    slots = [{"유형": "지역요건", "raw": REGION_CLAUSE}, {"유형": "실적요건", "raw": REGION_CLAUSE.replace("\n", " ")}]
    info = attach_clause_polarity(slots, structured_extract=extractor, memory=memory)
    assert [slot[POLARITY_KEY] for slot in slots] == ["POSITIVE", "POSITIVE"]
    assert len(calls) == 1 and info["asked"] == 1                      # 줄바꿈만 다른 같은 조항은 한 번만 묻는다
    again = [{"유형": "지역요건", "raw": REGION_CLAUSE}]
    attach_clause_polarity(again, structured_extract=extractor, memory=memory)
    assert len(calls) == 1 and again[0][POLARITY_KEY] == "POSITIVE"    # 기억한 답을 쓴다


def test_failed_call_or_missing_answer_is_unsure():
    def broken(_system, _body, _schema):
        raise RuntimeError("down")

    slots = [{"유형": "지역요건", "raw": REGION_CLAUSE}]
    attach_clause_polarity(slots, structured_extract=broken, memory={})
    assert slots[0][POLARITY_KEY] == "UNSURE"
    slots = [{"유형": "지역요건", "raw": REGION_CLAUSE}]
    attach_clause_polarity(slots, structured_extract=lambda *_: {"clauses": []}, memory={})
    assert slots[0][POLARITY_KEY] == "UNSURE"


def test_city_or_county_requirement_is_not_widened_to_its_province():
    """시·군 한정 요건을 시·도로 넓혀 확정하면 자격 없는 회사에 '충족' 이 나간다(2026-10-06 표본)."""
    raw = "가. 전기공사업(0037)을 등록한 업체로 본점소재지가「전남광주통합특별시 장흥군」에 있는 업체이어야 합니다."
    for span in ("전남광주통합특별시 장흥군", "전남광주통합특별시"):   # 모델이 시·도만 짚어도 원문대로 좁힌다
        requirements, _ = _adapt({"유형": "지역요건", "raw": raw, "지역_raw": span}, "POSITIVE")
        assert [(r.type, r.value) for r in requirements] == [("REGION", "전남광주통합특별시 장흥군")]

    cities = "라. 본점 소재지를 수원시, 용인시, 화성시, 안산시, 의왕시에 둔 업체이어야 합니다."
    requirements, _ = _adapt({"유형": "지역요건", "raw": cities, "지역_raw": "수원시, 용인시, 화성시, 안산시, 의왕시"}, "POSITIVE")
    assert [(r.value, r.group_operator) for r in requirements] == [
        (name, "ANY_OF") for name in ("수원시", "용인시", "화성시", "안산시", "의왕시")
    ]

    province = "본점 소재지가 강원도에 있는 업체"
    requirements, _ = _adapt({"유형": "지역요건", "raw": province, "지역_raw": "강원도"}, "POSITIVE")
    assert [r.value for r in requirements] == ["강원특별자치도"]       # 시·도뿐일 때만 정식 이름으로
    narrower = "본점 소재지가 경기도 남부에 있는 업체"
    requirements, _ = _adapt({"유형": "지역요건", "raw": narrower, "지역_raw": "경기도 남부"}, "POSITIVE")
    assert [r.value for r in requirements] == ["경기도 남부"]          # 장소를 좁히는 말은 지우지 않는다


def test_a_province_only_profile_cannot_satisfy_a_city_requirement():
    from bidengine.judgment.rules import _region_relation

    assert _region_relation("충청남도", "충청남도 보령시") == "too_coarse"    # 예전에는 문자열 포함으로 match
    assert _region_relation("충청남도 보령시", "충청남도 보령시") == "match"
    assert _region_relation("충청남도 보령시", "충청남도") == "match"
    assert _region_relation("경상북도 봉화군", "봉화군") == "match"
    assert _region_relation("충청남도 천안시", "충청남도 보령시") == "none"
    assert _region_relation("서울특별시", "서울특별시 소재") == "match"       # 꾸밈말만 다른 같은 지역


def test_particles_are_removed_before_reading_region_names():
    raw = "다. 주된 영업소의 소재지가 전남광주통합특별시의 북구, 서구, 남구, 동구, 광산구로 된 업체에 한합니다."
    span = "전남광주통합특별시의 북구, 서구, 남구, 동구, 광산구"
    requirements, _ = _adapt({"유형": "지역요건", "raw": raw, "지역_raw": span}, "POSITIVE")
    assert [r.value for r in requirements] == [f"전남광주통합특별시 {name}" for name in ("북구", "서구", "남구", "동구", "광산구")]


def test_region_value_without_any_region_name_is_not_confirmed():
    """지명이 없는 값은 어떤 회사와도 일치하지 않아 모든 회사를 미달로 만든다(2026-10-06 표본)."""
    for span in ("국내에 본사와 생산공장을 갖추어야", "지역제한", "해당 시․도의 관할구역 안"):
        requirements, diagnostics = _adapt({"유형": "지역요건", "raw": f"나. {span} 합니다.", "지역_raw": span}, "POSITIVE")
        assert requirements == []
        assert diagnostics[0]["reason"] == "NO_REGION_NAME"


def test_regions_are_judged_by_name():
    from bidengine.judgment.rules import _region_relation

    assert _region_relation("광주광역시 북구", "전남광주통합특별시 북구") == "match"     # 통합 전 시·도 이름의 회사
    assert _region_relation("대구광역시 북구", "전남광주통합특별시 북구") == "none"      # 같은 이름의 다른 북구
    assert _region_relation("강원도 춘천시", "강원특별자치도") == "match"
    assert _region_relation("충청남도", "충청남도 보령시") == "too_coarse"


@pytest.mark.parametrize("text", [
    "본점 소재지가 전주시인 업체", "전주시이며", "전주시이고", "전주시이어야", "전주시일 것", "전주시만", "전주시여야",
])
def test_copula_and_auxiliary_particles_after_a_sub_region_are_removed(text):
    from bidengine.normalization.regions import find_regions

    assert find_regions(text)[1] == ["전주시"]


def test_a_sub_region_followed_by_a_copula_becomes_a_region_requirement():
    raw = "가. 견적제출 공고일 전일부터 법인등기부상 본점 소재지가 전주시인 업체로서 계약체결일까지 유지되어야 합니다."
    requirements, _ = _adapt({"유형": "지역요건", "raw": raw, "지역_raw": "전주시인 업체"}, "POSITIVE")
    assert [r.value for r in requirements] and all("전주시" in r.value for r in requirements)
