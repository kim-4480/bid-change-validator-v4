"""조항 단위 추출(S3): 경계와 원문은 코드가, 라벨은 모델이."""
from __future__ import annotations

from bidengine.clauses.enumerate import enumerate_clauses
from bidengine.labeling.clause_labeling import CLAUSE_SCHEMA, extract_clause_slots
from bidengine.pipeline.analysis_pipeline import (
    QualificationAnalysisInput,
    QualificationDocumentInput,
    analyze_qualification_documents,
)

SECTION = """3. 입찰참가자격
□ 아래의 자격을 모두 갖춘 자
ㅇ 「국가종합전자조달시스템 입찰참가자격등록규정」에 의하여 나라장터(G2B)에 다음 분야의 입찰참가자격을 전자입찰서 제출마감일 전일까지 등록한 자
- 소프트웨어사업(컴퓨터관련서비스사업, 업종코드: 1468)
ㅇ 사업금액 20억 미만의 사업으로서 대기업 및 중견기업 참여 제한
ㅇ 본점 소재지가 서울특별시 또는 경기도에 있는 업체
※ 다만, 공동수급의 경우 구성원 모두 해당
4. 입찰보증금"""

CHUNK = {"chunk_id": "K0", "clause_label": "3", "text": SECTION, "source_blocks": [{"document_id": "d", "block_index": 0}]}


def test_enumeration_follows_item_markers_and_keeps_continuations():
    clauses = enumerate_clauses([CHUNK])
    assert [c.clause_id for c in clauses] == ["C001", "C002", "C003", "C004", "C005", "C006"]
    assert clauses[2].text.endswith("- 소프트웨어사업(컴퓨터관련서비스사업, 업종코드: 1468)")  # 하위 줄은 우산 조항에 붙는다
    assert clauses[4].text.endswith("※ 다만, 공동수급의 경우 구성원 모두 해당")      # 단서는 조항에 남는다


def test_enumeration_is_deterministic():
    assert [c.text for c in enumerate_clauses([CHUNK])] == [c.text for c in enumerate_clauses([CHUNK])]


def _slot(유형, **fields):
    names = CLAUSE_SCHEMA["schema"]["properties"]["clauses"]["items"]["properties"]["requirements"]["items"]["required"]
    slot = {name: None for name in names}
    slot.update({"유형": 유형, **fields})
    return slot


def fake_extractor(system, body, schema):
    assert "[C003]" in body and schema is CLAUSE_SCHEMA
    return {"clauses": [
        {"clause_id": "C001", "requirements": []},
        {"clause_id": "C003", "requirements": [_slot("등록요건", 등록인증_raw="소프트웨어사업(컴퓨터관련서비스사업, 업종코드: 1468)")]},
        {"clause_id": "C004", "requirements": [_slot("기업규모요건", 기업규모_raw="대기업 및 중견기업")]},
        {"clause_id": "C999", "requirements": [_slot("지역요건", 지역_raw="부산광역시")]},  # 없는 id
    ]}


def test_raw_is_the_clause_text_and_unknown_ids_are_ignored():
    result = extract_clause_slots([CHUNK], structured_extract=fake_extractor)
    assert result["status"] == "ok"
    assert [s["_clause_id"] for s in result["slots"]] == ["C003", "C004"]
    assert result["slots"][1]["raw"] == "ㅇ 사업금액 20억 미만의 사업으로서 대기업 및 중견기업 참여 제한"
    assert "없는 조항 id 1건" in result["notes"]
    assert result["selection_mode"] == "anchored"


def test_detail_not_in_clause_source_is_dropped():
    def invented(system, body, schema):
        return {"clauses": [{"clause_id": "C005", "requirements": [_slot("지역요건", 지역_raw="부산광역시")]}]}

    result = extract_clause_slots([CHUNK], structured_extract=invented)
    assert result["slots"] == []
    assert len(result["dropped_requirements"]) == 1


