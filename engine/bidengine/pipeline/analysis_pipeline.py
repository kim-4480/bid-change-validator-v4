"""Orchestration for qualification requirement analysis.

This module keeps the integration boundary inside `app.ai` and composes:

    backend document blocks
        -> canonical source blocks
        -> semantic chunks
        -> structured extraction
        -> deterministic value normalization
        -> canonical Requirement + Evidence
        -> RequirementAnalysisResult

The structured LLM extractor remains injectable. Normalization is deterministic;
callers may still override the normalizer in tests or experiments.
"""

from __future__ import annotations

import os
from collections.abc import MutableMapping

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field, model_validator

from bidengine.pipeline.analysis_result import RequirementAnalysisResult, build_requirement_analysis_result
from bidengine.document.backend_blocks import canonical_source_blocks
from bidengine.requirements.canonicalize import canonicalize_validated_slots
from bidengine.document.chunking import chunk_source_blocks
from bidengine.normalization import normalize_value as default_normalize_value
from bidengine.labeling.code_salvage import exception_guarded_codes, salvage_missing_industry_slots
from bidengine.judgment.clause_safety import GUARD_ASSESSED, GUARD_REASON_EXCEPTION
from bidengine.labeling.clause_labeling import extract_clause_slots
from bidengine.labeling.clause_polarity import attach_clause_polarity
from bidengine.labeling.requirement_extraction import StructuredExtractor, extract_legacy_slots
from bidengine.ports import IndustryNameResolver

ValueNormalizer = Callable[[str], dict[str, Any]]


class QualificationDocumentInput(BaseModel):
    """Minimal Backend -> AI document input used by the orchestration layer."""

    document_id: str
    file_sha256: str | None = None
    extracted_text_sha256: str | None = None
    extracted_blocks: list[dict[str, Any]] = Field(default_factory=list)


class QualificationAnalysisInput(BaseModel):
    """Backend-facing input contract for one notice-version analysis run."""

    notice_id: str
    notice_version_id: str
    documents: list[QualificationDocumentInput]

    @model_validator(mode="after")
    def validate_document_ids(self) -> "QualificationAnalysisInput":
        document_ids = [document.document_id for document in self.documents]
        if len(document_ids) != len(set(document_ids)):
            raise ValueError("document_id values must be unique inside one analysis input")
        return self


def _build_global_chunks(
    documents: list[QualificationDocumentInput],
    *,
    max_chunk_chars: int,
) -> list[dict[str, Any]]:
    """Chunk each document independently, then assign run-global chunk IDs."""
    chunks: list[dict[str, Any]] = []

    for document in documents:
        source_blocks = canonical_source_blocks(
            document_id=document.document_id,
            file_sha256=document.file_sha256,
            text_sha256=document.extracted_text_sha256,
            blocks=document.extracted_blocks,
        )
        document_chunks = chunk_source_blocks(source_blocks, max_chars=max_chunk_chars)

        for chunk in document_chunks:
            chunks.append({**chunk, "chunk_id": f"CHUNK-{len(chunks):04d}"})

    return chunks


def _normalize_extracted_slots(
    slots: list[dict[str, Any]],
    *,
    normalize_value: ValueNormalizer,
) -> list[dict[str, Any]]:
    """Apply code-only normalization to numeric operands exposed by extraction."""
    normalized_slots: list[dict[str, Any]] = []

    for source_slot in slots:
        slot = dict(source_slot)
        for raw_field, normalized_field in (
            ("금액_raw", "금액_norm"),
            ("기간_raw", "기간_norm"),
            ("인원_raw", "인원_norm"),
        ):
            raw_value = slot.get(raw_field)
            if raw_value:
                slot[normalized_field] = normalize_value(str(raw_value))
        normalized_slots.append(slot)

    return normalized_slots


