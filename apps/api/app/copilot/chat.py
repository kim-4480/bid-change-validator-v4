"""Stateless V0: deterministic product routing, opt-in document RAG, no writes."""

import os
import re
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy.orm import Session

from bidengine.contracts import Evidence
from bidengine.rag.answer import GroundedCitation
from bidengine.rag.retrieval import retrieve
from ..document_rag.service import load_or_build_version_index
from bidengine.rag.store import create_openai_embeddings
from ..models import PreflightCase
from ..qualification.judgment import QualificationJudgmentError
from .actions import ChangedNoticeResult, get_changed_notice, propose_answer
from .contracts import (
    ActionInput, ActionProposal, FreeChatTurn, JudgmentProfileResult, QualificationSummary,
    RequiredChecksResult, RequirementEvidenceResult, RevalidationProposal,
)
from .product_tools import (
    get_judgment_profile_snapshot, get_qualification_summary, get_required_checks,
    get_requirement_evidence, get_explanation_evidence, matching_provenance,
)
from .context import ConversationContext, ReplyContext, compact, depends_on_context, resolve_context
from .presentation import attach_analysis_scope, NextAction, Presentation, present_product, render_answer
from .source_map import SourceMap, cited_sources, source_identity
from .v31_contracts import AnswerEnvelope

Intent = Literal["QUALIFICATION_SUMMARY", "REQUIREMENT_EVIDENCE", "REQUIRED_CHECKS",
                 "PROFILE_SNAPSHOT", "DOCUMENT_QA", "ACTION_REQUEST", "CHANGED_NOTICE", "UNKNOWN"]


class CopilotChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    case_id: UUID
    message: str = Field(min_length=1, max_length=4000)
    requirement_key: str | None = Field(default=None, min_length=1, max_length=200)
    # Explicit UI intent is optional; it selects a read tool, never an eligibility value.
    intent: Intent | None = None
    user_input: ActionInput | None = None
    public_document_question: str | None = Field(default=None, min_length=1, max_length=2000)
    allow_external_processing: StrictBool = False
    conversation_context: ConversationContext | None = None
    response_version: Literal['legacy', '3.1'] = 'legacy'
    conversation_id: UUID | None = None
    context_revision: int | None = Field(default=None, ge=0)
    target_id: str | None = Field(default=None, max_length=100)
    job_id: str | None = Field(default=None, min_length=1, max_length=80)
    question_id: str | None = Field(default=None, min_length=1, max_length=80)
    # 사용자가 입력창에 직접 쓴 질문. 저장된 판정을 평문 한 장으로 만들어 모델에 한 번 묻는다(free_chat.py).
    # 버튼(안내형 질문, 요건 근거 보기)과 실행 요청은 이 경로를 타지 않는다.
    free_chat: StrictBool = False
    history: list[FreeChatTurn] = Field(default_factory=list, max_length=8)


class ProductSource(BaseModel):
    source_origin: Literal["PRODUCT_EVIDENCE"] = "PRODUCT_EVIDENCE"
    ref: str
    evidence: Evidence


class DocumentSource(GroundedCitation):
    source_origin: Literal["DOCUMENT_RAG"] = "DOCUMENT_RAG"


Source = Annotated[ProductSource | DocumentSource, Field(discriminator="source_origin")]


class CopilotChatResponse(BaseModel):
    answer: str
    intent: Intent
    product_state: QualificationSummary | RequirementEvidenceResult | RequiredChecksResult | JudgmentProfileResult | ChangedNoticeResult | None = None
    citations: list[Source] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    actions: list[ActionProposal] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    external_processing_used: bool = False
    external_processing_scope: Literal["PUBLIC_NOTICE_DOCUMENT"] | None = None
    reply_context: ReplyContext | None = None
    presentation: Presentation | None = None
    envelope: 'AnswerEnvelope | None' = None


REVALIDATION_VERB = r"(?:재검증|다시(?:검토|검증|판정|봐|보))"
ACTION_VERB = rf"(?:적용|반영|저장|{REVALIDATION_VERB})"
EXECUTION_END = r"(?:을|를)?(?:해(?:줘|주세요|주십시오|줄래)?|하자|하고싶어|진행해(?:줘|주세요)?|실행해(?:줘|주세요)?|줘)(?:요)?$"


