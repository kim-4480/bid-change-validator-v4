"""Human annotation validator and fail-closed, leakage-safe holdout exporter."""
import argparse
import csv
import hashlib
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

LABEL_RUBRIC={
    0:"Unrelated to company service/product; demonstrably irrelevant",
    1:"Weak/peripheral topical overlap, poor business relevance",
    2:"Plausible company capability and contract relevance; review conditions separately",
    3:"Strong, explicit company capability/domain relevance; NOT qualification or award probability",
}

def validated_reviews(dataset_dir,completed_csv,output):
    dataset_dir=Path(dataset_dir)
    manifest=json.loads((dataset_dir/"manifest.json").read_text(encoding="utf-8"))
    origin=dataset_dir/"company_notice_pairs.jsonl"
    if hashlib.sha256(origin.read_bytes()).hexdigest()!=manifest["sha256"]["company_notice_pairs.jsonl"]:
        raise ValueError("Dataset hash mismatch")
    candidates={x["pair_id"]:x for line in origin.read_text(encoding="utf-8").splitlines()
                if line.strip() for x in [json.loads(line)]}
    reviewed=[]
    seen=set()
    with Path(completed_csv).open(encoding="utf-8-sig",newline="") as file:
        for line,row in enumerate(csv.DictReader(file),2):
            grade=(row.get("label_0_3") or "").strip()
            if not grade:continue
            pid=row.get("pair_id")
            if pid not in candidates or pid in seen:raise ValueError(f"Unknown/duplicate pair at {line}")
            if grade not in ("0","1","2","3"):raise ValueError(f"Bad grade at {line}")
            reviewer=(row.get("reviewer_id") or "").strip()
            when=(row.get("reviewed_at") or "").strip()
            why=(row.get("rationale") or "").strip()
            if not reviewer or len(why)<10:raise ValueError(f"Reviewer and reason required at {line}")
            try:
                timestamp=datetime.fromisoformat(when.replace("Z","+00:00"))
                if timestamp.tzinfo is None:raise ValueError()
            except (ValueError,TypeError):
                raise ValueError(f"Timezone-aware reviewed_at required at {line}")
            item=candidates[pid].copy()
            for k in ("label","label_source","reviewer_id","reviewed_at","rationale"):
                item.pop(k,None)
            item.update(label=int(grade),label_source="human_reviewed",reviewer_id=reviewer,
                        reviewed_at=timestamp.isoformat(),rationale=why,
                        query_family_id="company:"+item["company_id"],
                        negative_type=("positive" if int(grade)>=2 else
                            "hard_negative" if grade=="0" and item["candidate_hint"]=="lexical_hard_candidate"
                            else "negative" if grade=="0" else "ambiguous"))
            # Qualification is independent of relevance; do NOT infer eligibility.
            item["qualification_status"]="UNKNOWN"
            seen.add(pid);reviewed.append(item)
    if not reviewed:raise ValueError("No human reviewed labels: real performance cannot be computed")
    groups=defaultdict(list)
    for x in reviewed:groups[x["split"]].append(x)
    valid=bool(manifest["valid_company_family_holdout"])
    if valid:
        for split in ("train","validation","test"):
            if not groups[split] or not any(r["label"]>0 for r in groups[split]):
                valid=False
        if valid:
            company_ids={s:{r["company_id"] for r in groups[s]} for s in groups}
            families={s:{r["candidate_family_id"] for r in groups[s]} for s in groups}
            for left,right in (("train","validation"),("train","test"),("validation","test")):
                if company_ids[left]&company_ids[right] or families[left]&families[right]:
                    raise ValueError("Holdout leakage between "+left+" and "+right)
            cutoff={s:sorted(r["posted_at"] or "" for r in groups[s]) for s in groups}
            if cutoff["train"][-1]>cutoff["validation"][0] or cutoff["validation"][-1]>cutoff["test"][0]:
                raise ValueError("Temporal holdout leakage")
    destination=Path(output);destination.parent.mkdir(parents=True,exist_ok=True)
    with destination.open("w",encoding="utf-8") as f:
        for r in reviewed:f.write(json.dumps(r,ensure_ascii=False,sort_keys=True,default=str)+"\n")
    return {"reviewed":len(reviewed),"label_counts":dict((i,sum(x["label"]==i for x in reviewed)) for i in range(4)),
            "sha256":hashlib.sha256(destination.read_bytes()).hexdigest(),"valid_holdout":valid,"evaluation_permitted":valid,
            "limitation":None if valid else "Review labels archived, but holdout cannot be used for model accuracy"}

def main():
    p=argparse.ArgumentParser(description="Human relevance grades 0..3; qualification status is separate")
    p.add_argument("--dataset",required=True);p.add_argument("--reviewed-csv",required=True);p.add_argument("--out",required=True)
    args=p.parse_args()
    print(json.dumps(validated_reviews(args.dataset,args.reviewed_csv,args.out),ensure_ascii=False,indent=2))
if __name__=="__main__":main()
