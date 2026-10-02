"""Combine deterministic and semantic intent routing without weakening safety.

This module is deliberately independent from `chat.py` so routing policy can be
unit-tested without a DB session. Product code should pass the deterministic
result first; semantic routing is only allowed to fill an UNKNOWN read request.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from .semantic_router import SemanticRoute

Intent = Literal[
    "QUALIFICATION_SUMMARY",
    "REQUIREMENT_EVIDENCE",
    "REQUIRED_CHECKS",
    "PROFILE_SNAPSHOT",
    "DOCUMENT_QA",
    "ACTION_REQUEST",
    "CHANGED_NOTICE",
    "UNKNOWN",
]


class SemanticClassifier(Protocol):
    def classify(
        self,
        message: str,
        *,
        last_intent: str | None = None,
        visible_targets: list[str] | None = None,
    ) -> SemanticRoute | None: ...


@dataclass(frozen=True)
class ResolvedIntent:
    intent: Intent
    route_source: Literal["DETERMINISTIC", "SEMANTIC", "FALLBACK"]
    semantic: SemanticRoute | None = None


def resolve_intent(
    *,
    deterministic_intent: Intent,
    message: str,
    classifier: SemanticClassifier | None,
    explicit_intent: Intent | None = None,
    has_user_input: bool = False,
    last_intent: str | None = None,
    visible_targets: list[str] | None = None,
) -> ResolvedIntent:
    """Semantic routing may only fill a deterministic UNKNOWN read request.

    Explicit UI routing, write payloads and already-resolved deterministic
    requests never reach the model. This preserves the existing write grammar
    and context controls even when semantic classification is enabled.
    """
    if explicit_intent is not None and explicit_intent != "UNKNOWN":
        return ResolvedIntent(intent=deterministic_intent, route_source="DETERMINISTIC")

    if has_user_input or deterministic_intent == "ACTION_REQUEST":
        return ResolvedIntent(intent=deterministic_intent, route_source="DETERMINISTIC")

    if deterministic_intent != "UNKNOWN":
        return ResolvedIntent(intent=deterministic_intent, route_source="DETERMINISTIC")

    if classifier is None or not getattr(classifier, "available", False):
        return ResolvedIntent(intent="UNKNOWN", route_source="FALLBACK")

    semantic = classifier.classify(
        message,
        last_intent=last_intent,
        visible_targets=visible_targets,
    )
    if semantic is None or semantic.intent == "UNKNOWN":
        return ResolvedIntent(intent="UNKNOWN", route_source="FALLBACK", semantic=semantic)

    # The semantic model is never permitted to create a write route from a
    # deterministic UNKNOWN. Writes remain owned by explicit deterministic
    # grammar / UI proposal flows.
    if semantic.intent == "ACTION_REQUEST":
        return ResolvedIntent(intent="UNKNOWN", route_source="FALLBACK", semantic=semantic)

    return ResolvedIntent(
        intent=semantic.intent,
        route_source="SEMANTIC",
        semantic=semantic,
    )
