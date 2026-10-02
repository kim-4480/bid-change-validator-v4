"""Evaluate E3 Grounded Answer quality after locking retrieval to Hybrid.

This evaluator intentionally separates retrieval from generation. It reuses the
same frozen 60-question Document QA fixture, skips the one known cross-version
scope gap, retrieves with the product-default Hybrid path, and generates one
Grounded Answer per evaluable case.

Automatically measured metrics are structural/grounding metrics only:
- valid citation presence
- expected frozen evidence actually cited (strict excerpt matcher)
- citation notice-version integrity
- retrieval / generation / total latency

It does NOT claim semantic answer correctness. The full answer, citation texts,
and conservative risk flags are written per case for later human/rubric review.
No product data or qualification judgment is changed.

Usage:
    python -m apps.api.app.scripts.evaluate_copilot_e3_grounded_answers \
      --output e3-grounded-answer-result.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path

from apps.api.app.scripts.evaluate_copilot_e3_document_qa import (
    KNOWN_TARGET_NOTES,
    _is_connection_limit,
    _prepare_eval_engine,
    emit,
    load_fixtures,
    load_local_env,
    percentile,
    quote_match,
    repository_root,
)


ELIGIBILITY_LANGUAGE_PATTERNS = (
    r"참가\s*(?:가능|불가)",
    r"입찰\s*(?:가능|불가)",
    r"자격(?:을|이)?\s*(?:충족|미충족)",
    r"참가자격(?:을|이)?\s*(?:충족|미충족)",
)


def _eligibility_language_flag(answer: str) -> bool:
    """Conservative review flag only; never treated as an automatic violation."""
    return any(re.search(pattern, answer) for pattern in ELIGIBILITY_LANGUAGE_PATTERNS)


def _latency(values: list[float]) -> dict[str, float | None]:
    return {
        "p50": round(statistics.median(values), 2) if values else None,
        "p95": round(percentile(values, 0.95), 2) if values else None,
        "mean": round(statistics.fmean(values), 2) if values else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--k", type=int, default=4)
    parser.add_argument("--fetch-k", type=int, default=12)
    parser.add_argument("--model", default=None)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.k < 1 or args.fetch_k < args.k:
        raise RuntimeError("require fetch-k >= k >= 1")

    root = repository_root()
    env_files = load_local_env(root)
    cases_path, evidence_path, fixture, evidence_by_id = load_fixtures(root)
    digests = {
        "cases_sha256": hashlib.sha256(cases_path.read_bytes()).hexdigest(),
        "evidence_sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
    }

    scope_gaps: list[dict] = []
    missing_evidence: list[dict] = []
    for case in fixture["cases"]:
        expected = []
        for evidence_id in case["expected_evidence_ids"]:
            row = evidence_by_id.get(evidence_id)
            if row is None:
                missing_evidence.append({"scenario_id": case["scenario_id"], "evidence_id": evidence_id})
                continue
            expected.append(row)
        cross = [row["evidence_id"] for row in expected if row["source_order"] != case["source_order"]]
        if cross:
            scope_gaps.append({
                "scenario_id": case["scenario_id"],
                "reason": "CURRENT_VERSION_RAG_CANNOT_RETRIEVE_PREVIOUS_VERSION_EVIDENCE",
                "cross_version_evidence_ids": cross,
            })
    if missing_evidence:
        raise RuntimeError(f"missing expected evidence rows: {missing_evidence}")

    if not os.getenv("OPENAI_API_KEY"):
        emit({
            "status": "not_run",
            "reason": "OPENAI_API_KEY is not configured after loading local env files",
            "evaluation_scope": "E3 Grounded Answer structural/citation evaluation",
            **digests,
            "count": 60,
            "model_calls": 0,
            "local_env_files_found": env_files,
        }, args.output)
        return 2

    # Delay runtime imports until .env is loaded.
    from openai import OpenAI
    from sqlalchemy import select
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm import Session

    from apps.api.app.config import get_settings
    from bidengine.rag.answer import DEFAULT_CHAT_MODEL, generate_grounded_answer
    from bidengine.rag.retrieval import retrieve
    from apps.api.app.document_rag.service import load_or_build_version_index
    from bidengine.rag.store import create_openai_embeddings
    from apps.api.app.models import BidNotice, BidNoticeVersion

    answer_model = (
        args.model
        or os.getenv("OPENAI_MODEL_DEFAULT")
        or DEFAULT_CHAT_MODEL
    )
    client = OpenAI(timeout=45.0, max_retries=2)

    configured_url = os.getenv("E3_DATABASE_URL") or get_settings().sqlalchemy_database_url
    try:
        engine, database_connection_mode, initial_connection_error = _prepare_eval_engine(configured_url)
    except OperationalError as error:
        reason = "DB_CONNECTION_LIMIT" if _is_connection_limit(error) else "DB_CONNECTION_FAILED"
        emit({
            "status": "not_run",
            "reason": reason,
            "evaluation_scope": "E3 Grounded Answer structural/citation evaluation",
            **digests,
            "count": 60,
            "model_calls": 0,
            "answer_model": answer_model,
            "local_env_files_found": env_files,
        }, args.output)
        return 3

    embeddings = create_openai_embeddings()
    scope_gap_ids = {row["scenario_id"] for row in scope_gaps}
    rows: list[dict] = []
    retrieval_latencies: list[float] = []
    generation_latencies: list[float] = []
    total_latencies: list[float] = []

    evaluated_cases = 0
    model_calls = 0
    generation_successes = 0
    citation_present_cases = 0
    citation_version_integrity_cases = 0
    expected_any_cited_cases = 0
    expected_all_cited_cases = 0
    zero_citation_cases = 0
    no_hit_abstentions = 0
    eligibility_language_flags = 0
    expected_evidence_total = 0
    expected_evidence_cited = 0

    try:
        with Session(engine, autoflush=False, expire_on_commit=False) as db:
            for case in fixture["cases"]:
                scenario_id = case["scenario_id"]
                if scenario_id in scope_gap_ids:
                    rows.append({
                        "scenario_id": scenario_id,
                        "notice_no": case["notice_no"],
                        "source_order": case["source_order"],
                        "question": case["question"],
                        "status": "SCOPE_GAP",
                        "expected_evidence_ids": case["expected_evidence_ids"],
                    })
                    continue

                version_ids = list(db.scalars(
                    select(BidNoticeVersion.id)
                    .join(BidNotice, BidNotice.id == BidNoticeVersion.notice_id)
                    .where(BidNotice.bid_notice_no == case["notice_no"])
                    .where(BidNoticeVersion.bid_notice_order == case["source_order"])
                ))
                if len(version_ids) != 1:
                    rows.append({
                        "scenario_id": scenario_id,
                        "notice_no": case["notice_no"],
                        "source_order": case["source_order"],
                        "question": case["question"],
                        "status": "SOURCE_LOOKUP_FAILED",
                        "resolved_version_count": len(version_ids),
                        "expected_evidence_ids": case["expected_evidence_ids"],
                    })
                    continue

                evaluated_cases += 1
                notice_version_id = version_ids[0]
                current_version = str(notice_version_id)
                expected_rows = [evidence_by_id[eid] for eid in case["expected_evidence_ids"]]
                expected_evidence_total += len(expected_rows)

                total_started = time.perf_counter()
                retrieval_started = time.perf_counter()
                index = load_or_build_version_index(
                    db,
                    notice_version_id=notice_version_id,
                    index_root=os.getenv("DOCUMENT_RAG_INDEX_ROOT", "data/document-rag"),
                    embeddings=embeddings,
                )
                if index.notice_version_id != current_version:
                    raise ValueError("document index does not match requested notice version")
                hits = retrieve(index, case["question"], method="hybrid", k=args.k, fetch_k=args.fetch_k)
                retrieval_ms = (time.perf_counter() - retrieval_started) * 1000
                retrieval_latencies.append(retrieval_ms)

                if any(hit.metadata.notice_version_id != current_version for hit in hits):
                    raise ValueError("retrieved hit does not match requested notice version")

                if not hits:
                    no_hit_abstentions += 1
                    total_ms = (time.perf_counter() - total_started) * 1000
                    total_latencies.append(total_ms)
                    rows.append({
                        "scenario_id": scenario_id,
                        "notice_no": case["notice_no"],
                        "source_order": case["source_order"],
                        "notice_version_id": current_version,
                        "question": case["question"],
                        "status": "ABSTAIN_NO_HITS",
                        "expected_evidence_ids": case["expected_evidence_ids"],
                        "retrieval_latency_ms": round(retrieval_ms, 2),
                        "generation_latency_ms": None,
                        "total_latency_ms": round(total_ms, 2),
                    })
                    continue

                generation_started = time.perf_counter()
                try:
                    grounded = generate_grounded_answer(
                        case["question"],
                        hits,
                        model=answer_model,
                        client=client,
                    )
                    model_calls += 1
                except Exception as error:
                    total_ms = (time.perf_counter() - total_started) * 1000
                    total_latencies.append(total_ms)
                    rows.append({
                        "scenario_id": scenario_id,
                        "notice_no": case["notice_no"],
                        "source_order": case["source_order"],
                        "notice_version_id": current_version,
                        "question": case["question"],
                        "status": "GENERATION_FAILED",
                        "error": str(error),
                        "expected_evidence_ids": case["expected_evidence_ids"],
                        "retrieval_latency_ms": round(retrieval_ms, 2),
                        "generation_latency_ms": None,
                        "total_latency_ms": round(total_ms, 2),
                    })
                    continue

                generation_ms = (time.perf_counter() - generation_started) * 1000
                total_ms = (time.perf_counter() - total_started) * 1000
                generation_latencies.append(generation_ms)
                total_latencies.append(total_ms)
                generation_successes += 1

                citations = list(grounded.citations)
                citation_present = bool(citations)
                citation_present_cases += int(citation_present)
                zero_citation_cases += int(not citation_present)

                version_integrity = all(citation.notice_version_id == current_version for citation in citations)
                citation_version_integrity_cases += int(version_integrity)
                if not version_integrity:
                    raise ValueError("grounded citation does not match requested notice version")

                expected_matches: dict[str, list[str]] = {}
                for expected in expected_rows:
                    matched_refs = [
                        citation.ref
                        for citation in citations
                        if quote_match(citation.quote, expected["quote"])
                    ]
                    expected_matches[expected["evidence_id"]] = matched_refs

                cited_count = sum(bool(refs) for refs in expected_matches.values())
                expected_evidence_cited += cited_count
                any_expected_cited = cited_count > 0
                all_expected_cited = cited_count == len(expected_rows)
                expected_any_cited_cases += int(any_expected_cited)
                expected_all_cited_cases += int(all_expected_cited)

                language_flag = _eligibility_language_flag(grounded.answer)
                eligibility_language_flags += int(language_flag)

                rows.append({
                    "scenario_id": scenario_id,
                    "notice_no": case["notice_no"],
                    "source_order": case["source_order"],
                    "notice_version_id": current_version,
                    "question": case["question"],
                    "status": "GENERATED",
                    "expected_evidence_ids": case["expected_evidence_ids"],
                    "expected_evidence_citation_refs": expected_matches,
                    "expected_evidence_cited_count": cited_count,
                    "expected_evidence_count": len(expected_rows),
                    "any_expected_evidence_cited": any_expected_cited,
                    "all_expected_evidence_cited": all_expected_cited,
                    "citation_present": citation_present,
                    "citation_version_integrity": version_integrity,
                    "eligibility_language_review_flag": language_flag,
                    "evaluation_target_note": KNOWN_TARGET_NOTES.get(scenario_id),
                    "answer": grounded.answer,
                    "citations": [citation.model_dump() for citation in citations],
                    "retrieved_sources": [source.model_dump() for source in grounded.sources],
                    "retrieval_latency_ms": round(retrieval_ms, 2),
                    "generation_latency_ms": round(generation_ms, 2),
                    "total_latency_ms": round(total_ms, 2),
                })
    finally:
        engine.dispose()

    generated_denominator = generation_successes or 1
    payload = {
        "status": "completed",
        "evaluation_scope": "E3 Hybrid retrieval + Grounded Answer structural/citation grounding only; semantic answer correctness requires separate review",
        "retrieval_method": "hybrid",
        "k": args.k,
        "fetch_k": args.fetch_k,
        "answer_model": answer_model,
        "model_calls": model_calls,
        "database_connection_mode": database_connection_mode,
        "session_pooler_preflight_failed": bool(initial_connection_error),
        **digests,
        "count": 60,
        "evaluated_cases": evaluated_cases,
        "scope_gap_cases": len(scope_gaps),
        "scope_gaps": scope_gaps,
        "source_lookup_failed_cases": sum(row["status"] == "SOURCE_LOOKUP_FAILED" for row in rows),
        "generation_successes": generation_successes,
        "generation_failed_cases": sum(row["status"] == "GENERATION_FAILED" for row in rows),
        "no_hit_abstentions": no_hit_abstentions,
        "citation_present_cases": citation_present_cases,
        "citation_presence_rate": round(citation_present_cases / generated_denominator, 4),
        "zero_citation_cases": zero_citation_cases,
        "citation_version_integrity_cases": citation_version_integrity_cases,
        "citation_version_integrity_rate": round(citation_version_integrity_cases / generated_denominator, 4),
        "expected_evidence_count": expected_evidence_total,
        "expected_evidence_cited": expected_evidence_cited,
        "expected_evidence_citation_recall": round(expected_evidence_cited / expected_evidence_total, 4) if expected_evidence_total else None,
        "case_any_expected_evidence_cited": round(expected_any_cited_cases / evaluated_cases, 4) if evaluated_cases else None,
        "case_all_expected_evidence_cited": round(expected_all_cited_cases / evaluated_cases, 4) if evaluated_cases else None,
        "eligibility_language_review_flags": eligibility_language_flags,
        "review_note": "eligibility_language_review_flags are conservative text flags, not automatic safety violations; semantic correctness and abstention appropriateness require rubric/human review",
        "retrieval_latency_ms": _latency(retrieval_latencies),
        "generation_latency_ms": _latency(generation_latencies),
        "total_latency_ms": _latency(total_latencies),
        "rows": rows,
    }
    if args.output:
        payload["output_file"] = str(args.output)
    emit(payload, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