def _limited_revalidation_scope(text, focus):
    # Exclusion/limitation overrides affirmative scope words, including "전체 말고".
    if re.search(r"말고|제외|빼고|빼(?:줘|주세요)|일부|만|번째|(?:전체|모든|전부)(?:는|가|이)?아니", text):
        return True
    return not any(word in text for word in ("전체", "모든", "전부")) and (
        focus is not None or depends_on_context(text) or any(word in text for word in ("선택", "조건", "요건", "항목"))
    )


def _action_control(request):
    """Classify the action verb's scope before considering an execution candidate."""
    text = compact(request.message)
    related = bool(re.search(ACTION_VERB, text))
    information = any(word in text for word in ("이유", "왜", "언제", "결과", "이력", "기록"))
    negative = re.search(
        rf"{ACTION_VERB}(?:은|는|을|를)?(?:하|해|되|돼)?(?:주|주시)?"
        r"(?:지(?:마|말|않)|고싶지않|기싫|안(?:해|하|되|돼|된)|못(?:해|하|되|돼))"
        rf"|(?:안|못){ACTION_VERB}", text,
    )
    bare_negative = re.fullmatch(r"(?:하|해)(?:주)?지(?:마|말|않).*", text)
    cancellation = (related and "취소" in text) or re.fullmatch(r"취소(?:해(?:줘|주세요)?)?", text)
    if negative or bare_negative or cancellation:
        # Past non-execution questions are reads, not commands to cancel.
        prohibition = re.search(r"지(?:마|말|않(?:을래|았으면|겠|길|도록))|고싶지않|기싫", text)
        return "status" if related and information and not prohibition else "cancel"
    if related and information:
        return "explain" if any(word in text for word in ("해야", "필요", "무슨뜻")) else "status"
    if related and any(word in text for word in ("뭐야", "무슨뜻", "설명", "해야", "필요")):
        return "explain"
    if re.search(REVALIDATION_VERB + EXECUTION_END, text):
        return "partial_scope" if _limited_revalidation_scope(text, request.requirement_key) else "revalidate"
    if re.search(r"(?:적용|반영)" + EXECUTION_END, text):
        return "answer"
    if (not request.message.rstrip().endswith(("?", "？")) and "왜" not in text
            and (any(word in text for word in ("충족해", "충족하지않", "충족못"))
                 or ("등록" in text and any(word in text for word in ("돼있", "되어있", "안돼", "안되어"))))):
        return "answer"
    # ponytail: bounded verb grammar; unknown wording/payload alone never proposes a write.
    return "explain" if related or request.intent == "ACTION_REQUEST" or request.user_input is not None else None


def route_intent(request: CopilotChatRequest) -> Intent:
    text = compact(request.message)
    control = _action_control(request)
    if control in ("cancel", "partial_scope"):
        return "ACTION_REQUEST"
    # Product truth wins over document routing, including explicit DOCUMENT_QA hints.
    if any(term in text for term in ("참여가능", "참가가능", "참여불가", "참가불가", "판정결과",
                                     "입찰넣", "입찰해도", "참여해도", "참가해도", "지원할수", "왜미달", "현재결과")):
        return "QUALIFICATION_SUMMARY"
    if any(term in text for term in ("근거", "원문", "어디")) and (request.requirement_key or depends_on_context(text)):
        return "REQUIREMENT_EVIDENCE"
    if request.intent and request.intent not in ("ACTION_REQUEST", "UNKNOWN"):
        return request.intent
    if control in (None, "explain", "status") and any(term in text for term in ("프로필", "회사정보", "판정당시")):
        return "PROFILE_SNAPSHOT"
    if control == "status":
        return "QUALIFICATION_SUMMARY"
    if control in ("answer", "revalidate"):
        return "ACTION_REQUEST"
    if control == "explain" and (re.search(ACTION_VERB, text) or request.intent == "ACTION_REQUEST"):
        return "ACTION_REQUEST"
    if any(term in text for term in ("변경공고", "뭐바뀌", "뭐가바뀌", "변경된요건", "전버전", "다른조건")):
        return "CHANGED_NOTICE"
    if text in ("왜", "왜그래", "이유는", "그러면", "그럼"):
        if request.conversation_context and request.conversation_context.last_response_intent == "CHANGED_NOTICE":
            return "CHANGED_NOTICE"
        return "QUALIFICATION_SUMMARY"
    if any(term in text for term in ("확인", "부족", "입력", "왜", "다음에", "뭘해야", "무엇을해야", "다음할일")):
        return "REQUIRED_CHECKS"
    if any(term in text for term in ("프로필", "회사정보", "판정당시")):
        return "PROFILE_SNAPSHOT"
    if depends_on_context(text):
        return "REQUIRED_CHECKS"
    if request.public_document_question or any(term in text for term in ("공고문", "문서", "근거", "원문")):
        return "DOCUMENT_QA"
    if control == "explain":
        return "ACTION_REQUEST"
    # ponytail: bounded Korean keyword routing; add intent evaluation before a classifier.
    return "UNKNOWN"


