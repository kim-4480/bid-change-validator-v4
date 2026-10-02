from bidengine.clause_review import (
    CATEGORY_BY_RULE,
    ClauseFinding,
    apply_overlapping_categories,
    overlapping_categories,
)
# 직렬화 계약은 Core 에 있다 — 이 테스트가 데모에 의존하면 데모를 뗄 수 없다.
from bidengine.clause_review import finding_to_payload as _finding_json


def _finding(
    rule_id: str, label: str, excerpt: str, verdict: str = "NEEDS_REVIEW"
) -> ClauseFinding:
    return ClauseFinding(
        rule_id=rule_id,
        risk_type=label,
        category=CATEGORY_BY_RULE[rule_id],
        label=label,
        detection_method="STANDARD_DIFF",
        verdict=verdict,
        reason="검토 필요",
        notice_version_id="version-1",
        chunk_id="CHUNK-0001",
        clause_label="6.1",
        excerpt=excerpt,
    )


def test_overlapping_clause_keeps_every_risk_type_and_category() -> None:
    sentence = "지체상금은 1일당 0.5%이며 총액은 계약금액의 30%를 한도로 한다."
    cap = _finding("penalty_cap", "지체상금 상한 초과", sentence)
    rate = _finding("penalty_rate", "지체상금 요율 과다", sentence)

    categories, risk_types = overlapping_categories(cap, [cap, rate])
    payload = _finding_json(cap, [cap, rate])

    assert categories == ["LATE_PENALTY", "LATE_PENALTY_RATE"]
    assert risk_types == ["지체상금 상한 초과", "지체상금 요율 과다"]
    assert payload["risk_type"] == "지체상금 상한 초과"
    assert payload["risk_types"] == risk_types
    assert payload["category"] == "LATE_PENALTY"
    assert payload["categories"] == categories

    # 스칼라는 그 finding 자신의 값이어야 한다. 대표값으로 덮어쓰면 rule_id 는
    # penalty_rate 인데 category 는 상한이 되어, 한 행 안에 서로 다른 위험의
    # verdict·standard·reason 이 섞인다.
    rate_payload = _finding_json(rate, [cap, rate])
    assert rate_payload["risk_type"] == "지체상금 요율 과다"
    assert rate_payload["category"] == "LATE_PENALTY_RATE"
    # 집합은 같고 자기 값만 맨 앞으로 온다 (categories[0] == category 불변식).
    assert rate_payload["categories"] == ["LATE_PENALTY_RATE", "LATE_PENALTY"]
    assert set(rate_payload["categories"]) == set(payload["categories"])


def test_actionable_verdict_wins_before_the_canonical_type_order() -> None:
    sentence = "지체상금은 1일당 0.5%이며 총액은 계약금액의 30%를 한도로 한다."
    compliant_cap = _finding(
        "penalty_cap", "지체상금 상한", sentence, verdict="COMPLIANT"
    )
    risky_rate = _finding(
        "penalty_rate", "지체상금 요율 과다", sentence, verdict="NEEDS_REVIEW"
    )

    # 우선순위는 **배열의 나머지 순서**를 정할 뿐, 스칼라를 바꾸지 않는다.
    categories, risk_types = overlapping_categories(
        compliant_cap, [compliant_cap, risky_rate]
    )
    assert categories == ["LATE_PENALTY_RATE", "LATE_PENALTY"]
    assert risk_types == ["지체상금 요율 과다", "지체상금 상한"]

    payload = _finding_json(compliant_cap, [compliant_cap, risky_rate])
    assert payload["risk_type"] == "지체상금 상한"
    assert payload["category"] == "LATE_PENALTY"
    # 자기 값이 앞으로 오되 집합은 그대로다.
    assert payload["categories"] == ["LATE_PENALTY", "LATE_PENALTY_RATE"]


