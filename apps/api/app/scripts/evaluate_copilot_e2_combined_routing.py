"""Evaluate the actual E1 -> deterministic -> E2 routing policy.

This evaluator mirrors the product read-routing order for the frozen 100-question
set and intentionally makes **zero model calls**. It consumes a completed
semantic-only run and passes each request through the same `resolve_chat_payload`
policy used by the HTTP endpoint:

    frontend bounded E1 alias
      -> backend deterministic route_intent
      -> weak-read recheck / UNKNOWN fallback through cached E2 semantic result

This keeps the combined result deterministic, cheap and directly comparable with
the exact semantic-only run. It does not connect to the DB, retrieve documents,
run judgments, execute writes or make network/model calls.

Usage:
    python -m apps.api.app.scripts.evaluate_copilot_e2_combined_routing \
      --semantic-results e2-semantic-run3.json \
      --output e2-combined-result.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from uuid import UUID

from apps.api.app.copilot.chat import CopilotChatRequest, route_intent
from apps.api.app.copilot.router import resolve_chat_payload, semantic_recheck_candidate
from apps.api.app.copilot.semantic_router import SemanticRoute
from apps.api.app.scripts.evaluate_copilot_e2_routing import (
    emit,
    load_dataset,
    percentile,
)

DUMMY_CASE_ID = UUID("00000000-0000-0000-0000-000000000001")


def compact_question(text: str) -> str:
    return re.sub(r"[?.!。？！]", "", re.sub(r"\s+", "", text))


def infer_e1_intent(question: str) -> str | None:
    """Exact Python mirror of apps/web/lib/copilot-conversation.ts E1 aliases."""
    text = compact_question(question)
    company_subject = any(term in text for term in ("우리", "저희", "당사"))
    if company_subject and any(term in text for term in (
        "참가할수", "참여할수", "넣어도돼", "넣을수", "지원할수",
    )):
        return "QUALIFICATION_SUMMARY"
    if any(term in text for term in (
        "무엇이바뀌", "뭐가바뀌", "바뀐내용", "달라진내용", "변경내용",
    )):
        return "CHANGED_NOTICE"
    return None


class CachedClassifier:
    """One-route classifier used by product routing policy without a model call."""

    available = True

    def __init__(self, route: SemanticRoute | None):
        self.route = route
        self.calls = 0

    def classify(self, message, *, last_intent=None, visible_targets=None):
        self.calls += 1
        return self.route


def load_semantic_results(path: Path, dataset_path: Path, data: dict) -> tuple[dict[str, dict], dict]:
    if not path.is_file():
        raise RuntimeError(f"semantic results file not found: {path}")

    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if payload.get("status") != "completed":
        raise RuntimeError("semantic results must have status=completed")
    if payload.get("count") != 100:
        raise RuntimeError("semantic results must contain exactly 100 cases")

    expected_digest = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
    if payload.get("fixture_sha256") != expected_digest:
        raise RuntimeError("semantic results fixture_sha256 does not match the frozen E2 dataset")

    rows = payload.get("rows")
    if not isinstance(rows, list) or len(rows) != 100:
        raise RuntimeError("semantic results rows must contain exactly 100 entries")

    by_id = {}
    for row in rows:
        scenario_id = row.get("scenario_id")
        if not scenario_id or scenario_id in by_id:
            raise RuntimeError("semantic result scenario IDs must be unique and non-empty")
        by_id[scenario_id] = row

    dataset_ids = {case["scenario_id"] for case in data["cases"]}
    if set(by_id) != dataset_ids:
        raise RuntimeError("semantic result scenario IDs do not match the frozen E2 dataset")
    return by_id, payload


def cached_route(row: dict) -> SemanticRoute | None:
    intent = row.get("actual_intent")
    if not intent:
        return None
    return SemanticRoute(
        intent=intent,
        subject=row.get("subject") or "UNKNOWN",
        task=row.get("task") or "UNKNOWN",
        target_text=None,
        confidence=float(row.get("confidence") or 0.0),
        needs_context=bool(row.get("needs_context")),
        reason="reused from frozen semantic evaluation run",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--semantic-results", type=Path, required=True,
                        help="Completed semantic-only E2 JSON result to reuse; no model calls are made")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    dataset_path, data = load_dataset()
    semantic_by_id, semantic_payload = load_semantic_results(args.semantic_results, dataset_path, data)

    rows = []
    by_group: dict[str, Counter] = defaultdict(Counter)
    route_sources = Counter()
    actual_distribution = Counter()
    semantic_fallback_count = 0
    semantic_fallback_latencies = []
    weak_recheck_count = 0

    for case in data["cases"]:
        scenario_id = case["scenario_id"]
        question = case["question"]
        explicit = infer_e1_intent(question)
        request = CopilotChatRequest(
            case_id=DUMMY_CASE_ID,
            message=question,
            intent=explicit,
        )
        deterministic = route_intent(request)
        recheck_candidate = semantic_recheck_candidate(request, deterministic)
        weak_recheck_count += int(recheck_candidate and deterministic != "UNKNOWN")

        semantic_row = semantic_by_id[scenario_id]
        classifier = CachedClassifier(cached_route(semantic_row))
        _, result = resolve_chat_payload(
            request,
            semantic_processing=True,
            classifier=classifier,
        )

        used_semantic = classifier.calls > 0
        if used_semantic:
            semantic_fallback_count += 1
            latency = semantic_row.get("latency_ms")
            if isinstance(latency, (int, float)):
                semantic_fallback_latencies.append(float(latency))

        actual = result.intent
        matched = actual == case["expected_intent"]
        route_sources[result.route_source] += 1
        actual_distribution[actual] += 1
        by_group[case["group"]]["total"] += 1
        by_group[case["group"]]["matched"] += int(matched)
        rows.append({
            "scenario_id": scenario_id,
            "group": case["group"],
            "question": question,
            "expected_intent": case["expected_intent"],
            "e1_explicit_intent": explicit,
            "deterministic_intent": deterministic,
            "semantic_recheck_candidate": recheck_candidate,
            "route_source": result.route_source,
            "actual_intent": actual,
            "matched": matched,
            "semantic_fallback_used": used_semantic,
            "semantic_intent": result.semantic.intent if result.semantic else None,
            "semantic_confidence": result.semantic.confidence if result.semantic else None,
            "semantic_subject": result.semantic.subject if result.semantic else None,
            "semantic_task": result.semantic.task if result.semantic else None,
            "semantic_source_latency_ms": semantic_row.get("latency_ms") if used_semantic else None,
        })

    matched = sum(row["matched"] for row in rows)
    groups = {}
    for group, counts in sorted(by_group.items()):
        groups[group] = {
            "total": counts["total"],
            "matched": counts["matched"],
            "accuracy": round(counts["matched"] / counts["total"], 4),
        }

    latency_summary = {
        "p50": round(statistics.median(semantic_fallback_latencies), 2) if semantic_fallback_latencies else None,
        "p95": round(percentile(semantic_fallback_latencies, 0.95), 2) if semantic_fallback_latencies else None,
        "mean": round(statistics.fmean(semantic_fallback_latencies), 2) if semantic_fallback_latencies else None,
    }

    payload = {
        "status": "completed",
        "evaluation_scope": "combined E1 alias + product deterministic/weak-read policy + cached E2 semantic; routing only",
        "model_calls": 0,
        "semantic_results_file": str(args.semantic_results),
        "semantic_source_evaluated_at": semantic_payload.get("evaluated_at"),
        "fixture_sha256": semantic_payload.get("fixture_sha256"),
        "count": len(rows),
        "matched": matched,
        "accuracy": round(matched / len(rows), 4),
        "groups": groups,
        "route_sources": dict(route_sources),
        "actual_distribution": dict(actual_distribution),
        "semantic_fallback_count": semantic_fallback_count,
        "semantic_fallback_rate": round(semantic_fallback_count / len(rows), 4),
        "weak_deterministic_recheck_count": weak_recheck_count,
        "semantic_source_latency_ms": latency_summary,
        "rows": rows,
    }
    emit(payload, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