def test_pipeline_clause_mode_produces_canonical_requirements():
    analysis = analyze_qualification_documents(
        QualificationAnalysisInput(
            notice_id="n", notice_version_id="v",
            documents=[QualificationDocumentInput(document_id="d", extracted_blocks=[{"text": SECTION}])],
        ),
        structured_extract=lambda s, b, sc: {"clauses": [
            {"clause_id": c, "requirements": r} for c, r in {
                "C003": [_slot("등록요건", 등록인증_raw="소프트웨어사업(컴퓨터관련서비스사업, 업종코드: 1468)")],
                "C004": [_slot("기업규모요건", 기업규모_raw="대기업 및 중견기업")],
            }.items()
        ]},
        extraction_mode="clause",
    )
    assert sorted((r.type, str(r.value)) for r in analysis.requirements) == [
        ("COMPANY_SIZE", "대기업 및 중견기업"), ("INDUSTRY", "1468"),
    ]


PARAGRAPHS = """2. 입찰참가자격
국가를 당사자로 하는 계약에 관한 법률시행령 제12조에 의한 소정의 자격을 갖춘 업체
사업자등록증의 종목에 의료기기(또는 의료용기기, 의료용기구및기기)로 등록된 업체.
※ 자격제한 : 공고일 기준으로 부정당 업체 지정 및 폐업신고수리를 받은 업체는 응모할 수 없으며
자격심사 후라도 상기 사항이 발견되면 계약을 취소함.
※ 단, 공동수급의 경우 구성원 모두 해당"""


def test_paragraphs_without_markers_become_separate_clauses():
    """C02 실측: 항목 기호 없이 문단으로만 쓴 공고. 배제 주석이 요건 문단에 붙으면 안 된다."""
    clauses = [c.text for c in enumerate_clauses([{"chunk_id": "K", "text": PARAGRAPHS}])]
    assert "사업자등록증의 종목에 의료기기(또는 의료용기기, 의료용기구및기기)로 등록된 업체." in clauses
    exclusion = next(text for text in clauses if text.startswith("※ 자격제한"))
    assert "응모할 수 없으며\n자격심사 후라도" in exclusion  # 문장 중간 줄바꿈은 이어 붙인다
    assert clauses[-1].endswith("※ 단, 공동수급의 경우 구성원 모두 해당")  # 단서는 앞 조항에 붙는다


def _one_chunk(*lines):
    return [{"chunk_id": "K", "text": chr(10).join(lines)}]


def test_sentence_children_under_a_heading_become_separate_clauses():
    clauses = [c.text for c in enumerate_clauses(_one_chunk(
        "가. 공통자격",
        "- 사업자등록증상 소프트웨어 개발·공급업을 영위하고 소프트웨어사업자(업종코드 1468)로 나라장",
        "터에 등록한 자",
        "- 「중소기업기본법」에 따른 중소기업자로서 유효한 중소기업 확인서를 소지한 자",
    ))]
    assert len(clauses) == 3
    assert clauses[1].endswith("터에 등록한 자")          # 줄바꿈으로 이어진 줄은 같은 조항이다
    assert clauses[2].startswith("- 「중소기업기본법」")


def test_children_stay_with_an_umbrella_that_states_alternatives():
    clauses = enumerate_clauses(_one_chunk(
        "가. 다음 중 하나에 해당하는 자",
        "- 「소프트웨어 진흥법」에 따른 소프트웨어사업자로 나라장터에 등록한 자",
        "- 「정보통신공사업법」에 따른 정보통신공사업을 등록한 자",
    ))
    assert len(clauses) == 1   # 나누면 '하나만' 이 사라진다


def test_line_ending_in_poham_is_not_a_sentence_end():
    clauses = enumerate_clauses(_one_chunk(
        "4. 최근 5년 이내 벌꿀 농축설비 또는 벌꿀 농축공정이 포함",
        "된 가공 생산라인의 완료실적 누계가 400,000,000원 이상인 자",
    ))
    assert len(clauses) == 1


def test_mode_is_taken_from_environment_when_not_given(monkeypatch):
    calls = []

    def recorder(system, body, schema):
        calls.append(schema["name"])
        return {"clauses": []} if schema["name"] == "clause_labels" else {"requirements": []}

    doc = QualificationAnalysisInput(notice_id="n", notice_version_id="v",
                                     documents=[QualificationDocumentInput(document_id="d", extracted_blocks=[{"text": SECTION}])])
    monkeypatch.setenv("BIDENGINE_EXTRACTION_MODE", "clause")
    analyze_qualification_documents(doc, structured_extract=recorder)
    monkeypatch.setenv("BIDENGINE_EXTRACTION_MODE", "legacy")
    analyze_qualification_documents(doc, structured_extract=recorder)
    assert calls == ["clause_labels", "eligibility_slots"]
