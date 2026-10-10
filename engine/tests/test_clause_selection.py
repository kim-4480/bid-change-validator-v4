"""조항 선택에 모델을 쓰는 경로, 공통 결격 조항 분류, 문서 간 중복 정리 (2026-10-03)."""
from __future__ import annotations

import re

from bidengine.contracts import QualificationRequirement
from bidengine.labeling.clause_labeling import extract_clause_slots
from bidengine.labeling.clause_polarity import POLARITY_KEY
from bidengine.pipeline.analysis_result import build_requirement_analysis_result
from bidengine.requirements.deduplicate import deduplicate_requirements
from bidengine.requirements.legacy_slots import adapt_legacy_slot, is_common_disqualification


def _chunk(index, label, text):
    return {"chunk_id": f"K{index}", "clause_label": label, "text": text, "source_blocks": [{"document_id": "d"}]}


CHUNKS = [
    _chunk(0, "1", "1. 입찰에 부치는 사항"),
    _chunk(1, "마", "마. 본 입찰은 지역제한 입찰이며 본점 소재지가 충청남도에 있는 업체여야 합니다."),
    _chunk(2, "2", "2. 입찰참가자격"),
    _chunk(3, "가", "가. 실내건축공사업(4990)을 등록한 업체"),
    _chunk(4, "3", "3. 입찰보증금"),
    _chunk(5, "가", "가. 입찰보증금은 납부 확약서로 갈음합니다."),
]


def _extractor(pick: tuple[str, ...] = ("지역제한",), *, fail_selection: bool = False):
    """선택 호출에는 pick 낱말이 든 조항 id 를, 라벨링 호출에는 조항마다 등록요건 하나를 돌려준다."""
    calls = {"selection": 0, "labeling": []}

    def extract(_system, body, schema):
        entries = re.findall(r"\[(\w+)\]\n([^\[]+)", body)
        if schema["name"] == "eligibility_clause_selection":
            calls["selection"] += 1
            if fail_selection:
                raise RuntimeError("down")
            return {"clause_ids": [cid for cid, text in entries if any(word in text for word in pick)]}
        calls["labeling"].append([text.strip() for _cid, text in entries])
        return {"clauses": [{"clause_id": cid, "requirements": []} for cid, _text in entries]}

    return extract, calls


def _labelled(calls):
    return [text.split(".")[0] + "." + text.split(".")[1][:12] for text in calls["labeling"][0]]


def test_code_selection_does_not_see_clauses_outside_the_section():
    extract, calls = _extractor()
    result = extract_clause_slots(CHUNKS, structured_extract=extract)
    assert calls["selection"] == 0
    assert not any("지역제한" in text for text in calls["labeling"][0])
    assert result["selection_mode"] == "anchored"


def test_hybrid_adds_the_clauses_the_model_picked():
    extract, calls = _extractor()
    extract_clause_slots(CHUNKS, structured_extract=extract, clause_selection="hybrid")
    texts = calls["labeling"][0]
    assert any("지역제한" in text for text in texts)        # 모델이 고른, 자격 절 밖의 조항
    assert any("실내건축공사업" in text for text in texts)  # 코드가 고른 조항은 그대로
    assert not any("입찰보증금" in text for text in texts)


def test_model_selection_keeps_only_picked_clauses():
    extract, calls = _extractor(("지역제한", "실내건축"))
    extract_clause_slots(CHUNKS, structured_extract=extract, clause_selection="model")
    texts = calls["labeling"][0]
    assert len(texts) == 2 and not any(text.startswith("2. 입찰참가자격") for text in texts)


def test_model_selection_falls_back_to_code_when_nothing_is_picked_or_the_call_fails():
    extract, calls = _extractor(("없는낱말",))
    extract_clause_slots(CHUNKS, structured_extract=extract, clause_selection="model")
    assert any("실내건축공사업" in text for text in calls["labeling"][0])

    extract, calls = _extractor(fail_selection=True)
    result = extract_clause_slots(CHUNKS, structured_extract=extract, clause_selection="hybrid")
    assert any("실내건축공사업" in text for text in calls["labeling"][0])
    assert "코드 선택으로" in result["notes"]


def test_selection_is_remembered_per_clause():
    memory: dict[str, bool] = {}
    extract, calls = _extractor()
    extract_clause_slots(CHUNKS, structured_extract=extract, clause_selection="hybrid", selection_memory=memory)
    extract_clause_slots(CHUNKS, structured_extract=extract, clause_selection="hybrid", selection_memory=memory)
    assert calls["selection"] == 1                    # 같은 문장은 다시 묻지 않는다
    assert sum(memory.values()) == 1


def _adapt(slot, polarity):
    return adapt_legacy_slot({**slot, POLARITY_KEY: polarity}, notice_version_id="v", key_prefix="REQ-001")


