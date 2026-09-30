"""실공고 문서로 LLM 추출을 실제로 돌려 안정성과 형식 민감도를 잰다 (ADR 0001 문제 1·6, S0 예비).

    OPENAI_API_KEY=... python eval/experiments/live_extraction_probe.py --runs 3 --out result.json

qualification-real-v0.1 에서 HWP/HWPX 와 PDF 가 함께 있는 공고문마다
  - 같은 형식을 --runs 번 돌려 요건 집합이 얼마나 같은지(안정성),
  - HWP/HWPX 와 PDF 결과가 얼마나 같은지(형식 민감도)
를 요건 서명(type, operator, value, 기간, 분야/역할/종류)의 집합으로 비교한다. raw 는 서명에
넣지 않는다 — 인용 경계 흔들림(문제 2)과 섞이지 않게 하려는 것이다.

DB 는 쓰지 않는다. 호출 수는 (공고 수 × 형식 2 × runs) 이다.
"""
from __future__ import annotations

import argparse
from collections import Counter
import itertools
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from bidengine.pipeline.analysis_pipeline import (
    QualificationAnalysisInput,
    QualificationDocumentInput,
    analyze_qualification_documents,
)
from bidengine.providers.openai import OpenAIStructuredExtractor

ROOT = Path(__file__).resolve().parents[2]
REAL = ROOT / "eval" / "golden" / "qualification-real-v0.1"
OPEN_VOCAB_KEYS = ("experience_field", "role", "client_requirement", "issuer")


def _pairs() -> list[tuple[str, str, dict, dict]]:
    out = []
    for case_dir in sorted((REAL / "cases").iterdir()):
        case = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
        by_stem: dict[str, dict] = {}
        for doc in case["documents"]:
            if not doc.get("blocks"):
                continue
            stem, _, ext = doc["name"].rpartition(".")
            by_stem.setdefault(stem, {})[ext.lower()] = doc
        for stem, formats in by_stem.items():
            native = formats.get("hwpx") or formats.get("hwp")
            if native and formats.get("pdf"):
                out.append((case["case_id"], stem, native, formats["pdf"]))
    return out


def _blocks(doc: dict) -> list[dict]:
    raw = json.loads((REAL / doc["blocks"]["path"]).read_text(encoding="utf-8"))
    return raw if isinstance(raw, list) else raw.get("blocks", [])


def _signature(req) -> tuple:
    scope = req.scope or {}
    detail = tuple(
        (k, str(scope.get(k))) for k in ("experience_field", "role", "kind", "client_requirement", "restriction")
        if scope.get(k) not in (None, "")
    )
    return (req.type, req.operator, str(req.value), req.period_months, req.requirement_role, detail)


def _run(case_id: str, label: str, doc: dict, run: int, extractor: OpenAIStructuredExtractor) -> dict:
    analysis_input = QualificationAnalysisInput(
        notice_id=case_id,
        notice_version_id=f"{case_id}-{label}",
        documents=[QualificationDocumentInput(document_id=doc["document_key"], extracted_blocks=_blocks(doc))],
    )
    started = time.monotonic()
    try:
        result = analyze_qualification_documents(analysis_input, structured_extract=extractor)
    except Exception as error:  # noqa: BLE001 - 한 실행의 실패가 전체를 멈추면 안 된다
        return {"case": case_id, "format": label, "run": run, "error": repr(error)[:300]}
    requirements = list(result.requirements)
    return {
        "case": case_id,
        "format": label,
        "run": run,
        "seconds": round(time.monotonic() - started, 1),
        "status": result.status,
        "requirement_count": len(requirements),
        "dropped": len(result.dropped_requirements),
        "diagnostics": dict(sorted(Counter(d.code for d in result.diagnostics).items())),
        "signatures": sorted(json.dumps(_signature(r), ensure_ascii=False) for r in requirements),
        "open_vocabulary_requirements": sum(
            1 for r in requirements
            if any((r.scope or {}).get(k) for k in OPEN_VOCAB_KEYS)
            or (r.type == "REGISTRATION_CERTIFICATION" and not str(r.value or "").isdigit())
        ),
        "types": sorted({r.type for r in requirements}),
        "coverage": result.coverage.model_dump(exclude={"gaps"}) if result.coverage else None,
        "coverage_gaps": [g.model_dump() for g in result.coverage.gaps] if result.coverage else [],
        "fingerprint": extractor.last_system_fingerprint,
        "requirements": [
            {"type": r.type, "operator": r.operator, "value": r.value, "scope": r.scope, "raw": r.raw[:160]}
            for r in requirements
        ],
    }


def _jaccard(a: set, b: set) -> float:
    # 둘 다 비었으면 같은 결과(요건 0개)로 본다.
    return round(len(a & b) / len(a | b), 3) if a | b else 1.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--only", nargs="*", help="case id 목록")
    args = parser.parse_args()
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY 가 필요합니다.")

    pairs = [p for p in _pairs() if not args.only or p[0] in args.only]
    jobs = [
        (case_id, label, doc, run)
        for case_id, _stem, native, pdf in pairs
        for label, doc in (("native", native), ("pdf", pdf))
        for run in range(args.runs)
    ]
    extractors = [OpenAIStructuredExtractor() for _ in range(args.workers)]
    print(f"model={extractors[0].model} temperature={extractors[0].temperature} seed={extractors[0].seed} calls={len(jobs)}")
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [
            pool.submit(_run, case_id, label, doc, run, extractors[i % args.workers])
            for i, (case_id, label, doc, run) in enumerate(jobs)
        ]
        runs = [f.result() for f in futures]

    summary = []
    for case_id, stem, _native, _pdf in pairs:
        row = {"case": case_id, "document": stem[:40]}
        sets = {}
        for label in ("native", "pdf"):
            ok = [r for r in runs if r["case"] == case_id and r["format"] == label and "error" not in r]
            sig_sets = [set(r["signatures"]) for r in ok]
            sets[label] = sig_sets
            pair_scores = [_jaccard(a, b) for a, b in itertools.combinations(sig_sets, 2)]
            row[label] = {
                "ok_runs": len(ok),
                "errors": sum(1 for r in runs if r["case"] == case_id and r["format"] == label and "error" in r),
                "statuses": [r["status"] for r in ok],
                "requirement_counts": [r["requirement_count"] for r in ok],
                "unmapped_counts": [r["diagnostics"].get("UNMAPPED_REQUIREMENT", 0) for r in ok],
                "identical_sets": len({frozenset(s) for s in sig_sets}) == 1 if sig_sets else None,
                "mean_pairwise_jaccard": round(sum(pair_scores) / len(pair_scores), 3) if pair_scores else None,
                "open_vocabulary_share": [
                    round(r["open_vocabulary_requirements"] / r["requirement_count"], 2) if r["requirement_count"] else None
                    for r in ok
                ],
            }
        cross = [_jaccard(a, b) for a in sets["native"] for b in sets["pdf"]]
        row["native_vs_pdf_mean_jaccard"] = round(sum(cross) / len(cross), 3) if cross else None
        summary.append(row)

    report = {"model": extractors[0].model, "runs_per_format": args.runs, "summary": summary, "runs": runs}
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
