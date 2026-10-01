"""차수 비교(S4)를 실제 추출 결과로 잰다.

  - 같은 공고를 여러 번 추출해 서로 비교한다. 공고가 같으니 전부 UNCHANGED 여야 한다(오탐).
  - G2 1차 → 2차(실제 변경공고, "강원도 본점 제한" 문구가 빠짐)를 비교한다.

추출 방식(legacy / clause)과 차수 비교 코드(--old-diff 로 준 이전 버전 / 현재)를 교차한다.

    python eval/experiments/diff_probe.py --runs 3 --old-diff /path/to/old_requirement_diff.py --out r.json
"""
from __future__ import annotations

import argparse
import importlib.util
import itertools
import json
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import live_extraction_probe as probe  # noqa: E402

from bidengine.contracts import QualificationRequirement  # noqa: E402
from bidengine.diff import requirement_diff as current_diff  # noqa: E402
from bidengine.pipeline.analysis_pipeline import (  # noqa: E402
    QualificationAnalysisInput,
    QualificationDocumentInput,
    analyze_qualification_documents,
)
from bidengine.providers.openai import OpenAIStructuredExtractor  # noqa: E402
from bideval.master_vocabulary import CsvIndustryNameResolver  # noqa: E402


def _documents() -> list[tuple[str, dict]]:
    docs = []
    for case_id, _stem, native, pdf in probe._pairs():
        docs += [(f"{case_id}-native", native), (f"{case_id}-pdf", pdf)]
    # G2 는 차수마다 공고문과 제안요청서를 **함께** 넣는다 — 제품도 한 차수의 문서를 모두 분석하고,
    # 빠진 "강원도 본점" 조항은 제안요청서 6쪽에 있다(공고문만 넣으면 처음부터 안 보인다).
    g2 = json.loads((probe.REAL / "cases" / "G2" / "case.json").read_text(encoding="utf-8"))
    for version in ("G2-v1", "G2-v2"):
        bundle = [d for d in g2["documents"]
                  if d["version_key"] == version and d["name"] in {"입찰공고문.pdf", "제안요청서.pdf"} and d.get("blocks")]
        docs.append((version, bundle))
    return docs


def _extract(label: str, doc: dict | list[dict], mode: str, run: int, model: str | None) -> dict:
    bundle = doc if isinstance(doc, list) else [doc]
    result = analyze_qualification_documents(
        QualificationAnalysisInput(
            notice_id=label, notice_version_id=f"{label}-{mode}-{run}",
            documents=[QualificationDocumentInput(document_id=d["document_key"], extracted_blocks=probe._blocks(d)) for d in bundle],
        ),
        structured_extract=OpenAIStructuredExtractor(model=model),
        industry_resolver=CsvIndustryNameResolver(),
        extraction_mode=mode,
    )
    return {"doc": label, "mode": mode, "run": run,
            "requirements": [r.model_dump(mode="json") for r in result.requirements]}


def _load_old(path: Path):
    spec = importlib.util.spec_from_file_location("old_requirement_diff", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # pydantic 이 모듈 안의 타입 이름을 찾을 수 있게
    spec.loader.exec_module(module)
    return module


def _changes(diff_module, a: list[dict], b: list[dict]) -> Counter:
    left = [QualificationRequirement.model_validate(r) for r in a]
    right = [QualificationRequirement.model_validate(r) for r in b]
    return Counter(c.change_type for c in diff_module.diff_requirements(left, right))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--model")
    parser.add_argument("--old-diff", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--only-g2", action="store_true", help="G2 차수 쌍만 다시 추출한다")
    parser.add_argument("--reuse", type=Path, help="이전 실행의 --out 파일에서 추출 결과를 다시 쓴다(모델 호출 없음)")
    args = parser.parse_args()
    old_diff = _load_old(args.old_diff)

    if args.reuse:
        runs = json.loads(args.reuse.read_text(encoding="utf-8"))["runs"]
    else:
        documents = [(l, d) for l, d in _documents() if not args.only_g2 or l.startswith("G2")]
        jobs = [(label, doc, mode, run) for label, doc in documents for mode in ("legacy", "clause") for run in range(args.runs)]
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            runs = list(pool.map(lambda j: _extract(*j, args.model), jobs))
        if args.out:  # 계산 전에 먼저 남긴다 — 계산이 실패해도 호출 결과는 잃지 않는다
            args.out.write_text(json.dumps({"runs": runs}, ensure_ascii=False), encoding="utf-8")

    by = {}
    for r in runs:
        by.setdefault((r["doc"], r["mode"]), []).append(r["requirements"])

    report = {"rerun_false_changes": {}, "g2_change": {}}
    for mode in ("legacy", "clause"):
        for name, module in (("old_diff", old_diff), ("new_diff", current_diff)):
            total = Counter()
            for (doc, m), reqsets in by.items():
                if m != mode or doc.startswith("G2"):  # G2 는 두 차수가 달라 오탐 측정에서 뺀다
                    continue
                for a, b in itertools.combinations(reqsets, 2):
                    total += _changes(module, a, b)
            n = sum(total.values())
            report["rerun_false_changes"][f"{mode}/{name}"] = {
                **dict(total), "false_change_rate": round(1 - total["UNCHANGED"] / n, 3) if n else None,
            }
            g2 = Counter()
            for a, b in itertools.product(by[("G2-v1", mode)], by[("G2-v2", mode)]):
                g2 += _changes(module, a, b)
            report["g2_change"][f"{mode}/{name}"] = dict(g2)
    report["g2_requirements"] = {
        f"{doc}/{mode}": [[(r["type"], r["value"]) for r in reqs] for reqs in sets]
        for (doc, mode), sets in by.items() if doc.startswith("G2")
    }
    if args.out:
        args.out.write_text(json.dumps({"report": report, "runs": runs}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
