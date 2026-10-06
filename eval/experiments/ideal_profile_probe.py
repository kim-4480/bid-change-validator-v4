"""공고마다 '모든 요건을 충족하는 가상 회사' 프로필을 만들어, 같은 공고를 여러 번 분석·판정해도 결과가 한결같은지 잰다.

    python eval/experiments/ideal_profile_probe.py --sample eval/golden/notice-sample-20261006c \
        --labels eval/golden/notice-sample-20261006c/labels.json --runs 3 --out artifacts/ideal_profile.json

정답 파일의 공고마다 ideal_profile(CompanyProfileSnapshot 모양)을 사람이 원문을 읽고 적는다. 그 회사는 공고의
참가 자격을 전부 갖췄다. 그러므로

  - 요건 하나라도 '미달'(UNSATISFIED)로 나오면 그것은 틀린 미달이다 — 자격 있는 회사의 공고를 숨기는, 검색
    필터에서 가장 나쁜 오류다.
  - '확인 필요'(UNKNOWN)는 틀린 것은 아니지만 많을수록 쓸모가 적다.
  - 같은 공고를 다시 돌렸을 때 종합 판정(eligible / insufficient_data / ineligible)과 요건별 판정이 같아야 한다.

방식은 polarity_guard_probe 와 같다(--modes). 기본은 채택한 조합(clause + 맥락 가드 + hybrid 선택)이다.
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from bidengine.judgment.rules import CompanyProfileSnapshot, judge_requirements
from bidengine.pipeline.analysis_pipeline import (
    QualificationAnalysisInput,
    QualificationDocumentInput,
    analyze_qualification_documents,
)
from bideval.master_vocabulary import CsvIndustryNameResolver
from bideval.notice_sample import SampleVersion, load_sample

sys.path.insert(0, str(Path(__file__).resolve().parent))
from polarity_guard_probe import CONFIG, FirstAnswerMemory, RetryingExtractor, _labelled_unselected  # noqa: E402

REFERENCE_DATE = date(2026, 10, 6)


def _run(version: SampleVersion, profile: CompanyProfileSnapshot, mode: str, model: str, run: int,
         polarity_memory: FirstAnswerMemory, selection_memory: FirstAnswerMemory,
         labeling_memory: FirstAnswerMemory | None) -> dict:
    polarity_guard, clause_selection = CONFIG[mode]
    started = time.monotonic()
    try:
        result = analyze_qualification_documents(
            QualificationAnalysisInput(
                notice_id=version.label, notice_version_id=f"{version.label}-{mode}-{run}",
                documents=[QualificationDocumentInput(document_id=d.document_key, extracted_blocks=d.blocks)
                           for d in version.documents],
            ),
            structured_extract=RetryingExtractor(model),
            industry_resolver=CsvIndustryNameResolver(),
            extraction_mode="clause",
            polarity_guard=polarity_guard,
            polarity_memory=polarity_memory if polarity_guard else None,
            clause_selection=clause_selection,
            selection_memory=selection_memory,
            labeling_memory=labeling_memory,
        )
        evaluation = judge_requirements(
            result.requirements, profile, preflight_case_id=f"{version.label}-{run}", reference_date=REFERENCE_DATE,
            analysis_status=result.status, coverage_complete=bool(result.coverage and result.coverage.complete),
        )
    except Exception as error:  # noqa: BLE001
        return {"version": version.label, "mode": mode, "run": run, "error": repr(error)[:300]}
    if not result.requirements:
        # 모델 호출이 전부 실패해도(키 없음 등) 요건 0건이 '틀린 미달 0' 으로 세어진다. 실패로 남긴다.
        return {"version": version.label, "mode": mode, "run": run, "error": f"요건 0건 (상태 {result.status})"}
    by_key = {r.requirement_key: r for r in result.requirements}
    judgments = []
    for judgment in evaluation.judgments:
        requirement = by_key.get(judgment.requirement_key)
        judgments.append({
            "status": judgment.status,
            "type": requirement.type if requirement else None,
            "value": str(requirement.value) if requirement else None,
            "group_operator": requirement.group_operator if requirement else None,
            "raw": " ".join((requirement.raw if requirement else "").split())[:120],
        })
    return {
        "version": version.label, "mode": mode, "run": run, "seconds": round(time.monotonic() - started, 1),
        "overall": evaluation.overall_status,
        "coverage_complete": bool(result.coverage and result.coverage.complete),
        "judgments": judgments,
    }


def _signature(run: dict) -> frozenset:
    return frozenset((j["type"], j["value"], j["status"]) for j in run["judgments"])


def summarize(runs: list[dict], modes: list[str]) -> dict:
    out = {}
    for mode in modes:
        mine = [r for r in runs if r["mode"] == mode and "error" not in r]
        by_version: dict[str, list[dict]] = {}
        for r in mine:
            by_version.setdefault(r["version"], []).append(r)
        false_unsatisfied = [r for r in mine if any(j["status"] == "UNSATISFIED" for j in r["judgments"])]
        per_notice = {}
        for version, group in sorted(by_version.items()):
            per_notice[version] = {
                "overall": [r["overall"] for r in sorted(group, key=lambda r: r["run"])],
                "unsatisfied": sorted({f"{j['type']} {j['value']}" for r in group for j in r["judgments"] if j["status"] == "UNSATISFIED"}),
                "same_overall": len({r["overall"] for r in group}) == 1,
                "same_judgments": len({_signature(r) for r in group}) == 1,
            }
        out[mode] = {
            "runs": len(mine), "errors": sum(1 for r in runs if r["mode"] == mode and "error" in r),
            "runs_with_false_unsatisfied": len(false_unsatisfied),
            "false_unsatisfied_rate": round(len(false_unsatisfied) / len(mine), 3) if mine else None,
            "overall": dict(Counter(r["overall"] for r in mine)),
            "notices_same_overall": sum(v["same_overall"] for v in per_notice.values()),
            "notices_same_judgments": sum(v["same_judgments"] for v in per_notice.values()),
            "notices": len(per_notice),
            "satisfied_mean": round(st.mean(sum(j["status"] == "SATISFIED" for j in r["judgments"]) for r in mine), 2) if mine else None,
            "unknown_mean": round(st.mean(sum(j["status"] == "UNKNOWN" for j in r["judgments"]) for r in mine), 2) if mine else None,
            "per_notice": per_notice,
        }
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--model", default="gpt-6-luna")
    parser.add_argument("--modes", nargs="+", default=["hybrid_polarity"], choices=list(CONFIG))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reuse", action="store_true")
    parser.add_argument("--no-labeling-memory", action="store_true", help="조항 라벨을 기억하지 않는다(전후 비교용)")
    args = parser.parse_args()

    labels = json.loads(args.labels.read_text(encoding="utf-8"))["notices"]
    profiles = {label: CompanyProfileSnapshot.model_validate(item["ideal_profile"])
                for label, item in labels.items() if item.get("ideal_profile")}
    notices, changed = load_sample(args.sample)
    versions = {v.label: v for v in notices}
    for chain in changed:
        versions.update({v.label: v for v in chain})
    for version in _labelled_unselected(args.sample, args.labels, set(versions)):
        versions[version.label] = version
    versions = {label: version for label, version in versions.items() if label in profiles}

    if args.reuse:
        runs = json.loads(args.out.read_text(encoding="utf-8"))["runs"]
    else:
        polarity_memory, selection_memory = FirstAnswerMemory(), FirstAnswerMemory()
        labeling_memory = None if args.no_labeling_memory else FirstAnswerMemory()
        jobs = [(versions[label], profiles[label], mode, args.model, run, polarity_memory, selection_memory, labeling_memory)
                for label in versions for mode in args.modes for run in range(args.runs)]
        print(f"notices={len(versions)} calls={len(jobs)}")
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            runs = list(pool.map(lambda job: _run(*job), jobs))
        args.out.parent.mkdir(parents=True, exist_ok=True)
    summary = summarize(runs, args.modes)
    args.out.write_text(json.dumps({"summary": summary, "runs": runs}, ensure_ascii=False), encoding="utf-8")
    for mode, row in summary.items():
        print(f"\n== {mode}: 실행 {row['runs']}회(실패 {row['errors']}), 틀린 미달이 나온 실행 {row['runs_with_false_unsatisfied']}회 "
              f"({row['false_unsatisfied_rate']}), 종합 {row['overall']}, 종합 판정이 3회 같은 공고 "
              f"{row['notices_same_overall']}/{row['notices']}, 요건별 판정까지 같은 공고 {row['notices_same_judgments']}/{row['notices']}, "
              f"충족 {row['satisfied_mean']}건/회, 확인 필요 {row['unknown_mean']}건/회")
        for version, item in row["per_notice"].items():
            print(f"   {version} {item['overall']} 미달: {item['unsatisfied']}")


if __name__ == "__main__":
    main()
