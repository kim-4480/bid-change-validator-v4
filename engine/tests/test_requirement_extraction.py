from bidengine.document.backend_blocks import canonical_source_blocks
from bidengine.document.chunking import chunk_source_blocks
from bidengine.labeling.requirement_extraction import (
    SLOT_SCHEMA,
    extract_legacy_slots,
    select_eligibility_chunks,
    validate_extracted_slot,
)


def _chunks():
    blocks = canonical_source_blocks(
        document_id="doc-1",
        text_sha256="sha",
        blocks=[
            {
                "block_index": 0,
                "page": 3,
                "location": "p.3",
                "text": "3. 입찰 참가자격\n3.1 최근 3년 실적 5억원 이상\n3.2 서울 소재 업체\n3.3 중소기업자만 참가 가능",
            },
            {
                "block_index": 1,
                "page": 4,
                "location": "p.4",
                "text": "4. 제출서류\n실적증명서 제출",
            },
        ],
    )
    return chunk_source_blocks(blocks)


def test_slot_schema_exposes_all_canonical_extraction_paths():
    item_schema = SLOT_SCHEMA["schema"]["properties"]["requirements"]["items"]
    slot_types = set(item_schema["properties"]["유형"]["enum"])

    assert {
        "실적요건",
        "인력요건",
        "인증요건",
        "면허요건",
        "등록요건",
        "지역요건",
        "업종요건",
        "경험분야요건",
        "기업규모요건",
        "기타요건",
    } == slot_types
    for field_name in (
        "기간_raw",
        "금액_raw",
        "건수_raw",
        "업종_raw",
        "경험분야_raw",
        "지역_raw",
        "인원_raw",
        "인력역할_raw",
        "등록인증_raw",
        "발급기관_raw",
        "기업규모_raw",
        "실적기관_raw",
    ):
        assert field_name in item_schema["properties"]
    assert set(item_schema["required"]) == set(item_schema["properties"])


def test_select_eligibility_section_includes_children_until_next_top_level():
    selected = select_eligibility_chunks(_chunks())
    assert [chunk["clause_label"] for chunk in selected] == ["3", "3.1", "3.2", "3.3"]


def test_select_eligibility_section_does_not_cross_backend_document_boundary():
    doc_a = canonical_source_blocks(
        document_id="doc-a",
        text_sha256="sha-a",
        blocks=[
            {
                "block_index": 0,
                "page": 1,
                "location": "p.1",
                "text": "3. 입찰 참가자격\n3.1 최근 3년 실적 5억원 이상",
            }
        ],
    )
    doc_b = canonical_source_blocks(
        document_id="doc-b",
        text_sha256="sha-b",
        blocks=[
            {
                "block_index": 0,
                "page": 1,
                "location": "p.1",
                "text": "이 문장은 다른 문서의 서두이며 자격요건이 아니다.",
            }
        ],
    )

    chunks = chunk_source_blocks(doc_a)
    offset = len(chunks)
    for index, chunk in enumerate(chunk_source_blocks(doc_b), start=offset):
        chunks.append({**chunk, "chunk_id": f"CHUNK-{index:04d}"})

    selected = select_eligibility_chunks(chunks)
    selected_document_ids = {
        block["document_id"]
        for chunk in selected
        for block in chunk["source_blocks"]
    }
    assert selected_document_ids == {"doc-a"}


def test_validate_slot_rejects_hallucinated_raw():
    ok, reason, source = validate_extracted_slot(
        {
            "유형": "실적요건",
            "raw": "최근 5년 실적 10억원 이상",
            "기간_raw": "최근 5년",
            "금액_raw": "10억원 이상",
            "근거조항": "3.1",
        },
        _chunks(),
    )

    assert ok is False
    assert "본문에 존재하지 않음" in reason
    assert source is None


def test_validate_slot_rejects_hallucinated_detail_field():
    ok, reason, source = validate_extracted_slot(
        {
            "유형": "실적요건",
            "raw": "최근 3년 실적 5억원 이상",
            "기간_raw": "최근 3년",
            "금액_raw": "5억원 이상",
            "경험분야_raw": "공공기관 정보시스템 구축",
            "근거조항": "3.1",
        },
        _chunks(),
    )

    assert ok is False
    assert "경험분야_raw가 본문에 존재하지 않음" in reason
    assert source is not None


