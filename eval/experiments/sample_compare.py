"""수집한 공고 표본으로 추출 방식 × 모델을 한 번에 비교한다 (기본값 전환 판단용).

    python eval/experiments/sample_compare.py --sample eval/golden/notice-sample-20261001 \
        --runs 3 --models gpt-5.6-luna gpt-6-luna --out artifacts/sample_compare.json

재는 것 (방식 × 모델마다)
  - 위치 일치도: 요건을 (유형, 원문 조항)으로 식별한 반복 일치도
  - 값 일치도: (유형, 연산자, 값, 기간, 분야)로 식별한 반복 일치도
  - 판정 요건 수, 커버리지 완료율, 호출 시간
  - 재추출 오탐률: 같은 차수를 다시 추출해 차수 비교한 결과 중 UNCHANGED 가 아닌 비율
  - 변경 탐지 합의도: 변경공고 차수 쌍마다, 실행 조합별로 잡은 변경 집합이 서로 얼마나 같은지
    (정답 라벨이 없으므로 "매번 같은 변경을 잡는가" 를 잰다)

모든 추출 결과는 계산 전에 --out 에 먼저 남긴다. --reuse 로 다시 계산할 수 있다.
"""
from __future__ import annotations

import argparse
import itertools
import json
import re
import statistics as st
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from bidengine.contracts import QualificationRequirement
from bidengine.diff.requirement_diff import diff_requirements
from bidengine.pipeline.analysis_pipeline import (
    QualificationAnalysisInput,
    QualificationDocumentInput,
    analyze_qualification_documents,
)
from bidengine.providers.openai import OpenAIStructuredExtractor
from bideval.master_vocabulary import CsvIndustryNameResolver
from bideval.notice_sample import SampleVersion, load_sample

MODES = ("legacy", "clause")


def _extract(version: SampleVersion, mode: str, model: str, run: int) -> dict:
    started = time.monotonic()
    try:
        result = analyze_qualification_documents(
            QualificationAnalysisInput(
                notice_id=version.label, notice_version_id=f"{version.label}-{mode}-{model}-{run}",
                documents=[QualificationDocumentInput(document_id=d.document_key, extracted_blocks=d.blocks)
                           for d in version.documents],
            ),
            structured_extract=OpenAIStructuredExtractor(model=model),
            industry_resolver=CsvIndustryNameResolver(),
            extraction_mode=mode,
        )
    except Exception as error:  # noqa: BLE001
        return {"version": version.label, "mode": mode, "model": model, "run": run, "error": repr(error)[:300]}
    return {
        "version": version.label, "mode": mode, "model": model, "run": run,
        "seconds": round(time.monotonic() - started, 1),
        "status": result.status,
        "coverage_complete": bool(result.coverage and result.coverage.complete),
        "requirements": [r.model_dump(mode="json") for r in result.requirements],
    }


def _jac(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a | b else 1.0


def _anchor(r: dict) -> tuple:
    return (r["type"], re.sub(r"\s+", "", r["raw"]))


def _value(r: dict) -> tuple:
    scope = r.get("scope") or {}
    detail = tuple(sorted((k, str(v)) for k, v in scope.items() if k in {"experience_field", "role", "kind", "restriction"}))
    return (r["type"], r["operator"], str(r["value"]), r["period_months"], detail)


def _reqs(run: dict) -> list[QualificationRequirement]:
    return [QualificationRequirement.model_validate(r) for r in run["requirements"]]


def _change_set(a: dict, b: dict) -> frozenset:
    return frozenset(
        (c.change_type, (c.current or c.baseline).type, str((c.current or c.baseline).value))
        for c in diff_requirements(_reqs(a), _reqs(b)) if c.change_type != "UNCHANGED"
    )


def summarize(runs: list[dict], changed_labels: list[list[str]], modes: tuple[str, ...] = MODES) -> dict:
    ok = [r for r in runs if "error" not in r]
    out = {}
    for model in sorted({r["model"] for r in ok}):
        for mode in modes:
            mine = [r for r in ok if r["model"] == model and r["mode"] == mode]
            if not mine:
                continue
            by_version: dict[str, list[dict]] = {}
            for r in mine:
                by_version.setdefault(r["version"], []).append(r)
            anchor, value, false_changes, total_changes = [], [], 0, 0
            for group in by_version.values():
                for a, b in itertools.combinations(group, 2):
                    anchor.append(_jac({_anchor(x) for x in a["requirements"]}, {_anchor(x) for x in b["requirements"]}))
                    value.append(_jac({_value(x) for x in a["requirements"]}, {_value(x) for x in b["requirements"]}))
                    kinds = Counter(c.change_type for c in diff_requirements(_reqs(a), _reqs(b)))
                    false_changes += sum(v for k, v in kinds.items() if k != "UNCHANGED")
                    total_changes += sum(kinds.values())
            agreement = []
            for labels in changed_labels:
                for before, after in zip(labels, labels[1:]):
                    sets = [_change_set(a, b) for a, b in itertools.product(by_version.get(before, []), by_version.get(after, []))]
                    agreement += [_jac(set(x), set(y)) for x, y in itertools.combinations(sets, 2)]
            errors = sum(1 for r in runs if r["model"] == model and r["mode"] == mode and "error" in r)
            out[f"{model}/{mode}"] = {
                "runs": len(mine), "errors": errors,
                "anchor_stability": round(st.mean(anchor), 3) if anchor else None,
                "value_stability": round(st.mean(value), 3) if value else None,
                "rerun_false_change_rate": round(false_changes / total_changes, 3) if total_changes else None,
                "change_detection_agreement": round(st.mean(agreement), 3) if agreement else None,
                "judged_mean": round(st.mean(len(r["requirements"]) for r in mine), 2),
                "coverage_complete_rate": round(sum(r["coverage_complete"] for r in mine) / len(mine), 3),
                "seconds_mean": round(st.mean(r["seconds"] for r in mine), 1),
            }
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--models", nargs="+", default=["gpt-5.6-luna", "gpt-6-luna"])
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reuse", action="store_true", help="--out 의 추출 결과로 다시 계산만 한다")
    args = parser.parse_args()

    notices, changed = load_sample(args.sample)
    versions = {v.label: v for v in notices}
    for chain in changed:
        versions.update({v.label: v for v in chain})
    changed_labels = [[v.label for v in chain] for chain in changed]

    if args.reuse:
        runs = json.loads(args.out.read_text(encoding="utf-8"))["runs"]
    else:
        jobs = [(v, mode, model, run) for v in versions.values() for mode in MODES for model in args.models
                for run in range(args.runs)]
        print(f"versions={len(versions)} calls={len(jobs)}")
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            runs = list(pool.map(lambda job: _extract(*job), jobs))
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({"runs": runs}, ensure_ascii=False), encoding="utf-8")

    summary = summarize(runs, changed_labels)
    args.out.write_text(json.dumps({"summary": summary, "runs": runs}, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
