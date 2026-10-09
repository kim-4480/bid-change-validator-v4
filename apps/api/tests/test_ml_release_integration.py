"""Account 4 ML release guards. Only isolated synthetic fixtures used here."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.ml_recommendations import router as ml_router
from app.ml_recommendations.registry import active_model_dir, register_and_promote
from app.ml_recommendations.runtime import score_notices
from app.ml_recommendations.search_compare import bm25_map, rrf_map
from app.analysis_models import QualificationAnalysisRun
from app.database import SessionLocal
from app.models import BidNotice, BidNoticeVersion, NoticeDocument
from app.qualification.analysis import qualification_analysis_version_fingerprint


NOW = datetime(2026, 10, 9, 8, tzinfo=timezone.utc)


def version(*, days=5, posted_days=3, kind="일반공고", explicit=True):
    return SimpleNamespace(
        notice_kind=kind,
        bid_closed_at=NOW + timedelta(days=days) if explicit else None,
        posted_at=NOW - timedelta(days=posted_days),
    )


@pytest.mark.parametrize("notice,active,source", [
    (version(), True, "explicit"),
    (version(days=-1), False, None),
    (version(kind="취소공고"), False, None),
    (version(explicit=False, posted_days=39), True, "assumed_40_days"),
    (version(explicit=False, posted_days=41), False, None),
    (version(explicit=False, posted_days=0), True, "assumed_40_days"),
])
def test_notice_window_policy(notice, active, source):
    result = ml_router.eligible_window(notice, now=NOW)
    assert (result is not None) == active
    if result:
        assert result[0] == source


def _row(state, index):
    return {
        "notice_id": str(uuid4()), "title": f"Software {state} {index}",
        "score": float(100 - index),
        "version_number": 2,
        "analysis_run_id": None, "analysis_version": None,
        "analysis_status": "UNKNOWN", "is_stale": state == "stale",
        "deadline_source": "explicit", "effective_deadline": NOW + timedelta(days=1),
        "_state": state,
    }


def test_strict_eligible_unknown_and_ineligible_separation(monkeypatch):
    rows = [_row(name, i) for i, name in enumerate(
        ["ineligible", "UNKNOWN", "eligible", "stale", "eligible", "insufficient_data"]
    )]
    def judge(db, company, batch):
        return {r["notice_id"]: {"state": r["_state"], "reason": "test"} for r in batch}
    monkeypatch.setattr(ml_router, "evaluate", judge)
    primary, review = ml_router.partition_ranked(None, uuid4(), rows, 10, "local_lightgbm")
    assert [r.qualification_state for r in primary] == ["eligible", "eligible"]
    assert [r.qualification_state for r in review] == [
        "UNKNOWN", "stale", "insufficient_data"
    ]
    assert primary[0].rank == 1 and primary[1].rank == 2
    assert all(r.title != rows[0]["title"] for r in primary + review)


def test_query_only_can_never_be_eligible():
    rows = [_row("eligible", 1), _row("UNKNOWN", 2)]
    primary, review = ml_router.partition_ranked(None, None, rows, 10, "lexical_fallback")
    assert primary == [] and len(review) == 2
    assert all(r.qualification_state == "UNKNOWN" for r in review)


def test_entire_candidate_corpus_not_truncated(monkeypatch):
    monkeypatch.setattr(ml_router, "_current_analysis_runs", lambda db, ids: ({}, set()))
    class FakeDB:
        def __init__(self):
            self.rows = []
            for i in range(217):
                n = SimpleNamespace(
                    id=uuid4(), title=f"IT procurement {i}", notice_kind="일반공고",
                    business_type="GOODS", announcing_institution_name="Agency",
                    demanding_institution_name="Agency", last_seen_at=NOW
                )
                v = SimpleNamespace(
                    id=uuid4(), version_number=1, notice_kind="일반공고",
                    posted_at=NOW, bid_closed_at=NOW+timedelta(days=2),
                    contract_method="open", allocated_budget=1
                )
                self.rows.append((n, v))
        def execute(self, query):
            assert query._limit_clause is None
            return iter(self.rows)
        def scalars(self, query):
            return SimpleNamespace(all=lambda: [])
    rows = ml_router.candidates(FakeDB(), now=NOW)
    assert len(rows) == 217
    assert all("notice_text" in row for row in rows)


def test_ml_candidate_lineage_uses_latest_valid_run_on_postgresql():
    db = SessionLocal()
    notice_id, version_id, document_id = uuid4(), uuid4(), uuid4()
    try:
        notice = BidNotice(
            id=notice_id, bid_notice_no=f"TEST-ML-LINEAGE-{notice_id}",
            title="lineage test", business_type="SERVICE",
            first_seen_at=NOW, last_seen_at=NOW,
        )
        version = BidNoticeVersion(
            id=version_id, notice_id=notice_id, version_number=1,
            bid_notice_order="000", is_current=True, source_endpoint="pytest",
            payload_hash="1" * 64, raw_json={}, collected_at=NOW,
            posted_at=NOW - timedelta(days=1),
            bid_closed_at=NOW + timedelta(days=2),
        )
        document = NoticeDocument(
            id=document_id, notice_version_id=version_id,
            document_order=0, name="notice.pdf", url="https://example.invalid/test.pdf",
            source_field="stdNtceDocUrl", download_status="DOWNLOADED",
            extraction_status="EXTRACTED", extracted_text_sha256="a" * 64,
            extracted_blocks=[{"text": "qualification"}],
        )
        version.documents = [document]
        db.add_all([notice, version])
        db.flush()
        valid_fingerprint = qualification_analysis_version_fingerprint(version)
        older_valid = QualificationAnalysisRun(
            id=uuid4(), notice_version_id=version_id, contract_version="test",
            analysis_kind="QUALIFICATION_REQUIREMENTS", status="SUCCEEDED",
            input_fingerprint=valid_fingerprint, created_at=NOW,
        )
        newer_stale = QualificationAnalysisRun(
            id=uuid4(), notice_version_id=version_id, contract_version="test",
            analysis_kind="QUALIFICATION_REQUIREMENTS", status="SUCCEEDED",
            input_fingerprint="f" * 64, created_at=NOW + timedelta(minutes=1),
        )
        db.add_all([older_valid, newer_stale])
        db.flush()

        selected, history = ml_router._current_analysis_runs(db, [version_id])
        assert selected[version_id].id == older_valid.id
        assert version_id in history
        candidate = next(row for row in ml_router.candidates(db, now=NOW)
                         if row["notice_id"] == str(notice_id))
        assert candidate["analysis_run_id"] == str(older_valid.id)
        assert candidate["is_stale"] is False

        document.extracted_text_sha256 = "b" * 64
        db.flush()
        selected, history = ml_router._current_analysis_runs(db, [version_id])
        assert selected == {} and version_id in history
        candidate = next(row for row in ml_router.candidates(db, now=NOW)
                         if row["notice_id"] == str(notice_id))
        assert candidate["analysis_run_id"] is None
        assert candidate["is_stale"] is True

        newest_valid = QualificationAnalysisRun(
            id=uuid4(), notice_version_id=version_id, contract_version="test",
            analysis_kind="QUALIFICATION_REQUIREMENTS", status="SUCCEEDED",
            input_fingerprint=qualification_analysis_version_fingerprint(version),
            created_at=NOW + timedelta(minutes=2),
        )
        db.add(newest_valid)
        db.flush()
        selected, _ = ml_router._current_analysis_runs(db, [version_id])
        assert selected[version_id].id == newest_valid.id
        candidate = next(row for row in ml_router.candidates(db, now=NOW)
                         if row["notice_id"] == str(notice_id))
        assert candidate["analysis_run_id"] == str(newest_valid.id)
        assert candidate["is_stale"] is False

        newest_valid.status = "FAILED"
        db.flush()
        candidate = next(row for row in ml_router.candidates(db, now=NOW)
                         if row["notice_id"] == str(notice_id))
        assert candidate["analysis_run_id"] == str(newest_valid.id)
        assert candidate["analysis_status"] == "FAILED"

        newest_valid.input_fingerprint = None
        db.flush()
        candidate = next(row for row in ml_router.candidates(db, now=NOW)
                         if row["notice_id"] == str(notice_id))
        assert candidate["analysis_run_id"] is None
        assert candidate["is_stale"] is True
    finally:
        db.rollback()
        db.close()


def test_unapproved_registry_refuses_promotion(tmp_path):
    model = tmp_path / "unverified"
    model.mkdir()
    (model/"lightgbm.txt").write_text("mock")
    (model/"evaluation.json").write_text(json.dumps(
        {"evaluation_scope":"SYNTHETIC ONLY", "model_sha256": {"lightgbm.txt":"x"}}
    ))
    (model/"reviewed_manifest.json").write_text(json.dumps(
        {"valid_company_family_holdout": False}
    ))
    with pytest.raises(ValueError, match="human reviewed"):
        register_and_promote(tmp_path/"registry", model, approved_by="tester")
    with pytest.raises(FileNotFoundError):
        active_model_dir(tmp_path/"registry")


def test_corrupt_champion_pointer_falls_back(tmp_path, monkeypatch):
    registry = tmp_path/"registry"
    registry.mkdir()
    (registry/"champion.json").write_text(json.dumps({
        "relative_dir":"../escape",
        "approved_by":"tester",
        "decision":{"deploy_ml":True}
    }))
    monkeypatch.setenv("BIDCHECK_ML_REGISTRY_DIR", str(registry))
    monkeypatch.delenv("BIDCHECK_ML_INFERENCE_URL", raising=False)
    monkeypatch.delenv("BIDCHECK_ML_HF_DIR", raising=False)
    _, model, _, source, reason = score_notices(
        "IT", [{"notice_id":"1", "title":"IT"}], remote_url=""
    )
    assert source == "lexical_fallback"
    assert reason == "ValueError" and model is None


def test_bm25_and_rrf_on_isolated_rows():
    rows = [
        {"pair_id":"a","notice_id":"1","query_text":"software network",
         "notice_text":"software network maintenance","label":3},
        {"pair_id":"b","notice_id":"2","query_text":"software network",
         "notice_text":"furniture","label":0},
    ]
    scored = bm25_map([rows])
    assert scored["a"] > scored["b"]
    combined = rrf_map([rows], [scored,scored])
    assert combined["a"] > combined["b"]


def test_synthetic_model_is_never_claimed_real(tmp_path, monkeypatch):
    import hashlib
    import numpy as np
    lgb = pytest.importorskip("lightgbm")
    from app.ml_recommendations.trainer import features
    training = [("network service","network service",3),
                ("network service","office furniture",0),
                ("software support","software support",3),
                ("software support","highway works",0)]
    x = np.stack([features(q,t) for q,t,_ in training])
    y = np.asarray([label for _,_,label in training])
    model = lgb.train({"objective":"regression","verbosity":-1,"num_threads":1},
                      lgb.Dataset(x,label=y),num_boost_round=5)
    model.save_model(str(tmp_path/"lightgbm.txt"))
    digest = hashlib.sha256((tmp_path/"lightgbm.txt").read_bytes()).hexdigest()
    (tmp_path/"evaluation.json").write_text(json.dumps({
        "evaluation_scope":"SYNTHETIC ONLY",
        "model_sha256":{"lightgbm.txt":digest},
        "dataset_version":"test-synthetic"
    }))
    monkeypatch.setenv("BIDCHECK_ML_ALLOW_SYNTHETIC", "1")
    monkeypatch.delenv("BIDCHECK_ML_INFERENCE_URL", raising=False)
    monkeypatch.delenv("BIDCHECK_ML_HF_DIR", raising=False)
    notices = [{"notice_id":str(uuid4()),"title":"supplier",
                "notice_text":title} for _,title,_ in training]
    scored, version, dataset, source, failure = score_notices(
        "network service", notices, local_dir=str(tmp_path), remote_url=""
    )
    assert len(scored) == 4
    assert source == "local_lightgbm" and version.startswith("lightgbm-")
    assert dataset == "test-synthetic" and failure is None
    # The optional API route actually invokes the learned LightGBM scorer.
    # This is a synthetic inference smoke test, NEVER a real-ranking claim.
    from app.ml_recommendations.router import recommend_ml, MLRecommendationRequest
    monkeypatch.setenv("BIDCHECK_ML_MODEL_DIR", str(tmp_path))
    monkeypatch.delenv("BIDCHECK_ML_REGISTRY_DIR", raising=False)
    api_rows = [
        dict(row, version_number=1, analysis_run_id=None, analysis_version=None,
             analysis_status="UNKNOWN", is_stale=False, deadline_source="explicit",
             effective_deadline=NOW + timedelta(days=1))
        for row in notices
    ]
    monkeypatch.setattr(ml_router, "candidates", lambda db: api_rows)
    response = recommend_ml(MLRecommendationRequest(query="network service"),
                            db=object(), user=None)
    assert response.scoring_source == "local_lightgbm" and not response.fallback_used
    assert response.model_version.startswith("lightgbm-")
    assert response.items == []  # Synthetic relevance is not an eligible verdict.
    assert len(response.needs_review_items) == 4
    (tmp_path/"lightgbm.txt").write_text("corrupted",encoding="utf-8")
    _, _, _, source, failure = score_notices(
        "network service", notices, local_dir=str(tmp_path), remote_url=""
    )
    assert source == "lexical_fallback" and failure == "ValueError"


def test_remote_scoring_uses_all_rows_in_safe_chunks(monkeypatch):
    import httpx
    from app.ml_recommendations.runtime import score_notices
    calls = []
    monkeypatch.setenv("BIDCHECK_ML_REMOTE_TOKEN", "isolated-test-token")
    monkeypatch.delenv("BIDCHECK_ML_MODEL_DIR", raising=False)
    monkeypatch.delenv("BIDCHECK_ML_REGISTRY_DIR", raising=False)
    class Response:
        def __init__(self, data):
            self._data = data
        def raise_for_status(self):
            pass
        def json(self):
            return {"scores": [float(i) for i in range(len(self._data))],
                    "model_version": "approved-v1",
                    "dataset_version": "reviewed-v1",
                    "evaluation_scope": "HUMAN_REVIEWED_HOLDOUT",
                    "champion_approved": True}
    def mocked_post(url, *, json, headers, timeout, follow_redirects):
        assert url.startswith("https://")
        assert headers["Authorization"] == "Bearer isolated-test-token"
        calls.append(len(json["notices"]))
        return Response(json["notices"])
    monkeypatch.setattr(httpx, "post", mocked_post)
    notices = [{"notice_id": str(i), "title": "network " + str(i)} for i in range(217)]
    ranked, model, dataset, source, reason = score_notices(
        "network", notices, local_dir="", remote_url="https://localhost.example/v1/score"
    )
    assert calls == [100, 100, 17]
    assert len(ranked) == 217 and source == "remote_inference"
    assert model == "approved-v1" and dataset == "reviewed-v1" and reason is None


def test_unapproved_remote_response_is_rejected(monkeypatch):
    import httpx
    from app.ml_recommendations.runtime import score_notices
    monkeypatch.setenv("BIDCHECK_ML_REMOTE_TOKEN", "isolated-test-token")
    monkeypatch.delenv("BIDCHECK_ML_ALLOW_UNREGISTERED", raising=False)
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {"scores": [0.8], "model_version": "unapproved"}
    monkeypatch.setattr(httpx, "post", lambda *a, **k: Response())
    _, model, _, source, why = score_notices(
        "network", [{"notice_id": "1", "title": "network"}],
        local_dir="", remote_url="https://worker.example/v1/score"
    )
    assert source == "lexical_fallback" and model is None and why == "ValueError"


def test_manual_approval_and_deep_worker_registry_contract(tmp_path, monkeypatch):
    """Mock holdout/weights: tests only the approval protocol, not model accuracy."""
    from app.ml_recommendations import remote_worker
    from app.ml_recommendations.registry import register_and_promote, active_model_dir
    from fastapi.testclient import TestClient
    import hashlib

    source = tmp_path/"candidate"
    source.mkdir()
    (source/"cross_encoder.pt").write_bytes(b"mock-only-pytorch-weights")
    digest = hashlib.sha256((source/"cross_encoder.pt").read_bytes()).hexdigest()
    reviewed = hashlib.sha256(b"test-only-reviewed-provenance").hexdigest()
    baseline = {"nDCG@K":0.1,"MRR":0.2,"queries":21,"latency_p95_ms":10.0}
    cross = {"nDCG@K":0.8,"MRR":0.3,"queries":21,"latency_p95_ms":19.0}
    report = {
        "evaluation_scope":"HUMAN_REVIEWED_HOLDOUT",
        "leakage":{"passed":True}, "dataset_version":"unit-fixture",
        "reviewed_labels_sha256":reviewed,
        "metrics":{"baseline_rule":baseline,"cross_encoder":cross},
        "model_sha256":{"cross_encoder.pt":digest}
    }
    (source/"evaluation.json").write_text(json.dumps(report))
    (source/"reviewed_manifest.json").write_text(json.dumps({
        "valid_company_family_holdout":True,
        "label_counts":{"human_reviewed":21},
        "reviewed_labels_sha256":reviewed
    }))
    registry = tmp_path/"registry"
    entry = register_and_promote(registry, source, approved_by="human-test-approver",
                                 model_kind="cross_encoder")
    assert entry["model_kind"] == "cross_encoder"
    assert active_model_dir(registry, expected_kind="cross_encoder").is_dir()
    with pytest.raises(ValueError, match="model type"):
        active_model_dir(registry, expected_kind="lightgbm")
    monkeypatch.setenv("BIDCHECK_DL_REGISTRY_DIR", str(registry))
    monkeypatch.setenv("BIDCHECK_DL_KIND", "cross_encoder")
    monkeypatch.setenv("BIDCHECK_ML_REMOTE_TOKEN", "isolated-worker-test")
    monkeypatch.setattr(remote_worker, "_load_scoring",
        lambda folder, kind, sha, device: (lambda row: 0.25, "mock-deep-version"))
    response = TestClient(remote_worker.app).post(
        "/v1/score",
        headers={"Authorization":"Bearer isolated-worker-test"},
        json={"query":"software procurement", "notices":[{"notice_id":"1",
            "title":"supply","notice_text":"software procurement supply"}]}
    )
    assert response.status_code == 200
    assert response.json()["champion_approved"] is True
    assert response.json()["evaluation_scope"] == "HUMAN_REVIEWED_HOLDOUT"
    assert response.json()["dataset_version"] == "unit-fixture"
    path = active_model_dir(registry, expected_kind="cross_encoder") / "cross_encoder.pt"
    path.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="integrity"):
        active_model_dir(registry, expected_kind="cross_encoder")
    denied = TestClient(remote_worker.app).post(
        "/v1/score", headers={"Authorization":"Bearer isolated-worker-test"},
        json={"query":"software procurement", "notices":[{"notice_id":"1","title":"supply"}]}
    )
    assert denied.status_code == 503
