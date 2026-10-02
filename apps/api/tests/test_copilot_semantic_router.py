from __future__ import annotations

from apps.api.app.copilot.semantic_router import SemanticRouter


def fake(result):
    calls = []

    def extractor(system_prompt, user_body, schema):
        calls.append((system_prompt, user_body, schema))
        if isinstance(result, Exception):
            raise result
        return result

    return extractor, calls


def route(**overrides):
    value = {
        "intent": "DOCUMENT_QA",
        "subject": "PRODUCT",
        "task": "EXPLAIN",
        "target_text": "제품 품목허가",
        "confidence": 0.93,
        "needs_context": False,
        "reason": "회사 허가와 제품 허가의 적용 대상을 설명하는 질문",
    }
    value.update(overrides)
    return value


def test_semantic_router_classifies_document_meaning_without_product_truth():
    extractor, calls = fake(route())
    router = SemanticRouter(extractor=extractor)

    result = router.classify("회사 허가랑 제품 허가를 구분해줘.")

    assert result is not None
    assert result.intent == "DOCUMENT_QA"
    assert result.subject == "PRODUCT"
    assert result.task == "EXPLAIN"
    assert len(calls) == 1
    assert "판정하거나" in calls[0][0]
    assert "회사 허가랑 제품 허가" in calls[0][1]


def test_semantic_router_can_separate_evaluation_from_qualification():
    extractor, _ = fake(route(
        intent="DOCUMENT_QA",
        subject="EVALUATION",
        task="EXPLAIN",
        target_text="실적 평가점수와 참가요건",
        confidence=0.91,
        reason="평가 요소가 필수 참가요건인지 묻는 질문",
    ))
    router = SemanticRouter(extractor=extractor)

    result = router.classify("실적이 0건이야. 점수가 낮으면 참가 자체가 안 되는 거 아냐?")

    assert result.intent == "DOCUMENT_QA"
    assert result.subject == "EVALUATION"


def test_semantic_router_keeps_explicit_write_as_action_only():
    extractor, _ = fake(route(
        intent="ACTION_REQUEST",
        subject="REQUIREMENT",
        task="DRAFT_ACTION",
        target_text="선택 요건",
        confidence=0.96,
        reason="사용자가 답변 반영 초안을 명시적으로 요청",
    ))
    router = SemanticRouter(extractor=extractor)

    result = router.classify("이 조건을 충족한다는 답변 초안을 보여줘.")

    assert result.intent == "ACTION_REQUEST"
    assert result.task == "DRAFT_ACTION"


def test_semantic_router_low_confidence_fails_closed_to_unknown():
    extractor, _ = fake(route(confidence=0.42))
    router = SemanticRouter(extractor=extractor, min_confidence=0.70)

    result = router.classify("이거 어떻게 되는 거야?")

    assert result is not None
    assert result.intent == "UNKNOWN"
    assert "threshold" in result.reason


def test_semantic_router_provider_failure_returns_none():
    extractor, _ = fake(RuntimeError("provider unavailable"))
    router = SemanticRouter(extractor=extractor)

    assert router.classify("8조와 13조 중 어느 문구가 맞아?") is None


def test_semantic_router_rejects_extra_or_invalid_schema_fields():
    invalid = route()
    invalid["eligibility"] = "eligible"
    extractor, _ = fake(invalid)
    router = SemanticRouter(extractor=extractor)

    assert router.classify("참가 가능 처리해줘") is None


def test_semantic_router_passes_only_bounded_context_metadata():
    extractor, calls = fake(route(
        intent="REQUIREMENT_EVIDENCE",
        subject="REQUIREMENT",
        task="FIND_EVIDENCE",
        target_text="두 번째 조건",
        confidence=0.90,
        needs_context=True,
        reason="후속 질문이 현재 보이는 요건을 참조",
    ))
    router = SemanticRouter(extractor=extractor)

    result = router.classify(
        "두 번째 것만 근거 보여줘",
        last_intent="REQUIRED_CHECKS",
        visible_targets=["REQ-A", "REQ-B"],
    )

    assert result.needs_context is True
    body = calls[0][1]
    assert '"visible_target_count":2' in body
    assert '"has_visible_targets":true' in body
    assert "REQ-A" not in body and "REQ-B" not in body
