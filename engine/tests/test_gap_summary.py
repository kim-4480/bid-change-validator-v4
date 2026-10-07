"""요건으로 정리하지 못한 조항을 확인용 문장으로 바꾼다 — 2026-10-07 사용자 요청."""
from bidengine.labeling.gap_summary import SCHEMA, context_before, summarize_gaps, summary_is_grounded, summary_key
from bidengine.pipeline.analysis_pipeline import (
    QualificationAnalysisInput,
    QualificationDocumentInput,
    analyze_qualification_documents,
)

FACILITY = "다. 납품할 종자를 생산할 수 있는 생산시설(친어지, 부화지, 치어사육지)을 갖춘 자로서 직접 자가생산하며"


def test_summary_must_stay_within_the_source():
    good = "친어지·부화지·치어사육지 등 종자 생산시설을 갖추고 납품할 종자를 직접 생산해야 합니다."
    assert summary_is_grounded(good, FACILITY)
    assert not summary_is_grounded("생산시설 3곳 이상을 갖추어야 합니다.", FACILITY)        # 원문에 없는 숫자
    assert not summary_is_grounded("생산시설이 있으면 참가 가능합니다.", FACILITY)          # 판정 말
    assert not summary_is_grounded("가" * 200, FACILITY)                                     # 너무 길다
    assert summary_is_grounded("최근 3년간 1억원 이상 실적이 있어야 합니다.", "최근 3년간 1억원 이상의 실적")


def test_answers_are_checked_and_remembered():
    calls = []

    def model(system, body, schema):
        calls.append(schema["name"])
        return {"items": [{"id": "G1", "category": "FACILITY_EQUIPMENT", "summary": "종자 생산시설(친어지·부화지·치어사육지)을 갖추어야 합니다."},
                          {"id": "G2", "category": "PERFORMANCE", "summary": "최근 5년간 실적이 있어야 합니다."}]}

    gaps = [{"raw": FACILITY, "context": "4. 입찰참가자격"}, {"raw": "라. 납품 실적이 있는 자", "context": ""}]
    memory: dict = {}
    out = summarize_gaps(gaps, structured_extract=model, memory=memory)
    first = summary_key(FACILITY, "4. 입찰참가자격")
    assert out == {first: {"category": "FACILITY_EQUIPMENT", "summary": "종자 생산시설(친어지·부화지·치어사육지)을 갖추어야 합니다."}}
    assert list(memory) == [first]                       # '5년' 을 지어낸 G2 는 버리고 기억하지 않는다
    again = summarize_gaps(gaps[:1], structured_extract=model, memory=memory)
    assert again == out and calls == ["gap_summary"]     # 기억한 조항은 다시 묻지 않는다


def test_failed_call_leaves_the_raw_text_only():
    def broken(system, body, schema):
        raise RuntimeError("timeout")

    assert summarize_gaps([{"raw": FACILITY, "context": ""}], structured_extract=broken) == {}


def test_context_is_the_text_just_before_the_clause():
    chunks = [{"text": "4. 입찰참가자격\n가. 강원특별자치도 업체\n" + FACILITY}]
    assert context_before(FACILITY, chunks).endswith("가. 강원특별자치도 업체")


def test_pipeline_attaches_category_and_summary_to_gaps():
    section = "2. 입찰참가자격\n가. 본점 소재지가 강릉시인 업체\n" + FACILITY + "\n3. 입찰보증금"

    import re

    def model(system, body, schema):
        if schema is SCHEMA:
            return {"items": [{"id": "G1", "category": "FACILITY_EQUIPMENT", "summary": "종자 생산시설을 갖추고 직접 생산해야 합니다."}]}
        # 생산시설 조항은 '요구' 인데 담을 닫힌 값이 없다 → 요건으로 정리하지 못한 조항(공백)이 된다.
        clauses = []
        for block in body.split("\n\n"):
            cid = re.match(r"\[(C\d+)\]", block)
            if cid:
                clauses.append({"clause_id": cid.group(1), "polarity": "POSITIVE" if "생산시설" in block else "NOT_REQUIREMENT",
                                "candidates": [], "open_requirements": []})
        return {"clauses": clauses}

    result = analyze_qualification_documents(
        QualificationAnalysisInput(notice_id="n", notice_version_id="v",
                                   documents=[QualificationDocumentInput(document_id="d", extracted_blocks=[{"text": section}])]),
        structured_extract=model, extraction_mode="closed_first", clause_selection="code",
    )
    described = [(g.category, g.summary) for g in result.coverage.gaps if "생산시설" in g.raw]
    assert described and all(item == ("FACILITY_EQUIPMENT", "종자 생산시설을 갖추고 직접 생산해야 합니다.") for item in described)
