from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from app.ml_recommendations import remote_worker
from app.ml_recommendations.runtime import score_notices
from app.ml_recommendations.router import recommend_ml,MLRecommendationRequest

def test_worker_is_off_by_default(monkeypatch):
    monkeypatch.delenv("BIDCHECK_ML_REMOTE_TOKEN",raising=False)
    r=TestClient(remote_worker.app).post("/v1/score",json={"query":"network","notices":[{"notice_id":"1","title":"network"}]})
    assert r.status_code==503

def test_worker_requires_authentication(monkeypatch):
    monkeypatch.setenv("BIDCHECK_ML_REMOTE_TOKEN","testsecret")
    r=TestClient(remote_worker.app).post("/v1/score",json={"query":"network","notices":[{"notice_id":"1","title":"network"}]})
    assert r.status_code==401

def test_worker_mocked_success(monkeypatch):
    monkeypatch.setenv("BIDCHECK_ML_REMOTE_TOKEN","testsecret")
    monkeypatch.setattr(remote_worker,"model",lambda:(lambda row:0.75,"mock-v1"))
    r=TestClient(remote_worker.app).post("/v1/score",
      headers={"Authorization":"Bearer testsecret"},
      json={"query":"network","notices":[{"notice_id":"1","title":"network"}]})
    assert r.status_code==200 and r.json()["scores"]==[0.75]

def test_remote_without_approved_credentials_never_calls_network(monkeypatch):
    monkeypatch.delenv("BIDCHECK_ML_REMOTE_TOKEN",raising=False)
    def fail(*args,**kwargs):
        raise AssertionError("network call attempted")
    import httpx
    monkeypatch.setattr(httpx,"post",fail)
    out=score_notices("network",[{"notice_id":"1","title":"network"}],
        remote_url="https://remote.example/v1/score",local_dir="")
    assert out[3]=="lexical_fallback"
    assert out[4]=="ValueError"

def test_api_fallback_is_read_only_and_has_unknown_status(monkeypatch):
    from app.ml_recommendations import router as module
    monkeypatch.delenv("BIDCHECK_ML_MODEL_DIR",raising=False)
    monkeypatch.delenv("BIDCHECK_ML_INFERENCE_URL",raising=False)
    import uuid
    uid=str(uuid.uuid4())
    monkeypatch.setattr(module,"candidates",lambda db:[dict(
        notice_id=uid,title="network",version_number=1,analysis_run_id=None,
        analysis_version=None,analysis_status="UNKNOWN",is_stale=False)])
    result=recommend_ml(MLRecommendationRequest(query="network"),db=object(),user=None)
    assert result.scoring_source=="lexical_fallback"
    assert result.items[0].qualification_state=="UNKNOWN"
