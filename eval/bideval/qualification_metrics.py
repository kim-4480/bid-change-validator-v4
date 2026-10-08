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
          if precision is not None and recall is not None and precision + recall else None)
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
