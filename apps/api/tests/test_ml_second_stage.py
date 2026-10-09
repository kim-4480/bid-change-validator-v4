"""Second-stage offline contract tests. No AWS network calls."""
from pathlib import Path
import csv
import hashlib
import json
import sys
from types import SimpleNamespace
from uuid import uuid4

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pytest
from app.ml_recommendations.real_dataset import create_review_dataset,family_map
from app.ml_recommendations.review import validated_reviews
from app.ml_recommendations.runtime import score_notices
from app.ml_recommendations import qualification_adapter as qa

def input_data(count=8):
    notices=[{"notice_id":str(uuid4()),"notice_version_id":str(uuid4()),
        "version_number":1,"title":f"Software infrastructure supply {i}",
        "business_type":"GOODS","posted_at":f"2026-10-{i+1:02}",
        "institution":"agency","contract_method":"open",
        "budget":None,"requirements":[]} for i in range(count)]
    for n in notices:n["family_id"]=n["notice_id"]
    c={"company_id":str(uuid4()),"name":"Company A","region_code":"11","region_name":"Seoul",
       "company_size":"SME","industries":[{"industry_name":"Software","industry_code":"123"}],
       "certifications":[{"name":"License test"}],"performances":[{"name":"software supply"}],
       "staff_roles":[{"role_name":"engineer"}],"staff_count":3}
    return notices,[c]

def test_confirmed_related_notices_share_family():
    notices,_=input_data()
    mapping=family_map(notices,[(notices[1]["notice_id"],notices[0]["notice_id"])])
    assert mapping[notices[1]["notice_id"]]==mapping[notices[0]["notice_id"]]
    assert mapping[notices[2]["notice_id"]]!=mapping[notices[0]["notice_id"]]

def test_local_human_review_preparation_has_no_oracle_labels(tmp_path):
    notices,companies=input_data()
    result=create_review_dataset(notices,companies,tmp_path)
    assert result["pair_count"]==len(notices)
    assert result["valid_company_family_holdout"] is False
    assert result["label_counts"]=={"unreviewed":8,"human_reviewed":0}
    rows=[json.loads(line) for line in (tmp_path/"company_notice_pairs.jsonl").read_text(encoding="utf-8").splitlines()]
    assert all(x["label"] is None and x["qualification_status"]=="UNKNOWN" for x in rows)
    assert {x["split"] for x in rows}=={"review_only"}
    for filename,sha in result["sha256"].items():
        assert sha==hashlib.sha256((tmp_path/filename).read_bytes()).hexdigest()

def _save_review(csv_path,fix=None):
    with csv_path.open(encoding="utf-8-sig",newline="") as f:
        reader=csv.DictReader(f);rows=list(reader);columns=reader.fieldnames
    rows[0].update(label_0_3="3",reviewer_id="reviewer-testing",
        reviewed_at="2026-10-09T08:00:00+09:00",rationale="Relevant software integration evidence")
    if fix:fix(rows[0])
    with csv_path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=columns);w.writeheader();w.writerows(rows)

