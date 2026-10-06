"""닫힌 값 먼저(closed_first): 코드가 후보를 찾고, 모델은 역할만 정하고, 코드가 요건을 만든다."""
from __future__ import annotations

from bidengine.labeling.closed_first import SCHEMA, scan_candidates
from bidengine.pipeline.analysis_pipeline import (
    QualificationAnalysisInput,
    QualificationDocumentInput,
    analyze_qualification_documents,
)
from bidengine.pipeline.analysis_result import clause_accounting

SECTION = """3. 입찰참가자격
가. 관광진흥법에 의한 종합여행업(업종코드 1 2 6 1) 또는 국내외여행업(업종코드 1262)으로 등록한 업체
나. 본점 소재지가 전주시인 업체이어야 합니다. 납품장소: 서울특별시 중구
다. 중기업·소기업 또는 소상공인으로서 확인서를 소지한 업체
라. 대기업 및 중견기업은 참여할 수 없습니다.
마. 최근 3년 이내 단일 계약 1억원 이상의 행사 대행 실적이 있는 업체
4. 입찰보증금"""


class Resolver:
    def code_for(self, name):
        return None


def test_candidates_are_found_by_code():
    found = {(c.kind, c.value) for c in scan_candidates(SECTION, Resolver())}
    assert ("INDUSTRY", "1261") in found and ("INDUSTRY", "1262") in found
    assert ("REGION", "전주시") in found and ("REGION", "서울특별시 중구") in found
    assert {("SIZE", "중기업"), ("SIZE", "소기업"), ("SIZE", "소상공인"), ("SIZE", "대기업")} <= found


def fake_model(system, body, schema):
    if schema is not SCHEMA:
        return {"clauses": []}  # 조항 선택 호출(code 선택이면 부르지 않는다)
    answers = []
    for block in body.split("\n\n"):
        head = block.split("\n", 1)[0]
        cid = head[1:5]
        ids = {part.split()[0]: part for part in head.split("후보: ", 1)[1].split("; ")} if "후보: V" in head else {}
        text = block.split("\n", 1)[1]
        roles, polarity, open_reqs = [], "NOT_REQUIREMENT", []
        if "여행업" in text:
            polarity = "POSITIVE"
            roles = [{"id": i, "role": "ALTERNATIVE", "group": "G1"} for i in ids]
        elif "전주시" in text:
            polarity = "POSITIVE"
            roles = [{"id": i, "role": "REQUIRED" if "전주시" in p else "NOT_RELATED", "group": ""} for i, p in ids.items()]
        elif "소상공인" in text:
            polarity = "POSITIVE"
            roles = [{"id": i, "role": "ALTERNATIVE", "group": "G1"} for i in ids]
        elif "대기업" in text:
            polarity = "EXCLUSION"
            roles = [{"id": i, "role": "EXCLUDED", "group": ""} for i in ids]
        elif "실적" in text:
            polarity = "POSITIVE"
            open_reqs = [{name: None for name in SCHEMA["schema"]["properties"]["clauses"]["items"]["properties"]["open_requirements"]["items"]["required"]}
                         | {"유형": "실적요건", "기간_raw": "최근 3년 이내", "금액_raw": "1억원 이상", "경험분야_raw": "행사 대행"}]
        answers.append({"clause_id": cid, "polarity": polarity, "candidates": roles, "open_requirements": open_reqs})
    return {"clauses": answers}


def _analyze(memory=None):
    return analyze_qualification_documents(
        QualificationAnalysisInput(notice_id="n", notice_version_id="v", documents=[
            QualificationDocumentInput(document_id="d", extracted_blocks=[{"block_index": 0, "text": SECTION}])]),
        structured_extract=fake_model, extraction_mode="closed_first", clause_selection="code",
        industry_resolver=Resolver(), labeling_memory=memory, memory_namespace="fake",
    )


def test_roles_become_requirements_without_retyping():
    result = _analyze()
    got = {(r.type, str(r.value), r.group_operator, r.scope.get("restriction")) for r in result.requirements}
    assert ("INDUSTRY", "1261", "ANY_OF", None) in got and ("INDUSTRY", "1262", "ANY_OF", None) in got
    assert ("REGION", "전주시", "ALL_OF", None) in got
    assert not any(t == "REGION" and "중구" in v for t, v, _g, _r in got)  # 납품 장소는 요건이 아니다
    assert ("COMPANY_SIZE", "중소기업", "ALL_OF", None) in got            # 중기업∪소기업∪소상공인
    assert ("COMPANY_SIZE", "대기업 및 중견기업", "ALL_OF", "EXCLUDE") in got
    assert any(r.type == "PERFORMANCE_AMOUNT" for r in result.requirements)


def test_every_clause_has_a_visible_outcome_and_answers_are_remembered():
    memory: dict = {}
    result = _analyze(memory)
    from bidengine.labeling.clause_labeling import select_clauses
    from bidengine.pipeline.analysis_pipeline import _build_global_chunks

    chunks = _build_global_chunks([QualificationDocumentInput(document_id="d", extracted_blocks=[{"block_index": 0, "text": SECTION}])], max_chunk_chars=1800)
    kept, *_ = select_clauses(chunks, structured_extract=fake_model)
    assert clause_accounting([c.text for c in kept], result) == []
    assert memory  # 답을 기억했다
    again = _analyze(memory)
    assert [(r.type, r.value) for r in again.requirements] == [(r.type, r.value) for r in result.requirements]