def _uses_read_receipt(request):
    return bool(request.conversation_context and request.conversation_context.last_read_receipt
                and (depends_on_context(request.message) or route_intent(request) == "ACTION_REQUEST"))


def chat(db: Session, request: CopilotChatRequest) -> CopilotChatResponse:
    with db.no_autoflush:
        for attempt in range(2):
            try:
                result = _chat(db, request)
                break
            except _ReadConflict:
                if attempt == 1:
                    result = CopilotChatResponse(intent=route_intent(request), answer="")
                    result.reply_context = ReplyContext(
                        status="STALE_CONTEXT",
                        request_id=request.conversation_context.request_id if request.conversation_context else None,
                        context_revision=request.conversation_context.context_revision if request.conversation_context else 0,
                    )
                    _context_message(result)
            except QualificationJudgmentError as error:
                if not (_uses_read_receipt(request)
                        and error.code in ("STALE_JUDGMENT", "CURRENT_JUDGMENT_REQUIRED", "STALE_ACTION_CONTEXT")):
                    raise
                result = CopilotChatResponse(intent=route_intent(request), answer="", reply_context=ReplyContext(
                    status="STALE_CONTEXT", request_id=request.conversation_context.request_id,
                    context_revision=request.conversation_context.context_revision,
                ))
                _context_message(result)
                break
        if result.presentation is None:
            result.presentation = Presentation(conclusion=result.answer, limitations=list(result.warnings))
        mapping = SourceMap()
        for source in result.sources:
            mapping.add(source)
        result.sources = mapping.finalize(result.presentation)
        result.answer = render_answer(result.presentation, result.sources)
        result.citations = cited_sources(result.answer, result.presentation, result.sources)
        result.reply_context.visible_requirement_keys = list(dict.fromkeys(
            reason.requirement_key for reason in result.presentation.reasons if reason.requirement_key
        ))[:100]
        return result


class _ReadConflict(Exception):
    """Discard the entire explanation and retry the read bundle once."""


def _context_message(result):
    messages = {
        "STALE_CONTEXT": "검토 기준이 바뀌었습니다. 현재 항목을 다시 선택해 주세요.",
        "NEEDS_CONTEXT": "어떤 결과를 보고 말씀하셨는지 확인이 필요합니다. 현재 결과에서 항목을 선택해 주세요.",
        "NEEDS_TARGET": "대상 요건을 하나로 확인하지 못했습니다. 확인할 항목을 직접 선택해 주세요.",
    }
    result.answer = messages[result.reply_context.status]
    result.presentation = Presentation(conclusion=result.answer, next_action=NextAction(
        kind="SELECT_REQUIREMENT", label="현재 검토 결과를 확인하고 요건을 다시 선택해 주세요.",
    ))
    result.actions = []
    result.product_state = None
    result.sources = []
    result.reply_context.requirement_key = None
    return result


def _attach_evidence(result, bundles):
    refs = {}
    for bundle in bundles:
        refs[bundle.requirement.requirement_key] = []
        for evidence in bundle.evidence:
            source = ProductSource(ref="", evidence=evidence)
            result.sources.append(source)
            refs[bundle.requirement.requirement_key].append(source_identity(source))
    return refs


