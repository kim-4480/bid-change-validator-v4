"""맥락 가드: 조항의 극성(모델)과 닫힌 값의 개수(코드)로 낱말 가드를 다시 판단한다 (2026-10-02)."""
from __future__ import annotations

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
