"""구조 진단(ADR 0001 문제 2·4·5·6)을 LLM·DB 없이 재현하고 수치로 남긴다.

    python eval/experiments/structural_diagnosis.py [--out result.json]

각 실험은 현재 엔진 코드를 그대로 호출한다. 결과는 "지금 코드가 이렇게 동작한다"는
관찰이며, 고친 뒤 같은 스크립트로 다시 재면 전후 비교가 된다.
"""
from __future__ import annotations

import argparse
import collections
import copy
import json
import re
from datetime import date
from pathlib import Path

from bidengine import contracts
from bidengine.diff.requirement_diff import diff_requirements
from bidengine.document.chunking import chunk_source_blocks
from bidengine.judgment import rules
from bidengine.labeling.requirement_extraction import select_eligibility_chunks

ROOT = Path(__file__).resolve().parents[2]
GOLDEN_V02 = ROOT / "eval" / "golden" / "qualification-v0.2" / "fixture_bundle.json"
REAL_V01 = ROOT / "eval" / "golden" / "qualification-real-v0.1"


def _golden_cases() -> list[dict]:
    bundle = json.loads(GOLDEN_V02.read_text(encoding="utf-8"))
    return bundle["cases"] + bundle.get("previous_cases", [])


def _requirements(case: dict) -> list[contracts.QualificationRequirement]:
    return [
        contracts.QualificationRequirement.model_validate(item["requirement"])
        for item in case["canonical_inputs"]
    ]


# ── 문제 2: 요건 정체성이 원문 문자열이다 ─────────────────────────────────────


def _renumber(reqs: list[contracts.QualificationRequirement]) -> list[contracts.QualificationRequirement]:
    """제품의 requirement_key는 추출 순서다. 그 성질을 흉내 낸다."""
    out = []
    for index, req in enumerate(reqs):
        clone = req.model_copy(deep=True)
        clone.requirement_key = f"R{index:03d}"
        if clone.requirement_group_key:
            clone.requirement_group_key = f"G-{clone.requirement_group_key}"
        out.append(clone)
    return out


def _with_raw(req, raw):
    clone = req.model_copy(deep=True)
    clone.raw = raw
    return clone


def _insert_linebreaks(raw: str) -> str:
    mid = len(raw) // 2
    return raw[:mid] + "\n" + raw[mid:].replace(" ", "  ", 1)


def _extend_quote(raw: str) -> str:
    # 모델이 같은 조항을 인용하면서 바로 뒤 각주 한 줄을 붙여 오는 경우
    return raw + " ※ 세부 사항은 붙임 참조"


def _strip_decoration(raw: str) -> str:
    # 모델이 ※·괄호 주석을 빼고 인용하는 경우
    return re.sub(r"[※▶■□●○]", "", re.sub(r"\([^)]{0,40}\)", "", raw)).strip()


_NEW_REQ = {
    "requirement_key": "NEW",
    "notice_version_id": "v2",
    "type": "REGION",
    "operator": "MATCH",
    "value": "서울특별시",
    "scope": {},
    "raw": "본점 소재지가 서울특별시인 업체",
}


def experiment_identity() -> dict:
    """원문과 같은 조항인데 인용 경계·순서만 바뀐 2차 공고를 만들어 diff를 돌린다.

    모든 변형에서 요건의 의미는 그대로다. 이상적인 diff는 기존 요건을 전부 UNCHANGED로,
    새로 끼운 요건만 ADDED로 봐야 한다.
    """
    variants = {
        "줄바꿈·공백만 다름": lambda reqs: [_with_raw(r, _insert_linebreaks(r.raw)) for r in reqs],
        "인용에 각주 한 줄이 붙음": lambda reqs: [_with_raw(r, _extend_quote(r.raw)) for r in reqs],
        "인용에서 ※·괄호 주석이 빠짐": lambda reqs: [_with_raw(r, _strip_decoration(r.raw)) for r in reqs],
        "앞에 요건 1개 추가(순서 밀림)": lambda reqs: [
            contracts.QualificationRequirement.model_validate(
                {**_NEW_REQ, "notice_version_id": reqs[0].notice_version_id}
            ),
            *reqs,
        ],
        "각주 붙음 + 순서 밀림": lambda reqs: [
            contracts.QualificationRequirement.model_validate(
                {**_NEW_REQ, "notice_version_id": reqs[0].notice_version_id}
            ),
            *[_with_raw(r, _extend_quote(r.raw)) for r in reqs],
        ],
    }
    results = {}
    for name, make in variants.items():
        totals = collections.Counter()
        for case in _golden_cases():
            base = _requirements(case)
            if not base:
                continue
            current_raw = make(base)
            changed_raw = sum(1 for r in current_raw if r.raw != "본점 소재지가 서울특별시인 업체")
            before, after = _renumber(base), _renumber(current_raw)
            inserted = {r.requirement_key for r in after if r.raw == _NEW_REQ["raw"]}
            for change in diff_requirements(before, after):
                if change.current_key in inserted and change.change_type == "ADDED":
                    totals["new_requirement_detected"] += 1
                    continue
                totals[change.change_type] += 1
            totals["baseline_requirements"] += len(base)
            del changed_raw
        n = totals["baseline_requirements"]
        results[name] = {
            "baseline_requirements": n,
            "UNCHANGED": totals["UNCHANGED"],
            "MODIFIED(오탐)": totals["MODIFIED"],
            "REMOVED(오탐)": totals["REMOVED"],
            "ADDED(오탐)": totals["ADDED"],
            "unchanged_rate": round(totals["UNCHANGED"] / n, 3) if n else None,
        }
    return results


