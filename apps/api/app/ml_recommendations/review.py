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

def validated_reviews(dataset_dir,completed_csv,output,approved_export=None):
    dataset_dir=Path(dataset_dir)
    manifest=json.loads((dataset_dir/"manifest.json").read_text(encoding="utf-8"))
    origin=dataset_dir/"company_notice_pairs.jsonl"
    if hashlib.sha256(origin.read_bytes()).hexdigest()!=manifest["sha256"]["company_notice_pairs.jsonl"]:
        raise ValueError("Dataset hash mismatch")
    candidates={x["pair_id"]:x for line in origin.read_text(encoding="utf-8").splitlines()
                if line.strip() for x in [json.loads(line)]}
    approvals={}
    approval_sha=None
    if approved_export is not None:
        export_path=Path(approved_export)
        export=json.loads(export_path.read_text(encoding="utf-8"))
        if export.get("label_source")!="human_reviewed_approved":
            raise ValueError("Approved label export has an invalid provenance")
        if export.get("approved_count")!=len(export.get("items",[])):
            raise ValueError("Approved label export count mismatch")
        approval_sha=hashlib.sha256(export_path.read_bytes()).hexdigest()
        for item in export.get("items",[]):
            key=(item.get("company_id"),item.get("notice_version_id"))
            if key in approvals:raise ValueError("Duplicate approved label pair")
            if not item.get("approved_by_id") or item.get("approved_by_id")==item.get("reviewer_id"):
                raise ValueError("Independent approval is required")
            if item.get("subject_origin") != "REAL":
                raise ValueError("Only independently approved real-company labels may train")
            try:
                approved_at=datetime.fromisoformat(str(item.get("approved_at")).replace("Z","+00:00"))
                if approved_at.tzinfo is None:raise ValueError()
            except (ValueError,TypeError):
                raise ValueError("Approved timestamp requires a timezone")
            if any(len(str(item.get(field) or ""))!=64 for field in ("company_fingerprint","notice_fingerprint")):
                raise ValueError("Approved label is missing input fingerprints")
            approvals[key]=item
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
            approved=approvals.get((item["company_id"],item["notice_version_id"]))
            if approved and (not item.get("company_fingerprint") or not item.get("notice_fingerprint") or
                             approved.get("company_fingerprint") != item["company_fingerprint"] or
                             approved.get("notice_fingerprint") != item["notice_fingerprint"]):
                raise ValueError(f"Approved label input fingerprint differs from frozen dataset at {line}")
            if approved and (approved.get("label")!=item["label"] or
                             approved.get("reviewer_id")!=reviewer or approved.get("rationale")!=why):
                raise ValueError(f"Approved label and review CSV disagree at {line}")
            item["approval_status"]="APPROVED" if approved else "DRAFT"
            item["approved_by_id"]=approved.get("approved_by_id") if approved else None
            item["approved_at"]=approved.get("approved_at") if approved else None
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
    report = {"reviewed":len(reviewed),
              "label_counts":dict((i,sum(x["label"]==i for x in reviewed)) for i in range(4)),
              "sha256":hashlib.sha256(destination.read_bytes()).hexdigest(),
              "source_dataset_sha256":manifest["sha256"]["company_notice_pairs.jsonl"],
              "approved_export_sha256":approval_sha,
              "approved_count":sum(x["approval_status"]=="APPROVED" for x in reviewed),
              "valid_holdout":valid,"evaluation_permitted":valid and all(x["approval_status"]=="APPROVED" for x in reviewed),
              "limitation":None if valid and all(x["approval_status"]=="APPROVED" for x in reviewed)
              else "Review labels archived; independent approval and leak-free holdout are required for model accuracy"}
    destination.with_name(destination.name + ".validation.json").write_text(
        json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2),encoding="utf-8")
    return report

def main():
    p=argparse.ArgumentParser(description="Human relevance grades 0..3; qualification status is separate")
    p.add_argument("--dataset",required=True);p.add_argument("--reviewed-csv",required=True);p.add_argument("--out",required=True)
    p.add_argument("--approved-export",help="System-admin approved label export JSON; otherwise evaluation remains blocked")
    args=p.parse_args()
    print(json.dumps(validated_reviews(args.dataset,args.reviewed_csv,args.out,args.approved_export),ensure_ascii=False,indent=2))
if __name__=="__main__":main()
