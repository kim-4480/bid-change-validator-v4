from __future__ import annotations

from apps.api.app.copilot.intent_resolver import resolve_intent
from apps.api.app.copilot.semantic_router import SemanticRoute


class FakeClassifier:
    available = True

    def __init__(self, route):
        self.route = route
        self.calls = []

    def classify(self, message, *, last_intent=None, visible_targets=None):
        self.calls.append((message, last_intent, visible_targets))
        return self.route


def route(intent="DOCUMENT_QA"):
    return SemanticRoute(
        intent=intent,
        subject="DOCUMENT",
        task="EXPLAIN",
        target_text="조건 의미",
        confidence=0.95,
        needs_context=False,
        reason="test",
    )


def test_resolver_uses_semantic_only_for_unknown_read():
    classifier = FakeClassifier(route("DOCUMENT_QA"))

    result = resolve_intent(
        deterministic_intent="UNKNOWN",
        message="회사 허가랑 제품 허가를 구분해줘",
        classifier=classifier,
    )

    assert result.intent == "DOCUMENT_QA"
    assert result.route_source == "SEMANTIC"
    assert len(classifier.calls) == 1


def test_resolver_never_calls_semantic_when_deterministic_already_knows():
    classifier = FakeClassifier(route("DOCUMENT_QA"))

    result = resolve_intent(
        deterministic_intent="QUALIFICATION_SUMMARY",
        message="우리 회사 참여 가능해?",
        classifier=classifier,
    )

    assert result.intent == "QUALIFICATION_SUMMARY"
    assert result.route_source == "DETERMINISTIC"
    assert classifier.calls == []


def test_resolver_explicit_ui_intent_wins_without_model_call():
    classifier = FakeClassifier(route("DOCUMENT_QA"))

    result = resolve_intent(
        deterministic_intent="CHANGED_NOTICE",
        explicit_intent="CHANGED_NOTICE",
        message="버튼 클릭",
        classifier=classifier,
    )

    assert result.intent == "CHANGED_NOTICE"
    assert classifier.calls == []


def test_resolver_user_input_never_reaches_semantic():
    classifier = FakeClassifier(route("DOCUMENT_QA"))

    result = resolve_intent(
        deterministic_intent="ACTION_REQUEST",
        message="적용해줘",
        classifier=classifier,
        has_user_input=True,
    )

    assert result.intent == "ACTION_REQUEST"
    assert classifier.calls == []


def test_resolver_blocks_semantic_action_escalation_from_unknown():
    classifier = FakeClassifier(route("ACTION_REQUEST"))

    result = resolve_intent(
        deterministic_intent="UNKNOWN",
        message="응",
        classifier=classifier,
    )

    assert result.intent == "UNKNOWN"
    assert result.route_source == "FALLBACK"
    assert len(classifier.calls) == 1


def test_resolver_low_confidence_or_provider_failure_remains_unknown():
    low = FakeClassifier(SemanticRoute(
        intent="UNKNOWN",
        subject="UNKNOWN",
        task="UNKNOWN",
        target_text=None,
        confidence=0.40,
        needs_context=False,
        reason="low confidence",
    ))
    result = resolve_intent(
        deterministic_intent="UNKNOWN",
        message="애매한 질문",
        classifier=low,
    )
    assert result.intent == "UNKNOWN"
    assert result.route_source == "FALLBACK"


class UnavailableClassifier:
    available = False


def test_resolver_unavailable_classifier_stays_unknown():
    result = resolve_intent(
        deterministic_intent="UNKNOWN",
        message="문서 질문",
        classifier=UnavailableClassifier(),
    )
    assert result.intent == "UNKNOWN"
    assert result.route_source == "FALLBACK"
