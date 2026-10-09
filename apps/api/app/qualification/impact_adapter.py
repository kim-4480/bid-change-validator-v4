"""Read-only adapter for 024/025 analysis rows and current extracted blocks.

No ORM writes, cloud APIs, migrations, or model inference. PR #7 owns the
production stale policy and must be merged before the write route uses this.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from bidengine.contracts import Evidence, QualificationRequirement
from bidengine.diff.impact_plan import AnalysisSnapshot
from bidengine.labeling.requirement_extraction import _squash
from bidengine.pipeline.analysis_pipeline import QualificationDocumentInput


def analysis_input_fingerprint(documents: Sequence[QualificationDocumentInput]) -> str:
    """Mirror the PR #7 v1 fingerprint format for an offline parity check."""
    lineage = sorted((
        {"document_id": item.document_id,
         "extracted_text_sha256": item.extracted_text_sha256}
        for item in documents
    ), key=lambda item: item["document_id"])
    payload = json.dumps(lineage, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"qualification-analysis-input-v1\n{payload}".encode()).hexdigest()


def company_snapshot_fingerprint(profile: Mapping[str, Any]) -> str:
    payload = json.dumps(profile, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def snapshot_from_analysis(
    analysis_run: Any,
    *,
    notice_id: str,
    documents: Sequence[QualificationDocumentInput],
    company_snapshot: Mapping[str, Any],
    rule_version: str | None,
    model_version: str | None,
    all_documents_extracted: bool,
    verdict_complete: bool = False,
    reference_date: str | None = None,
) -> AnalysisSnapshot:
    """Missing 025 column or any missing document => never marks the run reusable."""
    recorded = getattr(analysis_run, "input_fingerprint", None)
    text_hashes = [doc.extracted_text_sha256 for doc in documents]
    all_hashed = bool(documents) and all(
        doc.document_id and doc.file_sha256 and doc.extracted_text_sha256
        and bool(doc.extracted_blocks) for doc in documents
    )
    source_identity = "|".join(sorted(str(value) for value in text_hashes)) if all_hashed else None
    return AnalysisSnapshot(
        notice_id=notice_id,
        notice_version_id=str(analysis_run.notice_version_id),
        document_fingerprint=source_identity,
        company_snapshot_fingerprint=company_snapshot_fingerprint(company_snapshot),
        rule_version=rule_version,
        extraction_complete=(all_documents_extracted and all_hashed
                             and analysis_run.status == "SUCCEEDED"),
        analysis_run_id=str(analysis_run.id),
        input_fingerprint=recorded,
        verified_input_fingerprint=analysis_input_fingerprint(documents) if all_hashed else None,
        model_version=model_version,
        verdict_complete=verdict_complete,
        reference_date=reference_date,
    )


def current_grounded_requirement_keys(
    requirements: Sequence[QualificationRequirement],
    evidence: Sequence[Evidence],
    documents: Sequence[QualificationDocumentInput],
    *,
    notice_version_id: str,
) -> set[str]:
    """Verify every cited quote is present in the correct extracted revision.

    A missing hash, mixed-version evidence, missing document, or a changed PDF
    page/location invalidates the requirement's current grounding.
    """
    by_document = {document.document_id: document for document in documents}
    by_evidence = {item.evidence_key: item for item in evidence}
    verified: set[str] = set()
    for req in requirements:
        if req.notice_version_id != notice_version_id or not req.evidence_keys:
            continue
        all_valid = True
        for key in req.evidence_keys:
            item = by_evidence.get(key)
            if item is None or item.source_type != "NOTICE_DOCUMENT" or item.notice_version_id != notice_version_id:
                all_valid = False
                break
            document = by_document.get(item.document_id)
            if (document is None or not document.file_sha256 or not document.extracted_text_sha256
                    or item.source_sha256 != document.file_sha256
                    or item.extracted_text_sha256 != document.extracted_text_sha256
                    or not item.quote or not _squash(item.quote)):
                all_valid = False
                break
            blocks = document.extracted_blocks
            start, end = item.location.block_start, item.location.block_end
            if start is not None and end is not None and start > end:
                all_valid = False
                break
            if start is not None:
                blocks = [block for block in blocks if isinstance(block.get("block_index"), int)
                          and start <= block["block_index"] <= (end if end is not None else start)]
            if item.location.page is not None:
                blocks = [block for block in blocks if block.get("page") == item.location.page]
            original = "\n".join(str(block.get("text") or "") for block in blocks)
            if not original or _squash(item.quote) not in _squash(original):
                all_valid = False
                break
        if all_valid:
            verified.add(req.requirement_key)
    return verified