def test_canonical_category_order_does_not_follow_detector_input_order() -> None:
    sentence = "지체상금은 1일당 0.5%이며 총액은 계약금액의 30%를 한도로 한다."
    cap = _finding("penalty_cap", "지체상금 상한 초과", sentence)
    rate = _finding("penalty_rate", "지체상금 요율 과다", sentence)

    # 탐지 입력 순서(rate 가 먼저)와 무관하게 배열은 확정 9종 순서를 따른다.
    categories, _risk_types = overlapping_categories(rate, [rate, cap])
    assert categories == ["LATE_PENALTY", "LATE_PENALTY_RATE"]

    payload = _finding_json(rate, [rate, cap])
    assert payload["category"] == "LATE_PENALTY_RATE"
    assert payload["risk_type"] == "지체상금 요율 과다"
    assert set(payload["categories"]) == {"LATE_PENALTY", "LATE_PENALTY_RATE"}


def test_different_source_text_in_same_chunk_is_not_merged() -> None:
    payment = _finding("payment_period", "대금지급 기한 과다", "대금은 30일 이내 지급한다.")
    liability = _finding("liability_scope", "손해배상 범위 과다", "모든 손해를 배상한다.")

    categories, risk_types = overlapping_categories(payment, [payment, liability])

    assert categories == ["PAYMENT_TERMS"]
    assert risk_types == ["대금지급 기한 과다"]

    stored = apply_overlapping_categories([payment])[0].model_dump()
    assert stored["risk_type"] == "대금지급 기한 과다"
    assert stored["risk_types"] == ["대금지급 기한 과다"]
    assert stored["category"] == "PAYMENT_TERMS"
    assert stored["categories"] == ["PAYMENT_TERMS"]


def test_warranty_bond_rule_uses_warranty_category_and_its_own_label() -> None:
    finding = _finding(
        "warranty_bond_rate", "하자보수보증금율", "하자보수보증금율은 2%로 한다."
    )

    payload = _finding_json(finding, [finding])
    stored = apply_overlapping_categories([finding])[0].model_dump()

    assert payload["risk_type"] == "하자보수보증금율"
    assert payload["risk_types"] == ["하자보수보증금율"]
    assert payload["category"] == "WARRANTY_PERIOD"
    assert payload["categories"] == ["WARRANTY_PERIOD"]
    assert stored["categories"] == ["WARRANTY_PERIOD"]


def test_multiple_korean_labels_are_kept_when_they_share_one_category() -> None:
    sentence = "하자보수 기간은 3년이며 하자보수보증금율은 2%로 한다."
    period = _finding("warranty_period", "하자보수 기간 과다", sentence)
    bond = _finding("warranty_bond_rate", "하자보수보증금율 과다", sentence)

    payload = _finding_json(period, [period, bond])

    assert payload["category"] == "WARRANTY_PERIOD"
    assert payload["categories"] == ["WARRANTY_PERIOD"]
    assert payload["risk_type"] == "하자보수 기간 과다"
    assert payload["risk_types"] == ["하자보수 기간 과다", "하자보수보증금율 과다"]


def test_payload_preserves_each_finding_when_rule_id_repeats() -> None:
    first = _finding("penalty_rate", "지체상금 요율 과다", "첫 번째 조항은 1일당 0.5%로 한다.")
    first.chunk_id = "CHUNK-0010"
    first.clause_label = "10.1"
    first.reason = "첫 번째 조항 검토 필요"

    second = _finding("penalty_rate", "지체상금 요율 과다", "두 번째 조항은 1일당 0.7%로 한다.")
    second.chunk_id = "CHUNK-0032"
    second.clause_label = "32.1"
    second.reason = "두 번째 조항 검토 필요"

    findings = [first, second]
    first_payload = _finding_json(first, findings)
    second_payload = _finding_json(second, findings)

    assert first_payload["chunk_id"] == "CHUNK-0010"
    assert first_payload["excerpt"] == "첫 번째 조항은 1일당 0.5%로 한다."
    assert first_payload["reason"] == "첫 번째 조항 검토 필요"

    assert second_payload["chunk_id"] == "CHUNK-0032"
    assert second_payload["excerpt"] == "두 번째 조항은 1일당 0.7%로 한다."
    assert second_payload["reason"] == "두 번째 조항 검토 필요"
