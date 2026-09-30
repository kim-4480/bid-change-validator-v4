"""Build Canonical Evidence from validated extraction provenance.

The extraction guardrail attaches `_source_chunk_id` and `_source_blocks` to
accepted slots. This module turns that provenance into the shared Evidence
contract without re-searching the document or inventing location data.
"""

from __future__ import annotations

from typing import Any

from bidengine.contracts import Evidence, EvidenceLocation


def _first_non_null(values: list[Any]) -> Any | None:
    for value in values:
        if value is not None:
            return value
    return None


def _last_non_null(values: list[Any]) -> Any | None:
    for value in reversed(values):
        if value is not None:
            return value
    return None


def _display_location(source_blocks: list[dict[str, Any]]) -> str | None:
    locations: list[str] = []
    for block in source_blocks:
        location = block.get("location")
        if location and location not in locations:
            locations.append(str(location))
    if not locations:
        return None
    if len(locations) == 1:
        return locations[0]
    return f"{locations[0]} ~ {locations[-1]}"


def _single_hash(source_blocks: list[dict[str, Any]], field: str) -> str | None:
    values = {str(block.get(field)) for block in source_blocks if block.get(field)}
    if len(values) > 1:
        raise ValueError(f"evidence source_blocks contain conflicting {field} values")
    return next(iter(values)) if values else None


def build_evidence_from_slot(
    slot: dict[str, Any],
    *,
    evidence_key: str,
    source_type: str,
    notice_version_id: str | None = None,
    case_id: str | None = None,
) -> Evidence:
    """Convert validated slot provenance to Canonical Evidence."""
    source_blocks = list(slot.get("_source_blocks") or [])
    if not source_blocks:
        raise ValueError("validated slot is missing _source_blocks provenance")

    document_ids = {
        str(block.get("document_id"))
        for block in source_blocks
        if block.get("document_id")
    }
    if len(document_ids) != 1:
        raise ValueError("evidence source_blocks must resolve to exactly one document_id")
    document_id = next(iter(document_ids))

    source_sha256 = _single_hash(source_blocks, "source_sha256")
    extracted_text_sha256 = _single_hash(source_blocks, "extracted_text_sha256")

    pages = [block.get("page") for block in source_blocks]
    sections = [block.get("section_index") for block in source_blocks]
    paragraphs = [block.get("paragraph_index") for block in source_blocks]
    block_indexes = [block.get("block_index") for block in source_blocks]
    line_starts = [block.get("source_line_start") for block in source_blocks]
    line_ends = [block.get("source_line_end") for block in source_blocks]

    unique_pages = {page for page in pages if page is not None}
    page = next(iter(unique_pages)) if len(unique_pages) == 1 else None

    unique_sections = {section for section in sections if section is not None}
    section_index = next(iter(unique_sections)) if len(unique_sections) == 1 else None

    return Evidence(
        evidence_key=evidence_key,
        source_type=source_type,
        document_id=document_id,
        notice_version_id=notice_version_id,
        case_id=case_id,
        chunk_id=slot.get("_source_chunk_id"),
        location=EvidenceLocation(
            block_start=_first_non_null(block_indexes),
            block_end=_last_non_null(block_indexes),
            page=page,
            section_index=section_index,
            paragraph_start=_first_non_null(paragraphs),
            paragraph_end=_last_non_null(paragraphs),
            source_line_start=_first_non_null(line_starts),
            source_line_end=_last_non_null(line_ends),
            clause_label=slot.get("근거조항"),
            display=_display_location(source_blocks),
        ),
        quote=(slot.get("raw") or "").strip(),
        source_sha256=source_sha256,
        extracted_text_sha256=extracted_text_sha256,
    )
