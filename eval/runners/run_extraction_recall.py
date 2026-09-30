"""골든셋 20공고에서 정답 요건이 추출 단계를 통과해 판정기에 도달하는지 잰다.

    골든셋 정답 요건 ──┐
                        ├─ 대조 → REACHED / DROPPED(사유) / UNMAPPED / MISSED
    제품 추출 결과   ──┘

골든 러너가 판정기에 정답을 직접 넣고 잰 것과 달리, 여기는 **제품 추출이 정답을
판정기까지 넘기는가**를 잰다. 그 구간이 비어 있었고, 실제 실패가 거기서 났다.

두 가지 출처
------------
--source db    공용 DB 에 이미 있는 분석 실행을 읽는다. LLM 을 부르지 않는다. 0원.
               제품이 실제로 낸 결과라 가장 정직하지만, 공고마다 실행 횟수가 다르다.
--source live  파이프라인을 직접 돌린다. DB 에 쓰지 않는다. 공고 수 × 반복 만큼 LLM 콜.
               같은 조건으로 20건을 N 번 돌려 분산까지 본다.

같은 공고를 여러 번 돌린 결과는 평균내지 않고 실행별로 남긴다. 추출은 매번 다르다 —
R26BK01634263 은 4번 중 요건 1건/0건/1건/0건이었다. "평균 0.5건" 은 아무것도 말해
주지 않는다.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import sys
from datetime import datetime
from datetime import timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

from bideval.extraction_recall import (  # noqa: E402
    GoldenRequirement,
    place_requirements,
    unmapped_raws_from_diagnostics,
)


def load_env(env_file: Path) -> None:
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key and value and key not in os.environ:
            os.environ[key] = value


def golden_by_version(bundle_path: Path) -> dict[str, dict]:
    """notice_version_id -> {source_id, title, requirements[]}. 같은 공고의 케이스는 요건이 같다."""
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    for case in bundle["cases"]:
        vid = case["notice_version_id"]
        if vid in out:
            continue
        out[vid] = {
            "source_id": case["source_id"],
            "notice_no": case["notice_no"],
            "title": case["title"],
            "requirements": [
                GoldenRequirement(
                    key=item["requirement"]["requirement_key"].split(":", 1)[-1],
                    type=item["requirement"]["type"],
                    raw=item["requirement"].get("raw") or "",
                    value=item["requirement"].get("value"),
                )
                for item in case["canonical_inputs"]
            ],
        }
    return out


def results_from_db(db, version_id: str, limit: int) -> list[dict]:
    """공용 DB 의 분석 실행을 그대로 읽는다. 최신순 limit 개."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.analysis_models import QualificationAnalysisRun

    runs = db.scalars(
        select(QualificationAnalysisRun)
        .where(QualificationAnalysisRun.notice_version_id == version_id)
        .options(selectinload(QualificationAnalysisRun.requirements))
        .order_by(QualificationAnalysisRun.created_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "run_id": str(run.id),
            "status": run.status,
            "extracted": [
                {"raw": r.raw, "type": r.type, "value": getattr(r, "value", None)}
                for r in run.requirements
            ],
            "dropped": list(run.dropped_requirements or []),
            "diagnostics": list(run.diagnostics or []),
        }
        for run in runs
    ]


