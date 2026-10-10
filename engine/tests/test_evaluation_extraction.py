from bidengine.labeling.evaluation_extraction import (
    extract_evaluation_criteria, select_evaluation_chunks,
)

def chunk(identifier, text, document="doc", page=1, label="4"):
    return {
        "chunk_id": identifier, "clause_label": label, "text": text,
        "source_blocks": [{
            "document_id": document, "block_index": 0, "page": page,
            "text": text, "source_sha256": "s1", "extracted_text_sha256": "s2",
        }],
    }

def model_answer(*items):
    return lambda *_args: {"criteria": list(items)}

def test_eligibility_section_separated_from_rubric():
    chunks = [
        chunk("C1", "3. 입찰참가자격", label="3"),
        chunk("C2", "3.1 서울 소재 업체", label="3.1"),
        chunk("C3", "4. 제안서 평가기준", page=2, label="4"),
        chunk("C4", "4.1 사업 수행능력: 배점 20점", page=2, label="4.1"),
        chunk("C5", "5. 제출서류", page=3, label="5"),
    ]
    selected = select_evaluation_chunks(chunks)
    assert [c["chunk_id"] for c in selected] == ["C3", "C4"]

def test_valid_criterion_keeps_version_and_source_location():
    raw = "4.1 사업 수행능력: 배점 20점"
    result = extract_evaluation_criteria(
        [chunk("CH1", "4. 제안서 평가기준", label="4"),
         chunk("CH2", raw, page=6, label="4.1")],
        notice_id="notice", notice_version_id="version",
        structured_extract=model_answer({
            "title": "사업 수행능력", "raw": raw, "max_score": 20,
            "evaluation_method": "QUANTITATIVE",
        }),
    )
    assert result.analysis.status == "SUCCEEDED"
    assert len(result.analysis.criteria) == 1
    assert result.analysis.criteria[0].notice_version_id == "version"
    assert result.evidence[0].location.page == 6
    assert result.evidence[0].document_id == "doc"
    assert result.evidence[0].quote == raw
    assert result.analysis.criteria[0].evidence_keys == [result.evidence[0].evidence_key]

def test_hallucinated_quote_and_score_rejected():
    raw = "사업 수행능력: 배점 20점"
    snippets = [chunk("C1", "4. 평가기준", label="4"),
                chunk("C2", raw, label="4.1")]
    response = model_answer(
        {"title": "가공된 점수", "raw": raw, "max_score": 80, "evaluation_method": "OTHER"},
        {"title": "없는 항목", "raw": "인증 100점", "max_score": 100, "evaluation_method": "OTHER"},
    )
    result = extract_evaluation_criteria(snippets, notice_id="n", notice_version_id="v", structured_extract=response)
    assert result.analysis.status == "PARTIAL"
    assert result.analysis.criteria == []
    assert {d["code"] for d in result.analysis.diagnostics} == {"UNVERIFIED_SCORE", "EVALUATION_SOURCE_NOT_FOUND"}

def test_no_rubric_must_not_be_misreported_as_success():
    result = extract_evaluation_criteria(
        [chunk("C1", "3. 참가자격 및 지역제한", label="3")],
        notice_id="n", notice_version_id="v", structured_extract=model_answer(),
    )
    assert result.analysis.status == "PARTIAL"
    assert result.analysis.criteria == []

def test_extractor_failure_never_generates_criteria():
    def fail(*_args):
        raise ConnectionError("mocked offline failure")
    result = extract_evaluation_criteria(
        [chunk("C1", "4. 평가기준: 배점 100점", label="4")],
        notice_id="n", notice_version_id="v", structured_extract=fail,
    )
    assert result.analysis.status == "FAILED"
    assert result.analysis.criteria == []

def test_doc_boundary_does_not_capture_next_document():
    chunks = [chunk("C1", "4. 평가기준", document="d1", label="4"),
              chunk("C2", "4.1 10점", document="d2", label="4.1"),
              chunk("C3", "5. 제출서류", document="d2", label="5")]
    assert [r["chunk_id"] for r in select_evaluation_chunks(chunks)] == ["C1", "C2"]
