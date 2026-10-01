"""자격 조항 선택을 코드와 모델이 함께 하는 방식(하이브리드)을 표본으로 잰다. 제품 코드는 바꾸지 않는다.

    python eval/experiments/hybrid_selection_probe.py --sample eval/golden/notice-sample-20261001 \
        --runs 3 --model gpt-6-luna --out artifacts/hybrid_selection.json

배경 (2026-10-01 표본 측정)
  코드는 제목·키워드로 자격 절을 고른다. 고르지 못한 조항은 모델에 닿지 않고, 빠졌다는 흔적도 남지 않는다.

하이브리드
  1. 코드가 **문서 전체**를 조항으로 나눈다(경계와 원문은 여전히 코드가 정한다).
  2. 모델은 조항 목록을 보고 참가자격인 조항의 id 만 고른다. 원문을 쓰거나 경계를 바꿀 수 없다.
  3. 선택 = 코드 선택 ∪ 모델 선택. 모델이 고른 조항이 든 청크를 자격 절에 더한다.
  4. 선택 결과는 조항 원문의 해시로 기억한다. 같은 문장은 다시 돌려도, 다음 차수에서도 같은 결정을 받는다.
  5. 라벨링은 clause 방식 그대로다.

재는 것
  - 선택 일치도: 같은 문서로 선택 호출을 되풀이했을 때 고른 조항 집합이 얼마나 같은가(기억을 쓰지 않을 때의 흔들림).
  - 불일치: 모델만 고른 조항 / 코드만 고른 조항. 지금은 보이지 않는 누락과 과잉 선택이 여기 드러난다.
  - sample_compare.py 와 같은 지표를 clause(코드 선택)와 hybrid 에 대해.

모든 호출 결과는 계산 전에 --out 에 남긴다. --reuse 로 다시 계산만 하고, --resume 으로 실패한 선택 호출과
hybrid 라벨링만 다시 돌린다. 문서 전체를 보내는 선택 호출은 분당 토큰 한도에 잘 걸려 따로 천천히 돌린다.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import statistics as st
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from bidengine.clauses.enumerate import Clause, enumerate_clauses
from bidengine.labeling import clause_labeling
from bidengine.labeling.requirement_extraction import select_eligibility_chunks_with_mode
from bidengine.pipeline.analysis_pipeline import (
    QualificationAnalysisInput,
    QualificationDocumentInput,
    _build_global_chunks,
    analyze_qualification_documents,
)
from bidengine.providers.openai import OpenAIStructuredExtractor
from bideval.master_vocabulary import CsvIndustryNameResolver
from bideval.notice_sample import SampleVersion, load_sample

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sample_compare import summarize  # noqa: E402

MODES = ("clause", "hybrid")
CLAUSE_PREVIEW_CHARS = 300   # 고르는 데는 조항 앞부분이면 된다
SELECTION_BATCH_CHARS = 40_000

SELECTION_SCHEMA = {
    "name": "eligibility_clause_selection",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {"clause_ids": {"type": "array", "items": {"type": "string"}}},
        "required": ["clause_ids"],
    },
}

SELECTION_SYSTEM_PROMPT = """너는 입찰공고 문서에서 참가자격 조항을 고르는 도구다. 조항은 이미 [C0001] 같은 id 로 나뉘어 있다.
규칙:
1. 입찰에 참가하려는 업체가 갖춰야 하는 자격·조건을 정한 조항의 id 만 고른다. 업종·면허·등록·인증 보유, 본점 소재지, 기업 규모, 실적, 인력, 공동수급 허용 여부가 그런 조건이다.
2. 제목, 일정, 제출 서류 목록, 입찰 방법과 절차 안내, 무효·유의 사항, 규격과 사양, 평가 기준, 계약 조건, 서식은 고르지 않는다.
3. 받은 id 를 그대로 쓴다. 없는 id 를 만들지 마라.
4. 원문은 쓰지 않는다. id 만 낸다. 참가자격 조항이 없으면 빈 배열."""

_local = threading.local()
_original_selector = select_eligibility_chunks_with_mode


def _selector_with_extra(chunks):
    """코드 선택에, 이 스레드가 지정한 청크(모델이 고른 조항이 든 청크)를 더한다."""
    target, mode = _original_selector(chunks)
    extra = getattr(_local, "extra_chunk_ids", None)
    if not extra:
        return target, mode
    wanted = {chunk["chunk_id"] for chunk in target} | extra
    return [chunk for chunk in chunks if chunk["chunk_id"] in wanted], mode


clause_labeling.select_eligibility_chunks_with_mode = _selector_with_extra


def _documents(version: SampleVersion) -> list[QualificationDocumentInput]:
    return [QualificationDocumentInput(document_id=d.document_key, extracted_blocks=d.blocks) for d in version.documents]


def _hash(text: str) -> str:
    return hashlib.sha256("".join(text.split()).encode("utf-8")).hexdigest()[:20]


class Prepared:
    """한 차수의 문서 전체 조항과 코드 선택."""

    def __init__(self, version: SampleVersion) -> None:
        self.label = version.label
        chunks = _build_global_chunks(_documents(version), max_chunk_chars=1800)
        target, self.selection_mode = _original_selector(chunks)
        self.code_chunk_ids = {chunk["chunk_id"] for chunk in target}
        raw = enumerate_clauses(chunks)
        # 문서 전체 조항은 수백 개라 id 를 네 자리로 다시 붙인다.
        self.clauses = [Clause(f"C{i + 1:04d}", c.text, c.chunk_id, c.source_blocks) for i, c in enumerate(raw)]
        self.hash_of = {c.clause_id: _hash(c.text) for c in self.clauses}
        self.chunk_of_hash: dict[str, set[str]] = {}
        for clause in self.clauses:
            self.chunk_of_hash.setdefault(self.hash_of[clause.clause_id], set()).add(clause.chunk_id)
        self.code_hashes = {self.hash_of[c.clause_id] for c in self.clauses if c.chunk_id in self.code_chunk_ids}
        self.text_of_hash = {self.hash_of[c.clause_id]: c.text for c in self.clauses}
        self.body_key = _hash("\n".join(c.text for c in self.clauses))

    def batches(self) -> list[str]:
        out, current, size = [], [], 0
        for clause in self.clauses:
            entry = f"[{clause.clause_id}]\n{clause.text[:CLAUSE_PREVIEW_CHARS]}"
            if current and size + len(entry) > SELECTION_BATCH_CHARS:
                out.append("\n\n".join(current))
                current, size = [], 0
            current.append(entry)
            size += len(entry) + 2
        if current:
            out.append("\n\n".join(current))
        return out


def _call_with_backoff(extractor: OpenAIStructuredExtractor, body: str) -> dict:
    for attempt in range(8):
        try:
            return extractor(SELECTION_SYSTEM_PROMPT, body, SELECTION_SCHEMA)
        except Exception as error:  # noqa: BLE001 - SDK 예외 타입은 런타임 의존
            if "429" not in str(error) or attempt == 7:
                raise
            time.sleep(20 + 10 * attempt)
    raise RuntimeError("unreachable")


def _select(prepared: Prepared, model: str, run: int) -> dict:
    started = time.monotonic()
    picked: set[str] = set()
    unknown = 0
    try:
        for body in prepared.batches():
            result = _call_with_backoff(OpenAIStructuredExtractor(model=model), body)
            for clause_id in result.get("clause_ids") or []:
                digest = prepared.hash_of.get(str(clause_id).strip("[] "))
                if digest is None:
                    unknown += 1
                else:
                    picked.add(digest)
    except Exception as error:  # noqa: BLE001
        return {"body_key": prepared.body_key, "run": run, "error": repr(error)[:300]}
    return {"body_key": prepared.body_key, "run": run, "picked": sorted(picked), "unknown_ids": unknown,
            "seconds": round(time.monotonic() - started, 1)}


def _extract(version: SampleVersion, mode: str, model: str, run: int, extra_chunk_ids: set[str]) -> dict:
    started = time.monotonic()
    _local.extra_chunk_ids = extra_chunk_ids if mode == "hybrid" else None
    try:
        result = analyze_qualification_documents(
            QualificationAnalysisInput(notice_id=version.label, notice_version_id=f"{version.label}-{mode}-{run}",
                                       documents=_documents(version)),
            structured_extract=OpenAIStructuredExtractor(model=model),
            industry_resolver=CsvIndustryNameResolver(),
            extraction_mode="clause",
        )
    except Exception as error:  # noqa: BLE001
        return {"version": version.label, "mode": mode, "model": model, "run": run, "error": repr(error)[:300]}
    finally:
        _local.extra_chunk_ids = None
    return {
        "version": version.label, "mode": mode, "model": model, "run": run,
        "seconds": round(time.monotonic() - started, 1),
        "status": result.status,
        "coverage_complete": bool(result.coverage and result.coverage.complete),
        "input_truncated": bool(result.coverage and getattr(result.coverage, "input_truncated", False)),
        "target_chunks": len(result.target_chunk_ids),
        "requirements": [r.model_dump(mode="json") for r in result.requirements],
    }


def _jac(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a | b else 1.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--model", default="gpt-6-luna")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--selection-workers", type=int, default=2)
    parser.add_argument("--reuse", action="store_true", help="--out 의 호출 결과로 다시 계산만 한다")
    parser.add_argument("--resume", action="store_true", help="--out 에서 성공한 선택과 clause 실행은 두고 나머지만 다시 돈다")
    args = parser.parse_args()

    notices, changed = load_sample(args.sample)
    versions = {v.label: v for v in notices}
    for chain in changed:
        versions.update({v.label: v for v in chain})
    changed_labels = [[v.label for v in chain] for chain in changed]
    prepared = {label: Prepared(version) for label, version in versions.items()}
    unique = {p.body_key: p for p in prepared.values()}   # 차수끼리 문서가 같으면 선택 호출도 한 번이면 된다

    saved = json.loads(args.out.read_text(encoding="utf-8")) if args.reuse or args.resume else {"selections": [], "runs": []}
    selections = [s for s in saved["selections"] if args.reuse or "error" not in s]
    kept_runs = [r for r in saved["runs"] if args.reuse or (r["mode"] == "clause" and "error" not in r)]
    runs = kept_runs
    if not args.reuse:
        done = {(s["body_key"], s["run"]) for s in selections}
        jobs = [(p, args.model, run) for p in unique.values() for run in range(args.runs) if (p.body_key, run) not in done]
        print(f"versions={len(versions)} unique_documents={len(unique)} selection_calls={len(jobs)}")
        with ThreadPoolExecutor(max_workers=args.selection_workers) as pool:
            selections += list(pool.map(lambda job: _select(*job), jobs))
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({"selections": selections, "runs": kept_runs}, ensure_ascii=False), encoding="utf-8")

    # 기억: 조항 해시마다 첫 실행의 결정을 쓴다. 같은 문장은 어느 차수에서나 같은 결정이다.
    by_body: dict[str, list[dict]] = {}
    for selection in selections:
        if "error" not in selection:
            by_body.setdefault(selection["body_key"], []).append(selection)
    remembered: set[str] = set()
    for group in by_body.values():
        remembered.update(min(group, key=lambda s: s["run"])["picked"])

    extra = {label: {chunk for digest in remembered & set(p.chunk_of_hash) for chunk in p.chunk_of_hash[digest]}
             - p.code_chunk_ids for label, p in prepared.items()}

    if not args.reuse:
        done_runs = {(r["version"], r["mode"], r["run"]) for r in kept_runs}
        jobs = [(versions[label], mode, args.model, run, extra[label])
                for label in versions for mode in MODES for run in range(args.runs)
                if (label, mode, run) not in done_runs]
        print(f"labeling_calls={len(jobs)}")
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            runs = kept_runs + list(pool.map(lambda job: _extract(*job), jobs))
        args.out.write_text(json.dumps({"selections": selections, "runs": runs}, ensure_ascii=False), encoding="utf-8")

    per_version = {}
    agreement = []
    for label, p in prepared.items():
        group = by_body.get(p.body_key, [])
        sets = [set(s["picked"]) for s in group]
        pair = [_jac(a, b) for a, b in itertools.combinations(sets, 2)]
        model = remembered & set(p.chunk_of_hash)
        per_version[label] = {
            "section_selection": p.selection_mode,
            "clauses": len(p.clauses),
            "code_selected": len(p.code_hashes),
            "model_selected": len(model),
            "both": len(model & p.code_hashes),
            "model_only": len(model - p.code_hashes),
            "code_only": len(p.code_hashes - model),
            "added_chunks": len(extra[label]),
            "selection_agreement": round(st.mean(pair), 3) if pair else None,
            "model_only_clauses": [p.text_of_hash[d] for d in sorted(model - p.code_hashes, key=lambda d: p.text_of_hash[d])],
        }
    for group in by_body.values():
        sets = [set(s["picked"]) for s in group]
        agreement += [_jac(a, b) for a, b in itertools.combinations(sets, 2)]

    summary = summarize(runs, changed_labels, MODES)
    selection_summary = {
        "selection_calls": len(selections),
        "selection_errors": sum("error" in s for s in selections),
        "selection_agreement": round(st.mean(agreement), 3) if agreement else None,
        "selection_seconds_mean": round(st.mean(s["seconds"] for s in selections if "error" not in s), 1),
    }
    args.out.write_text(json.dumps({"summary": summary, "selection_summary": selection_summary,
                                    "per_version": per_version, "selections": selections, "runs": runs},
                                   ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"selection": selection_summary, "extraction": summary}, ensure_ascii=False, indent=1))
    for label, row in per_version.items():
        print(f"{label:20s} 조항 {row['clauses']:4d}  코드 {row['code_selected']:4d}  모델 {row['model_selected']:3d}  "
              f"둘 다 {row['both']:3d}  모델만 {row['model_only']:3d}  코드만 {row['code_only']:4d}  "
              f"더한 청크 {row['added_chunks']:3d}  선택 일치도 {row['selection_agreement']}")


if __name__ == "__main__":
    main()
