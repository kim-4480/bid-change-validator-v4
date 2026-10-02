"""Semantic chunking over backend extracted blocks.

This ports the useful clause-heading idea from the LLM/RAG PoC while keeping
backend document/page/section/paragraph locators attached to every chunk.

PDF extraction currently produces one source block per page. A single page can
contain several clauses, so chunking must also inspect headings *inside* a source
block instead of only looking at the first line. Derived source fragments keep
the original backend locator plus line-range metadata for traceability.
"""

from __future__ import annotations

import re
from typing import Any

_HEADING_PATTERNS = [
    re.compile(r"^\s*(제\d+조(?:의\d+)?)\s*[(\s]"),
    re.compile(r"^\s*(제\d+장)\s"),
    re.compile(r"^\s*(\d+(?:\.\d+)+)[.)]?\s+"),
    re.compile(r"^\s*(\d+)[.)]\s+"),
    re.compile(r"^\s*([IVXivx]+)\.\s+"),
    re.compile(r"^\s*([가-힣])[.)]\s+"),
]


def _heading(line: str) -> str | None:
    for pattern in _HEADING_PATTERNS:
        match = pattern.match(line)
        if match:
            return match.group(1)
    return None


def _split_source_block(block: dict[str, Any]) -> list[dict[str, Any]]:
    """Split headings inside one backend block without losing its locator.

    Backend PDF extraction is page-based, while HWP/HWPX is usually
    section/paragraph-based. This function works for both: a one-line paragraph
    simply stays one fragment, while a multi-line PDF page can become several
    clause fragments.

    `source_line_start` / `source_line_end` are 1-based and refer to the text of
    the original backend block. They are internal trace metadata, not a new
    backend source-of-truth identifier.
    """
    block_text = (block.get("text") or "").strip()
    if not block_text:
        return []

    lines = block_text.splitlines() or [block_text]
    boundaries = [index for index, line in enumerate(lines) if _heading(line) is not None]

    # Preserve leading text before the first heading as its own fragment.
    starts: list[int] = []
    if not boundaries or boundaries[0] != 0:
        starts.append(0)
    starts.extend(boundaries)
    starts = sorted(set(starts))

    fragments: list[dict[str, Any]] = []
    for fragment_index, start in enumerate(starts):
        end = starts[fragment_index + 1] if fragment_index + 1 < len(starts) else len(lines)
        text = "\n".join(lines[start:end]).strip()
        if not text:
            continue
        fragments.append(
            {
                **block,
                "text": text,
                "fragment_index": len(fragments),
                "source_line_start": start + 1,
                "source_line_end": end,
            }
        )
    return fragments


def chunk_source_blocks(
    blocks: list[dict[str, Any]],
    *,
    max_chars: int = 1800,
) -> list[dict[str, Any]]:
    """Create semantic chunks while retaining all source block locators."""
    chunks: list[dict[str, Any]] = []
    current_text: list[str] = []
    current_sources: list[dict[str, Any]] = []
    current_label: str | None = None

    def flush() -> None:
        nonlocal current_text, current_sources, current_label
        text = "\n".join(current_text).strip()
        if text:
            chunks.append(
                {
                    "chunk_id": f"CHUNK-{len(chunks):04d}",
                    "clause_label": current_label,
                    "text": text,
                    "source_blocks": list(current_sources),
                }
            )
        current_text = []
        current_sources = []

    for block in blocks:
        for fragment in _split_source_block(block):
            fragment_text = fragment["text"]
            first_line = fragment_text.splitlines()[0]
            fragment_label = _heading(first_line)

            if fragment_label is not None and current_text:
                flush()
            if fragment_label is not None:
                current_label = fragment_label

            current_text.append(fragment_text)
            current_sources.append(fragment)

            if sum(len(part) for part in current_text) >= max_chars:
                flush()

    flush()
    return chunks


