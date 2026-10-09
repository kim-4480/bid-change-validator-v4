"""Source-grounded evaluation rubric extraction, separate from qualification verdicts.

This module never creates a QualificationRequirement or a bidder score.
The injected extractor is mocked in tests; no cloud calls are required.
"""
from __future__ import annotations

import re
from typing import Any, Callable

from pydantic import BaseModel, Field

from bidengine.contracts import Evidence, EvidenceLocation
from bidengine.evaluation_contracts import EvaluationAnalysisResult, EvaluationCriterion
from bidengine.labeling.requirement_extraction import (
    _chunk_document_id, _heading_text, _label_rank, _squash, build_extraction_body,
)

_EVAL_HEADERS = ("평가기준", "평가 기준", "평가항목", "평가 항목", "제안서 평가", "평가방법", "평가 방법", "기술능력평가", "적격심사", "평가배점")
_EVAL_ROW = re.compile(r"배점|평가점수|점수\s*[:：]|\d+(?:\.\d+)?\s*점|평가항목|평가기준")
_SCORE = re.compile(r"(?<![\d.])\d+(?:\.\d+)?\s*점|배점\s*[:：]?\s*\d+(?:\.\d+)?(?!\d)")
_METHODS = {"QUANTITATIVE", "QUALITATIVE", "PASS_FAIL", "PRESENTATION", "OTHER"}
ExtractFn = Callable[[str, str, dict[str, Any]], dict[str, Any]]

EVALUATION_SCHEMA = {
    "name": "evaluation_criteria",
    "schema": {
        "type": "object", "additionalProperties": False,
        "properties": {"criteria": {
            "type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "properties": {
                    "title": {"type": "string"},
                    "raw": {"type": "string"},
                    "max_score": {"type": ["number", "null"]},
                    "evaluation_method": {"type": "string", "enum": sorted(_METHODS)},
                },
                "required": ["title", "raw", "max_score", "evaluation_method"],
            },
        }},
        "required": ["criteria"],
    },
}

EVALUATION_PROMPT = (
    "Extract only proposal evaluation/scoring criteria, never bidder eligibility. "
    "Copy raw verbatim as a contiguous source excerpt; do not summarize or invent "
    "a point value. If no rubric is present, return an empty criteria list. "
    "Keep score and evaluation_method descriptive; do not predict bidder score."
)

class EvaluationExtractionOutput(BaseModel):
    analysis: EvaluationAnalysisResult
    evidence: list[Evidence] = Field(default_factory=list)