# ── 문제 4: 열린 어휘를 문자열 포함으로 판정한다 ──────────────────────────────


def _performance(ref: str, name: str, fields: list[str], completed: date) -> dict:
    return {
        "ref": ref,
        "name": name,
        "client_name": "OO시청",
        "amount": 300_000_000,
        "completed_at": completed.isoformat(),
        "fields": fields,
        "verified": True,
    }


def experiment_open_vocabulary() -> dict:
    """골든 J06 조항("2개 이상 단체급식소를 1년 이상 운영한 실적")을 추출기가 채우는 모양
    (operator/value/기간)으로 두고, 실제로 자격이 있는 회사의 실적 표기만 바꿔 판정한다."""
    source = next(c for c in _golden_cases() if c["case_id"] == "J06")
    base = next(
        i["requirement"] for i in source["canonical_inputs"] if i["requirement"]["type"] == "PERFORMANCE_COUNT"
    )
    requirement = contracts.QualificationRequirement.model_validate(
        {
            **base,
            "operator": ">=",
            "value": 2,
            "period_months": 24,
            "scope": {"experience_field": "단체급식 운영"},
            "condition_complexity": "simple",
        }
    )
    reference = date(2026, 9, 1)
    qualifying = {
        "단체급식 운영": ["단체급식 운영"],
        "단체급식소 위탁운영": ["단체급식소 위탁운영"],
        "집단급식소 운영": ["집단급식소 운영"],
        "위탁급식": ["위탁급식"],
        "급식 운영": ["급식 운영"],
        "구내식당 운영": ["구내식당 운영"],
    }
    not_qualifying = {
        "청소 용역": ["청소 용역"],
        "시설 경비": ["시설 경비"],
    }

    def judge(fields: list[str]) -> str:
        profile = rules.CompanyProfileSnapshot.model_validate(
            {
                "company_id": "X",
                "performances": [
                    _performance("P1", f"A기관 {fields[0]}", fields, date(2025, 6, 30)),
                    _performance("P2", f"B기관 {fields[0]}", fields, date(2026, 3, 31)),
                ],
                "completeness": {"performances": True},
            }
        )
        return rules.judge_requirement(
            requirement, profile, preflight_case_id="exp", reference_date=reference
        ).status

    q = {label: judge(fields) for label, fields in qualifying.items()}
    n = {label: judge(fields) for label, fields in not_qualifying.items()}
    return {
        "requirement": {"type": requirement.type, "operator": requirement.operator, "value": requirement.value,
                        "experience_field": requirement.scope.get("experience_field")},
        "자격 있는 회사(표기만 다름)": q,
        "자격 있는 회사 중 미달 판정": f"{sum(v == 'UNSATISFIED' for v in q.values())}/{len(q)}",
        "자격 없는 회사": n,
        "자격 없는 회사 중 미달 판정": f"{sum(v == 'UNSATISFIED' for v in n.values())}/{len(n)}",
    }


# ── 문제 5: 파이프라인 사정(PARTIAL)이 전체 적합을 막는다 ─────────────────────