def test_validate_slot_rejects_hallucinated_company_size_detail():
    ok, reason, source = validate_extracted_slot(
        {
            "유형": "기업규모요건",
            "raw": "중소기업자만 참가 가능",
            "기업규모_raw": "대기업",
            "근거조항": "3.3",
        },
        _chunks(),
    )

    assert ok is False
    assert "기업규모_raw가 본문에 존재하지 않음" in reason
    assert source is not None


def test_validate_slot_clears_wrong_clause_reference_without_losing_requirement():
    slot = {
        "유형": "실적요건",
        "raw": "최근 3년 실적 5억원 이상",
        "기간_raw": "최근 3년",
        "금액_raw": "5억원 이상",
        "근거조항": "9.9",
    }
    ok, reason, source = validate_extracted_slot(slot, _chunks())

    assert ok is True
    assert reason == ""
    assert slot["근거조항"] is None
    assert source is not None


def test_extract_legacy_slots_keeps_source_provenance():
    def fake_extract(system, body, schema):
        assert "입찰 참가자격" in body
        assert "제출서류" not in body
        assert "문서 doc-1" in body
        assert schema["name"] == "eligibility_slots"
        return {
            "requirements": [
                {
                    "유형": "실적요건",
                    "raw": "최근 3년 실적 5억원 이상",
                    "기간_raw": "최근 3년",
                    "금액_raw": "5억원 이상",
                    "근거조항": "3.1",
                }
            ]
        }

    result = extract_legacy_slots(_chunks(), structured_extract=fake_extract)

    assert result["status"] == "ok"
    assert len(result["slots"]) == 1
    slot = result["slots"][0]
    assert slot["_source_chunk_id"] == "CHUNK-0001"
    assert slot["_source_blocks"][0]["page"] == 3
    assert slot["_source_blocks"][0]["document_id"] == "doc-1"


def test_extract_legacy_slots_retries_when_all_slots_fail_validation():
    calls = {"count": 0}

    def fake_extract(system, body, schema):
        calls["count"] += 1
        if calls["count"] == 1:
            return {
                "requirements": [
                    {
                        "유형": "실적요건",
                        "raw": "존재하지 않는 문장",
                        "근거조항": "3.1",
                    }
                ]
            }
        return {"requirements": []}

    result = extract_legacy_slots(_chunks(), structured_extract=fake_extract, max_retry=1)

    assert calls["count"] == 2
    assert result["status"] == "partial"
    assert result["slots"] == []
    assert result["dropped_requirements"] == [
        {
            "raw": "존재하지 않는 문장",
            "reason_code": "RAW_NOT_FOUND_IN_SOURCE",
        }
    ]


def test_quote_suffix_cannot_be_fabricated_after_matching_prefix():
    raw = "서울특별시에주된영업소를두고입찰공고일전일부터계약체결일까지계속하여해당소재지에서사업을운영하는업체는"
    assert not validate_extracted_slot({"raw": raw + " 모든 자격이 면제된다."}, [{"text": raw + " 등록하여야 한다."}])[0]
    assert validate_extracted_slot({"raw": "서울  소재\n업체"}, [{"text": "서울 소재 업체"}])[0]


def test_truncated_input_is_partial_and_not_silently_successful():
    chunks = [{"text": "서울 소재 업체\n" + "긴 원문 " * 10000, "chunk_id": "long"}]
    result = extract_legacy_slots(chunks, structured_extract=lambda *args: {"requirements": [{"유형": "지역요건", "raw": "서울 소재 업체", "지역_raw": "서울"}]})
    assert result["status"] == "partial"
    assert "길이 제한" in result["notes"]


def test_other_document_requirements_are_not_suppressed_by_section_anchor():
    chunks = _chunks() + [{"text": "개발 인력 5명 이상 보유", "chunk_id": "extra", "source_blocks": [{"document_id": "rfp"}]}]
    assert chunks[-1] in select_eligibility_chunks(chunks)


def test_clause_reference_must_belong_to_the_grounded_chunk():
    from bidengine.labeling.requirement_extraction import validate_extracted_slot
    chunks = [{"text": "안내문\n" * 40 + "2-1-1. 서울 소재 업체", "clause_label": "2"}, {"text": "9. 다른 문서", "clause_label": "9"}]
    assert validate_extracted_slot({"raw": "서울 소재 업체", "근거조항": "2-1-1"}, chunks)[0]
    slot = {"raw": "서울 소재 업체", "근거조항": "9"}
    assert validate_extracted_slot(slot, chunks)[0]
    assert slot["근거조항"] is None


