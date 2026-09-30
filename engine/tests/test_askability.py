from bidengine.judgment.askability import build_semantic_question, classify_askability
from bidengine.contracts import QualificationRequirement


def requirement(**overrides):
    payload = {
        "requirement_key": "REQ-1",
        "notice_version_id": "notice-version",
        "type": "REGISTRATION_CERTIFICATION",
        "operator": "MATCH",
        "value": "정보통신공사업",
        "scope": {"kind": "REGISTRATION"},
        "raw": "정보통신공사업 등록업체이어야 한다.",
    }
    payload.update(overrides)
    return QualificationRequirement(**payload)


def test_simple_registration_is_askable_and_preserves_raw_semantics():
    item = requirement()
    decision = classify_askability(item)
    assert decision.askable is True
    question = build_semantic_question(item)
    assert "정보통신공사업" in question
    assert item.raw in question


def test_joint_contract_clause_is_not_askable():
    item = requirement(
        raw="공동수급체를 구성하여 참가하는 경우 구성원 모두 입찰참가자격등록을 하여야 한다."
    )
    decision = classify_askability(item)
    assert decision.askable is False
    assert decision.reason_code == "COMPOSITE_PARTY_RULE"


def test_representative_conflict_clause_is_not_askable():
    item = requirement(
        raw="입찰참가자격등록증상의 상호 및 대표자가 동일한 경우 변경등록하고 입찰에 참여하여야 한다."
    )
    decision = classify_askability(item)
    assert decision.askable is False
    assert decision.reason_code == "REPRESENTATIVE_CONFLICT_RULE"


def test_negated_registration_clause_is_not_askable():
    item = requirement(raw="입찰참가자격등록을 하지 않아야 하는 자이어야 한다.")
    decision = classify_askability(item)
    assert decision.askable is False
    assert decision.reason_code == "NEGATED_RULE"


def test_numeric_requirement_without_value_is_not_askable():
    item = requirement(
        type="PERFORMANCE_AMOUNT",
        value=None,
        scope={},
        raw="최근 수행실적 금액 기준을 충족하여야 한다.",
    )
    decision = classify_askability(item)
    assert decision.askable is False
    assert decision.reason_code == "STRUCTURED_VALUE_REQUIRED"


def test_missing_or_incompatible_operator_is_not_askable():
    for operator in (None, ">="):
        assert not classify_askability(requirement(operator=operator)).askable
    assert not classify_askability(requirement(type="PERFORMANCE_COUNT", operator=">=", value="not numeric")).askable


def test_real_staff_table_ditto_is_not_a_single_user_fact():
    from bidengine.judgment.clause_safety import unsafe_clause_reason
    assert unsafe_clause_reason("4. 인허가중급1〃") == "UNRESOLVED_TABLE_REFERENCE"