def select_evaluation_chunks(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep evaluation sections and child clauses; never cross document boundaries."""
    selected: set[int] = set()
    for index, chunk in enumerate(chunks):
        heading = _heading_text(chunk).strip()
        rank = _label_rank(chunk)
        if rank is not None and any(word in heading[:65] for word in _EVAL_HEADERS):
            selected.add(index)
            document = _chunk_document_id(chunk)
            for other_index in range(index + 1, len(chunks)):
                other = chunks[other_index]
                if _chunk_document_id(other) != document:
                    break
                other_rank = _label_rank(other)
                if other_rank is not None and other_rank <= rank:
                    break
                selected.add(other_index)
        elif _EVAL_ROW.search(str(chunk.get("text") or "")) and (
            "참가자격" not in heading and "참가 자격" not in heading
        ):
            selected.add(index)
    return [chunk for index, chunk in enumerate(chunks) if index in selected]

def extract_evaluation_criteria(
    chunks: list[dict[str, Any]], *, notice_id: str, notice_version_id: str,
    structured_extract: ExtractFn, max_chars: int = 32000,
) -> EvaluationExtractionOutput:
    """Only output source-cited, versioned rubric entries and diagnostics."""
    selected = select_evaluation_chunks(chunks)
    if not selected:
        return EvaluationExtractionOutput(
            analysis=EvaluationAnalysisResult(
                notice_id=notice_id, notice_version_id=notice_version_id,
                status="PARTIAL", diagnostics=[{"code": "NO_EVALUATION_SECTION"}],
            )
        )
    full_text = build_extraction_body(selected, max_chars=None)
    truncated = len(full_text) > max_chars
    diagnostics: list[dict[str, str]] = []
    if truncated:
        diagnostics.append({"code": "EVALUATION_INPUT_TRUNCATED"})
    try:
        response = structured_extract(EVALUATION_PROMPT, full_text[:max_chars], EVALUATION_SCHEMA)
    except Exception as error:
        return EvaluationExtractionOutput(
            analysis=EvaluationAnalysisResult(
                notice_id=notice_id, notice_version_id=notice_version_id,
                status="FAILED", diagnostics=[{"code": "EVALUATION_EXTRACTOR_ERROR", "detail": type(error).__name__}],
            )
        )
    candidates = response.get("criteria", []) if isinstance(response, dict) else []
    if not isinstance(candidates, list):
        candidates = []
        diagnostics.append({"code": "INVALID_CRITERIA_ARRAY"})
    criteria: list[EvaluationCriterion] = []
    evidences: list[Evidence] = []
    for item in candidates:
        if not isinstance(item, dict):
            diagnostics.append({"code": "INVALID_CRITERION"})
            continue
        raw = item.get("raw")
        title = item.get("title")
        score = item.get("max_score")
        method = item.get("evaluation_method", "OTHER")
        if not isinstance(raw, str) or not raw.strip() or not isinstance(title, str) or not title.strip():
            diagnostics.append({"code": "INVALID_CRITERION"})
            continue
        if method not in _METHODS:
            diagnostics.append({"code": "INVALID_EVALUATION_METHOD"})
            continue
        if score is not None and (
            isinstance(score, bool) or not isinstance(score, (int, float)) or
            not 0 <= score <= 10000 or not _SCORE.search(raw) or
            not any(float(number) == float(score) for number in re.findall(r"\d+(?:\.\d+)?", _SCORE.search(raw).group()))
        ):
            diagnostics.append({"code": "UNVERIFIED_SCORE", "raw": raw})
            continue
        matching = next((
            chunk for chunk in selected
            if _squash(raw) and _squash(raw) in _squash(str(chunk.get("text") or ""))
            and chunk.get("source_blocks")
            and _chunk_document_id(chunk)
        ), None)
        if matching is None:
            diagnostics.append({"code": "EVALUATION_SOURCE_NOT_FOUND", "raw": raw})
            continue
        blocks = matching["source_blocks"]
        document_id = _chunk_document_id(matching)
        first = blocks[0]
        key = f"EVAL-{len(criteria):04d}"
        evidence_key = f"EV-EVAL-{len(criteria):04d}"
        try:
            criterion = EvaluationCriterion(
                criterion_key=key, notice_version_id=notice_version_id,
                title=title, raw=raw, max_score=score,
                evaluation_method=method, evidence_keys=[evidence_key],
            )
            evidence = Evidence(
                evidence_key=evidence_key, source_type="NOTICE_DOCUMENT",
                document_id=document_id, notice_version_id=notice_version_id,
                chunk_id=str(matching["chunk_id"]), quote=raw,
                location=EvidenceLocation(
                    page=first.get("page"), block_start=first.get("block_index"),
                    block_end=blocks[-1].get("block_index"),
                    source_line_start=first.get("source_line_start"),
                    source_line_end=blocks[-1].get("source_line_end"),
                    clause_label=matching.get("clause_label"),
                ),
                source_sha256=first.get("source_sha256"),
                extracted_text_sha256=first.get("extracted_text_sha256"),
            )
        except (ValueError, TypeError):
            diagnostics.append({"code": "INVALID_CRITERION"})
            continue
        criteria.append(criterion)
        evidences.append(evidence)
    status = "PARTIAL" if diagnostics else "SUCCEEDED"
    return EvaluationExtractionOutput(
        analysis=EvaluationAnalysisResult(
            notice_id=notice_id, notice_version_id=notice_version_id,
            status=status, criteria=criteria,
            evidence_keys=[e.evidence_key for e in evidences], diagnostics=diagnostics,
        ),
        evidence=evidences,
    )
