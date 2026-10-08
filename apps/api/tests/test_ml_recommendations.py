from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import json
import hashlib
import pytest

from app.ml_recommendations.dataset import audit,export
from app.ml_recommendations.runtime import score_notices


def make_notices(n=20):
    return [{"notice_id":str(i),"family_id":str(i),"title":f"school network hardware tender zone {i}",
             "business_type":"GOODS" if i%2 else "SERVICE",
             "posted_at":f"2026-10-{(i%9)+1:02d}"} for i in range(n)]


def test_export_hash_and_leakage(tmp_path):
    manifest=export(make_notices(),[],tmp_path)
    assert manifest["leakage"]["passed"]
    assert manifest["reviewed_labels"]==0
    assert manifest["sha256"]["pairs.jsonl"]==hashlib.sha256((tmp_path/"pairs.jsonl").read_bytes()).hexdigest()
    assert {r["label_source"] for r in map(json.loads,(tmp_path/"pairs.jsonl").read_text().splitlines())}=={"synthetic_title"}


def test_split_violation_rejected():
    rows=[{"split":"train","query_family_id":"1","candidate_family_id":"2"},
          {"split":"test","query_family_id":"3","candidate_family_id":"2"}]
    assert not audit(rows)["passed"]


def test_unreviewed_label_rejected(tmp_path):
    ann=tmp_path/"review.jsonl"
    ann.write_text(json.dumps({"notice_id":"1","label":3,"label_source":"human_reviewed"})+"\n")
    with pytest.raises(ValueError,match="Unverified"):
        export(make_notices(),[],tmp_path/"out",reviewed=ann)


def test_fallback_without_model(monkeypatch):
    monkeypatch.delenv("BIDCHECK_ML_INFERENCE_URL",raising=False)
    monkeypatch.delenv("BIDCHECK_ML_MODEL_DIR",raising=False)
    ranked,model,dataset,source,why=score_notices("network",[
       {"notice_id":"1","title":"network hardware"},
       {"notice_id":"2","title":"office furniture"}])
    assert source=="lexical_fallback" and model is None and dataset is None
    assert ranked[0]["notice_id"]=="1" and why=="model_not_configured"


def test_fallback_corrupt_model(tmp_path,monkeypatch):
    monkeypatch.delenv("BIDCHECK_ML_INFERENCE_URL",raising=False)
    (tmp_path/"lightgbm.txt").write_text("garbage")
    (tmp_path/"evaluation.json").write_text(json.dumps({"model_sha256":{"lightgbm.txt":"deadbeef"}}))
    _,_,_,source,why=score_notices("abc",[{"notice_id":"1","title":"abc"}],local_dir=str(tmp_path))
    assert source=="lexical_fallback" and why=="ValueError"


def test_router_path_exists():
    from fastapi import FastAPI
    from app.ml_recommendations.router import router
    app=FastAPI()
    app.include_router(router)
    assert any(r.path=="/api/v1/recommendations/ml" and "POST" in r.methods for r in router.routes)
