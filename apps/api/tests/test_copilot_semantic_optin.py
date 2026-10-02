from __future__ import annotations

from uuid import uuid4

from apps.api.app.copilot.chat import CopilotChatRequest
from apps.api.app.copilot.router import resolve_chat_payload
from apps.api.app.copilot.semantic_router import SemanticRoute


class FakeClassifier:
    available = True

    def __init__(self, intent="DOCUMENT_QA", confidence=0.95):
        self.intent = intent
        self.confidence = confidence
        self.calls = []

    def classify(self, message, *, last_intent=None, visible_targets=None):
        self.calls.append({
            "message": message,
            "last_intent": last_intent,
            "visible_targets": visible_targets,
        })
        return SemanticRoute(
            intent=self.intent,
            subject="DOCUMENT",
            task="EXPLAIN",
            target_text="공고 조건",
            confidence=self.confidence,
            needs_context=False,
            reason="test",
        )


def request(message="회사 허가랑 제품 허가를 구분해줘", **updates):
    values = {
        "case_id": uuid4(),
        "message": message,
    }
    values.update(updates)
    return CopilotChatRequest(**values)


def test_optin_off_never_calls_semantic_classifier():
    classifier = FakeClassifier()
    payload, resolved = resolve_chat_payload(
        request("회사 허가랑 제품 허가를 구분해줘"),
        semantic_processing=False,
        classifier=classifier,
    )

    assert payload.intent is None
    assert resolved.intent == "UNKNOWN"
    assert resolved.route_source == "FALLBACK"
    assert classifier.calls == []


def test_optin_on_can_fill_deterministic_unknown_read():
    classifier = FakeClassifier("DOCUMENT_QA")
    payload, resolved = resolve_chat_payload(
        request("회사 허가랑 제품 허가를 구분해줘"),
        semantic_processing=True,
        classifier=classifier,
    )

    assert payload.intent == "DOCUMENT_QA"
    assert resolved.intent == "DOCUMENT_QA"
    assert resolved.route_source == "SEMANTIC"
    assert [call["message"] for call in classifier.calls] == ["회사 허가랑 제품 허가를 구분해줘"]


def test_high_confidence_product_truth_read_skips_semantic():
    classifier = FakeClassifier("DOCUMENT_QA")
    payload, resolved = resolve_chat_payload(
        request("우리 회사 참여 가능해?"),
        semantic_processing=True,
        classifier=classifier,
    )

    assert payload.intent is None
    assert resolved.intent == "QUALIFICATION_SUMMARY"
    assert resolved.route_source == "DETERMINISTIC"
    assert classifier.calls == []


def test_weak_required_checks_keyword_match_can_be_rechecked():
    classifier = FakeClassifier("DOCUMENT_QA")
    payload, resolved = resolve_chat_payload(
        request("중소기업 확인서의 제출 시점 조건을 설명해줘."),
        semantic_processing=True,
        classifier=classifier,
    )

    assert payload.intent == "DOCUMENT_QA"
    assert resolved.intent == "DOCUMENT_QA"
    assert resolved.route_source == "SEMANTIC"
    assert len(classifier.calls) == 1


def test_weak_required_checks_can_be_rechecked_as_change_impact():
    classifier = FakeClassifier("CHANGED_NOTICE")
    payload, resolved = resolve_chat_payload(
        request("변경된 조건 때문에 지금 판정이 달라지는지 확인해줘."),
        semantic_processing=True,
        classifier=classifier,
    )

    assert payload.intent == "CHANGED_NOTICE"
    assert resolved.intent == "CHANGED_NOTICE"
    assert resolved.route_source == "SEMANTIC"
    assert len(classifier.calls) == 1


def test_passive_application_explanation_can_be_rechecked():
    classifier = FakeClassifier("DOCUMENT_QA")
    payload, resolved = resolve_chat_payload(
        request("변경된 업종 조건이 지금 공고에서 어떻게 적용되는지 원문 기준으로 설명해줘."),
        semantic_processing=True,
        classifier=classifier,
    )

    assert payload.intent == "DOCUMENT_QA"
    assert resolved.intent == "DOCUMENT_QA"
    assert resolved.route_source == "SEMANTIC"
    assert len(classifier.calls) == 1


def test_semantic_failure_restores_weak_deterministic_read():
    classifier = FakeClassifier("UNKNOWN")
    payload, resolved = resolve_chat_payload(
        request("무엇을 확인해야 해?"),
        semantic_processing=True,
        classifier=classifier,
    )

    assert payload.intent is None
    assert resolved.intent == "REQUIRED_CHECKS"
    assert resolved.route_source == "DETERMINISTIC"
    assert len(classifier.calls) == 1


def test_explicit_ui_intent_skips_semantic():
    classifier = FakeClassifier("DOCUMENT_QA")
    payload, resolved = resolve_chat_payload(
        request("버튼 질문", intent="CHANGED_NOTICE"),
        semantic_processing=True,
        classifier=classifier,
    )

    assert payload.intent == "CHANGED_NOTICE"
    assert resolved.intent == "CHANGED_NOTICE"
    assert classifier.calls == []


def test_user_input_write_boundary_skips_semantic():
    classifier = FakeClassifier("DOCUMENT_QA")
    payload, resolved = resolve_chat_payload(
        request(
            "적용해줘",
            requirement_key="REQ-1",
            user_input={"satisfies_requirement": True},
        ),
        semantic_processing=True,
        classifier=classifier,
    )

    assert resolved.intent == "ACTION_REQUEST"
    assert resolved.route_source == "DETERMINISTIC"
    assert classifier.calls == []


def test_clear_execution_command_skips_semantic_even_without_payload():
    classifier = FakeClassifier("DOCUMENT_QA")
    payload, resolved = resolve_chat_payload(
        request("전체 변경 요건 재검증해줘"),
        semantic_processing=True,
        classifier=classifier,
    )

    assert resolved.intent == "ACTION_REQUEST"
    assert resolved.route_source == "DETERMINISTIC"
    assert classifier.calls == []


def test_semantic_action_escalation_is_blocked():
    classifier = FakeClassifier("ACTION_REQUEST")
    payload, resolved = resolve_chat_payload(
        request("응"),
        semantic_processing=True,
        classifier=classifier,
    )

    assert payload.intent is None
    assert resolved.intent == "UNKNOWN"
    assert resolved.route_source == "FALLBACK"
    assert len(classifier.calls) == 1
