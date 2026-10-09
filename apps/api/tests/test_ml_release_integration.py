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


def test_entire_candidate_corpus_not_truncated():
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
