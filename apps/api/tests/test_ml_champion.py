from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.ml_recommendations.champion import choose_champion

def test_synthetic_champion_cannot_be_promoted():
    manifest={"valid_company_family_holdout":False,"label_counts":{"human_reviewed":0}}
    comparison={"baseline_rule":{"nDCG@K":1,"MRR":1},
                "cross_encoder":{"queries":50,"nDCG@K":1.2,"MRR":1,"latency_p95_ms":10}}
    result=choose_champion(manifest,comparison)
    assert not result["deploy_ml"] and result["champion"]=="lexical_fallback"

def test_real_human_holdout_needed_to_promote():
    manifest={"valid_company_family_holdout":True,"label_counts":{"human_reviewed":100}}
    scores={"baseline_rule":{"nDCG@K":.6,"MRR":.62},
            "lightgbm":{"queries":30,"nDCG@K":.69,"MRR":.63,"latency_p95_ms":10}}
    assert choose_champion(manifest,scores)["champion"]=="lightgbm"

def test_high_latency_rejects_improvement():
    manifest={"valid_company_family_holdout":True,"label_counts":{"human_reviewed":100}}
    scores={"baseline_rule":{"nDCG@K":.6,"MRR":.62},
            "cross_encoder":{"queries":30,"nDCG@K":.85,"MRR":.8,"latency_p95_ms":2000}}
    assert choose_champion(manifest,scores)["champion"]=="lexical_fallback"
