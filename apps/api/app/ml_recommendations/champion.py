"""Gate production champion against HUMAN reviewed leakage-safe metrics only."""
from __future__ import annotations

def choose_champion(manifest,metrics,minimum_test_queries=20,max_p95_ms=200.0):
    if not manifest.get("valid_company_family_holdout"):
        return {"champion":"lexical_fallback","deploy_ml":False,
                "reason":"No independent company/notice-family holdout"}
    if manifest.get("label_counts",{}).get("human_reviewed",0)<minimum_test_queries:
        return {"champion":"lexical_fallback","deploy_ml":False,
                "reason":"Insufficient human reviewed relevance labels"}
    baseline=metrics.get("baseline_rule")
    if not baseline or baseline.get("nDCG@K") is None:
        return {"champion":"lexical_fallback","deploy_ml":False,
                "reason":"No human-reviewed baseline"}
    candidates=[]
    for name,score in metrics.items():
        if name=="baseline_rule":continue
        if (score.get("queries",0)>=minimum_test_queries
            and score.get("nDCG@K",0)>baseline["nDCG@K"]+0.01
            and score.get("MRR",0)>=baseline.get("MRR",0)
            and score.get("latency_p95_ms",float("inf"))<=max_p95_ms):
            candidates.append((score["nDCG@K"],score.get("MRR",0),name))
    if not candidates:
        return {"champion":"lexical_fallback","deploy_ml":False,
                "reason":"No validated model beats baseline within latency envelope"}
    winner=max(candidates)[2]
    return {"champion":winner,"deploy_ml":True,
            "reason":"Human-reviewed nDCG improvement with MRR and latency gate"}