def analyze_qualification_documents(
    analysis_input: QualificationAnalysisInput,
    *,
    structured_extract: StructuredExtractor,
    normalize_value: ValueNormalizer = default_normalize_value,
    max_retry: int = 1,
    max_chunk_chars: int = 1800,
    industry_resolver: IndustryNameResolver | None = None,
    extraction_mode: str | None = None,
    polarity_guard: bool | None = None,
    polarity_memory: MutableMapping[str, str] | None = None,
    clause_selection: str | None = None,
    selection_memory: MutableMapping[str, bool] | None = None,
) -> RequirementAnalysisResult:
    """Run one qualification Requirement analysis without touching Backend state."""
    document_ids = [document.document_id for document in analysis_input.documents]
    chunks = _build_global_chunks(analysis_input.documents, max_chunk_chars=max_chunk_chars)

    if not chunks:
        return build_requirement_analysis_result(
            notice_id=analysis_input.notice_id,
            notice_version_id=analysis_input.notice_version_id,
            document_ids=document_ids,
            canonicalized={"requirements": [], "evidence": [], "diagnostics": []},
            extraction_status="failed",
            extraction_notes="분석 가능한 extracted_blocks가 없습니다.",
            target_chunk_ids=[],
        )

    # "clause": 조항 경계와 원문을 코드가 정하고 모델은 조항마다 라벨만 붙인다(S3, 실험 중).
    # "legacy": 자격 절 본문을 통째로 주고 모델이 경계와 원문까지 정한다(현재 기본값).
    # 지정하지 않으면 BIDENGINE_EXTRACTION_MODE 를 본다. 전환은 배포 설정으로 한다.
    mode = extraction_mode or os.getenv("BIDENGINE_EXTRACTION_MODE", "legacy")
    if mode not in {"legacy", "clause"}:
        raise ValueError(f"알 수 없는 추출 방식: {mode}")
    if mode == "clause":
        # 조항 선택 방식: code(제목·키워드) | hybrid(코드 ∪ 모델) | model(모델만). 지정하지 않으면
        # BIDENGINE_CLAUSE_SELECTION 을 본다(기본 code). clause 방식에서만 쓴다.
        extraction = extract_clause_slots(
            chunks,
            structured_extract=structured_extract,
            max_retry=max_retry,
            clause_selection=clause_selection or os.getenv("BIDENGINE_CLAUSE_SELECTION", "code").strip().lower(),
            selection_memory=selection_memory,
        )
    else:
        extraction = extract_legacy_slots(
            chunks,
            structured_extract=structured_extract,
            max_retry=max_retry,
        )

    normalized_slots = _normalize_extracted_slots(
        list(extraction.get("slots") or []),
        normalize_value=normalize_value,
    )

    # 맥락 가드(실험 중): 조항마다 극성을 모델에게 물어 슬롯에 붙인다. 붙은 슬롯은 낱말 가드 대신
    # context_guard 로 판단된다. 지정하지 않으면 BIDENGINE_POLARITY_GUARD(on | off, 기본 off)를 본다.
    use_polarity = (
        polarity_guard if polarity_guard is not None
        else os.getenv("BIDENGINE_POLARITY_GUARD", "off").strip().lower() == "on"
    )
    if use_polarity:
        attach_clause_polarity(
            normalized_slots, structured_extract=structured_extract, memory=polarity_memory, max_retry=max_retry
        )

    canonicalized = canonicalize_validated_slots(
        normalized_slots,
        notice_version_id=analysis_input.notice_version_id,
        source_type="NOTICE_DOCUMENT",
        industry_resolver=industry_resolver,
    )

    if use_polarity:
        # 공동수급·공동계약 조항은 모델이 요건으로 올리지 않아도 확인 필요로 남긴다. 낱말이 닫혀 있어 코드가
        # 찾을 수 있고, 모델의 라벨링에 맡기면 실행에 따라 사람이 볼 자리에서 사라진다.
        seen_raws = {"".join(str(item.get("raw") or "").split()) for item in canonicalized["diagnostics"]}
        seen_raws |= {"".join(item.raw.split()) for item in canonicalized["requirements"]}
        for text in extraction.get("party_clauses") or []:
            key = "".join(text.split())
            if key not in seen_raws:
                seen_raws.add(key)
                canonicalized["diagnostics"].append(
                    {"code": "UNMAPPED_REQUIREMENT", "raw": text, "reason": "COMPOSITE_PARTY_RULE"}
                )

    if chunks:
        # 모델이 빠뜨린 업종코드 조항을 원문에서 채운다. 같은 공고를 반복해 돌리면 어떤
        # 실행에서는 업종 조항이 안 올라오거나, 올라와도 매핑이 못 푼다 — 원문의 숫자는
        # 그대로인데. 기준은 **요건으로 도달한 코드**다. 코드가 확신할 수 있는 것은 코드가
        # 채운다. LLM 호출은 없다.
        #
        # 추출이 통째로 실패해도(호출 오류·전 슬롯 검증 탈락) 돌린다. 원문은 모델과 무관하게
        # 거기 있다. 그 경우 결과는 PARTIAL 로 남아 "모델 없이 채운 것" 임이 드러난다.
        reached = {
            str(item.value)
            for item in canonicalized["requirements"]
            if item.type == "INDUSTRY" and str(item.value).isdigit()
        }
        target_ids = set(extraction.get("target_chunk_ids") or [])
        target_chunks = [chunk for chunk in chunks if chunk.get("chunk_id") in target_ids]
        salvaged = salvage_missing_industry_slots(reached, target_chunks)
        if salvaged:
            salvaged = _normalize_extracted_slots(salvaged, normalize_value=normalize_value)
            if use_polarity:
                attach_clause_polarity(
                    salvaged, structured_extract=structured_extract, memory=polarity_memory, max_retry=max_retry
                )
            extra = canonicalize_validated_slots(
                salvaged,
                notice_version_id=analysis_input.notice_version_id,
                source_type="NOTICE_DOCUMENT",
                key_prefix="REQ-S",
            )
            canonicalized["requirements"].extend(extra["requirements"])
            canonicalized["evidence"].extend(extra["evidence"])
            canonicalized["diagnostics"].extend(extra["diagnostics"])

        # [검수 3차] 업종코드 조항 바로 다음 줄이 갈음·대체·예외 단서면, 그 코드는 무조건
        # 필수로 확정하지 않는다 — 모델 슬롯에서 왔든 위 salvage 에서 왔든 똑같이 적용한다.
        # 원문 청크만 보고 판단하므로 모델이 그 줄을 raw 에 담았는지와 무관하게 매번 같다.
        #
        # 그 코드를 지우지 않고 **구조에 새긴다** — condition_complexity=composite, 사유는
        # scope.guard_reason. 판정기는 composite 를 확인 필요(UNKNOWN)로 두므로 요건 행이 화면에
        # 남고, 사람이 예외 사실을 확인할 자리가 생긴다(골든 J04 transport 가 같은 모양이다).
        guarded = exception_guarded_codes(target_chunks)
        if guarded:
            marked: list = []
            exempted: list = []
            for item in canonicalized["requirements"]:
                if item.type == "INDUSTRY" and str(item.value) in guarded:
                    item = item.model_copy(update={
                        "condition_complexity": "composite",
                        "scope": {**item.scope, "guard": GUARD_ASSESSED, "guard_reason": GUARD_REASON_EXCEPTION},
                    })
                    exempted.append(item)
                marked.append(item)
            if exempted:
                canonicalized["requirements"] = marked
                canonicalized["diagnostics"].extend([
                    {
                        "code": "INDUSTRY_CODE_EXCEPTION_UNRESOLVED",
                        "raw": item.raw,
                        "value": item.value,
                        "reason": "업종코드 조항 다음 줄에 갈음·대체·예외 단서가 있어 무조건 필수로 확정하지 않습니다.",
                    }
                    for item in exempted
                ])

    return build_requirement_analysis_result(
        notice_id=analysis_input.notice_id,
        notice_version_id=analysis_input.notice_version_id,
        document_ids=document_ids,
        canonicalized=canonicalized,
        extraction_status=str(extraction.get("status") or "failed"),
        extraction_notes=str(extraction.get("notes") or ""),
        extraction_dropped_requirements=list(
            extraction.get("dropped_requirements") or []
        ),
        target_chunk_ids=list(extraction.get("target_chunk_ids") or []),
        section_selection=str(extraction.get("selection_mode") or "unknown"),
        input_truncated=bool(extraction.get("input_truncated")),
        candidate_count=int(extraction.get("candidate_count") or 0),
    )