def test_reviewed_can_be_archived_but_no_false_holdout(tmp_path):
    notices,companies=input_data()
    create_review_dataset(notices,companies,tmp_path)
    _save_review(tmp_path/"review_template.csv")
    result=validated_reviews(tmp_path,tmp_path/"review_template.csv",tmp_path/"reviewed.jsonl")
    assert result["reviewed"]==1
    assert result["valid_holdout"] is False and result["evaluation_permitted"] is False
    row=json.loads((tmp_path/"reviewed.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert row["label_source"]=="human_reviewed" and row["qualification_status"]=="UNKNOWN"
    assert row["negative_type"]=="positive"

def test_review_rejects_missing_reviewer(tmp_path):
    notices,companies=input_data()
    create_review_dataset(notices,companies,tmp_path)
    _save_review(tmp_path/"review_template.csv",lambda r:r.update(reviewer_id=""))
    with pytest.raises(ValueError,match="Reviewer"):
        validated_reviews(tmp_path,tmp_path/"review_template.csv",tmp_path/"reviews.jsonl")

def test_review_rejects_tampered_pair_source(tmp_path):
    notices,companies=input_data()
    create_review_dataset(notices,companies,tmp_path)
    _save_review(tmp_path/"review_template.csv")
    with (tmp_path/"company_notice_pairs.jsonl").open("a",encoding="utf-8") as f:f.write("{}\n")
    with pytest.raises(ValueError,match="hash"):
        validated_reviews(tmp_path,tmp_path/"review_template.csv",tmp_path/"reviews.jsonl")

def test_qualification_fails_closed_when_no_analysis(monkeypatch):
    company_id=uuid4()
    monkeypatch.setattr(qa,"_load_company",lambda db,c:SimpleNamespace())
    monkeypatch.setattr(qa,"_record_to_completeness",lambda x:None)
    monkeypatch.setattr(qa,"build_company_profile_snapshot",lambda company,completeness:object())
    class FakeDB:
        def get(self,*args):return None
    records=[{"notice_id":"n1","analysis_run_id":None,"is_stale":False},
             {"notice_id":"n2","analysis_run_id":None,"is_stale":True}]
    result=qa.evaluate(FakeDB(),company_id,records)
    assert result["n1"]["state"]=="UNKNOWN"
    assert result["n2"]["state"]=="stale"

def test_qualification_uses_deterministic_engine_for_complete_analysis(monkeypatch):
    company_id=uuid4()
    runid=uuid4()
    monkeypatch.setattr(qa,"_load_company",lambda db,c:object())
    monkeypatch.setattr(qa,"_record_to_completeness",lambda x:object())
    monkeypatch.setattr(qa,"build_company_profile_snapshot",lambda company,completeness:object())
    run=SimpleNamespace(id=runid,status="SUCCEEDED")
    monkeypatch.setattr(qa,"analysis_run_response",lambda value:SimpleNamespace(
        verdict_complete=True,requirements=["simulated"]))
    called=[]
    def judge(req,profile,**kwargs):
        called.append(kwargs)
        return SimpleNamespace(overall_status="eligible",rule_version="rule-v")
    monkeypatch.setattr(qa,"judge_requirements",judge)
    class FakeDB:
        def get(self,*args):return None
        def scalars(self,*args):return SimpleNamespace(all=lambda:[run])
    result=qa.evaluate(FakeDB(),company_id,[{"notice_id":"n1","analysis_run_id":str(runid),"is_stale":False}])
    assert result["n1"]["state"]=="eligible" and called
    assert called[0]["coverage_complete"] is True

def test_synthetic_weights_are_not_enabled_by_default(monkeypatch,tmp_path):
    monkeypatch.delenv("BIDCHECK_ML_ALLOW_SYNTHETIC",raising=False)
    monkeypatch.delenv("BIDCHECK_ML_INFERENCE_URL",raising=False)
    monkeypatch.delenv("BIDCHECK_ML_HF_DIR",raising=False)
    (tmp_path/"evaluation.json").write_text(json.dumps({
        "evaluation_scope":"SYNTHETIC ONLY","model_sha256":{"lightgbm.txt":"unknown"}}))
    scored,version,ds,source,reason=score_notices("network",[{"notice_id":"1","title":"network"}],
                                                    local_dir=str(tmp_path),remote_url="")
    assert source=="lexical_fallback"
    assert reason=="ValueError"
    assert version is None

def test_hf_checksum_rejection(tmp_path):
    pytest.importorskip("transformers")
    from app.ml_recommendations.hf_inference import load_finetuned
    (tmp_path/"hf_finetune_evaluation.json").write_text(json.dumps({
        "models":{"cross_encoder":{"sha256":"incorrect"}}}))
    (tmp_path/"hf_cross_encoder.pt").write_bytes(b"junk")
    with pytest.raises(ValueError,match="SHA256"):
        load_finetuned(str(tmp_path),str(tmp_path),"cross_encoder")
