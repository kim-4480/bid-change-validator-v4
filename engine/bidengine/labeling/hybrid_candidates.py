"""Offline section/keyword vs BM25/embedding candidate comparison.

No embedding model or external API is invoked. Dense rankings may be injected
from a precomputed, version-scoped local index and must reference source chunks.
RRF scores indicate ranking only, never legal eligibility/confidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Sequence

from bidengine.labeling.requirement_extraction import (
    _chunk_document_id, select_eligibility_chunks_with_mode,
)
from bidengine.rag.retrieval import _lexical_ranking

DEFAULT_QUERY = "입찰참가자격 참가 요건 지역 소재 업종 등록 면허 인증 실적 인력 기업규모"

@dataclass(frozen=True, slots=True)
class HybridCandidateComparison:
    candidates: list[dict[str, Any]]
    section_ids: tuple[str, ...]
    bm25_ids: tuple[str, ...]
    dense_ids: tuple[str, ...]
    fused_ids: tuple[str, ...]
    section_mode: str

def compare_eligibility_candidates(
    chunks: list[dict[str, Any]], *,
    query: str = DEFAULT_QUERY,
    dense_ranked_ids: Sequence[str] | None = None,
    extra_budget: int = 6,
    context_neighbors: int = 1,
) -> HybridCandidateComparison:
    """Preserve baseline section coverage; add a bounded number of hybrid hits.

    Fused BM25, section and dense hit scores use reciprocal ranks (k=60).
    Adjacent material is included only within the same source document.
    """
    if extra_budget < 0 or context_neighbors < 0:
        raise ValueError("budgets must be nonnegative")
    ids = [str(chunk.get("chunk_id") or "") for chunk in chunks]
    if not all(ids) or len(set(ids)) != len(ids):
        raise ValueError("source chunk ids must be nonempty and unique")
    valid = set(ids)
    dense = list(dense_ranked_ids or [])
    if len(set(dense)) != len(dense) or any(item not in valid for item in dense):
        raise ValueError("dense ranks must be unique ids from the current source")
    selected, mode = select_eligibility_chunks_with_mode(chunks)
    sections = [str(chunk["chunk_id"]) for chunk in selected]
    records = [SimpleNamespace(text=str(chunk.get("text") or ""),
                               metadata=SimpleNamespace(chunk_id=chunk["chunk_id"])) for chunk in chunks]
    lexical = _lexical_ranking(records, query) if records and query.strip() else []
    scores: dict[str, float] = {}
    for ranking in (sections, lexical, dense):
        for rank, item in enumerate(ranking, 1):
            scores[item] = scores.get(item, 0.0) + 1 / (60 + rank)
    fused = sorted(scores, key=lambda item: (-scores[item], item))
    include = set(sections)
    index = {item: i for i, item in enumerate(ids)}
    extras = 0
    for item in fused:
        if item in include or extras >= extra_budget:
            continue
        position = index[item]
        neighbors = [item]
        for distance in range(1, context_neighbors + 1):
            for neighbor in (position - distance, position + distance):
                if 0 <= neighbor < len(chunks) and _chunk_document_id(chunks[neighbor]) == _chunk_document_id(chunks[position]):
                    neighbors.append(ids[neighbor])
        for candidate_id in neighbors:
            if candidate_id not in include and extras < extra_budget:
                include.add(candidate_id)
                extras += 1
    return HybridCandidateComparison(
        candidates=[c for c in chunks if str(c["chunk_id"]) in include],
        section_ids=tuple(sections), bm25_ids=tuple(lexical),
        dense_ids=tuple(dense), fused_ids=tuple(fused), section_mode=mode,
    )
