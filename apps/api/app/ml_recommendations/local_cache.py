"""Create an explicitly NON-PRODUCTION local smoke dataset from bundled notices only.

No AWS, OpenAI, network, S3, or database calls. Existing sample is not a
representative population and contains no human relevance annotations.
"""
from __future__ import annotations
import argparse
import json
import re
import uuid
from pathlib import Path
from .dataset import export

def notices_from_manifest(path):
    raw=Path(path).read_text(encoding="utf-8",errors="replace")
    # The frozen legacy corpus may contain malformed JSON strings. Only take
    # bounded notice-no + title metadata; never fetch source_url assets.
    found=re.findall(r'"notice_no":\s*"(R\d+BK\d+)"\s*,\s*"business_type":\s*"([^"]+)"\s*,\s*"title":\s*"([^"\r\n]+)"',raw)
    notices=[]
    for i,(number,kind,title) in enumerate(dict.fromkeys(found)):
        notices.append({"notice_id":str(uuid.uuid5(uuid.NAMESPACE_URL,"bidcheck-local:"+number)),
            "family_id":number,"notice_no":number,"title":title,"business_type":kind,
            "posted_at":f"2026-10-{(i%7)+1:02d}"})
    return notices

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--manifest",default="eval/golden/notice-changes-20261006/manifest.json")
    p.add_argument("--out",required=True)
    args=p.parse_args()
    notices=notices_from_manifest(args.manifest)
    manifest=export(notices,[],args.out)
    from .dataset import digest
    manifest["source"]={"type":"local_repo_cached_notice_manifest",
                        "manifest_sha256":digest(Path(args.manifest))}
    (Path(args.out)/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(manifest,ensure_ascii=False,indent=2))
if __name__=="__main__":
    main()
