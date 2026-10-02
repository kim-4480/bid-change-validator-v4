"""Evaluate E3 hybrid + LLM reranking on the frozen Document QA set.

This script deliberately reuses the same 60-question fixture, expected excerpts,
database policy, and strict quote matcher as evaluate_copilot_e3_document_qa.
It measures only whether paid reranking improves Top-K retrieval over the already
measured hybrid baseline. It does not score generated answers or product task
completion and it never changes product data.

Usage:
    python -m apps.api.app.scripts.evaluate_copilot_e3_rerank `
      --output e3-retrieval-hybrid-rerank.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
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
            "evaluation_scope": "E3 hybrid rerank retrieval only",
            **digests,
            "count": 60,
            "model_calls": 0,
            "local_env_files_found": env_files,
        }, args.output)
        return 2

    # Delay runtime imports until local env files have been loaded.
    from openai import OpenAI
    from sqlalchemy import select
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm import Session

    from apps.api.app.config import get_settings
    from bidengine.rag.answer import DEFAULT_CHAT_MODEL
    from bidengine.rag.retrieval import retrieve
    from apps.api.app.document_rag.service import load_or_build_version_index
    from bidengine.rag.store import create_openai_embeddings
    from apps.api.app.models import BidNotice, BidNoticeVersion

    rerank_model = (
        args.model
        or os.getenv("OPENAI_MODEL_RERANK")
        or os.getenv("OPENAI_MODEL_DEFAULT")
        or DEFAULT_CHAT_MODEL
    )
    client = OpenAI(timeout=30.0, max_retries=2)

    configured_url = os.getenv("E3_DATABASE_URL") or get_settings().sqlalchemy_database_url
    try:
        engine, database_connection_mode, initial_connection_error = _prepare_eval_engine(configured_url)
    except OperationalError as error:
        reason = "DB_CONNECTION_LIMIT" if _is_connection_limit(error) else "DB_CONNECTION_FAILED"
        emit({
            "status": "not_run",
            "reason": reason,
            "evaluation_scope": "E3 hybrid rerank retrieval only",
            **digests,
            "count": 60,
            "model_calls": 0,
            "rerank_model": rerank_model,
            "local_env_files_found": env_files,
        }, args.output)
        return 3

    embeddings = create_openai_embeddings()
    rows: list[dict] = []
    latencies: list[float] = []
    total_expected = 0
    total_hits = 0
    any_hit_cases = 0
    all_hit_cases = 0
    evaluated_cases = 0
    model_calls = 0
    scope_gap_ids = {row["scenario_id"] for row in scope_gaps}

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
                        "evaluation_target_note": KNOWN_TARGET_NOTES.get(scenario_id),
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

                notice_version_id = version_ids[0]
                expected_rows = [evidence_by_id[eid] for eid in case["expected_evidence_ids"]]
                expected_version_ids = {row["version_id"] for row in expected_rows}
                source_identity_matches = expected_version_ids == {str(notice_version_id)}

                index = load_or_build_version_index(
                    db,
                    notice_version_id=notice_version_id,
                    index_root=os.getenv("DOCUMENT_RAG_INDEX_ROOT", "data/document-rag"),
                    embeddings=embeddings,
                )

                started = time.perf_counter()
                try:
                    hits = retrieve(
                        index,
                        case["question"],
                        method="hybrid_rerank",
                        k=args.k,
                        fetch_k=args.fetch_k,
                        rerank_client=client,
                        rerank_model=rerank_model,
                    )
                    model_calls += 1
                except Exception as error:
                    emit({
                        "status": "not_run",
                        "reason": "RERANK_FAILED",
                        "message": str(error),
                        "evaluation_scope": "E3 hybrid rerank retrieval only; no partial score claim",
                        "method": "hybrid_rerank",
                        "k": args.k,
                        "fetch_k": args.fetch_k,
                        "rerank_model": rerank_model,
                        "model_calls": model_calls,
                        "completed_cases_before_failure": evaluated_cases,
                        **digests,
                        "count": 60,
                        "scope_gap_cases": len(scope_gaps),
                        "database_connection_mode": database_connection_mode,
                        "local_env_files_found": env_files,
                    }, args.output)
                    return 4

                elapsed_ms = (time.perf_counter() - started) * 1000
                latencies.append(elapsed_ms)

                expected_matches: dict[str, list[int]] = {}
                for expected in expected_rows:
                    ranks = [i for i, hit in enumerate(hits, 1) if quote_match(hit.text, expected["quote"])]
                    expected_matches[expected["evidence_id"]] = ranks

                hit_count = sum(bool(ranks) for ranks in expected_matches.values())
                expected_count = len(expected_rows)
                total_hits += hit_count
                total_expected += expected_count
                any_hit = hit_count > 0
                all_hit = hit_count == expected_count
                any_hit_cases += int(any_hit)
                all_hit_cases += int(all_hit)
                evaluated_cases += 1

                rows.append({
                    "scenario_id": scenario_id,
                    "notice_no": case["notice_no"],
                    "source_order": case["source_order"],
                    "notice_version_id": str(notice_version_id),
                    "question": case["question"],
                    "status": "EVALUATED",
                    "source_identity_matches_frozen_evidence": source_identity_matches,
                    "expected_evidence_ids": case["expected_evidence_ids"],
                    "expected_match_ranks": expected_matches,
                    "expected_hit_count": hit_count,
                    "expected_count": expected_count,
                    "any_hit_at_k": any_hit,
                    "all_hit_at_k": all_hit,
                    "evaluation_target_note": KNOWN_TARGET_NOTES.get(scenario_id),
                    "latency_ms": round(elapsed_ms, 2),
                    "hits": [
                        {
                            "rank": i,
                            "chunk_id": hit.metadata.chunk_id,
                            "document_id": hit.metadata.document_id,
                            "document_name": hit.metadata.document_name,
                            "notice_version_id": hit.metadata.notice_version_id,
                            "clause_label": hit.metadata.clause_label,
                            "page": hit.metadata.page,
                            "source_locations": hit.metadata.source_locations,
                            "score": hit.score,
                            "text": hit.text,
                        }
                        for i, hit in enumerate(hits, 1)
                    ],
                })
    finally:
        engine.dispose()

    payload = {
        "status": "completed",
        "evaluation_scope": "E3 hybrid + paid LLM reranking only; strict draft excerpt retrieval, not answer correctness",
        "method": "hybrid_rerank",
        "k": args.k,
        "fetch_k": args.fetch_k,
        "rerank_model": rerank_model,
        "model_calls": model_calls,
        "database_connection_mode": database_connection_mode,
        "session_pooler_preflight_failed": bool(initial_connection_error),
        **digests,
        "count": 60,
        "evaluated_cases": evaluated_cases,
        "scope_gap_cases": len(scope_gaps),
        "scope_gaps": scope_gaps,
        "source_lookup_failed_cases": sum(row["status"] == "SOURCE_LOOKUP_FAILED" for row in rows),
        "expected_evidence_count": total_expected,
        "expected_evidence_hits": total_hits,
        "evidence_recall_at_k": round(total_hits / total_expected, 4) if total_expected else None,
        "case_any_hit_at_k": round(any_hit_cases / evaluated_cases, 4) if evaluated_cases else None,
        "case_all_hit_at_k": round(all_hit_cases / evaluated_cases, 4) if evaluated_cases else None,
        "known_target_note_cases": sorted(KNOWN_TARGET_NOTES),
        "latency_ms": {
            "p50": round(statistics.median(latencies), 2) if latencies else None,
            "p95": round(percentile(latencies, 0.95), 2) if latencies else None,
            "mean": round(statistics.fmean(latencies), 2) if latencies else None,
        },
        "rows": rows,
    }
    if args.output:
        payload["output_file"] = str(args.output)
    emit(payload, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
