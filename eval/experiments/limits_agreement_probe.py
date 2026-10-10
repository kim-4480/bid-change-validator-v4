"""정답 없이 오류를 찾는다: 문서만으로 뽑은 업종·지역을 나라장터에 입력된 면허제한·참가가능지역과 견준다(2026-10-10).

    python eval/experiments/limits_agreement_probe.py --out artifacts/limits_agreement.jsonl --memory artifacts/regression_memory.json

사람이 쓴 정답은 수가 적고 틀리기도 한다. 면허제한과 참가가능지역은 발주처가 나라장터에 코드로 입력한 값이라, 업종과 지역에
한해서는 정답 대용으로 쓸 수 있다. 공고마다 문서만 읽어(면허제한 보강 없이) 요건을 뽑고, 입력된 값과 어긋나는 공고를 모은다.

어긋남의 종류:
  문서가 놓침      나라장터에는 있는데 문서 요건에 없는 업종·지역. 그 이름이 문서에 적혀 있으면 추출이 놓친 것이고,
                   없으면 문서에 없는 정보다(나라장터 값으로만 알 수 있다).
  문서가 더 요구   문서는 필수로 읽었는데 나라장터에서는 대안이거나 없는 업종. 틀린 부적합의 원인이 된다.
  문서에만 있음    문서 요건에는 있는데 나라장터에 없는 업종·지역. 발주처가 덜 입력했거나 추출이 잘못 읽었다.

발주처가 값을 비워 둔 공고는 견줄 것이 없어 뺀다. 그래서 이 측정은 '나라장터에 값이 있는 공고' 에 대한 것이다.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from bidengine.normalization.regions import sidos_of
from bidengine.pipeline.analysis_pipeline import (
    QualificationAnalysisInput,
    QualificationDocumentInput,
    analyze_qualification_documents,
)
from bidengine.pipeline.notice_limits import NoticeLimits, license_groups
from bideval.master_vocabulary import CsvIndustryNameResolver
from bideval.notice_sample import load_sample

sys.path.insert(0, str(Path(__file__).resolve().parent))
from polarity_guard_probe import RetryingExtractor  # noqa: E402
from regression_probe import FileMemory  # noqa: E402

RESOLVER = CsvIndustryNameResolver()


def _compact(text: object) -> str:
    return "".join(str(text or "").split()).replace("·", "").replace("ㆍ", "")


def compare(version, limits: NoticeLimits, result) -> dict:
    document_text = _compact(" ".join(str(block.get("text") or "") for d in version.documents for block in d.blocks))
    names = {item.code: item.name for item in limits.licenses if item.code}
    groups = license_groups(limits)
    industry = [r for r in result.requirements if r.type == "INDUSTRY" and str(r.value).isdigit() and len(str(r.value)) == 4]
    doc_all = {str(r.value) for r in industry} | {str(c) for r in industry for c in r.scope.get("with_codes") or []}
    doc_required = {str(r.value) for r in industry if r.requirement_role == "mandatory" and (r.group_operator or "ALL_OF") == "ALL_OF"
                    and r.scope.get("evidence") not in {"family", "model_match", "compound"}}
    row: dict = {"label": version.label, "industry": None, "region": None, "details": []}

    if groups:
        api_all = set().union(*groups)
        api_common = set.intersection(*groups)
        # 포함 면허(토목건축 ⊃ 건축)는 같은 것으로 본다.
        covers = lambda code: code in doc_all or any(p in doc_all for p in RESOLVER.including_codes(code)) or any(  # noqa: E731
            code in RESOLVER.including_codes(other) for other in doc_all)
        missed = sorted(code for code in api_all if not covers(code))
        over = sorted(code for code in doc_required if code in api_all and code not in api_common)
        only_doc = sorted(code for code in doc_all - api_all if not any(code in RESOLVER.including_codes(a) or a in RESOLVER.including_codes(code) for a in api_all))
        for code in missed:
            written = _compact(names.get(code, "")) in document_text or code in document_text
            row["details"].append({"kind": "문서가 놓침(업종)", "code": code, "name": names.get(code, ""), "in_document": written})
        for code in over:
            row["details"].append({"kind": "문서가 더 요구(업종)", "code": code, "name": names.get(code, "")})
        for code in only_doc:
            row["details"].append({"kind": "문서에만 있음(업종)", "code": code})
        row["industry"] = "같음" if not (missed or over or only_doc) else "어긋남"

    regions = [region for region in limits.regions if region]
    if regions:
        api_sidos = set().union(*(sidos_of(region) for region in regions))
        doc_regions = [str(r.value) for r in result.requirements if r.type == "REGION" and r.requirement_role == "mandatory"]
        doc_sidos = set().union(set(), *(sidos_of(region) for region in doc_regions))
        if not doc_regions:
            row["details"].append({"kind": "문서가 놓침(지역)", "api": regions[:3], "in_document": any(_compact(r.split()[-1]) in document_text for r in regions)})
            row["region"] = "어긋남"
        elif api_sidos and doc_sidos and not (api_sidos & doc_sidos):
            row["details"].append({"kind": "지역이 다름", "api": regions[:3], "document": doc_regions})
            row["region"] = "어긋남"
        else:
            row["region"] = "같음"
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=Path, default=Path("eval/golden/notice-sample-20261006f"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--memory", type=Path)
    parser.add_argument("--model", default="gpt-6-luna")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--only", nargs="*")
    args = parser.parse_args()

    notices, _changed = load_sample(args.sample)
    targets = []
    for version in notices:
        path = args.sample / version.label / "notice_api.json"
        if not path.exists() or (args.only and version.label not in args.only):
            continue
        limits = NoticeLimits.from_collected(json.loads(path.read_text(encoding="utf-8")))
        if limits.licenses or limits.regions:
            targets.append((version, limits))

    memories = None
    if args.memory:
        stored = json.loads(args.memory.read_text(encoding="utf-8")) if args.memory.exists() else {}
        memories = {kind: FileMemory(stored.get(kind)) for kind in ("labeling", "selection", "polarity", "gap_summary")}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("", encoding="utf-8")
    lock = threading.Lock()
    rows: list[dict] = []

    def work(item) -> None:
        version, limits = item
        try:
            result = analyze_qualification_documents(
                QualificationAnalysisInput(
                    notice_id=version.label, notice_version_id=f"{version.label}-agree",
                    documents=[QualificationDocumentInput(document_id=d.document_key, extracted_blocks=d.blocks) for d in version.documents],
                ),
                structured_extract=RetryingExtractor(args.model), industry_resolver=RESOLVER,
                extraction_mode="closed_first", clause_selection="hybrid",
                labeling_memory=(memories or {}).get("labeling", {}), selection_memory=(memories or {}).get("selection", {}),
                polarity_memory=(memories or {}).get("polarity", {}), gap_summary_memory=(memories or {}).get("gap_summary", {}),
                memory_namespace=args.model, summarize_gaps=False,
            )
            row = compare(version, limits, result)
        except Exception as error:  # noqa: BLE001 - 한 공고의 실패가 전체 측정을 멈추지 않게
            row = {"label": version.label, "error": repr(error)[:300], "details": []}
        with lock:
            rows.append(row)
            with args.out.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(version.label[7:], row.get("industry"), row.get("region"), "; ".join(d["kind"] for d in row["details"]), flush=True)

    with ThreadPoolExecutor(args.workers) as pool:
        list(pool.map(work, targets))
    if memories is not None:
        args.memory.write_text(json.dumps({k: dict(v) for k, v in memories.items()}, ensure_ascii=False), encoding="utf-8")

    counter: Counter = Counter()
    kinds: Counter = Counter()
    for row in rows:
        if "error" in row:
            counter["오류"] += 1
            continue
        for field in ("industry", "region"):
            if row[field]:
                counter[f"{field}_{row[field]}"] += 1
        for detail in row["details"]:
            kinds[detail["kind"] + ("·문서에 적힘" if detail.get("in_document") else "·문서에 없음" if "in_document" in detail else "")] += 1
    print("\n== 요약 ==", f"견준 공고 {len(rows)}건", json.dumps(dict(counter), ensure_ascii=False))
    print("== 어긋남 종류 ==", json.dumps(dict(kinds.most_common()), ensure_ascii=False))
    print("\n== 어긋난 공고 ==")
    for row in sorted(rows, key=lambda r: r["label"]):
        for detail in row["details"]:
            print(f"  {row['label'][7:]} {json.dumps(detail, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