def test_statute_citation_is_preserved_in_raw_not_document_location():
    raw = "국가계약법 시행령 제12조 및 시행규칙 제14조의 자격요건을 갖춘 자"
    slot = {"유형": "기타요건", "raw": raw, "근거조항": "제12조, 제14조"}
    assert validate_extracted_slot(slot, [{"text": raw, "clause_label": "2"}])[0]
    assert slot["raw"] == raw
    assert slot["근거조항"] is None


def test_valid_document_label_is_retained():
    slot = {"raw": "최근 3년 실적 5억원 이상", "근거조항": "3.1"}
    assert validate_extracted_slot(slot, _chunks())[0]
    assert slot["근거조항"] == "3.1"


def test_successful_retry_is_not_penalized_by_previous_rejection():
    answers = iter([
        {"requirements": [{"raw": "원문에 없는 요건"}]},
        {"requirements": [{"raw": "서울 소재 업체", "유형": "지역요건", "지역_raw": "서울"}]},
    ])
    result = extract_legacy_slots(_chunks(), structured_extract=lambda *args: next(answers))
    assert result["status"] == "ok"
    assert len(result["slots"]) == 1
    assert result["notes"] == ""


def test_section_body_under_korean_sub_labels_is_kept_as_children():
    """'3. 입찰참가자격' 아래의 가·나·다 항목은 그 절의 본문이지 다음 절이 아니다.

    예전에는 한 글자 한글 기호를 상위 제목으로 봐서 첫 '가.' 에서 자식 수집이 멈췄다.
    자격 절 본문이 통째로 빠졌고 그 항목들은 제목에 키워드가 없어 앵커도 못 됐다.
    전체 측정 수치는 fixture bundle을 포함한 골든 러너 결과로 별도 검증한다.
    """
    blocks = canonical_source_blocks(
        document_id="doc-k",
        text_sha256="sha-k",
        blocks=[
            {"block_index": 0, "page": 1, "location": "p.1", "text": "3. 입찰참가자격"},
            {"block_index": 1, "page": 1, "location": "p.1", "text": "가. 나라장터 입찰참가등록을 마친 자"},
            {"block_index": 2, "page": 1, "location": "p.1", "text": "나. 식품위생법에 의거 단체급식업 등록업체(업종코드 1450)"},
            {"block_index": 3, "page": 1, "location": "p.1", "text": "1) 등록증 사본 제출"},
            {"block_index": 4, "page": 1, "location": "p.1", "text": "다. 충청북도에 주된 영업소가 있는 업체"},
            {"block_index": 5, "page": 1, "location": "p.1", "text": "4. 입찰방법"},
            {"block_index": 6, "page": 1, "location": "p.1", "text": "가. 전자입찰"},
        ],
    )
    chunks = chunk_source_blocks(blocks)

    selected = "\n".join(chunk["text"] for chunk in select_eligibility_chunks(chunks))

    assert "1450" in selected and "충청북도" in selected and "등록증 사본" in selected
    # 다음 상위 절("4. 입찰방법")과 그 아래는 들어오지 않는다.
    assert "전자입찰" not in selected


def test_dotted_eligibility_heading_keeps_korean_children() -> None:
    blocks = canonical_source_blocks(
        document_id="doc-dotted",
        text_sha256="sha-dotted",
        blocks=[
            {"block_index": 0, "text": "3.1 입찰참가자격"},
            {"block_index": 1, "text": "가. 업종코드 1253 등록업체"},
            {"block_index": 2, "text": "나. 충청북도 소재 업체"},
            {"block_index": 3, "text": "3.2 입찰방법"},
            {"block_index": 4, "text": "가. 전자입찰"},
        ],
    )

    selected = "\n".join(
        chunk["text"]
        for chunk in select_eligibility_chunks(chunk_source_blocks(blocks))
    )

    assert "1253" in selected and "충청북도" in selected
    assert "전자입찰" not in selected


def test_parenthesized_number_can_be_an_eligibility_anchor() -> None:
    blocks = canonical_source_blocks(
        document_id="doc-paren",
        text_sha256="sha-paren",
        blocks=[
            {"block_index": 0, "text": "1) 입찰참가자격"},
            {"block_index": 1, "text": "가) 업종코드 1169 등록업체"},
            {"block_index": 2, "text": "나) 서울특별시 소재 업체"},
            {"block_index": 3, "text": "2) 제출서류"},
            {"block_index": 4, "text": "가) 법인등기부등본"},
        ],
    )

    selected = "\n".join(
        chunk["text"]
        for chunk in select_eligibility_chunks(chunk_source_blocks(blocks))
    )

    assert "1169" in selected and "서울특별시" in selected
    assert "법인등기부등본" not in selected