def _split_oversized_fragment(
    fragment: dict[str, Any],
    *,
    max_chars: int,
    overlap_chars: int,
) -> list[dict[str, Any]]:
    """Split one large source fragment without manufacturing new locators."""
    text = str(fragment.get("text") or "").strip()
    if len(text) <= max_chars:
        return [fragment]

    lines = text.splitlines() or [text]
    parts: list[dict[str, Any]] = []
    current: list[tuple[int, str]] = []

    def emit() -> None:
        nonlocal current
        if not current:
            return
        part_text = "\n".join(line for _, line in current).strip()
        if part_text:
            line_offset = int(fragment.get("source_line_start") or 1) - 1
            parts.append(
                {
                    **fragment,
                    "text": part_text,
                    "source_line_start": line_offset + current[0][0] + 1,
                    "source_line_end": line_offset + current[-1][0] + 1,
                    "oversized_part_index": len(parts),
                }
            )
        previous = current[-1:] if current else []
        current = previous if previous and len(previous[0][1]) <= overlap_chars else []

    for line_index, line in enumerate(lines):
        # A single physical line may itself exceed the cap. Character slicing is
        # the only safe fallback because there is no finer source locator.
        if len(line) > max_chars:
            emit()
            step = max(1, max_chars - overlap_chars)
            for start in range(0, len(line), step):
                piece = line[start : start + max_chars]
                if not piece:
                    break
                line_offset = int(fragment.get("source_line_start") or 1) - 1
                parts.append(
                    {
                        **fragment,
                        "text": piece,
                        "source_line_start": line_offset + line_index + 1,
                        "source_line_end": line_offset + line_index + 1,
                        "oversized_part_index": len(parts),
                    }
                )
                if start + max_chars >= len(line):
                    break
            current = []
            continue

        candidate = "\n".join([*(value for _, value in current), line])
        if current and len(candidate) > max_chars:
            emit()
            candidate = "\n".join([*(value for _, value in current), line])
            if current and len(candidate) > max_chars:
                current = []
        current.append((line_index, line))

    emit()
    return parts


def chunk_source_blocks_hygienic(
    blocks: list[dict[str, Any]],
    *,
    min_chars: int = 300,
    max_chars: int = 1800,
    overlap_chars: int = 120,
) -> list[dict[str, Any]]:
    """Experimental chunker with a minimum size and a hard maximum.

    The production/default chunker remains byte-for-byte unchanged so the
    goldenset report can compare both strategies before rollout.
    """
    if min_chars < 0 or max_chars < 1 or overlap_chars < 0:
        raise ValueError("chunk size options must be non-negative and max_chars positive")
    if min_chars > max_chars:
        raise ValueError("min_chars cannot exceed max_chars")
    if overlap_chars >= max_chars:
        raise ValueError("overlap_chars must be smaller than max_chars")

    chunks: list[dict[str, Any]] = []
    current_text: list[str] = []
    current_sources: list[dict[str, Any]] = []
    current_label: str | None = None

    def current_length() -> int:
        return len("\n".join(current_text))

    def flush() -> None:
        nonlocal current_text, current_sources, current_label
        text = "\n".join(current_text).strip()
        if text:
            chunks.append(
                {
                    "chunk_id": f"CHUNK-{len(chunks):04d}",
                    "clause_label": current_label,
                    "text": text,
                    "source_blocks": list(current_sources),
                }
            )
        current_text = []
        current_sources = []
        current_label = None

    for block in blocks:
        for source_fragment in _split_source_block(block):
            for fragment in _split_oversized_fragment(
                source_fragment,
                max_chars=max_chars,
                overlap_chars=overlap_chars,
            ):
                fragment_text = str(fragment["text"])
                fragment_label = _heading(fragment_text.splitlines()[0])

                if fragment_label is not None and current_text and current_length() >= min_chars:
                    flush()
                if current_text and current_length() + 1 + len(fragment_text) > max_chars:
                    flush()
                if current_label is None and fragment_label is not None:
                    current_label = fragment_label

                current_text.append(fragment_text)
                current_sources.append(fragment)

                if current_length() >= max_chars:
                    flush()

    flush()
    return chunks
