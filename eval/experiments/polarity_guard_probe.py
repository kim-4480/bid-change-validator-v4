"""맥락 가드(조항 극성)를 켰을 때와 껐을 때를 같은 표본으로 잰다.

    python eval/experiments/polarity_guard_probe.py --sample eval/golden/notice-sample-20261001 \
        --runs 3 --model gpt-6-luna --out artifacts/polarity_guard.json
    python eval/experiments/score_against_labels.py --labels eval/golden/notice-sample-20261001/labels.json \
        --runs artifacts/polarity_guard.json

방식 (--modes)
  - clause          : 조항 단위 추출, 낱말 가드 그대로 (지금의 clause 방식)
  - clause_polarity : 같은 추출에 맥락 가드를 켠다 (polarity_guard=True)
  - hybrid_polarity : 맥락 가드 + 조항 선택 hybrid (코드가 고른 조항 ∪ 모델이 고른 조항)
  - model_polarity  : 맥락 가드 + 조항 선택 model (모델이 고른 조항만)

극성 답과 조항 선택은 조항 원문 해시로 기억해 실행·차수·방식 사이에 공유한다. 같은 문장은 항상 같은 답을 받는다.

채점에 필요해서 요건뿐 아니라 커버리지 공백과 극성 분포도 저장한다 — 공동수급처럼 '확인 필요'로 남겨야 하는
조항은 요건 목록이 아니라 공백에 있다. 정답이 붙은 공고가 manifest 의 unselected 에 있으면 그것도 함께 돌린다.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from bidengine.pipeline.analysis_pipeline import (
    QualificationAnalysisInput,
    QualificationDocumentInput,
    analyze_qualification_documents,
)
from bidengine.providers.openai import OpenAIStructuredExtractor
from bideval.master_vocabulary import CsvIndustryNameResolver
from bideval.notice_sample import SampleDocument, SampleVersion, load_sample

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sample_compare import summarize  # noqa: E402

# 방식 → (맥락 가드, 조항 선택)
CONFIG = {
    "clause": (False, "code"),
    "clause_polarity": (True, "code"),
    "hybrid_polarity": (True, "hybrid"),
    "model_polarity": (True, "model"),
}
MODES = tuple(CONFIG)


# 조항 라벨 기억. --no-labeling-memory 로 끈다(전후 비교용).
USE_LABELING_MEMORY = True


class FirstAnswerMemory(dict):
    """조항마다 처음 받은 답을 지킨다. 여러 실행이 동시에 같은 조항을 물어도 답은 하나다."""

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()

    def __setitem__(self, key: str, value: str) -> None:
        with self._lock:
            if key not in self:
                super().__setitem__(key, value)


LABELING_MEMORY = FirstAnswerMemory()


class RetryingExtractor:
    """분당 토큰 한도(429)에 걸리면 기다렸다 다시 부른다."""

    def __init__(self, model: str) -> None:
        self._extractor = OpenAIStructuredExtractor(model=model)

    def __call__(self, system_prompt: str, body: str, schema: dict) -> dict:
        for attempt in range(8):
            try:
                return self._extractor(system_prompt, body, schema)
            except Exception as error:  # noqa: BLE001 - SDK 예외 타입은 런타임 의존
                if "429" not in str(error) or attempt == 7:
                    raise
                time.sleep(20 + 10 * attempt)
        raise RuntimeError("unreachable")


def _labelled_unselected(sample: Path, labels: Path | None, known: set[str]) -> list[SampleVersion]:
    """정답이 붙었는데 notices·changed 에 없는 차수를 manifest 의 unselected 에서 읽는다."""
    if labels is None:
        return []
    wanted = set(json.loads(labels.read_text(encoding="utf-8"))["notices"]) - known
    manifest = json.loads((sample / "manifest.json").read_text(encoding="utf-8"))
    versions = []
    for entry in manifest.get("unselected", []):
        for version in entry["versions"]:
            if version["dir"] in wanted:
                versions.append(SampleVersion(label=version["dir"], documents=[
                    SampleDocument(
                        name=d["name"], document_key=f"{version['dir']}/{d['blocks']}",
                        blocks=json.loads((sample / version["dir"] / d["blocks"]).read_text(encoding="utf-8")),
                    )
                    for d in version["documents"]
                ]))
                wanted.discard(version["dir"])
    return versions


def _extract(version: SampleVersion, mode: str, model: str, run: int, memory: FirstAnswerMemory,
             selection_memory: FirstAnswerMemory) -> dict:
    started = time.monotonic()
    polarity_guard, clause_selection = CONFIG[mode]
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
            polarity_memory=memory if polarity_guard else None,
            clause_selection=clause_selection,
            selection_memory=selection_memory,
            labeling_memory=LABELING_MEMORY if USE_LABELING_MEMORY else None,
        )
    except Exception as error:  # noqa: BLE001
        return {"version": version.label, "mode": mode, "model": model, "run": run, "error": repr(error)[:300]}
    coverage = result.coverage
    return {
        "version": version.label, "mode": mode, "model": model, "run": run,
        "seconds": round(time.monotonic() - started, 1),
        "status": result.status,
        "coverage_complete": bool(coverage and coverage.complete),
        "target_chunks": len(result.target_chunk_ids),
        "input_truncated": bool(coverage and coverage.input_truncated),
        "requirements": [r.model_dump(mode="json") for r in result.requirements],
        "gaps": [gap.model_dump(mode="json") for gap in (coverage.gaps if coverage else [])],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--labels", type=Path, help="정답 파일. 정답이 붙은 unselected 차수도 함께 돌린다.")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--model", default="gpt-6-luna")
    parser.add_argument("--modes", nargs="+", default=["clause", "clause_polarity"], choices=MODES)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reuse", action="store_true", help="--out 의 호출 결과로 다시 계산만 한다")
    parser.add_argument("--only-labelled", action="store_true", help="정답이 붙은 차수만 돌린다")
    parser.add_argument("--no-labeling-memory", action="store_true", help="조항 라벨을 기억하지 않는다(실행마다 새로 묻는다)")
    args = parser.parse_args()
    global USE_LABELING_MEMORY
    USE_LABELING_MEMORY = not args.no_labeling_memory

    notices, changed = load_sample(args.sample)
    versions = {v.label: v for v in notices}
    for chain in changed:
        versions.update({v.label: v for v in chain})
    for version in _labelled_unselected(args.sample, args.labels, set(versions)):
        versions[version.label] = version
    if args.only_labelled and args.labels is not None:
        labelled = set(json.loads(args.labels.read_text(encoding="utf-8"))["notices"])
        versions = {label: version for label, version in versions.items() if label in labelled}
    changed_labels = [[v.label for v in chain if v.label in versions] for chain in changed]

    memory = FirstAnswerMemory()
    selection_memory = FirstAnswerMemory()
    if args.reuse:
        saved = json.loads(args.out.read_text(encoding="utf-8"))
        runs, polarity = saved["runs"], saved.get("polarity", {})
    else:
        jobs = [(version, mode, args.model, run, memory, selection_memory)
                for version in versions.values() for mode in args.modes for run in range(args.runs)]
        print(f"versions={len(versions)} calls={len(jobs)} (+ 극성 호출)")
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            runs = list(pool.map(lambda job: _extract(*job), jobs))
        polarity = dict(memory)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({"runs": runs, "polarity": polarity,
                                        "selected_clauses": sum(selection_memory.values()),
                                        "seen_clauses": len(selection_memory)}, ensure_ascii=False), encoding="utf-8")

    summary = summarize(runs, changed_labels, MODES)
    counts: dict[str, int] = {}
    for value in polarity.values():
        counts[value] = counts.get(value, 0) + 1
    for key, row in summary.items():
        mine = [r for r in runs if "error" not in r and f"{r['model']}/{r['mode']}" == key]
        row["target_chunks_mean"] = round(sum(r.get("target_chunks", 0) for r in mine) / len(mine), 1)
        row["input_truncated"] = sum(bool(r.get("input_truncated")) for r in mine)
    args.out.write_text(json.dumps({"summary": summary, "polarity_counts": counts, "runs": runs, "polarity": polarity},
                                   ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"extraction": summary, "polarity_counts": counts}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
