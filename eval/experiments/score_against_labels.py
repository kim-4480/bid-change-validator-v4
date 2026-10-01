"""표본에 붙인 정답(labels.json)으로 추출 결과를 채점한다. 모델을 부르지 않는다.

    python eval/experiments/score_against_labels.py --labels eval/golden/notice-sample-20261001/labels.json \
        --runs artifacts/polarity_guard.json

sample_compare.py 와 hybrid_selection_probe.py 의 지표는 "다시 돌려도 같은가" 만 잰다. 틀린 결과를 한결같이
내도 점수가 좋다. 여기서는 "맞는가" 를 잰다.

채점 (labels.json 의 policy 와 같다)
  - core     : 유형과 값이 모두 맞는 요건이 있으면 찾음. 대안(values 여럿)은 값이 모두 있고 ANY_OF 로 묶여야 찾음,
               일부만 있거나 묶이지 않았으면 부분.
  - 배제     : exclusion 인 core 는 배제로 담겨야(scope.restriction=EXCLUDE) 찾음이다. 같은 값을 요구로 확정했으면
               **뒤집힌 확정** — 가장 나쁜 오류라 따로 센다.
  - confirm  : 그 조항이 커버리지 공백이나 복합 조건으로 남았으면 확인 필요(맞음), 단순 요건으로 나왔으면 단정.
               실행 결과에 공백이 저장돼 있지 않으면(예전 러너) 요건 목록만 보고, 없으면 '없음' 이다.
  - 오답     : 어느 core 에도 맞지 않는 요건. 공통·조건부 항목에서 나온 것은 세지 않는다.
  - 중복     : 이미 찾은 core 값을 다시 낸 요건.
  - 경로     : 찾은 core 가 낱말 가드를 그냥 통과했는지(code), 극성으로 가드를 풀어 나왔는지(model_polarity).
"""
from __future__ import annotations

import argparse
import json
import re
import statistics as st
from collections import Counter, defaultdict
from pathlib import Path

NEUTRAL_REASONS = {"common", "conditional", "detail"}


def _norm(value: object) -> str:
    return re.sub(r"[\s\[\]「」｢｣()（）:：,.·ㆍ]", "", str(value if value is not None else ""))


def _number(value: object) -> float | None:
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def _value_matches(requirement: dict, key: str) -> bool:
    value = requirement.get("value")
    number, wanted = _number(value), _number(key)
    if number is not None and wanted is not None:
        return number == wanted
    scope = requirement.get("scope") or {}
    haystack = _norm(value) + "|" + _norm(scope.get("industry_name")) + "|" + _norm(scope.get("industry_code"))
    return _norm(key) in haystack


