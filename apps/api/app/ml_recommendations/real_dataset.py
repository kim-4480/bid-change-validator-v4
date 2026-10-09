"""Local-only, read-only company x current-notice human-review dataset preparation.

Eligibility and relevance are separate. Unreviewed hints are never labels.
No S3, AWS, external API or DB write is performed.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from .cost_guard import require_isolated_data_url

def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def _tokens(value):
    return set(re.findall(r"[\uac00-\ud7a3A-Za-z0-9]+", str(value).lower()))

def family_map(notices, edges):
    parents = {n["notice_id"]: n["notice_id"] for n in notices}
    def root(x):
        while parents[x] != x:
            x=parents[x]
        return x
    for child,prev in edges:
        if child in parents and prev in parents:
            a,b=root(child),root(prev)
            parents[max(a,b)] = min(a,b)
    return {key:root(key) for key in parents}

def local_snapshot(db_url, max_notices=500, max_companies=30):
    require_isolated_data_url(db_url)
    if not (1<=max_notices<=2000 and 1<=max_companies<=100):
        raise ValueError("Bounded local snapshot limits exceeded")
    import psycopg
    from psycopg.rows import dict_row
    companies=[]
    with psycopg.connect(db_url,connect_timeout=5,options="-c default_transaction_read_only=on",row_factory=dict_row) as db:
        with db.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute("""SELECT n.id::text AS notice_id, n.bid_notice_no, n.title,
                n.business_type, n.announcing_institution_name AS institution,
                v.id::text AS notice_version_id,v.version_number,
                COALESCE(v.posted_at,v.created_at)::text AS posted_at,
                v.contract_method,v.allocated_budget::text AS budget,
                v.raw_json ->> 'rgstDt' AS registration_date
                FROM bid_notices n JOIN bid_notice_versions v
                    ON v.notice_id=n.id AND v.is_current=TRUE
                ORDER BY COALESCE(v.posted_at,v.created_at) DESC,n.id LIMIT %s""",(max_notices,))
            notices=list(cur.fetchall())
            cur.execute("""SELECT notice_id::text,previous_notice_id::text FROM notice_relations
                WHERE match_confidence='CONFIRMED' AND previous_notice_id IS NOT NULL LIMIT 3000""")
            edges=[tuple(x.values()) for x in cur.fetchall()]
            cur.execute("""SELECT id::text AS company_id,name,region_code,region_name,company_size
                FROM companies ORDER BY id LIMIT %s""",(max_companies,))
            companies=list(cur.fetchall())
            ids=[c["company_id"] for c in companies]
            lookup={c["company_id"]:c for c in companies}
            for c in companies:
                c.update(industries=[],certifications=[],performances=[],staff_roles=[],
                         staff_count=None)
            if ids:
                cur.execute("""SELECT ci.company_id::text AS company_id,ci.industry_code,
                      COALESCE(i.name,'') AS industry_name,ci.verified
                      FROM company_industries ci LEFT JOIN industry_codes i ON i.code=ci.industry_code
                      WHERE ci.company_id=ANY(%s::uuid[]) LIMIT 3000""",(ids,))
                for r in cur.fetchall():lookup[r["company_id"]]["industries"].append(dict(r))
                cur.execute("""SELECT company_id::text AS company_id,name,certification_code,
                    verified,expires_at::text AS expires_at FROM company_certifications
                    WHERE company_id=ANY(%s::uuid[]) LIMIT 3000""",(ids,))
                for r in cur.fetchall():lookup[r["company_id"]]["certifications"].append(dict(r))
                cur.execute("""SELECT company_id::text AS company_id,name,description,
                   amount::text AS amount,completed_at::text AS completed_at,
                   NULL::integer AS completed_year,verified FROM company_performances
                   WHERE company_id=ANY(%s::uuid[]) LIMIT 3000""",(ids,))
                for r in cur.fetchall():lookup[r["company_id"]]["performances"].append(dict(r))
                cur.execute("""SELECT company_id::text AS company_id,role_name,headcount,
                   NULL::text AS career_years,verified FROM company_staff_roles
                   WHERE company_id=ANY(%s::uuid[]) LIMIT 3000""",(ids,))
                for r in cur.fetchall():lookup[r["company_id"]]["staff_roles"].append(dict(r))
                cur.execute("""SELECT company_id::text AS company_id,total_count,verified
                   FROM company_staff WHERE company_id=ANY(%s::uuid[]) LIMIT 3000""",(ids,))
                for r in cur.fetchall():lookup[r["company_id"]]["staff_count"]=r["total_count"]
            version_ids=[n["notice_version_id"] for n in notices]
            reqs={}
            if version_ids:
                cur.execute("""SELECT r.id::text AS version_id,
                   a.id::text AS analysis_run_id,a.status,NULL::jsonb AS coverage,
                   q.type,q.raw,q.requirement_role,q.condition_complexity
                   FROM qualification_analysis_runs a
                   JOIN qualification_requirements q ON q.analysis_run_id=a.id
                   JOIN bid_notice_versions r ON r.id=a.notice_version_id
                   WHERE a.notice_version_id=ANY(%s::uuid[]) LIMIT 8000""",(version_ids,))
                for r in cur.fetchall():
                    reqs.setdefault(r["version_id"],[]).append(dict(r))
    fam=family_map(notices,edges)
    for n in notices:
        n["family_id"]=fam[n["notice_id"]]
        n["requirements"]=reqs.get(n["notice_version_id"],[])
    return notices,companies

def _profile(company):
    terms=[company["name"],company.get("region_name"),company.get("company_size")]
    terms.extend(x.get("industry_name") or x.get("industry_code") for x in company["industries"])
    terms.extend(x.get("name") for x in company["certifications"])
    terms.extend(x.get("name") for x in company["performances"])
    terms.extend(x.get("role_name") for x in company["staff_roles"])
    return " ".join(str(t) for t in terms if t)

def create_review_dataset(notices,companies,out,seed=42,max_pairs=2000):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    if not 1<=max_pairs<=10000:raise ValueError("Invalid max_pairs")
    company_ids={c["company_id"] for c in companies}
    family_ids={n["family_id"] for n in notices}
    # Independent company and notice family splits cannot work for one company.
    # Never mark one-company holdout as real measured generalization.
    feasible=len(company_ids)>=3 and len(family_ids)>=6
    # Chronological family partition plus disjoint company allocation:
    families={}
    for n in notices:
        families.setdefault(n["family_id"],[]).append(n["posted_at"] or "")
    ordered=sorted(families,key=lambda k:(min(families[k]),k))
    a,b=int(len(ordered)*.7),int(len(ordered)*.85)
    fsplit={k:("train" if i<a else "validation" if i<b else "test") for i,k in enumerate(ordered)}
    # With a small number of companies this can become sparse; holdout remains
    # disabled unless all three splits contain actually reviewed positive pairs.
    cids=sorted(company_ids)
    ca=max(1,int(len(cids)*.7))
    cb=min(len(cids)-1,max(ca+1,int(len(cids)*.85)))
    csplit={k:("train" if i<ca else "validation" if i<cb else "test") for i,k in enumerate(cids)}
    rows=[]
    for company in companies:
        profile=_profile(company)
        matching=[]
        for notice in notices:
            hint=len(_tokens(profile)&_tokens(notice["title"]))
            matching.append((hint,notice))
        # Include lexical hard candidates + low-overlap negatives but DO NOT
        # assert that either group is actually positive/negative without review.
        matching.sort(key=lambda item:(-item[0],item[1]["notice_id"]))
        for hint,notice in matching:
            if len(rows)>=max_pairs:break
            split=(fsplit[notice["family_id"]]
                   if feasible and fsplit[notice["family_id"]]==csplit[company["company_id"]]
                   else "review_only")
            row={"pair_id":hashlib.sha256((company["company_id"]+"|"+notice["notice_version_id"]).encode()).hexdigest()[:20],
                 "company_id":company["company_id"],"query_id":"company:"+company["company_id"],
                 "query_text":profile,"profile":company,
                 "notice_id":notice["notice_id"],"candidate_family_id":notice["family_id"],
                 "notice_version_id":notice["notice_version_id"],
                 "version_number":notice["version_number"],"notice_text":notice["title"],
                 "business_type":notice["business_type"],"posted_at":notice["posted_at"],
                 "institution":notice["institution"],"contract_method":notice["contract_method"],
                 "budget":notice["budget"],"requirements":notice["requirements"],
                 "qualification_status":"UNKNOWN", "label":None,"label_source":"unreviewed",
                 "candidate_hint":"lexical_hard_candidate" if hint>0 else "low_overlap_candidate",
                 "split":split}
            rows.append(row)
        if len(rows)>=max_pairs:break
    path=out/"company_notice_pairs.jsonl"
    with path.open("w",encoding="utf-8") as f:
        for row in rows:f.write(json.dumps(row,ensure_ascii=False,sort_keys=True,default=str)+"\n")
    csv_path=out/"review_template.csv"
    with csv_path.open("w",newline="",encoding="utf-8-sig") as f:
        fields=["pair_id","company_id","notice_id","notice_version_id","split",
                "company_name","company_profile","notice_title","requirements",
                "candidate_hint","label_0_3","reviewer_id","reviewed_at","rationale",
                "qualification_status_reviewed_separately"]
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
        for row in rows:
            writer.writerow({"pair_id":row["pair_id"],"company_id":row["company_id"],
                "notice_id":row["notice_id"],"notice_version_id":row["notice_version_id"],
                "split":row["split"],"company_name":row["profile"]["name"],
                "company_profile":row["query_text"],"notice_title":row["notice_text"],
                "requirements":" | ".join(str(req.get("raw",""))[:200] for req in row["requirements"][:10]),
                "candidate_hint":row["candidate_hint"],"qualification_status_reviewed_separately":""})
    test=out/"frozen_test_manifest.json"
    test_ids=sorted(r["pair_id"] for r in rows if r["split"]=="test")
    test.write_text(json.dumps({"sealed":True,"can_evaluate":False,
        "pair_ids":test_ids,"policy":"Release test only when human labels and disjoint company/family splits exist"},
        ensure_ascii=False,indent=2),encoding="utf-8")
    rubric={"0":"Unrelated","1":"Weak peripheral relevance",
            "2":"Plausible business relevance","3":"Strong business relevance",
            "note":"Relevance is not eligibility or probability of winning. Do not auto-label from rule engine.",
            "required":["reviewer_id","reviewed_at with timezone","rationale >= 10 characters"]}
    (out/"label_rubric.json").write_text(json.dumps(rubric,ensure_ascii=False,indent=2),encoding="utf-8")
    manifest={"schema":"bidcheck-company-notice-review-v2","seed":seed,
        "dataset_version":datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "notice_count":len(notices),"company_count":len(companies),"pair_count":len(rows),
        "label_counts":{"unreviewed":len(rows),"human_reviewed":0},
        "source":"isolated_local_postgresql_read_only","analysis_run_count":len({r["analysis_run_id"] for n in notices for r in n["requirements"]}),
        "families":len(family_ids),
        "valid_company_family_holdout":feasible and all(any(row["split"]==s for row in rows) for s in ("train","validation","test")),
        "holdout_policy":"No actual holdout metrics until >=3 disjoint companies, families, and human graded pairs",
        "sha256":{p.name:_digest(p) for p in (path,csv_path,test,out/"label_rubric.json")}}
    (out/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    return manifest

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--out",required=True)
    p.add_argument("--max-notices",type=int,default=500)
    p.add_argument("--max-companies",type=int,default=30)
    args=p.parse_args()
    import os
    url=os.getenv("BIDCHECK_LOCAL_DATABASE_URL")
    if not url:raise SystemExit("BIDCHECK_LOCAL_DATABASE_URL is required; remote sources blocked")
    notices,companies=local_snapshot(url,args.max_notices,args.max_companies)
    print(json.dumps(create_review_dataset(notices,companies,args.out),ensure_ascii=False,indent=2))
if __name__=="__main__":main()