def test_common_disqualification_is_procedural_not_a_coverage_gap():
    raw = "자. 조세포탈 등을 한 자로서 유죄판결이 확정된 날부터 2년이 지나지 않은 자는 입찰참가 불가"
    assert is_common_disqualification(raw)
    _requirements, diagnostics = _adapt({"유형": "기타요건", "raw": raw}, "EXCLUSION")
    assert diagnostics[0]["reason"] == "COMMON_DISQUALIFICATION"
    result = build_requirement_analysis_result(
        notice_id="n", notice_version_id="v", document_ids=["d"],
        canonicalized={"requirements": [], "evidence": [], "diagnostics": diagnostics},
        section_selection="anchored", candidate_count=1,
    )
    assert result.coverage.procedural == 1 and result.coverage.unrepresentable == 0

    # 닫힌 값이 있는 배제 조항은 실제 자격 조건이다 — 확인 필요로 남는다.
    assert not is_common_disqualification("종합건설사업자는 본 입찰의 입찰참가자격을 제한합니다")
    assert not is_common_disqualification("건설폐기물중간처리업(1253) 영업정지 중인 업체는 참가 불가")
    assert not is_common_disqualification("경기도에 소재한 업체로서 부정당업자 제재 중인 자는 참가 불가")
    _requirements, diagnostics = _adapt({"유형": "기타요건", "raw": "종합건설사업자의 참여를 제한합니다"}, "EXCLUSION")
    assert diagnostics[0]["reason"] == "MODEL_POLARITY_EXCLUSION"


def test_clause_the_model_reads_as_not_a_requirement_is_procedural():
    raw = "※ 확인서는 계약체결일까지 발급된 것으로 유효기간 내에 있어야 합니다."
    _requirements, diagnostics = _adapt({"유형": "인증요건", "raw": raw, "등록인증_raw": "확인서"}, "NOT_REQUIREMENT")
    result = build_requirement_analysis_result(
        notice_id="n", notice_version_id="v", document_ids=["d"],
        canonicalized={"requirements": [], "evidence": [], "diagnostics": diagnostics},
        section_selection="anchored", candidate_count=1,
    )
    assert result.coverage.procedural == 1 and result.coverage.complete


def test_product_code_is_the_value_whatever_name_the_model_quoted():
    raw = "2) 무선송수신기(세부품명번호: 4319151001)으로 입찰참가 등록한 업체로서, 제조 또는 납품할 수 있어야 합니다."
    for name in ("무선송수신기(세부품명번호: 4319151001)", "4319151001"):
        requirements, _ = _adapt({"유형": "등록요건", "raw": raw, "등록인증_raw": name}, "POSITIVE")
        assert [(r.type, r.value) for r in requirements] == [("REGISTRATION_CERTIFICATION", "4319151001")]


def _requirement(key, value, *, group, basis="code", raw="건축공사업(또는 토목건축공사업)을 등록한 자"):
    return QualificationRequirement(
        requirement_key=key, requirement_group_key=group, group_operator="ANY_OF", notice_version_id="v",
        type="INDUSTRY", operator="MATCH", value=value, scope={"guard": "assessed", "guard_basis": basis}, raw=raw,
    )


def test_identical_alternative_group_from_a_second_document_is_folded():
    first = [_requirement("A1", "0002", group="A"), _requirement("A2", "0003", group="A")]
    second = [_requirement("B1", "0002", group="B", basis="model_polarity", raw="건축공사업 ( 또는 토목건축공사업 ) 을 등록한 자"),
              _requirement("B2", "0003", group="B", basis="model_polarity", raw="건축공사업 ( 또는 토목건축공사업 ) 을 등록한 자")]
    kept, diagnostics = deduplicate_requirements(first + second)
    assert [r.requirement_key for r in kept] == ["A1", "A2"]
    assert [d["code"] for d in diagnostics] == ["DUPLICATE_REQUIREMENT", "DUPLICATE_REQUIREMENT"]


def test_alternative_groups_that_only_share_a_member_are_both_kept():
    first = [_requirement("A1", "0002", group="A"), _requirement("A2", "0003", group="A")]
    other = [_requirement("B1", "0002", group="B"), _requirement("B2", "0004", group="B")]
    kept, _ = deduplicate_requirements(first + other)
    assert [r.requirement_key for r in kept] == ["A1", "A2", "B1", "B2"]   # (A 또는 B) 그리고 (A 또는 C) 는 그대로


