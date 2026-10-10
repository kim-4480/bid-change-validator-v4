"""가상 변경공고로 차수 비교가 바뀐 자격만 잡는지 잰다.

    python eval/experiments/synthetic_change_probe.py --model gpt-6-luna --out artifacts/synthetic_change.json

표본 공고의 문서 텍스트를 직접 고쳐 '2차' 를 만든다(PDF 판의 글자 사이 공백은 무시하고 모든 문서에서 같이
바꾼다). 1차와 2차를 서비스와 같은 조건(답 기억 공유)으로 분석해 diff_requirements 를 보고, 시나리오마다
기대한 변경을 잡았는지(탐지)와 기대에 없는 변경(오탐)을 센다. 실제 변경공고는 자격이 바뀐 사례가 드물어
(최근 30일 12쌍 중 4쌍) 이렇게 변경을 만들어 잰다.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import time
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

SAMPLE = Path("eval/golden/notice-sample-20261006f")

# (이름, 공고, [(찾을 문구, 바꿀 문구)], 기대 변경 [(종류, 유형, 값 조각)]) — 종류: ADDED | REMOVED
SCENARIOS = [
    ("날짜만 변경", "R26BK01749032-000", [("2026.", "2027.")], []),
    ("소재지 제주→서울", "R26BK01744673-000", [("제주특별자치도내에", "서울특별시내에")],
     [("REMOVED", "REGION", "제주"), ("ADDED", "REGION", "서울")]),
    ("업종 전기→정보통신", "R26BK01744673-000", [("전기공사업", "정보통신공사업")],
     [("REMOVED", "INDUSTRY", "0037"), ("ADDED", "INDUSTRY", "0036")]),
    ("규모 소기업→중소기업", "R26BK01749032-000", [("소기업 또는", "중소기업 또는")],
     [("ADDED", "COMPANY_SIZE", "중소기업")]),
    ("품명번호 변경", "R26BK01749012-000", [("6010640201", "6010640202")],
     [("REMOVED", "REGISTRATION_CERTIFICATION", "6010640201"), ("ADDED", "REGISTRATION_CERTIFICATION", "6010640202")]),
    ("소재지 조건 추가", "R26BK01749012-000",
     [("마. 「국가종합전자조달시스템", "마. 입찰공고일 현재 법인등기부상 본점 소재지가 서울특별시에 있는 업체이어야 합니다. 바. 「국가종합전자조달시스템")],
     [("ADDED", "REGION", "서울")]),
    ("소재지 조건 삭제", "R26BK01748730-000", [("제주특별자치도에 주된 영업소를 두고 있어야", "주된 영업소를 두고 있어야")],
     [("REMOVED", "REGION", "제주")]),
]


# 두 번째 묶음: 첫 묶음과 다른 공고(2026-10-07). 첫 묶음으로 차수 비교를 고쳤으므로 일반화 확인용이다.
SCENARIOS_B = [
    ("연락처만 변경", "R26BK01747549-000", [("02-590-8690", "02-590-8691")], []),
    ("업종 1468→1470", "R26BK01747549-000", [("업종코드: 1468", "업종코드: 1470")],
     [("REMOVED", "INDUSTRY", "1468"), ("ADDED", "INDUSTRY", "1470")]),
    ("품명번호 변경", "R26BK01747549-000", [("8111189901", "8111159901")],
     [("REMOVED", "REGISTRATION_CERTIFICATION", "8111189901"), ("ADDED", "REGISTRATION_CERTIFICATION", "8111159901")]),
    ("소재지 인천→경기", "R26BK01746653-000", [("인천광역시에 소재", "경기도에 소재"), ("지역제한(인천광역시)", "지역제한(경기도)")],
     [("REMOVED", "REGION", "인천"), ("ADDED", "REGION", "경기")]),
    ("대안 업종 1263 삭제", "R26BK01749004-000", [("또는 국내여행업[업종코드 1263]", "")],
     [("REMOVED", "INDUSTRY", "1263")]),
    ("소재지 경남→부산", "R26BK01749004-000", [("경상남도에 둔", "부산광역시에 둔"), ("지역제한(경상남도)", "지역제한(부산광역시)")],
     [("REMOVED", "REGION", "경상남도"), ("ADDED", "REGION", "부산")]),
    ("규모 소기업→중소기업", "R26BK01748255-000", [("소기업 또는 소상공인간 경쟁입찰", "중소기업자간 경쟁입찰")],
     [("ADDED", "COMPANY_SIZE", "중소기업")]),
]
SETS = {"a": SCENARIOS, "b": SCENARIOS_B}


def _pattern(text: str) -> re.Pattern[str]:
    return re.compile(r"\s*".join(map(re.escape, text.replace(" ", ""))))


def _documents(label: str, edits: list[tuple[str, str]] | None = None) -> list[QualificationDocumentInput]:
    manifest = json.loads((SAMPLE / "manifest.json").read_text(encoding="utf-8"))
    entry = next(n for n in manifest["notices"] if n["dir"] == label)
    out = []
    for doc in entry["documents"]:
        blocks = json.loads((SAMPLE / label / doc["blocks"]).read_text(encoding="utf-8"))
        if edits:
            blocks = copy.deepcopy(blocks)
            for block in blocks:
                for old, new in edits:
                    block["text"] = _pattern(old).sub(new, block["text"])
        out.append(QualificationDocumentInput(document_id=f"{label}/{doc['blocks']}", extracted_blocks=blocks))
    return out


def _analyze(label: str, version: str, documents, extractor, memories) -> list[QualificationRequirement]:
    result = analyze_qualification_documents(
        QualificationAnalysisInput(notice_id=label, notice_version_id=version, documents=documents),
        structured_extract=extractor, industry_resolver=CsvIndustryNameResolver(),
        extraction_mode="closed_first", clause_selection="hybrid",
        labeling_memory=memories["label"], selection_memory=memories["selection"], memory_namespace=extractor.model,
    )
    return list(result.requirements)


def _hit(change, expected) -> bool:
    kind, req_type, fragment = expected
    req = change.current if kind == "ADDED" else change.baseline
    if req is None or req.type != req_type:
        return False
    if change.change_type == "MODIFIED":
        return fragment in str(req.value)
    return change.change_type == kind and fragment in str(req.value)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gpt-6-luna")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--set", default="a", choices=list(SETS))
    args = parser.parse_args()
    extractor = OpenAIStructuredExtractor(model=args.model)
    memories = {"label": {}, "selection": {}}  # 서비스의 DB 기억처럼 시험 전체에서 공유한다
    baseline_cache: dict[str, list[QualificationRequirement]] = {}
    rows = []
    for name, label, edits, expected in SETS[args.set]:
        started = time.monotonic()
        if label not in baseline_cache:
            baseline_cache[label] = _analyze(label, f"{label}-v1", _documents(label), extractor, memories)
        before = baseline_cache[label]
        after = _analyze(label, f"{label}-v2-{name}", _documents(label, edits), extractor, memories)
        changes = [c for c in diff_requirements(before, after) if c.change_type != "UNCHANGED"]
        found = [e for e in expected if any(_hit(c, e) for c in changes)]
        extra = [c for c in changes if not any(_hit(c, e) for e in expected)]
        describe = lambda c: f"{c.change_type} {(c.current or c.baseline).type} {(c.current or c.baseline).value}" + (
            f" ← {c.baseline.value}" if c.change_type == "MODIFIED" else "")
        row = {"scenario": name, "notice": label, "seconds": round(time.monotonic() - started),
               "expected": len(expected), "found": len(found), "false_changes": [describe(c) for c in extra],
               "changes": [describe(c) for c in changes]}
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    summary = {
        "detected": sum(r["found"] for r in rows), "expected": sum(r["expected"] for r in rows),
        "false_changes": sum(len(r["false_changes"]) for r in rows),
        "scenarios_exact": sum(r["found"] == r["expected"] and not r["false_changes"] for r in rows), "scenarios": len(rows),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("▶", json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
