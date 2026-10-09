"""Read-only data export. Pseudo labels are NEVER verified relevance judgments."""
import argparse
import hashlib
import json
import os
import random
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from .cost_guard import require_isolated_data_url, require_bounded_limit

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def write_jsonl(path, rows):
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

def split_families(notices):
    families = {}
    for n in notices:
        families.setdefault(n["family_id"], []).append(n)
    ids = sorted(families, key=lambda k: (min(str(n.get("posted_at") or "9999") for n in families[k]), k))
    if len(ids) < 6:
        raise ValueError("At least six independent notice families needed")
    a, b = max(2, int(len(ids)*.7)), max(4, int(len(ids)*.85))
    b = min(b, len(ids)-2)
    return {k: ("train" if i < a else "validation" if i < b else "test") for i,k in enumerate(ids)}

def audit(rows):
    sets = {s:set() for s in ("train","validation","test")}
    companies = {s:set() for s in sets}
    for r in rows:
        sets[r["split"]].update((r["query_family_id"],r["candidate_family_id"]))
        if r.get("company_id"):
            companies[r["split"]].add(r["company_id"])
    overlaps = {a+"_"+b: sorted(sets[a] & sets[b]) for a,b in (("train","validation"),("train","test"),("validation","test"))}
    co = {a+"_"+b: sorted(companies[a] & companies[b]) for a,b in (("train","validation"),("train","test"),("validation","test"))}
    return {"family_overlap":overlaps,"company_overlap":co,"passed":not any(overlaps.values()) and not any(co.values())}

def from_postgres(url, limit=15000, allow_remote=False):
    require_isolated_data_url(url, allow_remote=allow_remote)
    require_bounded_limit(limit)
    import psycopg
    notices, companies = [], []
    with psycopg.connect(url,connect_timeout=8,options="-c default_transaction_read_only=on") as conn:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute("""SELECT n.id::text,n.bid_notice_no,n.title,n.business_type,
                n.announcing_institution_name,v.posted_at::text
                FROM bid_notices n JOIN bid_notice_versions v ON v.notice_id=n.id AND v.is_current=TRUE
                WHERE length(trim(n.title))>=4 ORDER BY v.posted_at NULLS LAST,n.id LIMIT %s""",(limit,))
            for uid,no,title,kind,agency,posted in cur:
                notices.append(dict(notice_id=uid,family_id=uid,notice_no=no,title=title,
                                    business_type=kind,institution=agency,posted_at=posted))
            cur.execute("""SELECT c.id::text,c.name,c.region_name,c.company_size,
                COALESCE(string_agg(i.name,' ' ORDER BY i.name),'')
                FROM companies c LEFT JOIN company_industries ci ON ci.company_id=c.id
                LEFT JOIN industry_codes i ON i.code=ci.industry_code
                GROUP BY c.id,c.name,c.region_name,c.company_size LIMIT 5000""")
            for uid,name,region,size,industry in cur:
                companies.append({"company_id":uid,"profile_text":" ".join(str(x) for x in (name,region,size,industry) if x)})
    return notices,companies

def normalize(text):
    return re.findall(r"[\uac00-\ud7a3A-Za-z0-9]+",text.lower())

def export(notices,companies,out,seed=42,reviewed=None):
    out=Path(out)
    out.mkdir(parents=True,exist_ok=True)
    split=split_families(notices)
    rng=random.Random(seed)
    by_split={s:[n for n in notices if split[n["family_id"]]==s] for s in ("train","validation","test")}
    rows=[]
    for s,group in by_split.items():
        for n in group:
            words=normalize(n["title"])
            pool=[other for other in group if other["family_id"]!=n["family_id"]]
            if not words or not pool:
                continue
            same=[o for o in pool if o["business_type"]==n["business_type"]]
            hard=max(same or pool,key=lambda other:(len(set(words)&set(normalize(other["title"]))),other["notice_id"]))
            easy=rng.choice([o for o in pool if o["notice_id"]!=hard["notice_id"]] or [hard])
            for cand,grade,kind in ((n,3,"positive"),(hard,0,"hard_negative"),(easy,0,"negative")):
                rows.append(dict(task="query_notice",query_id="q:"+n["notice_id"],
                    query_family_id=n["family_id"],query_text=" ".join(words[:7]),
                    candidate_family_id=cand["family_id"],notice_id=cand["notice_id"],notice_text=cand["title"],
                    business_type=cand["business_type"],label=grade,negative_type=kind,
                    label_source="synthetic_title",split=s))
    reviewed_count=0
    lookup={n["notice_id"]:n for n in notices}
    if reviewed:
        for line_no,line in enumerate(Path(reviewed).read_text(encoding="utf-8").splitlines(),1):
            if not line.strip():
                continue
            r=json.loads(line)
            if r.get("label_source")!="human_reviewed" or not r.get("reviewer_id") or not r.get("reviewed_at") or type(r.get("label"))!=int or r["label"] not in range(4):
                raise ValueError("Unverified relevance label line "+str(line_no))
            n=lookup.get(r.get("notice_id"))
            if not n or not r.get("query_text"):
                raise ValueError("Unknown/empty annotation line "+str(line_no))
            family=r.get("query_family_id",n["family_id"])
            if family not in split or split[family]!=split[n["family_id"]]:
                raise ValueError("Cross-split annotation line "+str(line_no))
            r.update(split=split[n["family_id"]],candidate_family_id=n["family_id"],query_family_id=family,
                     notice_text=n["title"],task=r.get("task","query_notice"))
            rows.append(r)
            reviewed_count+=1
    check=audit(rows)
    if not check["passed"]:
        raise ValueError("Leakage audit failed: "+str(check))
    # Real company profiles: unlabelled candidates; cannot claim suitability automatically.
    company_rows=[]
    for i,c in enumerate(companies):
        n=notices[i%len(notices)]
        company_rows.append(dict(**c,notice_id=n["notice_id"],notice_text=n["title"],
                                 label=None,label_source="unlabeled"))
    write_jsonl(out/"pairs.jsonl",rows)
    write_jsonl(out/"company_candidates.jsonl",company_rows)
    manifest=dict(schema_version="recommendation-pairs-v1",
       dataset_version=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
       seed=seed,notice_count=len(notices),company_count=len(companies),reviewed_labels=reviewed_count,
       synthetic_labels=len(rows)-reviewed_count,unlabeled_company_pairs=len(company_rows),
       counts={str(k):v for k,v in Counter((r["split"],r["label_source"]) for r in rows).items()},
       label_policy="Synthetic title matches are pipeline smoke tests, not real recommendation accuracy",
       split_policy="Chronological notice-family split; cross-split candidates prohibited",
       historical_187_unknown_excluded=True,leakage=check,
       sha256={f:digest(out/f) for f in ("pairs.jsonl","company_candidates.jsonl")})
    (out/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    return manifest

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--out",required=True)
    p.add_argument("--limit",type=int,default=15000)
    p.add_argument("--seed",type=int,default=42)
    p.add_argument("--reviewed")
    p.add_argument("--db-url-env",default="DATABASE_URL")
    p.add_argument("--allow-remote-source",action="store_true",help="Requires explicit operator approval; defaults to isolated DB only")
    args=p.parse_args()
    url=os.getenv(args.db_url_env)
    if not url:
        raise SystemExit("No DB URL provided. Use only read-only DB credentials.")
    notices,companies=from_postgres(url,args.limit,args.allow_remote_source)
    print(json.dumps(export(notices,companies,args.out,args.seed,args.reviewed),ensure_ascii=False,indent=2))
if __name__=="__main__":
    main()