def results_live(db, version_id: str, runs: int) -> list[dict]:
    """파이프라인을 직접 돌린다. DB 에 쓰지 않는다."""
    from bidengine.providers.openai import OpenAIStructuredExtractor
    from bidengine.pipeline.analysis_pipeline import analyze_qualification_documents
    from app.models import BidNoticeVersion
    from app.qualification.analysis import build_qualification_analysis_input
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    version = db.scalar(
        select(BidNoticeVersion)
        .where(BidNoticeVersion.id == version_id)
        .options(selectinload(BidNoticeVersion.documents))
    )
    if version is None:
        return []
    extractor = OpenAIStructuredExtractor()
    if not extractor.available:
        raise SystemExit("OPENAI_API_KEY 가 없습니다. --source db 로 돌리거나 키를 환경변수에 넣으세요.")
    analysis_input = build_qualification_analysis_input(version)
    out = []
    for _ in range(runs):
        result = analyze_qualification_documents(analysis_input, structured_extract=extractor)
        out.append({
            "run_id": None,
            "status": result.status,
            "extracted": [
                {"raw": r.raw, "type": r.type, "value": r.value} for r in result.requirements
            ],
            "dropped": [d.model_dump(mode="json") for d in result.dropped_requirements],
            "diagnostics": [d.model_dump(mode="json") for d in result.diagnostics],
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--golden-root", type=Path, required=True)
    ap.add_argument("--source", choices=["db", "live"], default="db")
    ap.add_argument("--runs", type=int, default=3, help="공고당 실행 수 (db: 최신 N개, live: N번 호출)")
    ap.add_argument("--limit", type=int, default=0, help="공고 수 제한 (0=전체 20)")
    ap.add_argument("--only", default=None, help="source_id 하나만 (예: 01634263-003)")
    ap.add_argument("--env-file", type=Path, default=REPO_ROOT / ".env")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    load_env(args.env_file)
    from app.database import SessionLocal

    golden = golden_by_version(args.golden_root / "fixture_bundle.json")
    items = list(golden.items())
    if args.only:
        items = [(v, g) for v, g in items if g["source_id"] == args.only]
    if args.limit:
        items = items[: args.limit]

    db = SessionLocal()
    records = []
    try:
        for version_id, info in items:
            runs = (
                results_from_db(db, version_id, args.runs)
                if args.source == "db"
                else results_live(db, version_id, args.runs)
            )
            if not runs:
                print(f"  {info['source_id']:<16} (분석 실행 없음)")
                continue
            for index, run in enumerate(runs):
                recall = place_requirements(
                    info["source_id"],
                    info["requirements"],
                    extracted=run["extracted"],
                    dropped=run["dropped"],
                    unmapped_raws=unmapped_raws_from_diagnostics(run["diagnostics"]),
                )
                counts = {o: recall.count(o) for o in ("REACHED", "DROPPED", "UNMAPPED", "MISSED")}
                records.append({
                    "source_id": info["source_id"],
                    "notice_no": info["notice_no"],
                    "title": info["title"],
                    "run_index": index,
                    "run_id": run["run_id"],
                    "analysis_status": run["status"],
                    "golden_total": len(info["requirements"]),
                    **counts,
                    "extras": len(recall.extras),
                    "placements": [p.__dict__ for p in recall.placements],
                    "extra_raws": recall.extras[:5],
                })
                print(
                    f"  {info['source_id']:<16} run{index}  {run['status']:<8} "
                    f"골든 {len(info['requirements'])}  도달 {counts['REACHED']}  "
                    f"버림 {counts['DROPPED']}  미분류 {counts['UNMAPPED']}  놓침 {counts['MISSED']}  "
                    f"추가 {len(recall.extras)}",
                    flush=True,
                )
    finally:
        db.close()

    if not records:
        raise SystemExit("잰 것이 없습니다.")

    golden_rows = sum(r["golden_total"] for r in records)
    by_outcome = collections.Counter()
    by_type_outcome = collections.Counter()
    drop_reasons = collections.Counter()
    for r in records:
        for p in r["placements"]:
            by_outcome[p["outcome"]] += 1
            by_type_outcome[(p["type"], p["outcome"])] += 1
            if p["outcome"] == "DROPPED":
                drop_reasons[p["reason_code"]] += 1

    # 공고별로 "한 번이라도 전부 도달한 실행이 있었나" — 분산을 보는 가장 짧은 지표
    per_notice = collections.defaultdict(list)
    for r in records:
        per_notice[r["source_id"]].append((r["REACHED"], r["golden_total"]))
    fully_reached_some_run = sum(1 for runs in per_notice.values() if any(a == b for a, b in runs))
    fully_reached_every_run = sum(1 for runs in per_notice.values() if all(a == b for a, b in runs))

    summary = {
        "source": args.source,
        "notices": len(per_notice),
        "runs": len(records),
        "golden_requirement_rows": golden_rows,
        "outcome": dict(by_outcome),
        "reach_rate": round(by_outcome["REACHED"] / golden_rows, 3) if golden_rows else None,
        "drop_reasons": dict(drop_reasons),
        "by_type": {
            t: {o: by_type_outcome[(t, o)] for o in ("REACHED", "DROPPED", "UNMAPPED", "MISSED")}
            for t in sorted({p["type"] for r in records for p in r["placements"]})
        },
        "notices_fully_reached_in_some_run": fully_reached_some_run,
        "notices_fully_reached_in_every_run": fully_reached_every_run,
        "extras_total": sum(r["extras"] for r in records),
    }

    out_dir = args.out or (args.golden_root / "results")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"extraction_recall_{args.source}_{stamp}.json"
    path.write_text(json.dumps({"executed_at": stamp, "summary": summary, "records": records},
                               ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n-> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
