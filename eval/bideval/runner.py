"""Offline runner using Core public functions, without a parallel extractor."""

from bidengine.pipeline.analysis_pipeline import analyze_qualification_documents
from bidengine.document.backend_blocks import canonical_source_blocks
from bidengine.document.chunking import chunk_source_blocks
from bidengine.labeling.requirement_extraction import build_extraction_body, select_eligibility_chunks
from bideval.scoring import score_case


def chunk_and_select(document_blocks):
    """Chunk each document separately, preserving Core's global chunk numbering."""
    chunks = []
    for blocks in document_blocks:
        for chunk in chunk_source_blocks(blocks):
            chunks.append({**chunk, "chunk_id": f"CHUNK-{len(chunks):04d}"})
    return chunks, select_eligibility_chunks(chunks)


def evaluate_case(case, *, structured_extract=None):
    chunks, selected = chunk_and_select(
        canonical_source_blocks(document_id=doc.document_id,
                                blocks=doc.extracted_blocks,
                                file_sha256=doc.file_sha256,
                                text_sha256=doc.extracted_text_sha256)
        for doc in case.analysis_input.documents)
    result = None
    calls = 0
    if structured_extract is not None:
        def observed(system, body, schema):
            nonlocal calls
            if body != build_extraction_body(selected):
                raise ValueError("evaluation context differs from Core context")
            calls += 1
            return structured_extract(system, body, schema)
        result = analyze_qualification_documents(case.analysis_input, structured_extract=observed)
        if result.target_chunk_ids != [c["chunk_id"] for c in selected]:
            raise ValueError("evaluation selection differs from Core selection")
        if chunks and not calls:
            raise ValueError("Core did not receive the expected evaluation context")
    report = score_case(case.spans, chunks, selected, result)
    # 모델이 빠뜨려 코드가 원문에서 채운 요건 수. 채우기가 들어간 뒤로는 모델이 빈 결과를
    # 줘도 일치율이 안 떨어질 수 있어서, 모델이 실제로 얼마나 흔들렸는지는 이 숫자로 본다.
    salvaged = 0 if result is None else sum(
        1 for d in result.diagnostics if d.code == "INDUSTRY_CODE_SALVAGED_FROM_SOURCE"
    )
    return {"case_id": case.spec.case_id, "notice_no": case.spec.notice_no,
            "notice_version_id": case.spec.notice_version_id,
            "provenance": case.spec.provenance, "extractor_calls": calls if structured_extract is not None else None,
            "salvaged_from_source": salvaged,
            **report, "analysis": None if result is None else result.model_dump(mode="json")}


# 모델은 같은 입력에도 매번 다르게 답한다. 한 번 돌린 값으로 "정확도 N%" 라고
# 말하면 그 숫자는 다음 실행에서 바뀐다. 그래서 같은 케이스를 여러 번 돌리고
# 평균과 개별 값을 함께 남긴다 — 평균만 남기면 "3번 중 2번 성공" 과 "매번 66%"
# 를 구분할 수 없는데, 대응 방법이 서로 다르다.
#
# 결정적 단계는 평균 내지 않는다. 청킹·선별·컨텍스트 예산은 모델을 타지 않으므로
# 매 실행 같아야 정상이고, 다르면 측정기 자체가 흔들린 것이다. 그걸 평균으로
# 덮으면 모델 성능 변동으로 오독하게 되므로 오류로 올린다.
MODEL_DEPENDENT_METRICS = ("canonical_match", "evidence_preserved")


def _mean(values):
    """측정된 값만 평균낸다. 미측정(None)과 0 점을 섞지 않는다."""
    measured = [v for v in values if v is not None]
    return sum(measured) / len(measured) if measured else None


def evaluate_case_runs(case, *, structured_extract, runs=3):
    """같은 케이스를 runs 번 돌려 모델 의존 지표의 분산을 드러낸다."""
    if runs < 1:
        raise ValueError("runs must be at least 1")
    if structured_extract is None:
        raise ValueError("repeated runs measure model variance; an extractor is required")

    reports = [evaluate_case(case, structured_extract=structured_extract)
               for _ in range(runs)]
    report = dict(reports[0])

    for name in ("chunk_health", "context"):
        if any(r[name] != report[name] for r in reports[1:]):
            raise ValueError(f"deterministic stage varied across runs: {name}")

    metrics = dict(report["metrics"])
    for name in MODEL_DEPENDENT_METRICS:
        values = [r["metrics"][name]["value"] for r in reports]
        metrics[name] = {**metrics[name], "value": _mean(values), "runs": values}
    report["metrics"] = metrics

    report["run_count"] = runs
    report["runs"] = [
        {"analysis_status": r["analysis_status"], "extractor_calls": r["extractor_calls"],
         "salvaged_from_source": r["salvaged_from_source"],
         **{name: r["metrics"][name]["value"] for name in MODEL_DEPENDENT_METRICS}}
        for r in reports
    ]
    # 여러 번 돌린 결과를 한 번의 analysis 로 대표하면 오해를 부른다.
    report["analysis"] = None
    return report
