"""Adapters for backend-managed extracted document blocks.

Backend document extraction is the source of truth for file parsing and source
locations. Semantic chunking must preserve those locators instead of flattening
them away.

Backend documents expose two different hashes and they must not be conflated:
- `file_sha256`: hash of the original uploaded/downloaded file
- `extracted_text_sha256`: hash of the extracted text representation
"""

from __future__ import annotations

from typing import Any


def canonical_source_block(
    *,
    document_id: str,
    block: dict[str, Any],
    file_sha256: str | None = None,
    text_sha256: str | None = None,
) -> dict[str, Any]:
    """Normalize a backend extracted block without discarding source provenance."""
    return {
        "document_id": document_id,
        "block_index": block.get("block_index"),
        "page": block.get("page"),
        "section_index": block.get("section_index"),
        "paragraph_index": block.get("paragraph_index"),
        "location": block.get("location"),
        "text": (block.get("text") or "").strip(),
        # `source_sha256` intentionally means the original source file hash.
        "source_sha256": file_sha256,
        "extracted_text_sha256": text_sha256,
    }


def canonical_source_blocks(
    *,
    document_id: str,
    blocks: list[dict[str, Any]] | None,
    file_sha256: str | None = None,
    text_sha256: str | None = None,
) -> list[dict[str, Any]]:
    if not blocks:
        return []
    return [
        canonical_source_block(
            document_id=document_id,
            block=block,
            file_sha256=file_sha256,
            text_sha256=text_sha256,
        )
        for block in blocks
        if (block.get("text") or "").strip()
    ]
