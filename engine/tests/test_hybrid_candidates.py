import pytest
from bidengine.labeling.hybrid_candidates import compare_eligibility_candidates
from bidengine.labeling.requirement_extraction import extract_legacy_slots

def chunk(i, text, doc="A", label=None):
    return {
        "chunk_id": str(i), "text": text, "clause_label": label,
        "source_blocks": [{"document_id": doc, "block_index": 0, "text": text}],
    }

def sample():
    return [
        chunk("A1", "3. 입찰참가자격", label="3"),
        chunk("A2", "3.1 서울 소재 업체", label="3.1"),
        chunk("A3", "4. 제안서 평가 80점", label="4"),
        chunk("B1", "참고 별첨: 기업규모 확인 필요", doc="B"),
        chunk("B2", "표 제목: 보유 인증", doc="B"),
        chunk("B3", "다만 유효한 등록증 보유해야 함", doc="B"),
    ]

def test_hybrid_preserves_section_and_adds_dense_context():
    base = compare_eligibility_candidates(sample(), dense_ranked_ids=["B3"], extra_budget=3)
    selected = {x["chunk_id"] for x in base.candidates}
    assert {"A1", "A2", "B3", "B2"} <= selected
    assert len(selected - set(base.section_ids)) <= 3
    assert base.dense_ids == ("B3",)
    assert len(base.fused_ids) == len(set(base.fused_ids))

def test_cross_document_neighbor_is_not_included():
    chunks = [chunk("A1", "입찰참가자격", label="3"),
              chunk("A2", "공고 기술평가", label="4"),
              chunk("B1", "관련 면허 취득", doc="B")]
    result = compare_eligibility_candidates(chunks, dense_ranked_ids=["A2"], extra_budget=1)
    assert set(x["chunk_id"] for x in result.candidates) <= {"A1", "A2", "B1"}
    assert len(result.candidates) <= len(result.section_ids) + 1

def test_foreign_embedding_ids_are_rejected():
    with pytest.raises(ValueError, match="current source"):
        compare_eligibility_candidates(sample(), dense_ranked_ids=["OTHER"])
    with pytest.raises(ValueError, match="unique"):
        compare_eligibility_candidates(sample(), dense_ranked_ids=["A2", "A2"])

def test_hybrid_legacy_extraction_is_opt_in_and_offline():
    called=[]
    def mock_extractor(_system, body, _schema):
        called.append(body)
        return {"requirements": []}
    result = extract_legacy_slots(sample(), structured_extract=mock_extractor,
                                  retrieval_mode="hybrid", dense_ranked_ids=["B3"], hybrid_extra_budget=4)
    assert result["selection_mode"].startswith("hybrid_")
    assert "B3" in result["target_chunk_ids"]
    assert len(called) == 1

def test_hybrid_rejects_bad_mode():
    with pytest.raises(ValueError, match="retrieval_mode"):
        extract_legacy_slots(sample(), structured_extract=lambda *_: {"requirements": []},
                             retrieval_mode="unbounded")
