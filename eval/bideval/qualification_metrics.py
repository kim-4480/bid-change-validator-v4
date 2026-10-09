"""Offline, label-gated extraction and qualification-verdict metrics.

Draft/unreviewed observations are not truth. Undefined denominators return
None rather than invented zero-valued performance measurements.
"""
from __future__ import annotations

from typing import Literal

Status = Literal["SATISFIED", "UNSATISFIED", "UNKNOWN"]


def extraction_prf(
    predicted: set[str], gold: set[str], *, labels_verified: bool,
) -> dict[str, float | int | None]:
    if not labels_verified:
        return {"precision": None, "recall": None, "f1": None,
                "true_positive": None, "false_positive": None, "false_negative": None}
    tp = len(predicted & gold)
    fp = len(predicted - gold)
    fn = len(gold - predicted)
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = (2 * precision * recall / (precision + recall)
          if precision is not None and recall is not None and precision + recall else 0.0 if precision is not None and recall is not None else None)
    return {"precision": precision, "recall": recall, "f1": f1,
            "true_positive": tp, "false_positive": fp, "false_negative": fn}


def verdict_quality(
    predicted: dict[str, Status], expected: dict[str, Status], *,
    labels_verified: bool,
) -> dict[str, float | int | None]:
    if not labels_verified or not expected:
        return {"unknown_rate": None, "false_satisfied": None, "false_unsatisfied": None,
                "missing_predictions": None, "evaluated": None}
    valid = {"SATISFIED", "UNSATISFIED", "UNKNOWN"}
    if any(value not in valid for value in (*predicted.values(), *expected.values())):
        raise ValueError("unsupported verdict")
    return {
        "unknown_rate": sum(predicted.get(key) == "UNKNOWN" for key in expected) / len(expected),
        "false_satisfied": sum(predicted.get(key) == "SATISFIED" and value != "SATISFIED"
                               for key, value in expected.items()),
        "false_unsatisfied": sum(predicted.get(key) == "UNSATISFIED" and value != "UNSATISFIED"
                                 for key, value in expected.items()),
        "missing_predictions": sum(key not in predicted for key in expected),
        "evaluated": len(expected),
    }



def retrieval_recall_at_k(
    ranked_hits: list[tuple[str, str]],
    relevant_chunk_ids: set[str],
    *,
    notice_version_id: str,
    k: int,
    labels_verified: bool,
) -> dict[str, float | int | None]:
    """Measure document-version-scoped Recall@K against HUMAN-approved chunk labels.

    ranked_hits contains (chunk_id, notice_version_id). Never score unreviewed
    labels, empty ground truth, cross-version hits, or duplicated chunk IDs.
    """
    if k < 1:
        raise ValueError("k must be positive")
    if not notice_version_id:
        raise ValueError("notice_version_id is required")
    if any(version != notice_version_id for _, version in ranked_hits):
        raise ValueError("retrieval result contains a different notice version")
    ids = [chunk_id for chunk_id, _ in ranked_hits]
    if any(not chunk_id for chunk_id in ids) or len(set(ids)) != len(ids):
        raise ValueError("retrieval results need unique, non-empty chunk IDs")
    if not labels_verified or not relevant_chunk_ids:
        return {"recall_at_k": None, "retrieved_relevant": None, "relevant": None}
    found = len(set(ids[:k]) & relevant_chunk_ids)
    return {
        "recall_at_k": found / len(relevant_chunk_ids),
        "retrieved_relevant": found,
        "relevant": len(relevant_chunk_ids),
    }