def experiment_status_semantics() -> dict:
    cases = _golden_cases()
    all_satisfied_blocked = []
    flips = collections.Counter()
    for case in cases:
        reqs = _requirements(case)
        profile = rules.CompanyProfileSnapshot.model_validate(case["profile"])
        ref = date.fromisoformat(case["reference_date"])
        partial = rules.judge_requirements(reqs, profile, preflight_case_id=case["case_id"], reference_date=ref,
                                           analysis_status=case["analysis_status"])
        succeeded = rules.judge_requirements(reqs, profile, preflight_case_id=case["case_id"], reference_date=ref,
                                             analysis_status="SUCCEEDED")
        flips[(partial.overall_status, succeeded.overall_status)] += 1
        mandatory = [j for j, r in zip(partial.judgments, reqs) if r.requirement_role == "mandatory"]
        if mandatory and all(j.status == "SATISFIED" for j in mandatory):
            all_satisfied_blocked.append(case["case_id"])

    # 합성: 요건 1개, 회사가 충족. 추출 후보 중 안내문 한 줄이 원문 대조에 실패해 PARTIAL.
    req = contracts.QualificationRequirement.model_validate(
        {"requirement_key": "R1", "notice_version_id": "v", "type": "REGION", "operator": "MATCH",
         "value": "서울특별시", "raw": "본점 소재지가 서울특별시인 업체"}
    )
    profile = rules.CompanyProfileSnapshot.model_validate({"company_id": "X", "region_name": "서울특별시"})
    synthetic = {
        status: rules.judge_requirements([req], profile, preflight_case_id="s", reference_date=date(2026, 9, 1),
                                         analysis_status=status).overall_status
        for status in ("SUCCEEDED", "PARTIAL")
    }
    empty = rules.judge_requirements([], profile, preflight_case_id="s", reference_date=date(2026, 9, 1),
                                     analysis_status="SUCCEEDED").overall_status
    return {
        "golden_analysis_status": dict(collections.Counter(c["analysis_status"] for c in cases)),
        "golden_expected_overall": dict(collections.Counter(c["expected_safe_overall"] for c in cases)),
        "PARTIAL→SUCCEEDED 로 바꿨을 때 전체 판정 변화": {f"{a}→{b}": v for (a, b), v in flips.items()},
        "필수 요건 전부 충족인데 PARTIAL로 막힌 골든 케이스": all_satisfied_blocked,
        "합성: 충족 요건 1개": synthetic,
        "합성: 요건 0개 + SUCCEEDED": empty,
    }


# ── 문제 6: 문서 모델이 없다 ─────────────────────────────────────────────────

_PAGE_LINE = re.compile(r"(?m)^[ \t]*(-\s*\d{1,3}\s*-|\d{1,3}\s*/\s*\d{1,3}|\d{1,3})[ \t]*$")
_MIDWORD_BREAK = re.compile(r"[가-힣]\n[가-힣]")
_SHINGLE = 12


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _shingles(text: str) -> set[str]:
    t = _norm(text)
    return {t[i : i + _SHINGLE] for i in range(max(0, len(t) - _SHINGLE + 1))}


def _load_blocks(doc: dict) -> list[dict]:
    raw = json.loads((REAL_V01 / doc["blocks"]["path"]).read_text(encoding="utf-8"))
    return raw if isinstance(raw, list) else raw.get("blocks", [])


def experiment_document_model() -> dict:
    """같은 공고문을 HWP/HWPX와 PDF로 각각 넣고, 청킹·자격절 선별 결과를 비교한다."""
    pairs = []
    for case_dir in sorted((REAL_V01 / "cases").iterdir()):
        case = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
        docs = [d for d in case["documents"] if d.get("blocks")]
        by_stem = collections.defaultdict(dict)
        for d in docs:
            stem, _, ext = d["name"].rpartition(".")
            if ext.lower() in {"hwp", "hwpx", "pdf"}:
                by_stem[stem][ext.lower()] = d
        for stem, formats in by_stem.items():
            if "pdf" in formats and ({"hwp", "hwpx"} & formats.keys()):
                pairs.append((case["case_id"], stem, formats[next(iter({"hwp", "hwpx"} & formats.keys()))], formats["pdf"]))

    rows = []
    for case_id, stem, native, pdf in pairs:
        row = {"case": case_id, "document": stem[:40]}
        selected_text = {}
        for label, doc in (("native", native), ("pdf", pdf)):
            blocks = _load_blocks(doc)
            chunks = chunk_source_blocks(blocks)
            selected = select_eligibility_chunks(chunks)
            text = "\n".join(c["text"] for c in selected)
            selected_text[label] = text
            row[label] = {
                "blocks": len(blocks),
                "avg_block_chars": round(sum(len(b.get("text", "")) for b in blocks) / max(1, len(blocks))),
                "chunks": len(chunks),
                "chunks_with_label": sum(1 for c in chunks if c.get("clause_label")),
                "selected_chunks": len(selected),
                "selected_is_whole_document": len(selected) == len(chunks),
                "selected_chars": len(_norm(text)),
                "page_number_lines_in_selected": len(_PAGE_LINE.findall(text)),
                "midword_linebreaks_in_selected": len(_MIDWORD_BREAK.findall(text)),
            }
        a, b = _shingles(selected_text["native"]), _shingles(selected_text["pdf"])
        row["selected_overlap_jaccard"] = round(len(a & b) / len(a | b), 3) if a | b else None
        rows.append(row)
    return {"pairs": rows}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    report = {
        "problem_2_identity": experiment_identity(),
        "problem_4_open_vocabulary": experiment_open_vocabulary(),
        "problem_5_status_semantics": experiment_status_semantics(),
        "problem_6_document_model": experiment_document_model(),
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