def test_grounding_normalizes_compatibility_dots_without_changing_raw() -> None:
    raw = "건설폐기물수집·운반업 (업종코드 : 6728)을 등록한 업체"
    source = "건설폐기물수집․운반업 (업종코드 : 6728)을 등록한 업체"
    slot = {"유형": "업종요건", "raw": raw, "업종_raw": "건설폐기물수집·운반업"}

    ok, reason, source_chunk = validate_extracted_slot(slot, [{"text": source}])

    assert ok is True
    assert reason == ""
    assert source_chunk is not None
    assert slot["raw"] == raw


def test_a_detail_in_a_neighbouring_chunk_is_still_grounded():
    """청크 경계는 우리가 자른 것이지 공고가 나눈 것이 아니다.

    실측(2026-09-14)에서 같은 조항이 한 실행에서는 요건으로 올라가고 다른 실행에서는
    DETAIL_NOT_FOUND_IN_SOURCE 로 버려졌다. 모델이 세부 조건을 어디까지 끊어 적느냐에
    따라 그 문자열이 옆 청크로 넘어가기 때문이다.
    """
    chunks = [
        {"text": "다. 입찰 공고일 기준 2년 내에 2개 이상 각 단체급식소를 운영한 실적이 있는 업체"},
        {"text": "※ 1일 평균 800식 이상, 1년 이상 운영한 실적에 한함"},
    ]
    slot = {
        "raw": "다. 입찰 공고일 기준 2년 내에 2개 이상 각 단체급식소를 운영한 실적이 있는 업체",
        "경험분야_raw": "1일 평균 800식 이상",
    }

    ok, reason, source_chunk = validate_extracted_slot(slot, chunks)

    assert ok, reason
    assert source_chunk is chunks[0]
    # 어디서 확인했는지는 남긴다 — 같은 청크가 아니었다는 사실 자체가 신호다.
    assert slot["_details_found_outside_source_chunk"] == ["경험분야_raw"]


def test_a_detail_found_nowhere_in_the_notice_is_still_rejected():
    """넓어진 것은 '어디서 찾는가' 이지 '무엇을 받아주는가' 가 아니다."""
    chunks = [
        {"text": "다. 최근 2년 내 단체급식소를 운영한 실적이 있는 업체"},
        {"text": "※ 관공서와 기업체에 한함"},
    ]
    slot = {
        "raw": "다. 최근 2년 내 단체급식소를 운영한 실적이 있는 업체",
        "금액_raw": "5억원 이상",  # 공고 어디에도 없다
    }

    ok, reason, _ = validate_extracted_slot(slot, chunks)

    assert not ok
    assert "금액_raw" in reason


def test_semicolon_joined_details_are_checked_part_by_part():
    """실측(2026-09-14)에서 나온 실제 값. 조각은 전부 원문에 있는데 이어붙인 문자열은 없다."""
    source = (
        "다. 입찰 공고일 기준 2년 내에 2개 이상 각 단체급식소※(1일 평균 800식 이상)를 "
        "1년 이상 운영한 실적이 있는 업체(실적증명)"
    )
    slot = {"raw": source, "기간_raw": "입찰 공고일 기준 2년 내에; 1년 이상"}

    ok, reason, _ = validate_extracted_slot(slot, [{"text": source}])

    assert ok, reason


def test_one_ungrounded_part_still_rejects_the_slot():
    """조각으로 나눈 것이 느슨해진다는 뜻은 아니다. 하나라도 근거가 없으면 버린다."""
    source = "다. 입찰 공고일 기준 2년 내에 운영한 실적이 있는 업체"
    slot = {"raw": source, "기간_raw": "입찰 공고일 기준 2년 내에; 5년 이상"}

    ok, reason, _ = validate_extracted_slot(slot, [{"text": source}])

    assert not ok
    assert "기간_raw" in reason
    assert slot["_rejected_detail"]["part"] == "5년 이상"


def test_a_decoration_mark_the_model_omits_does_not_break_grounding():
    """공고문은 눈에 띄라고 ※ 를 찍고, 모델은 인용할 때 그것을 빼고 적는다.

    실측(2026-09-14)에서 나온 실제 값이다. 같은 문장인데 기호 하나로 대조가 어긋났다.
    """
    source = "다. 2개 이상 각 단체급식소※(1일 평균 800식 이상)를 1년 이상 운영한 실적이 있는 업체"
    slot = {"raw": source, "경험분야_raw": "각 단체급식소(1일 평균 800식 이상)를 1년 이상 운영"}

    ok, reason, _ = validate_extracted_slot(slot, [{"text": source}])

    assert ok, reason


