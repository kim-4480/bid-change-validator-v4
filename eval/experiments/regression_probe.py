"""정답이 붙은 공고 전체로 판정을 다시 재고, 위험한 틀림을 따로 센다(2026-10-08).

    python eval/experiments/regression_probe.py --out artifacts/regression.jsonl \
        --memory artifacts/regression_memory.json --baseline artifacts/regression_prev.jsonl

공고 하나를 고치면 다른 공고가 깨지는 일을 그 자리에서 잡으려고 만들었다. 정답 파일(labels*.json)이 붙은 공고를
모두 돌리고, 결과를 두 갈래로 나눈다.

위험한 틀림 — 0 이어야 한다:
  - 틀린 부적합: 공고의 자격을 모두 갖춘 가상 회사(ideal_profile)가 '부적합' 이다.
  - 틀린 충족: 가상 회사에서 핵심 요건 하나를 빼도(업종을 지우고, 소재지를 옮기고, 규모를 바꾸고) '핵심 자격 충족' 이다.
    엔진이 그 요건을 놓쳤거나 못 막았다는 뜻이다.

안전한 틀림 — 줄이면 좋지만 오류는 아니다:
  - 판단 보류: 가상 회사가 '확인 필요' 로 끝난다. 사람이 보게 넘긴 것이다.

--memory 를 주면 조항 답 기억을 파일에 이어 쓴다. 바뀌지 않은 조항은 모델을 다시 부르지 않으므로, 코드 변경의 효과만
보이고 모델이 실행마다 다르게 답하는 흔들림은 섞이지 않는다. 흔들림을 재려면 --memory 없이 --runs 2 로 돌린다.
--baseline 을 주면 공고별 종합 판정이 이전 결과와 달라진 곳을 따로 보여 준다.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from bidengine.judgment.rules import CompanyProfileSnapshot, judge_requirements, requirement_tier
from bidengine.pipeline.analysis_pipeline import (
    QualificationAnalysisInput,
    QualificationDocumentInput,
    analyze_qualification_documents,
)
from bidengine.normalization.regions import sidos_of
from bidengine.pipeline.notice_limits import NoticeLimits, license_groups
from bideval.master_vocabulary import CsvIndustryNameResolver
from bideval.notice_sample import load_sample

sys.path.insert(0, str(Path(__file__).resolve().parent))
from polarity_guard_probe import RetryingExtractor  # noqa: E402
from score_against_labels import score_run  # noqa: E402

SAMPLE = Path("eval/golden/notice-sample-20261006f")
REFERENCE_DATE = date(2026, 10, 7)
# 핵심 요건 지역을 옮길 곳. 정답 값과 겹치지 않는 첫 곳을 쓴다.
_FAR_REGIONS = ("제주특별자치도 서귀포시", "강원특별자치도 삼척시", "전라남도 신안군")
# 규모 요건을 어기는 규모: 요구한 규모 낱말 → 그보다 큰 규모.
_BREAK_SIZE = {"소상공인": "MEDIUM", "소기업": "MEDIUM", "중기업": "LARGE", "중소기업": "LARGE"}


_STATUS_NAME = {"eligible": "core_met", "ineligible": "core_unmet", "insufficient_data": "needs_review"}


class FileMemory(dict):
    """조항마다 처음 받은 답을 지키고, 끝나면 파일로 남긴다."""

    def __init__(self, initial: dict | None = None) -> None:
        super().__init__(initial or {})
        self._lock = threading.Lock()

    def __setitem__(self, key: str, value: object) -> None:
        with self._lock:
            if key not in self:
                super().__setitem__(key, value)


def load_labels(paths: list[Path]) -> dict[str, dict]:
    labels: dict[str, dict] = {}
    for path in paths:
        labels.update(json.loads(path.read_text(encoding="utf-8"))["notices"])
    return labels


def broken_profiles(label: dict) -> list[tuple[str, dict]]:
    """핵심 요건마다 그 요건만 어긴 가상 회사. 바꿀 것이 없는 요건은 건너뛴다."""
    ideal = label["ideal_profile"]
    out: list[tuple[str, dict]] = []
    for item in label["core"]:
        values = [str(v) for v in [*item["values"], *item.get("also_accept", [])]]
        profile = json.loads(json.dumps(ideal))
        if item["type"] == "INDUSTRY":
            profile["industries"] = [i for i in profile["industries"] if i["code"] not in values]
            changed = len(profile["industries"]) != len(ideal["industries"])
        elif item["type"] == "REGISTRATION_CERTIFICATION":
            profile["certifications"] = [c for c in profile["certifications"] if c.get("certification_code") not in values]
            changed = len(profile["certifications"]) != len(ideal["certifications"])
        elif item["type"] == "REGION":
            far = next((r for r in _FAR_REGIONS if not any(v in r for v in values)), None)
            profile["region_name"] = far
            changed = far is not None
        elif item["type"] == "COMPANY_SIZE":
            if item.get("exclusion"):
                profile["company_size"] = "LARGE"
            else:
                profile["company_size"] = next((_BREAK_SIZE[v] for v in values if v in _BREAK_SIZE), None)
            changed = profile["company_size"] not in (None, ideal["company_size"])
        else:
            changed = False
        if changed:
            out.append((item["id"], profile))
    return out


def load_limits(label_id: str) -> NoticeLimits | None:
    """collect_notice_limits.py 가 받아 둔 나라장터 면허제한·참가가능지역. 없으면 None."""
    path = SAMPLE / label_id / "notice_api.json"
    return NoticeLimits.from_collected(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else None


def with_notice_limits(label: dict, limits: NoticeLimits | None) -> dict:
    """가상 회사는 공고의 자격을 모두 갖춘 회사다 — 나라장터에 입력된 면허·지역도 갖춘 것으로 맞춘다.

    정답은 문서만 보고 썼다. 면허제한의 첫 묶음 면허를 더하고, 참가가능지역과 시·도가 어긋나면 첫 지역으로 옮긴다.
    핵심 요건을 하나씩 빼는 검사(broken_profiles)는 이렇게 맞춘 회사에서 뺀다.
    """
    if limits is None:
        return label
    profile = json.loads(json.dumps(label["ideal_profile"]))
    groups = license_groups(limits)
    held = {item["code"] for item in profile["industries"]}
    if groups and not any(group <= held for group in groups):
        names = {item.code: item.name for item in limits.licenses}
        profile["industries"] += [{"code": code, "name": names.get(code, code), "verified": True} for code in sorted(groups[0] - held)]
    api_sidos = set().union(set(), *(sidos_of(region) for region in limits.regions))
    if api_sidos and not (api_sidos & sidos_of(profile.get("region_name"))):
        profile["region_name"] = limits.regions[0]
    return {**label, "ideal_profile": profile}


def judge(result, profile: dict, label_id: str) -> tuple[str, dict[str, str]]:
    judged = judge_requirements(
        result.requirements, CompanyProfileSnapshot.model_validate(profile), preflight_case_id=label_id,
        reference_date=REFERENCE_DATE, analysis_status=result.status, coverage_complete=result.coverage.verdict_complete,
    )
    return judged.overall_status, {j.requirement_key: j.status for j in judged.judgments}


def run_one(version, label: dict, run: int, model: str, memories: dict[str, dict] | None, use_limits: bool = True) -> dict:
    started = time.monotonic()
    memories = memories or {}
    limits = load_limits(version.label) if use_limits else None
    label = with_notice_limits(label, limits)
    result = analyze_qualification_documents(
        QualificationAnalysisInput(
            notice_id=version.label, notice_version_id=f"{version.label}-r{run}",
            documents=[QualificationDocumentInput(document_id=d.document_key, extracted_blocks=d.blocks) for d in version.documents],
        ),
        structured_extract=RetryingExtractor(model), industry_resolver=CsvIndustryNameResolver(),
        extraction_mode="closed_first", clause_selection="hybrid",
        labeling_memory=memories.get("labeling", {}), selection_memory=memories.get("selection", {}),
        polarity_memory=memories.get("polarity", {}), gap_summary_memory=memories.get("gap_summary", {}),
        memory_namespace=model, notice_limits=limits,
    )
    reqs = [r.model_dump(mode="json") for r in result.requirements]
    gaps = [g.model_dump(mode="json") for g in result.coverage.gaps]
    score = score_run({"version": version.label, "requirements": reqs, "gaps": gaps}, label)
    overall, status = judge(result, label["ideal_profile"], version.label)
    # 정답 파일은 예전 이름(eligible·ineligible·insufficient_data)으로 적혀 있다.
    expect = _STATUS_NAME.get(label.get("expect", "core_met"), label.get("expect", "core_met"))
    broken = {core_id: judge(result, profile, version.label)[0] for core_id, profile in broken_profiles(label)}
    return {
        "label": version.label, "run": run, "seconds": round(time.monotonic() - started),
        "overall": overall, "expect": expect,
        "false_ineligible": overall == "core_unmet" and expect != "core_unmet",
        "false_eligible": sorted(core_id for core_id, verdict in broken.items() if verdict == "core_met"),
        "broken": broken, "core": score["core"],
        "wrong": [f"{w['type']} {w['value']}" for w in score["wrong"]],
        "requirements": [{"type": r.type, "value": r.value, "group": r.group_operator, "key": r.requirement_key,
                          "tier": requirement_tier(r), "judgment": status.get(r.requirement_key),
                          "raw": " ".join((r.raw or "").split())[:200]} for r in result.requirements],
        "blocking_gaps": [{"reason": g.reason, "raw": " ".join((g.raw or "").split())[:200]}
                          for g in result.coverage.gaps if g not in result.coverage.checklist_gaps],
    }


def summarize(rows: list[dict]) -> dict:
    counter: Counter = Counter()
    for row in rows:
        if "error" in row:
            counter["errors"] += 1
            continue
        counter["runs"] += 1
        counter[f"overall_{row['overall']}"] += 1
        counter["core"] += len(row["core"])
        counter["core_found"] += sum(v == "찾음" for v in row["core"].values())
        counter["false_ineligible"] += row["false_ineligible"]
        counter["broken_checked"] += len(row["broken"])
        counter["false_eligible"] += len(row["false_eligible"])
        counter["eligible_as_expected"] += row["overall"] == row["expect"]
    return dict(counter)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", type=Path, nargs="*", help="정답 파일. 없으면 표본 폴더의 labels*.json 전부")
    parser.add_argument("--only", nargs="*", help="이 공고만")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--model", default="gpt-6-luna")
    parser.add_argument("--memory", type=Path, help="조항 답 기억 파일(이어 쓴다)")
    parser.add_argument("--baseline", type=Path, help="비교할 이전 결과(jsonl)")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--no-limits", action="store_true", help="나라장터 면허제한·참가가능지역 없이(문서만으로) 잰다")
    args = parser.parse_args()

    label_paths = args.labels or sorted(SAMPLE.glob("labels*.json"))
    labels = load_labels(label_paths)
    notices, changed = load_sample(SAMPLE)
    versions = {v.label: v for v in [*notices, *(v for chain in changed for v in chain)]}
    targets = [key for key in labels if key in versions and (not args.only or key in args.only)]
    missing = sorted(set(labels) - set(versions))

    memories = None
    if args.memory:
        stored = json.loads(args.memory.read_text(encoding="utf-8")) if args.memory.exists() else {}
        memories = {kind: FileMemory(stored.get(kind)) for kind in ("labeling", "selection", "polarity", "gap_summary")}

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("", encoding="utf-8")
    lock = threading.Lock()
    rows: list[dict] = []

    def work(key: str) -> None:
        for run in range(1, args.runs + 1):
            try:
                row = run_one(versions[key], labels[key], run, args.model, memories, not args.no_limits)
            except Exception as error:  # noqa: BLE001 - 한 공고의 실패가 전체 측정을 멈추지 않게
                row = {"label": key, "run": run, "error": repr(error)[:300]}
            with lock:
                rows.append(row)
                with args.out.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
            danger = []
            if row.get("false_ineligible"):
                danger.append("틀린 부적합")
            if row.get("false_eligible"):
                danger.append("틀린 충족 " + ",".join(row["false_eligible"]))
            print(f"{key[7:]} r{run} {row.get('overall', row.get('error'))} {' / '.join(danger)}", flush=True)

    with ThreadPoolExecutor(args.workers) as pool:
        list(pool.map(work, targets))

    if memories is not None:
        args.memory.write_text(json.dumps({k: dict(v) for k, v in memories.items()}, ensure_ascii=False), encoding="utf-8")

    summary = summarize(rows)
    print("\n== 요약 ==", json.dumps(summary, ensure_ascii=False))
    if missing:
        print("표본에 없는 정답 공고:", len(missing))
    print("\n== 위험한 틀림 ==")
    for row in sorted(rows, key=lambda r: (r["label"], r["run"])):
        if row.get("false_ineligible") or row.get("false_eligible"):
            print(f"  {row['label'][7:]} r{row['run']} 판정 {row['overall']} 틀린 충족 {row['false_eligible']} 오답 {row['wrong'][:3]}")
    if args.baseline and args.baseline.exists():
        before = {}
        for line in args.baseline.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if "error" not in row:
                before.setdefault(row["label"], []).append(row["overall"])
        print("\n== 이전과 달라진 종합 판정 ==")
        for row in sorted(rows, key=lambda r: r["label"]):
            if "error" in row or row["run"] != 1 or row["label"] not in before:
                continue
            if before[row["label"]][0] != row["overall"]:
                print(f"  {row['label'][7:]} {before[row['label']][0]} → {row['overall']} (기대 {row['expect']})")


if __name__ == "__main__":
    main()