def score_run(run: dict, label: dict) -> dict:
    requirements = run["requirements"]
    core = {item["id"]: {"hit": set(), "any_of": True, "basis": set(), "inverted": False} for item in label["core"]}
    confirm = {item["id"]: "없음" for item in label["confirm"]}
    wrong, duplicates = [], 0
    for requirement in requirements:
        raw = _norm(requirement.get("raw"))
        scope = requirement.get("scope") or {}
        matched = False
        for item in label["core"]:
            if requirement["type"] != item["type"]:
                continue
            if "period_months" in item and requirement.get("period_months") not in (item["period_months"], None):
                continue
            keys = [*item["values"], *item.get("names", [])]
            hit = next((index % len(item["values"]) for index, key in enumerate(keys) if _value_matches(requirement, key)), None)
            if hit is None and any(_value_matches(requirement, key) for key in item.get("also_accept", [])):
                hit = 0
            if hit is None:
                continue
            state = core[item["id"]]
            if item.get("exclusion") and scope.get("restriction") != "EXCLUDE":
                # 배제 조건을 요구로 확정했다. 확인 필요(복합)로 둔 것은 뒤집힌 것이 아니다.
                if requirement.get("condition_complexity") != "composite":
                    state["inverted"] = True
                matched = True
                break
            if hit in state["hit"]:
                duplicates += 1
            state["hit"].add(hit)
            state["basis"].add(scope.get("guard_basis") or "code")
            if len(item["values"]) > 1 and requirement.get("group_operator") != "ANY_OF":
                state["any_of"] = False
            matched = True
            break
        if matched:
            continue
        item = next((c for c in label["confirm"] if _norm(c["phrase"]) in raw), None)
        if item is not None:
            marked = requirement.get("condition_complexity") == "composite"
            confirm[item["id"]] = "확인 필요" if marked and confirm[item["id"]] != "단정" else "단정"
            continue
        excluded = next((e for e in label["excluded"] if _norm(e["phrase"]) in raw
                         and requirement["type"] in e.get("types", [requirement["type"]])), None)
        if excluded is not None and excluded["reason"] in NEUTRAL_REASONS:
            continue
        wrong.append({"type": requirement["type"], "value": str(requirement.get("value"))[:40],
                      "why": excluded["reason"] if excluded else "unlabelled"})
    for gap in run.get("gaps") or []:
        raw = _norm(gap.get("raw"))
        for item in label["confirm"]:
            if _norm(item["phrase"]) in raw and confirm[item["id"]] == "없음":
                confirm[item["id"]] = "확인 필요"
    status, basis = {}, {}
    for item in label["core"]:
        state = core[item["id"]]
        if state["inverted"]:
            status[item["id"]] = "뒤집힘"
        elif len(state["hit"]) == len(item["values"]) and (len(item["values"]) == 1 or state["any_of"]):
            status[item["id"]] = "찾음"
            basis[item["id"]] = "model_polarity" if "model_polarity" in state["basis"] else "code"
        elif state["hit"]:
            status[item["id"]] = "부분"
        else:
            status[item["id"]] = "놓침"
    return {"core": status, "basis": basis, "confirm": confirm, "wrong": wrong, "duplicates": duplicates}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--runs", type=Path, nargs="+", required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    labels = json.loads(args.labels.read_text(encoding="utf-8"))["notices"]
    report = {}
    for path in args.runs:
        runs = json.loads(path.read_text(encoding="utf-8"))["runs"]
        by_mode: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
        for run in runs:
            if "error" not in run and run["version"] in labels:
                by_mode[run["mode"]][run["version"]].append(score_run(run, labels[run["version"]]))
        for mode, by_version in by_mode.items():
            total_core = sum(len(labels[version]["core"]) for version in by_version)
            per_label, confirm, wrong, basis = {}, {}, Counter(), Counter()
            found_per_run: dict[int, int] = defaultdict(int)
            inverted_per_run: dict[int, int] = defaultdict(int)
            wrong_per_run: dict[int, int] = defaultdict(int)
            duplicates_per_run: dict[int, int] = defaultdict(int)
            confirm_ok_per_run: dict[int, int] = defaultdict(int)
            for version, scores in by_version.items():
                for index, score in enumerate(scores):
                    found_per_run[index] += sum(value == "찾음" for value in score["core"].values())
                    inverted_per_run[index] += sum(value == "뒤집힘" for value in score["core"].values())
                    wrong_per_run[index] += len(score["wrong"])
                    duplicates_per_run[index] += score["duplicates"]
                    confirm_ok_per_run[index] += sum(value == "확인 필요" for value in score["confirm"].values())
                    basis.update(score["basis"].values())
                    for item in score["wrong"]:
                        wrong[(version, item["type"], item["value"], item["why"])] += 1
                for item in labels[version]["core"]:
                    per_label[item["id"]] = [score["core"][item["id"]] for score in scores]
                for item in labels[version]["confirm"]:
                    confirm[item["id"]] = [score["confirm"][item["id"]] for score in scores]
            report[f"{path.stem}/{mode}"] = {
                "notices": len(by_version),
                "core_total": total_core,
                "core_found_mean": round(st.mean(found_per_run.values()), 2),
                "core_recall": round(st.mean(found_per_run.values()) / total_core, 3),
                "core_found_every_run": sum(all(v == "찾음" for v in values) for values in per_label.values()),
                "core_never_found": sum(all(v != "찾음" for v in values) for values in per_label.values()),
                "inverted_per_run_mean": round(st.mean(inverted_per_run.values()), 2),
                "wrong_per_run_mean": round(st.mean(wrong_per_run.values()), 2),
                "duplicates_per_run_mean": round(st.mean(duplicates_per_run.values()), 2),
                "confirm_total": len(confirm),
                "confirm_ok_mean": round(st.mean(confirm_ok_per_run.values()), 2),
                "found_by": dict(basis),
                "per_label": per_label,
                "confirm": confirm,
                "wrong": [{"version": k[0], "type": k[1], "value": k[2], "why": k[3], "runs": n} for k, n in sorted(wrong.items())],
            }
    if args.out:
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    for name, row in report.items():
        print(f"\n== {name}: 공고 {row['notices']}건, 핵심 요건 {row['core_found_mean']}/{row['core_total']} "
              f"(재현율 {row['core_recall']}), 매번 찾음 {row['core_found_every_run']}, 한 번도 못 찾음 {row['core_never_found']}, "
              f"뒤집힌 확정 {row['inverted_per_run_mean']}건/회, 오답 {row['wrong_per_run_mean']}건/회, "
              f"중복 {row['duplicates_per_run_mean']}건/회, 확인 필요 {row['confirm_ok_mean']}/{row['confirm_total']}, 경로 {row['found_by']}")
        print("   " + "  ".join(f"{label}:{''.join(v[0] for v in values)}" for label, values in row["per_label"].items()))
        print("   확인 필요: " + "  ".join(f"{label}:{'/'.join(values)}" for label, values in row["confirm"].items()))


if __name__ == "__main__":
    main()