def test_comma_joined_details_are_checked_part_by_part():
    source = "나. 식품위생법에 따른 인·허가를 득하고 영업신고(업종코드 : 1450)를 한 업체"
    slot = {"raw": source, "등록인증_raw": "식품위생법에 따른 인·허가, 영업신고(업종코드 : 1450)"}

    ok, reason, _ = validate_extracted_slot(slot, [{"text": source}])

    assert ok, reason


def test_a_comma_inside_one_value_is_not_made_worse_by_splitting():
    """쉼표가 값 안에 있으면 쪼개기가 틀린다. 그래도 결과는 쪼개기 전과 같아야 한다."""
    source = "다. 대표자 전원의 성명을 모두 등재, 각자대표도 해당하는 업체"
    # 통째로 찾히는 경우 — 쪼개지 않는다
    ok, _, _ = validate_extracted_slot(
        {"raw": source, "등록인증_raw": "대표자 전원의 성명을 모두 등재, 각자대표도 해당"},
        [{"text": source}],
    )
    assert ok
    # 지어낸 값은 쪼개도 조각이 원문에 없어 그대로 버려진다
    ok, reason, _ = validate_extracted_slot(
        {"raw": source, "등록인증_raw": "대표자 전원의 성명을 모두 등재, 감사 선임 완료"},
        [{"text": source}],
    )
    assert not ok
    assert "등록인증_raw" in reason


def test_the_stored_detail_is_the_source_span_not_what_the_model_wrote():
    """모델이 적은 글자를 그대로 저장하지 않는다. 원문에서 잘라 온다.

    모델은 원문을 그대로 옮기라고 해도 옮기지 않는다 — ※ 를 빼고, 조사를 다듬는다.
    그 결과가 실행마다 다르고 판정과 차수 비교가 그 글자를 본다. 모델 값은 가리키는
    손가락으로만 쓰고, 저장은 원문에서 한다.
    """
    source = "다. 2개 이상 각 단체급식소※(1일 평균 800식 이상)를 1년 이상 운영한 실적이 있는 업체"
    slot = {"raw": source, "건수_raw": "2개이상"}

    ok, reason, _ = validate_extracted_slot(slot, [{"text": source}])

    assert ok, reason
    assert slot["건수_raw"] == "2개 이상"  # 모델이 적은 "2개이상" 이 아니다


def test_a_prose_detail_is_widened_to_its_sentence():
    """모델이 같은 문장에서 어디까지 끊어 적을지가 실행마다 다르다.

    스냅은 '원문과 다른 글자' 를 없앨 뿐 '어디부터 어디까지' 를 정하지 않는다.
    경험분야는 문장 경계까지 넓혀 셋이 같은 값이 되게 한다.
    """
    source = (
        "나. 단체급식업 등록업체이어야 한다.\n"
        "다. 2개 이상 각 단체급식소※(1일 평균 800식 이상)를 1년 이상 운영한 실적이 있는 업체\n"
        "라. 설명회에 참가한 업체"
    )
    # 항목 라벨("다.")은 문장 경계로 떨어져 나간다. 값에 들어가 봐야 도움이 안 된다.
    sentence = "2개 이상 각 단체급식소※(1일 평균 800식 이상)를 1년 이상 운영한 실적이 있는 업체"

    widened = set()
    for written in [
        "각 단체급식소(1일 평균 800식 이상)를 1년 이상 운영",
        "단체급식소",
        "각 단체급식소(1일 평균 800식 이상)를 1년 이상 운영한 실적",
    ]:
        slot = {"raw": source, "경험분야_raw": written}
        ok, reason, _ = validate_extracted_slot(slot, [{"text": source}])
        assert ok, reason
        widened.add(slot["경험분야_raw"])

    assert widened == {sentence}


def test_a_value_matched_detail_is_not_widened():
    """지역·업종처럼 값 자체를 회사 프로필과 맞대는 필드는 넓히면 비교가 깨진다."""
    source = "가. 주된 영업소의 소재지가 전북특별자치도에 있는 업체만 참가할 수 있다."
    slot = {"raw": source, "지역_raw": "전북특별자치도"}

    ok, _, _ = validate_extracted_slot(slot, [{"text": source}])

    assert ok
    assert slot["지역_raw"] == "전북특별자치도"
