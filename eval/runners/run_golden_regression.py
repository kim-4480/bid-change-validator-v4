"""골든셋 v0.2 로 판정 코드의 회귀를 잰다. CI 에서 매 PR 마다 돈다.

무엇을 재나
-----------
frozen fixture(eval/golden/qualification-v0.2) 의 케이스 40건에 대해
`rules.judge_requirements` 를 돌리고, 행마다 넷 중 하나로 분류한다.

    MATCH_DRAFT_TARGET          초안 기대값 일치
    SAFE_ABSTENTION             UNKNOWN 으로 보류 (안전)
    WRONG_DETERMINATE_POSITIVE  틀린 확정 — 충족이라 했는데 아님
    WRONG_DETERMINATE_NEGATIVE  틀린 확정 — 미달이라 했는데 아님

게이트는 둘이다. **잘못된 확정은 0 이어야 하고, 초안 기대값 일치는 summary.json 에
적힌 기준선 아래로 내려가면 안 된다.** 보류 자체에 별도 상한을 두지는 않지만,
기준 일치가 UNKNOWN 으로 바뀌어 일치 수가 하락하는 회귀는 막는다.

무엇을 재지 않나
---------------
추출 단계는 재지 않는다. 이 실행기는 골든셋의 canonical 요건을 판정 코드에 직접 넣는다.
제품이 실제로 그 요건을 추출해 내는지는 `run_extraction_recall.py --source live` 가
재고, 그것은 DB 와 OPENAI_API_KEY 가 필요해 CI 에 넣지 않았다. #128 에서 배운 것이
바로 이 구간이 비어 있으면 "오답 0" 이 제품을 보증하지 않는다는 것이므로, 두 숫자를
같이 읽어야 한다.

결과 파일
---------
상세 결과(행 단위)는 --out 으로 쓰고 CI 는 그것을 artifact 로 올린다. 리포에는
summary.json 의 기준선과 fixture 의 sha256 만 남긴다 — 상세 결과를 Git 에 쌓지 않는다.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sys
from datetime import date
from datetime import datetime
from datetime import timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_DIR = REPO_ROOT / "eval" / "golden" / "qualification-v0.2"
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_checksums(golden_dir: Path) -> None:
    """checksums·summary와 실제 fixture가 다르면 멈춘다."""
    expected = {}
    for line in (golden_dir / "checksums.sha256").read_text(encoding="utf-8").splitlines():
        # sha256sum 은 "<digest>  name" 또는 바이너리 모드 "<digest> *name" 으로 쓴다.
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            continue
        digest, name = parts
        expected[name.lstrip("*").strip()] = digest.strip()
    for name, digest in expected.items():
        actual = sha256_of(golden_dir / name)
        if actual != digest:
            raise SystemExit(
                f"골든셋 파일이 checksums.sha256 과 다릅니다: {name}\n"
                f"  기록 {digest[:16]}… / 실제 {actual[:16]}…\n"
                "fixture 를 바꿨다면 checksums.sha256 과 summary.json 을 함께 갱신하세요."
            )

    fixture_path = golden_dir / "fixture_bundle.json"
    summary_path = golden_dir / "summary.json"
    if not summary_path.is_file():
        raise SystemExit("골든셋 summary.json 이 없습니다.")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    actual_fixture_sha = sha256_of(fixture_path)
    summary_fixture_sha = summary.get("fixture_sha256")
    if summary_fixture_sha != actual_fixture_sha:
        raise SystemExit(
            "summary.json 의 fixture_sha256 이 실제 fixture_bundle.json 과 다릅니다:\n"
            f"  summary {str(summary_fixture_sha)[:16]}… / 실제 {actual_fixture_sha[:16]}…\n"
            "fixture 를 바꿨다면 checksums.sha256 과 summary.json 을 함께 갱신하세요."
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--golden-dir", type=Path, default=GOLDEN_DIR)
    ap.add_argument("--out", type=Path, default=None, help="상세 결과 JSON (CI 는 artifact 로 올림)")
    ap.add_argument("--no-gate", action="store_true", help="게이트를 걸지 않고 결과만 낸다")
    args = ap.parse_args()

    verify_checksums(args.golden_dir)
    bundle = json.loads((args.golden_dir / "fixture_bundle.json").read_text(encoding="utf-8"))
    summary_path = args.golden_dir / "summary.json"
    gate = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.is_file() else None

    from bidengine import contracts
    from bidengine.judgment import rules

    rows: list[dict] = []
    overall: list[dict] = []
    fatal: list[str] = []
    for case in bundle["cases"] + bundle.get("previous_cases", []):
        try:
            requirements = [
                contracts.QualificationRequirement.model_validate(item["requirement"])
                for item in case["canonical_inputs"]
            ]
            profile = rules.CompanyProfileSnapshot.model_validate(case["profile"])
            result = rules.judge_requirements(
                requirements,
                profile,
                preflight_case_id=case["case_id"],
                reference_date=date.fromisoformat(case["reference_date"]),
                analysis_status=case["analysis_status"],
            )
        except Exception as error:  # noqa: BLE001 - 한 케이스의 예외가 전체를 멈추면 안 된다
            fatal.append(f"{case['case_id']}: {error!r}")
            continue

        expected_by_key = {
            item["requirement"]["requirement_key"]: item for item in case["canonical_inputs"]
        }
        for judgment in result.judgments:
            target = expected_by_key[judgment.requirement_key]
            expected = target["semantic_expected"]
            if judgment.status == expected:
                category = "MATCH_DRAFT_TARGET"
            elif judgment.status == "UNKNOWN":
                category = "SAFE_ABSTENTION"
            elif judgment.status == "SATISFIED":
                category = "WRONG_DETERMINATE_POSITIVE"
            else:
                category = "WRONG_DETERMINATE_NEGATIVE"
            rows.append({
                "case_id": case["case_id"],
                "requirement_key": judgment.requirement_key,
                "type": target["requirement"]["type"],
                "mapping": target["mapping"],
                "expected": expected,
                "actual": judgment.status,
                "reason_code": judgment.reason_code,
                "category": category,
            })
        overall.append({
            "case_id": case["case_id"],
            "expected_overall": case["expected_safe_overall"],
            "actual_overall": result.overall_status,
            "match": result.overall_status == case["expected_safe_overall"],
        })

    counts = collections.Counter(row["category"] for row in rows)
    wrong = counts["WRONG_DETERMINATE_POSITIVE"] + counts["WRONG_DETERMINATE_NEGATIVE"]
    report = {
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "fixture_sha256": sha256_of(args.golden_dir / "fixture_bundle.json"),
        "case_count": len(overall),
        "row_count": len(rows),
        "categories": dict(counts),
        "wrong_determinate": wrong,
        "overall_match": sum(1 for item in overall if item["match"]),
        "fatal_errors": fatal,
        "rows": rows,
        "overall": overall,
    }
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({k: v for k, v in report.items() if k not in ("rows", "overall")},
                     ensure_ascii=False, indent=2))

    if args.no_gate or gate is None:
        return 1 if fatal else 0

    # 게이트 값은 summary.json 의 "gate" 블록에서 읽는다. "baseline" 은 기록이지 문턱이 아니다 —
    # 둘을 섞으면 기록만 고치고 문턱이 안 바뀌거나 그 반대가 된다.
    thresholds = gate["gate"]
    wrong_limit = int(thresholds["wrong_determinate_must_be"])
    baseline_match = int(thresholds["match_must_be_at_least"])
    failures = []
    if fatal:
        failures.append(f"실행 오류 {len(fatal)}건")
    if wrong > wrong_limit:
        failures.append(f"잘못된 확정 {wrong}건 ({wrong_limit} 이어야 함)")
    if counts["MATCH_DRAFT_TARGET"] < baseline_match:
        failures.append(f"초안 기대값 일치 {counts['MATCH_DRAFT_TARGET']} < 기준선 {baseline_match}")
    if failures:
        print("\n[골든셋 회귀] " + " / ".join(failures))
        return 1
    print(
        f"\n[골든셋 회귀] 통과 — 초안 기대값 일치 {counts['MATCH_DRAFT_TARGET']} "
        f"(기준선 {baseline_match}), "
        f"보류 {counts['SAFE_ABSTENTION']}, 잘못된 확정 0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