def test_joint_venture_clause_stays_for_review_whatever_the_model_says():
    from bidengine.judgment.context_guard import decide
    from bidengine.pipeline.analysis_pipeline import (
        QualificationAnalysisInput, QualificationDocumentInput, analyze_qualification_documents,
    )

    raw = "차. 본 입찰은 공동수급 및 하도급을 불허"
    assert decide(raw, "NOT_REQUIREMENT").action == "DEFAULT"
    _requirements, diagnostics = _adapt({"유형": "기타요건", "raw": raw}, "NOT_REQUIREMENT")
    assert diagnostics[0]["reason"] == "COMPOSITE_PARTY_RULE"

    # 모델이 그 조항에서 요건을 하나도 올리지 않아도 조항은 사라지지 않는다. 공동수급·하도급 허용 여부는 회사 자격이
    # 아니라 입찰 방식이라 확인 목록(공백)이 아니라 참고 정보(제외 목록, 이유 GAP_JOINT_CONTRACT_NOTE)로 간다(2026-10-07).
    section = "2. 입찰참가자격\n가. 실내건축공사업(4990)을 등록한 업체\n차. 본 입찰은 공동수급 및 하도급을 불허\n3. 입찰보증금"
    analysis = analyze_qualification_documents(
        QualificationAnalysisInput(
            notice_id="n", notice_version_id="v",
            documents=[QualificationDocumentInput(document_id="d", extracted_blocks=[{"text": section}])],
        ),
        structured_extract=lambda _s, _b, schema: {"clauses": []},
        extraction_mode="clause", polarity_guard=True,
    )
    assert [gap for gap in analysis.coverage.gaps if "공동수급" in gap.raw] == []
    assert [(gap.kind, gap.reason) for gap in analysis.coverage.ignored if "공동수급" in gap.raw] == [
        ("IGNORED", "GAP_JOINT_CONTRACT_NOTE")
    ]


def test_construction_work_name_with_a_code_is_an_industry_code():
    raw = "마. 건설산업기본법에 의한 [실내건축공사(4990)]을 등록하고 면허를 소지한 업체"
    requirements, _ = _adapt({"유형": "등록요건", "raw": raw, "등록인증_raw": "[실내건축공사(4990)]"}, "POSITIVE")
    assert [(r.type, r.value) for r in requirements] == [("INDUSTRY", "4990")]
    year = "가. 체육관 증축공사(2026) 설계 실적이 있는 업체"
    requirements, _ = _adapt({"유형": "등록요건", "raw": year, "등록인증_raw": "증축공사 설계"}, "POSITIVE")
    assert not any(r.type == "INDUSTRY" for r in requirements)


def test_section_path_tells_evaluation_items_from_requirements():
    from bidengine.labeling.clause_polarity import attach_clause_polarity
    from bidengine.labeling.requirement_extraction import section_paths

    chunks = [
        _chunk(0, "2", "2. 입찰참가자격"),
        _chunk(1, "가", "가. 최근 3년 콜센터 운영 실적이 있는 업체"),
        _chunk(2, "5", "5. 제안서 평가"),
        _chunk(3, "가", "가. 평가항목"),
        _chunk(4, None, "최근 3년 콜센터 운영 실적 6점"),
    ]
    paths = section_paths(chunks)
    assert paths["K1"] == "2. 입찰참가자격"
    assert paths["K4"] == "5. 제안서 평가 > 가. 평가항목"

    bodies = []

    def extractor(_system, body, _schema):
        bodies.append(body)
        return {"clauses": [{"clause_id": "P001", "polarity": "POSITIVE"}, {"clause_id": "P002", "polarity": "EVALUATION"}]}

    slots = [{"유형": "실적요건", "raw": "최근 3년 콜센터 운영 실적", "_section_path": paths["K1"]},
             {"유형": "실적요건", "raw": "최근 3년 콜센터 운영 실적", "_section_path": paths["K4"]}]
    attach_clause_polarity(slots, structured_extract=extractor, memory={})
    assert "위치: 5. 제안서 평가 > 가. 평가항목" in bodies[0]
    assert [slot[POLARITY_KEY] for slot in slots] == ["POSITIVE", "EVALUATION"]   # 같은 문장, 다른 위치, 다른 답


def test_evaluation_item_is_procedural_not_a_coverage_gap():
    raw = "최근 3년간 콜센터 운영 실적 100% 이상 배점의 100%"
    _requirements, diagnostics = _adapt({"유형": "실적요건", "raw": raw}, "EVALUATION")
    assert diagnostics[0]["reason"] == "MODEL_POLARITY_EVALUATION"
    result = build_requirement_analysis_result(
        notice_id="n", notice_version_id="v", document_ids=["d"],
        canonicalized={"requirements": [], "evidence": [], "diagnostics": diagnostics},
        section_selection="anchored", candidate_count=1,
    )
    assert result.coverage.procedural == 1 and result.coverage.unrepresentable == 0
