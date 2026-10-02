"""Evaluate E3 Document QA retrieval against the frozen 60-question draft set.

This evaluator measures retrieval separately from answer generation. It does not
change product data or judgments. By default it runs hybrid retrieval only and
matches frozen expected excerpts against returned chunk text after Unicode and
whitespace normalization.

The source workbook was originally authored against the first 78 evidence rows,
while golden_fixtures_v02 later added supplemental excerpts. Known target-version
caveats are reported instead of silently tuning the score around them.

Database policy
---------------
The evaluator owns one short-lived SQLAlchemy connection pool with NullPool so it
never reserves application-style idle connections. If the configured Supabase
session pooler (:5432) rejects the preflight with EMAXCONNSESSION, the evaluator
retries once against the same Supabase transaction pooler (:6543). The project
.env is never modified. The selected connection mode is written to the result.

Usage:
    python -m apps.api.app.scripts.evaluate_copilot_e3_document_qa --validate-only
    python -m apps.api.app.scripts.evaluate_copilot_e3_document_qa --output e3-retrieval.json
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


def repository_root() -> Path:
    return Path(__file__).resolve().parents[4]


def load_local_env(root: Path) -> list[str]:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return []
    loaded = []
    for path in (root / ".env", root / "apps/api/.env", root / ".env.local", root / "apps/api/.env.local"):
        if path.is_file():
            load_dotenv(path, override=False)
            loaded.append(str(path.relative_to(root)))
    return loaded


def load_fixtures(root: Path):
    cases_path = root / "apps/api/eval/copilot_e3_document_qa.json"
    evidence_path = root / "apps/api/eval/copilot_e3_expected_evidence.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    if cases.get("count") != 60 or len(cases.get("cases", [])) != 60:
        raise RuntimeError("E3 Document QA fixture must contain exactly 60 cases")
    if not evidence.get("evidence"):
        raise RuntimeError("E3 expected evidence fixture is empty")
    return cases_path, evidence_path, cases, {row["evidence_id"]: row for row in evidence["evidence"]}


def percentile(values: list[float], q: float):
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * q)))
    return ordered[index]


def emit(payload: dict, output: Path | None):
    if output is None:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    keys = [
        "status", "reason", "evaluation_scope", "method", "k", "count", "evaluated_cases", "scope_gap_cases",
        "database_connection_mode", "evidence_recall_at_k", "case_any_hit_at_k", "case_all_hit_at_k",
        "latency_ms", "output_file",
    ]
    summary = {key: payload.get(key) for key in keys if key in payload}
    summary["rows_written"] = len(payload.get("rows", []))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def quote_match(hit_text: str, expected_quote: str) -> bool:
    from bidengine.rag.retrieval import normalized_text

    hit = normalized_text(hit_text)
    expected = normalized_text(expected_quote)
    if not hit or not expected:
        return False
    if expected in hit:
        return True
    # Long excerpts may span a chunk boundary. Only allow reverse containment when
    # the returned chunk itself is substantive; this is not fuzzy semantic matching.
    return len(hit) >= 40 and hit in expected


KNOWN_TARGET_NOTES = {
    "D03-1": "Workbook target E010 predates supplemental detail excerpts E079-E081 containing the three industry names.",
    "D03-2": "Workbook target E011 predates supplemental OR-group excerpts E082-E086 that make alternative competencies explicit.",
    "D15-1": "Workbook target E060 predates supplemental code excerpts E087-E088 needed for 5898 AND (5815 OR 7607).",
    "D15-3": "Workbook target E060 predates supplemental code excerpts E087-E088 needed for 5898 AND (5815 OR 7607).",
}


def _is_connection_limit(error: Exception) -> bool:
    text = str(error).upper()
    return "EMAXCONNSESSION" in text or ("MAX CLIENTS" in text and "POOL_SIZE" in text)


def _supabase_transaction_pooler_url(database_url: str) -> str | None:
    """Return the same Supabase pooler URL on transaction-mode port 6543.

    No host/user/password/database component is changed. Non-Supabase URLs are
    left alone and therefore never receive an implicit connection-target change.
    """
    from sqlalchemy.engine import make_url

    url = make_url(database_url)
    host = (url.host or "").lower()
    if not host.endswith(".pooler.supabase.com") or url.port != 5432:
        return None
    return url.set(port=6543).render_as_string(hide_password=False)


def _create_eval_engine(database_url: str, *, transaction_pooler: bool = False):
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    connect_args = {"connect_timeout": 10}
    if transaction_pooler:
        # Supabase transaction pooling must not depend on connection-local prepared
        # statement state across transactions.
        connect_args["prepare_threshold"] = None
    return create_engine(
        database_url,
        poolclass=NullPool,
        pool_pre_ping=True,
        connect_args=connect_args,
    )


def _prepare_eval_engine(database_url: str):
    """Preflight one evaluator connection and return (engine, mode, fallback_error)."""
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError

    engine = _create_eval_engine(database_url)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return engine, "CONFIGURED", None
    except OperationalError as error:
        engine.dispose()
        fallback_url = _supabase_transaction_pooler_url(database_url)
        if not (_is_connection_limit(error) and fallback_url):
            raise

        fallback = _create_eval_engine(fallback_url, transaction_pooler=True)
        try:
            with fallback.connect() as connection:
                connection.execute(text("SELECT 1"))
            return fallback, "SUPABASE_TRANSACTION_POOLER_FALLBACK", str(error)
        except Exception:
            fallback.dispose()
            raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--method", choices=["dense_post", "hybrid"], default="hybrid")
    parser.add_argument("--k", type=int, default=4)
    parser.add_argument("--fetch-k", type=int, default=12)
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

    scope_gaps = []
    missing_evidence = []
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

    if args.validate_only:
        emit({
            "status": "dataset_valid",
            "evaluation_scope": "E3 frozen Document QA retrieval fixture validation only",
            **digests,
            "count": 60,
            "scope_gap_cases": len(scope_gaps),
            "scope_gaps": scope_gaps,
            "known_target_note_cases": sorted(KNOWN_TARGET_NOTES),
            "model_calls": 0,
            "local_env_files_found": env_files,
        }, args.output)
        return 0

    if not os.getenv("OPENAI_API_KEY"):
        emit({
            "status": "not_run",
            "reason": "OPENAI_API_KEY is not configured after loading local env files",
            **digests,
            "count": 60,
            "model_calls": 0,
            "local_env_files_found": env_files,
        }, args.output)
        return 2

    # Delay DB/config imports until local .env files have been loaded.
    from sqlalchemy import select
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm import Session
    from apps.api.app.config import get_settings
    from bidengine.rag.retrieval import retrieve
    from apps.api.app.document_rag.service import load_or_build_version_index
    from bidengine.rag.store import create_openai_embeddings
    from apps.api.app.models import BidNotice, BidNoticeVersion

    configured_url = os.getenv("E3_DATABASE_URL") or get_settings().sqlalchemy_database_url
    try:
        engine, database_connection_mode, initial_connection_error = _prepare_eval_engine(configured_url)
    except OperationalError as error:
        reason = "DB_CONNECTION_LIMIT" if _is_connection_limit(error) else "DB_CONNECTION_FAILED"
        emit({
            "status": "not_run",
            "reason": reason,
            "message": (
                "Supabase database connection capacity is exhausted. The evaluator made no retrieval score claim. "
                "Stop unused local API/poller/database clients or use a transaction-pooler URL via E3_DATABASE_URL."
                if reason == "DB_CONNECTION_LIMIT" else
                "The evaluator could not connect to the configured database. No retrieval score was produced."
            ),
            **digests,
            "count": 60,
            "model_calls": 0,
            "local_env_files_found": env_files,
        }, args.output)
        return 3

    embeddings = create_openai_embeddings()
    rows = []
    latencies = []
    total_expected = 0
    total_hits = 0
    any_hit_cases = 0
    all_hit_cases = 0
    evaluated_cases = 0
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

                started = time.perf_counter()
                index = load_or_build_version_index(
                    db,
                    notice_version_id=notice_version_id,
                    index_root=os.getenv("DOCUMENT_RAG_INDEX_ROOT", "data/document-rag"),
                    embeddings=embeddings,
                )
                hits = retrieve(index, case["question"], method=args.method, k=args.k, fetch_k=args.fetch_k)
                elapsed_ms = (time.perf_counter() - started) * 1000
                latencies.append(elapsed_ms)

                expected_matches = {}
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
        "evaluation_scope": "E3 retrieval only; draft expected excerpts, not answer correctness or user task completion",
        "method": args.method,
        "k": args.k,
        "fetch_k": args.fetch_k,
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
