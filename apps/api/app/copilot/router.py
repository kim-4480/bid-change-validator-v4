"""Additive Copilot endpoints. Chat never calls action execution."""

from uuid import UUID

from fastapi import APIRouter, Depends, Header
from openai import OpenAIError
from sqlalchemy.orm import Session

from ..auth import authorize_case_access, get_optional_current_user
from ..auth_models import AppUser
from ..ask_back_schemas import QualificationAnswerRead
from ..database import get_db
from ..errors import ApiError
from ..qualification.judgment import QualificationJudgmentError
from ..revalidation_schemas import QualificationRevalidationRead
from .actions import confirm_action
from .chat import CopilotChatRequest, CopilotChatResponse, chat, route_intent
from .context import compact
from .contracts import ConfirmAction
from .document_qa import answer_grounded_document_question
from .intent_resolver import ResolvedIntent, resolve_intent
from .job_catalog import GuidedJobCatalog, catalog_for_case, ensure_question_available, get_question
from .narration import apply_product_narration
from .semantic_router import SemanticRouter

router = APIRouter(prefix="/api/v1/copilot", tags=["copilot"])


@router.get("/jobs", response_model=GuidedJobCatalog)
def copilot_jobs(
    case_id: UUID,
    db: Session = Depends(get_db),
    user: AppUser | None = Depends(get_optional_current_user),
):
    case = authorize_case_access(db, user, case_id)
    return catalog_for_case(case)


def semantic_recheck_candidate(payload: CopilotChatRequest, deterministic: str) -> bool:
    """Return True only for weak free-text deterministic reads."""
    if payload.intent is not None and payload.intent != "UNKNOWN":
        return False
    if payload.user_input is not None:
        return False
    if deterministic == "UNKNOWN":
        return True
    if deterministic == "REQUIRED_CHECKS":
        return True
    if deterministic == "ACTION_REQUEST":
        text = compact(payload.message)
        passive_application_read = "적용되" in text and any(
            word in text for word in ("설명", "어떻게", "의미", "조건", "예외", "원문")
        )
        return passive_application_read
    return False


def resolve_chat_payload(
    payload: CopilotChatRequest,
    *,
    semantic_processing: bool,
    classifier=None,
) -> tuple[CopilotChatRequest, ResolvedIntent]:
    deterministic = route_intent(payload)
    semantic_classifier = classifier
    if semantic_processing and semantic_classifier is None:
        semantic_classifier = SemanticRouter()

    recheck = semantic_processing and semantic_recheck_candidate(payload, deterministic)
    resolver_input = "UNKNOWN" if recheck else deterministic
    context = payload.conversation_context
    resolved = resolve_intent(
        deterministic_intent=resolver_input,
        message=payload.message,
        classifier=semantic_classifier if semantic_processing else None,
        explicit_intent=payload.intent,
        has_user_input=payload.user_input is not None,
        last_intent=context.last_response_intent if context else None,
        visible_targets=context.visible_requirement_keys if context else None,
    )

    if recheck and deterministic != "UNKNOWN" and resolved.route_source == "FALLBACK":
        resolved = ResolvedIntent(
            intent=deterministic,
            route_source="DETERMINISTIC",
            semantic=resolved.semantic,
        )

    if resolved.route_source == "SEMANTIC":
        payload = payload.model_copy(update={"intent": resolved.intent})
    return payload, resolved


def _sync_visible_targets(result: CopilotChatResponse) -> CopilotChatResponse:
    if result.reply_context is None or result.presentation is None:
        return result
    result.reply_context.visible_requirement_keys = list(dict.fromkeys(
        reason.requirement_key
        for reason in result.presentation.reasons
        if reason.requirement_key
    ))[:100]
    return result


@router.post("/chat", response_model=CopilotChatResponse)
def copilot_chat(
    payload: CopilotChatRequest,
    db: Session = Depends(get_db),
    semantic_processing: bool = Header(False, alias="X-Copilot-Semantic-Processing"),
    user: AppUser | None = Depends(get_optional_current_user),
):
    case = authorize_case_access(db, user, payload.case_id)
    guided = get_question(payload.job_id, payload.question_id)
    if guided is not None:
        ensure_question_available(case, guided)
        payload = payload.model_copy(update={"message": guided.label})
    if payload.response_version == '3.1':
        from .orchestration import chat_v31
        return chat_v31(db, payload, user, case, semantic_processing)
    try:
        payload, _ = resolve_chat_payload(
            payload,
            semantic_processing=semantic_processing,
        )
        if route_intent(payload) == "DOCUMENT_QA":
            return answer_grounded_document_question(db, payload)
        result = chat(db, payload)
        if semantic_processing:
            result = apply_product_narration(db, payload, result)
            result = _sync_visible_targets(result)
        return result
    except QualificationJudgmentError as error:
        raise ApiError(error.status_code, error.code, error.message) from error
    except (ValueError, RuntimeError, OpenAIError) as error:
        raise ApiError(502, "DOCUMENT_QA_FAILED", "문서 근거 응답을 안전하게 생성하지 못했습니다.") from error


@router.post("/actions/confirm", response_model=QualificationAnswerRead | QualificationRevalidationRead)
def copilot_confirm(
    payload: ConfirmAction,
    db: Session = Depends(get_db),
    user: AppUser | None = Depends(get_optional_current_user),
):
    authorize_case_access(db, user, payload.action.expected.case_id)
    try:
        return confirm_action(db, payload)
    except QualificationJudgmentError as error:
        db.rollback()
        raise ApiError(error.status_code, error.code, error.message) from error
