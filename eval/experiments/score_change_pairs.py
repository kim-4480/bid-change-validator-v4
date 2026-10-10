"""변경공고 차수 쌍을 정답(expected_changes.json)으로 채점한다. 모델을 부르지 않는다.

    python eval/experiments/score_change_pairs.py --sample eval/golden/notice-changes-30d artifacts/chg30_mem.json

입력은 polarity_guard_probe 의 --out 파일(차수마다 3회 분석한 요건). 바뀐 쌍은 기대한 변경을 몇 개 잡았는지,
안 바뀐 쌍은 '변경 없음' 이 나왔는지, 정답에 없는 변경(오탐)이 몇 건인지, 3회 결과가 같은지 본다.
"""
import argparse, json
from pathlib import Path
from bidengine.contracts import QualificationRequirement
from bidengine.diff.requirement_diff import diff_requirements

parser = argparse.ArgumentParser()
parser.add_argument("--sample", type=Path, required=True)
parser.add_argument("runs", nargs="+")
args = parser.parse_args()
SAMPLE = args.sample
EXPECTED = {(p["before"], p["after"]): {(c["kind"], c["type"], c["value"]) for c in p["changes"]}
            for p in json.load(open(SAMPLE / "expected_changes.json", encoding="utf-8"))["pairs"]}

def describe(c):
    req = c.current or c.baseline
    return f"{c.change_type} {req.type} {req.value}" + (f" ← {c.baseline.value}" if c.change_type == "MODIFIED" else "")

def hit(c, exp):
    kind, typ, frag = exp
    if (c.current or c.baseline).type != typ:
        return False
    if kind == "CHANGED":
        return c.change_type in {"MODIFIED", "ADDED"} and str((c.current or c.baseline).value) == frag
    if c.change_type == "MODIFIED":
        return frag in str(c.baseline.value if kind == "REMOVED" else c.current.value)
    return c.change_type == kind and frag in str((c.current if kind == "ADDED" else c.baseline).value)

manifest = json.load(open(SAMPLE / "manifest.json", encoding="utf-8"))
pairs = [(a["dir"], b["dir"]) for c in manifest["changed"] for a, b in zip(c["versions"], c["versions"][1:])]
for path in args.runs:
    runs = json.load(open(path, encoding="utf-8"))["runs"]
    by = {}
    for r in runs:
        if "error" not in r:
            by.setdefault(r["version"], {})[r["run"]] = [QualificationRequirement.model_validate(x) for x in r["requirements"]]
    found = total_exp = false_changes = clean_pairs = clean_total = 0
    same_across_runs = 0
    print(f"\n==== {path}")
    for a, b in pairs:
        exp = EXPECTED.get((a, b), set())
        sigs = []
        for i in range(3):
            changes = [c for c in diff_requirements(by[a][i], by[b][i]) if c.change_type != "UNCHANGED"]
            matched = {e for e in exp if any(hit(c, e) for c in changes)}
            extra = [c for c in changes if not any(hit(c, e) for e in exp)]
            found += len(matched); total_exp += len(exp); false_changes += len(extra)
            if not exp:
                clean_total += 1; clean_pairs += not changes
            sigs.append(frozenset(describe(c) for c in changes))
            if i == 0:
                print(f"  {a}→{b[-3:]} {'[바뀜]' if exp else '[안 바뀜]'} 잡음 {len(matched)}/{len(exp)}, 오탐 {len(extra)} | "
                      + "; ".join(sorted(describe(c) for c in changes))[:300])
        same_across_runs += len(set(sigs)) == 1
    print(f"  ▶ 실제 변경 탐지 {found}/{total_exp} ({found/total_exp:.2f}), 안 바뀐 쌍에서 '변경 없음' {clean_pairs}/{clean_total}, "
          f"오탐 변경 {false_changes}건(쌍·회 합계), 3회 결과가 같은 쌍 {same_across_runs}/{len(pairs)}")