def _chat(db: Session, request: CopilotChatRequest) -> CopilotChatResponse:
    case = db.get(PreflightCase, request.case_id)
    if case is None:
        raise QualificationJudgmentError("PREFLIGHT_CASE_NOT_FOUND", "검토 건이 없습니다.", status_code=404)
    intent = route_intent(request)
    result = CopilotChatResponse(intent=intent, answer="질문의 요건 또는 요청 종류를 지정해 주세요.")
    hints = request.conversation_context
    result.reply_context = ReplyContext(
        request_id=hints.request_id if hints else None,
        context_revision=hints.context_revision if hints else 0,
        status="UNSUPPORTED" if intent == "UNKNOWN" else "RESOLVED",
    )
    control = _action_control(request)
    scope_reference = any(term in compact(request.message).lower() for term in (
        "판정밖", "판정에들어가지않", "판정대상이아닌", "구조화에서제외", "제외된요건", "공고확인사항", "notice_fact", "dropped_requirements",
    ))
    if scope_reference and (control in ("answer", "revalidate", "partial_scope") or request.user_input is not None):
        result.answer = "판정 밖 확인사항은 답변 반영 대상이 아닙니다. 참가자격 화면에서 원문과 제외 사유를 확인해 주세요."
        result.reply_context.status = "UNSUPPORTED"
        return result
    if intent == "ACTION_REQUEST" and control in ("cancel", "explain"):
        result.answer = ("요청에 따라 새 작업 제안을 만들지 않았습니다." if control == "cancel" else
                         "재검증은 변경된 참가자격 요건 전체를 다시 검증하는 작업입니다. 실행을 요청하면 제안을 보여주고, 확인 버튼을 누른 뒤에만 실행합니다."
                         if re.search(REVALIDATION_VERB, compact(request.message)) else
                         "답변 반영은 선택한 요건의 입력 내용을 제안으로 확인하고, 확인 버튼을 누른 뒤에만 실행합니다.")
        return result
    revalidation = intent == "ACTION_REQUEST" and control in ("revalidate", "partial_scope")
    if revalidation and request.user_input is not None:
        result.answer = "요건 답변 반영과 변경 요건 전체 재검증은 별도 작업입니다. 원하는 작업을 하나씩 요청해 주세요."
        return result
    summary = None
    changes = None
    focus = request.requirement_key
    if intent == "CHANGED_NOTICE" or revalidation:
        changes = get_changed_notice(db, case.id)
        keys = [c.current_key or c.baseline_key for c in changes.changes]
        result.reply_context = resolve_context(request.message, focus, hints, changes.provenance, keys)
    elif intent in ("QUALIFICATION_SUMMARY", "REQUIRED_CHECKS", "REQUIREMENT_EVIDENCE", "ACTION_REQUEST") or depends_on_context(request.message):
        summary = get_qualification_summary(db, case.id)
        result.reply_context = resolve_context(request.message, focus, hints, summary.provenance,
                                               [j.requirement_key for j in summary.judgments])
    if result.reply_context.status in ("STALE_CONTEXT", "NEEDS_CONTEXT", "NEEDS_TARGET"):
        return _context_message(result)
    if (_uses_read_receipt(request) and hints.last_read_receipt != result.reply_context.last_read_receipt):
        result.reply_context.status = "STALE_CONTEXT"
        return _context_message(result)
    if summary is not None or changes is not None:
        focus = result.reply_context.requirement_key
    if intent == "QUALIFICATION_SUMMARY":
        result.product_state = summary
        keys = [j.requirement_key for j in summary.judgments if not focus or j.requirement_key == focus]
        bundles = get_explanation_evidence(db, case.id, keys) if keys else []
        if not matching_provenance(summary, *bundles):
            raise _ReadConflict()
        result.presentation = present_product(summary, _attach_evidence(result, bundles), focus)
        if control == "status":
            result.presentation.limitations.append("현재 저장된 판정을 조회했습니다. 작업 실행 이력은 조회하지 않으므로 반영·재검증의 실행 시각이나 미처리 이유는 단정할 수 없습니다.")
        attach_analysis_scope(result.presentation, summary, result.sources)
    elif intent == "REQUIRED_CHECKS":
        checks = get_required_checks(db, case.id)
        keys = [q.requirement_key for q in checks.questions if not focus or q.requirement_key == focus]
        bundles = get_explanation_evidence(db, case.id, keys) if keys else []
        if not matching_provenance(summary, checks, *bundles):
            raise _ReadConflict()
        result.product_state = checks
        result.reply_context.visible_requirement_keys = keys[:100]
        result.presentation = present_product(checks, _attach_evidence(result, bundles), focus, summary)
        attach_analysis_scope(result.presentation, summary, result.sources)
    elif intent == "PROFILE_SNAPSHOT":
        result.product_state = get_judgment_profile_snapshot(db, case.id)
        if summary is not None and not matching_provenance(summary, result.product_state):
            raise _ReadConflict()
        result.reply_context = resolve_context(request.message, None, hints, result.product_state.provenance, [])
        if result.reply_context.status != "RESOLVED":
            return _context_message(result)
        result.presentation = present_product(result.product_state, {})
    elif intent == "REQUIREMENT_EVIDENCE":
        if focus:
            evidence = get_requirement_evidence(db, case.id, focus)
            if not matching_provenance(summary, evidence):
                raise _ReadConflict()
            result.product_state = evidence
            result.reply_context.visible_requirement_keys = [focus]
            result.presentation = present_product(evidence, _attach_evidence(result, [evidence]), focus)
        else:
            result.reply_context.status = "NEEDS_TARGET"
            return _context_message(result)
    elif intent == "CHANGED_NOTICE" or (intent == "ACTION_REQUEST" and request.user_input is None):
        if intent == "ACTION_REQUEST" and not revalidation:
            result.answer = "적용할 요건과 명시적인 사용자 답변을 먼저 입력해 주세요."
            return result
        result.product_state = changes
        text = compact(request.message)
        if revalidation and _limited_revalidation_scope(text, focus):
            result.answer = ("현재 재검증 기능은 일부 요건을 제외하거나 한 요건만 선택해서 실행할 수 없습니다. "
                             "변경된 참가자격 요건 전체를 재검증할 수 있습니다. "
                             "전체 변경 요건을 재검증하시려면 ‘전체 변경 요건 재검증해줘’라고 요청해 주세요.")
            return result
        # A read focus is never the scope of the whole-changes write proposal.
        result.presentation = present_product(changes, {}, None if revalidation else focus)
        if revalidation:
            result.actions = [RevalidationProposal(expected=changes.provenance)]
            result.presentation.next_action = NextAction(
                kind="REVIEW_PROPOSAL", label="변경된 참가자격 요건 전체의 재검증 제안입니다. 내용을 확인해 주세요. 아직 실행하지 않았습니다.",
            )
        result.warnings = ["변경 내역이며 새 참가자격 판정이 아닙니다. 재검증은 별도 확인 후 실행됩니다."]
        result.presentation.limitations.extend(result.warnings)
    elif intent == "ACTION_REQUEST":
        if focus and request.user_input is not None:
            proposal = propose_answer(db, case.id, focus, request.user_input)
            if proposal.expected != summary.provenance:
                raise _ReadConflict()
            result.actions = [proposal]
            result.answer = "답변 적용 제안입니다. 아직 저장하지 않았습니다. 내용을 확인해 주세요."
            result.presentation = Presentation(conclusion=result.answer, next_action=NextAction(
                kind="REVIEW_PROPOSAL", label="반영할 내용을 확인해 주세요.", requirement_key=focus,
            ))
        else:
            result.reply_context.status = "NEEDS_TARGET"
            return _context_message(result)
    elif intent == "DOCUMENT_QA":
        if not request.public_document_question or not request.allow_external_processing:
            result.answer = "공개 공고문 질문을 별도로 입력하고 외부 처리에 명시적으로 동의해 주세요."
            return result
        # Never pass message, profile or user_input to embeddings/the answer model.
        question = request.public_document_question
        if route_intent(CopilotChatRequest(case_id=case.id, message=question)) == "QUALIFICATION_SUMMARY":
            result.answer = "회사 참가자격은 저장된 판정 조회를 사용해 주세요."
            return result
        index = load_or_build_version_index(
            db, notice_version_id=case.current_version_id,
            index_root=os.getenv("DOCUMENT_RAG_INDEX_ROOT", "data/document-rag"),
            embeddings=create_openai_embeddings(),
        )
        if index.notice_version_id != str(case.current_version_id):
            raise ValueError("document index does not match current notice version")
        hits = retrieve(index, question, method="hybrid", k=4, fetch_k=12)
        if any(h.metadata.notice_version_id != str(case.current_version_id) for h in hits):
            raise ValueError("document hits do not match current notice version")
        # Copilot V0 exposes source text, never an LLM-generated eligibility claim.
        # The standalone Stage 5 grounded-answer implementation remains available.
        result.sources = [DocumentSource(
            ref="", document_id=h.metadata.document_id, document_name=h.metadata.document_name,
            notice_version_id=h.metadata.notice_version_id, chunk_id=h.metadata.chunk_id,
            clause_label=h.metadata.clause_label, page=h.metadata.page,
            source_locations=list(h.metadata.source_locations), quote=h.text,
        ) for h in hits]
        result.answer = (f"검색된 공고문 원문 {len(hits)}건입니다. 원문 근거를 확인해 주세요."
                         if hits else "검색된 공고문 근거가 없습니다.")
        result.presentation = Presentation(conclusion=result.answer)
        result.external_processing_used = True
        result.external_processing_scope = "PUBLIC_NOTICE_DOCUMENT"
        result.warnings = ["검색된 원문이며 질문의 답이나 참가자격 판정이 아닙니다. 회사 참가자격은 저장된 판정에서 확인해야 합니다."]
    return result
