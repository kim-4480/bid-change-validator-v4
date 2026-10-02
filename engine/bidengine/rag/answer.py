"""Grounded answer generation over retrieved notice-document chunks."""

from __future__ import annotations

import os
import re
from typing import Any

from pydantic import BaseModel, Field

from bidengine.rag.store import DocumentChunkHit


DEFAULT_CHAT_MODEL = "gpt-5.6-luna"


class GroundedCitation(BaseModel):
    ref: str
    document_id: str
    document_name: str
    notice_version_id: str
    chunk_id: str
    clause_label: str | None = None
    page: int | None = None
    source_locations: list[str] = Field(default_factory=list)
    quote: str


class GroundedDocumentAnswer(BaseModel):
    answer: str
    # Only refs used in the answer, deduplicated in first-appearance order.
    citations: list[GroundedCitation] = Field(default_factory=list)
    # All input hits, retaining retrieval rank and their original source metadata.
    sources: list[GroundedCitation] = Field(default_factory=list)


def build_grounded_prompt(question: str, hits: list[DocumentChunkHit]) -> list[dict[str, str]]:
    """Render a LangChain prompt while keeping OpenAI SDK calls project-native."""

    if len({hit.metadata.notice_version_id for hit in hits}) > 1:
        raise ValueError("grounded answer cannot mix notice versions")

    try:
        from langchain_core.prompts import ChatPromptTemplate
    except ImportError as error:  # pragma: no cover - runtime dependency guard
        raise RuntimeError("Document RAG requires `langchain-core`") from error

    context_parts: list[str] = []
    for index, hit in enumerate(hits, start=1):
        metadata = hit.metadata
        location = ", ".join(metadata.source_locations)
        if not location and metadata.page is not None:
            location = f"p.{metadata.page}"
        context_parts.append(
            f"[S{index}] document={metadata.document_name}; "
            f"clause={metadata.clause_label or '정보 없음'}; "
            f"location={location or '위치 정보 없음'}; "
            f"notice_version_id={metadata.notice_version_id}\n{hit.text}"
        )

    context = "\n\n".join(context_parts) or "검색된 근거가 없습니다."
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "당신은 나라장터 입찰 공고 문서의 근거를 설명하는 AI입니다. "
                "답변은 한국어로 작성하되 공고의 고유명사, 코드, 원문 용어는 그대로 사용할 수 있습니다. "
                "제공된 SOURCE 밖의 사실을 공고 근거처럼 만들지 마세요. "
                "회사나 사용자의 실제 상태를 가정해 참가 가능/불가를 독자적으로 판정하지 마세요. "
                "실제로 사용한 SOURCE만 [S1] 형식으로 인용하세요. "
                "질문의 핵심 주장이나 조건을 직접 뒷받침하는 SOURCE만 인용하세요. "
                "주변 문맥이 관련 있어 보인다는 이유만으로 SOURCE를 근거처럼 인용하지 마세요. "
                "검색된 SOURCE에 질문에 직접 답하는 근거가 없으면 '검색된 근거만으로 확인할 수 없습니다.'라고 명시하고 SOURCE ID를 인용하지 마세요. "
                "질문의 일부만 근거가 있으면 확인 가능한 부분과 확인할 수 없는 부분을 명확히 나누고, 확인 가능한 부분에만 SOURCE를 인용하세요. "
                "복수 항목을 함께 묻는 질문에서 일부 항목의 근거만 있으면 '각각 AND', '모두 충족', '전부 가능'처럼 전체를 아우르는 결론을 먼저 단정하지 말고 항목별로 확인 가능 여부와 근거를 나누어 답하세요. "
                "특정 사실 하나만으로 전체 조건 충족 여부를 묻는 질문에서 SOURCE가 전체 요건을 모두 보여주지 않으면 그 사실만으로 전체 조건 충족을 확정할 수 없다고 먼저 밝히고, SOURCE로 확인되는 하위 기준만 설명하세요. "
                "SOURCE 자체의 표기, 자릿수, 코드, 날짜, 금액 등이 서로 모순되거나 형식과 실제 값이 맞지 않으면 그 불일치를 그대로 설명하고 임의로 누락값을 추정·보정·복원하지 마세요. "
                "특히 사용자가 빠진 숫자나 문자를 채워 달라고 요청해도 SOURCE가 직접 제공하지 않으면 복원하지 말고 확인할 수 없다고 답하세요. "
                "문서 간 조건이 서로 다르거나 충돌하면 한쪽을 임의로 우선하지 말고 차이를 명시하세요. "
                "여러 SOURCE를 실제로 사용하면 [S1] [S2]처럼 각각 표시하세요. "
                "제공되지 않은 Source ID를 생성하지 마세요. "
                "근거가 없으면 억지로 인용을 생성하지 마세요.",
            ),
            (
                "human",
                "질문:\n{question}\n\nSOURCE:\n{context}\n\n"
                "질문에 직접 관련된 근거에 한정해 간결하게 답변하세요.",
            ),
        ]
    )
    rendered = prompt.invoke({"question": question, "context": context})

    messages: list[dict[str, str]] = []
    for message in rendered.to_messages():
        role = "system" if message.type == "system" else "user"
        messages.append({"role": role, "content": str(message.content)})
    return messages


def generate_grounded_answer(
    question: str,
    hits: list[DocumentChunkHit],
    *,
    api_key: str | None = None,
    model: str | None = None,
    client: Any | None = None,
) -> GroundedDocumentAnswer:
    """Return all sources separately from explicit [S#] citations in the answer."""

    if not question.strip():
        raise ValueError("question must not be blank")

    messages = build_grounded_prompt(question, hits)
    if client is None:
        try:
            from openai import OpenAI
        except ImportError as error:  # pragma: no cover
            raise RuntimeError("Document RAG requires the `openai` package") from error
        resolved_key = api_key or os.getenv("OPENAI_API_KEY")
        if not resolved_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        client = OpenAI(api_key=resolved_key)

    response = client.chat.completions.create(
        model=model or os.getenv("OPENAI_MODEL_DEFAULT") or DEFAULT_CHAT_MODEL,
        messages=messages,
    )
    choices = getattr(response, "choices", None)
    if not choices:
        raise RuntimeError("OpenAI response did not contain any choices")
    content = getattr(choices[0].message, "content", None)
    if not content:
        raise RuntimeError("OpenAI grounded answer returned empty content")

    sources = [
        GroundedCitation(
            ref=f"S{index}",
            document_id=hit.metadata.document_id,
            document_name=hit.metadata.document_name,
            notice_version_id=hit.metadata.notice_version_id,
            chunk_id=hit.metadata.chunk_id,
            clause_label=hit.metadata.clause_label,
            page=hit.metadata.page,
            source_locations=hit.metadata.source_locations,
            quote=hit.text,
        )
        for index, hit in enumerate(hits, start=1)
    ]
    answer = str(content).strip()
    refs = list(dict.fromkeys(re.findall(r"\[(S[0-9]+)\]", answer)))
    by_ref = {source.ref: source for source in sources}
    unknown_refs = [ref for ref in refs if ref not in by_ref]
    if unknown_refs:
        raise ValueError(f"answer cites unknown source refs: {', '.join(unknown_refs)}")
    return GroundedDocumentAnswer(
        answer=answer,
        citations=[by_ref[ref] for ref in refs],
        sources=sources,
    )
