"""Grounded public-document QA for Copilot.

This path is intentionally separate from product judgment. It may search and
explain the current public notice document only after explicit external-processing
opt-in. It never creates an eligibility judgment or a write proposal.
"""

from __future__ import annotations

import os
import re
from sqlalchemy.orm import Session

from bidengine.rag.answer import generate_grounded_answer
from bidengine.rag.retrieval import retrieve
from ..document_rag.service import load_or_build_version_index
from bidengine.rag.store import create_openai_embeddings
from ..models import PreflightCase
from ..qualification.judgment import QualificationJudgmentError
from .chat import CopilotChatRequest, CopilotChatResponse, DocumentSource, route_intent
from .context import ReplyContext
from .presentation import Presentation, Reason, render_answer
from .source_map import SourceMap, cited_sources, source_identity


def _finalize(result: CopilotChatResponse) -> CopilotChatResponse:
    if result.presentation is None:
        result.presentation = Presentation(conclusion=result.answer, limitations=list(result.warnings))
    mapping = SourceMap()
    for source in result.sources:
        mapping.add(source)
    result.sources = mapping.finalize(result.presentation)
    result.answer = render_answer(result.presentation, result.sources)
    result.citations = cited_sources(result.answer, result.presentation, result.sources)
    if result.reply_context is not None:
        result.reply_context.visible_requirement_keys = []
    return result


def _clean_generated_answer(text: str) -> str:
    # GroundedAnswer validates the refs first. Copilot re-renders response-local
    # refs from source identities, so remove the model's temporary [S#] markers.
    cleaned = re.sub(r"\s*\[(?:S[0-9]+)\]", "", text).strip()
    return re.sub(r"[ \t]+\n", "\n", cleaned)


def _is_company_eligibility_question(case_id, text: str) -> bool:
    if not text.strip():
        return False
    return route_intent(CopilotChatRequest(case_id=case_id, message=text.strip())) == "QUALIFICATION_SUMMARY"


def answer_grounded_document_question(
    db: Session,
    request: CopilotChatRequest,
) -> CopilotChatResponse:
    case = db.get(PreflightCase, request.case_id)
    if case is None:
        raise QualificationJudgmentError("PREFLIGHT_CASE_NOT_FOUND", "검토 건이 없습니다.", status_code=404)

    hints = request.conversation_context
    result = CopilotChatResponse(
        intent="DOCUMENT_QA",
        answer="",
        reply_context=ReplyContext(
            request_id=hints.request_id if hints else None,
            context_revision=hints.context_revision if hints else 0,
            status="RESOLVED",
        ),
    )

    if not request.public_document_question or not request.allow_external_processing:
        result.answer = "공고문 근거 답변을 사용하려면 공개 공고문 질문의 외부 처리를 먼저 허용해 주세요."
        result.presentation = Presentation(conclusion=result.answer)
        return _finalize(result)

    question = request.public_document_question.strip()
    # Product truth wins even when a caller explicitly labels the request as
    # DOCUMENT_QA or supplies a different public_document_question. The primary
    # user message and the external-processing question are both checked so a
    # company eligibility request cannot be smuggled through the RAG path.
    if _is_company_eligibility_question(case.id, request.message) or _is_company_eligibility_question(case.id, question):
        result.intent = "QUALIFICATION_SUMMARY"
        result.answer = "회사 참가 가능 여부는 공고문 생성 답변이 아니라 저장된 판정 결과에서 확인해 주세요."
        result.presentation = Presentation(conclusion=result.answer)
        return _finalize(result)

    index = load_or_build_version_index(
        db,
        notice_version_id=case.current_version_id,
        index_root=os.getenv("DOCUMENT_RAG_INDEX_ROOT", "data/document-rag"),
        embeddings=create_openai_embeddings(),
    )
    current_version = str(case.current_version_id)
    if index.notice_version_id != current_version:
        raise ValueError("document index does not match current notice version")

    hits = retrieve(index, question, method="hybrid", k=4, fetch_k=12)
    if any(hit.metadata.notice_version_id != current_version for hit in hits):
        raise ValueError("document hits do not match current notice version")

    result.external_processing_used = True
    result.external_processing_scope = "PUBLIC_NOTICE_DOCUMENT"

    if not hits:
        result.answer = "현재 공고문에서 이 질문에 답할 근거를 찾지 못했습니다. 원문을 직접 확인해 주세요."
        result.presentation = Presentation(
            conclusion=result.answer,
            limitations=["근거 검색 결과가 없어 생성형 답변은 실행하지 않았습니다."],
        )
        return _finalize(result)

    grounded = generate_grounded_answer(question, hits)
    for citation in grounded.citations:
        if citation.notice_version_id != current_version:
            raise ValueError("grounded citation does not match current notice version")

    # Expose only sources that the generated answer actually used. Retrieval-only
    # hits remain internal diagnostics and are evaluated separately in E3 metrics.
    result.sources = [DocumentSource(
        ref="",
        document_id=citation.document_id,
        document_name=citation.document_name,
        notice_version_id=citation.notice_version_id,
        chunk_id=citation.chunk_id,
        clause_label=citation.clause_label,
        page=citation.page,
        source_locations=list(citation.source_locations),
        quote=citation.quote,
    ) for citation in grounded.citations]

    if result.sources:
        generated = _clean_generated_answer(grounded.answer)
        conclusion = generated or "검색된 근거를 확인했습니다."
        refs = [source_identity(source) for source in result.sources]
        result.presentation = Presentation(
            conclusion=conclusion,
            reasons=[Reason(text="답변에 실제로 사용한 공고문 근거입니다.", evidence_refs=refs)],
            limitations=[
                "이 설명은 현재 공고 버전에서 검색된 공개 원문 근거에 한정됩니다.",
                "회사 참가 가능·불가 판정은 저장된 판정 결과에서 별도로 확인해야 합니다.",
            ],
        )
    else:
        # A model answer without any validated citation is not exposed as a factual
        # answer. This is a fail-closed abstention rather than trusting uncited text.
        result.presentation = Presentation(
            conclusion="검색된 근거만으로 이 질문에 답을 확정할 수 없습니다. 원문을 직접 확인해 주세요.",
            limitations=["생성 답변에 검증 가능한 공고문 인용이 없어 내용을 노출하지 않았습니다."],
        )

    return _finalize(result)
