from bidengine.document.backend_blocks import canonical_source_blocks
from bidengine.document.chunking import chunk_source_blocks
from bidengine.requirements.legacy_slots import adapt_legacy_slot


def test_pdf_backend_block_contract_is_preserved() -> None:
    blocks = canonical_source_blocks(
        document_id="pdf-doc",
        file_sha256="pdf-file-sha",
        text_sha256="pdf-text-sha",
        blocks=[
            {
                "block_index": 0,
                "page": 14,
                "location": "p.14",
                "text": "입찰 참가자격 본문",
            }
        ],
    )

    assert blocks == [
        {
            "document_id": "pdf-doc",
            "block_index": 0,
            "page": 14,
            "section_index": None,
            "paragraph_index": None,
            "location": "p.14",
            "text": "입찰 참가자격 본문",
            "source_sha256": "pdf-file-sha",
            "extracted_text_sha256": "pdf-text-sha",
        }
    ]


def test_hwpx_backend_block_contract_is_preserved() -> None:
    blocks = canonical_source_blocks(
        document_id="hwpx-doc",
        file_sha256="hwpx-file-sha",
        text_sha256="hwpx-text-sha",
        blocks=[
            {
                "block_index": 3,
                "section_index": 1,
                "paragraph_index": 7,
                "location": "section 2 · paragraph 8",
                "text": "3.2 최근 3년 실적 5억원 이상",
            }
        ],
    )

    assert blocks[0]["document_id"] == "hwpx-doc"
    assert blocks[0]["section_index"] == 1
    assert blocks[0]["paragraph_index"] == 7
    assert blocks[0]["location"] == "section 2 · paragraph 8"
    assert blocks[0]["source_sha256"] == "hwpx-file-sha"
    assert blocks[0]["extracted_text_sha256"] == "hwpx-text-sha"


def test_merged_semantic_chunk_keeps_every_source_block_in_order() -> None:
    blocks = canonical_source_blocks(
        document_id="doc-1",
        file_sha256="file-sha",
        text_sha256="text-sha",
        blocks=[
            {
                "block_index": 0,
                "section_index": 0,
                "paragraph_index": 0,
                "location": "section 1 · paragraph 1",
                "text": "3. 참가자격",
            },
            {
                "block_index": 1,
                "section_index": 0,
                "paragraph_index": 1,
                "location": "section 1 · paragraph 2",
                "text": "최근 3년 실적 5억원 이상",
            },
            {
                "block_index": 2,
                "section_index": 0,
                "paragraph_index": 2,
                "location": "section 1 · paragraph 3",
                "text": "관련 증빙서류를 제출해야 한다.",
            },
        ],
    )

    chunks = chunk_source_blocks(blocks)

    assert len(chunks) == 1
    assert chunks[0]["clause_label"] == "3"
    assert [block["block_index"] for block in chunks[0]["source_blocks"]] == [0, 1, 2]
    assert [block["paragraph_index"] for block in chunks[0]["source_blocks"]] == [0, 1, 2]


def test_pdf_page_block_splits_multiple_headings_and_keeps_page_locator() -> None:
    blocks = canonical_source_blocks(
        document_id="pdf-doc",
        file_sha256="pdf-file-sha",
        text_sha256="pdf-text-sha",
        blocks=[
            {
                "block_index": 0,
                "page": 14,
                "location": "p.14",
                "text": (
                    "3. 참가자격\n"
                    "최근 3년 실적 5억원 이상\n"
                    "3.1 세부 실적요건\n"
                    "유사사업 실적 2건 이상\n"
                    "4. 제출서류\n"
                    "실적증명서를 제출해야 한다."
                ),
            }
        ],
    )

    chunks = chunk_source_blocks(blocks)

    assert [chunk["clause_label"] for chunk in chunks] == ["3", "3.1", "4"]
    assert all(chunk["source_blocks"][0]["page"] == 14 for chunk in chunks)
    assert all(chunk["source_blocks"][0]["document_id"] == "pdf-doc" for chunk in chunks)
    assert [chunk["source_blocks"][0]["source_line_start"] for chunk in chunks] == [1, 3, 5]
    assert [chunk["source_blocks"][0]["source_line_end"] for chunk in chunks] == [2, 4, 6]


def test_pdf_leading_text_before_first_heading_is_not_dropped() -> None:
    blocks = canonical_source_blocks(
        document_id="pdf-doc",
        file_sha256="pdf-file-sha",
        text_sha256="pdf-text-sha",
        blocks=[
            {
                "block_index": 0,
                "page": 2,
                "location": "p.2",
                "text": "계속되는 설명 문장\n2. 계약조건\n계약기간은 12개월이다.",
            }
        ],
    )

    chunks = chunk_source_blocks(blocks)

    assert chunks[0]["clause_label"] is None
    assert chunks[0]["text"] == "계속되는 설명 문장"
    assert chunks[0]["source_blocks"][0]["page"] == 2
    assert chunks[1]["clause_label"] == "2"
    assert "계약기간은 12개월이다." in chunks[1]["text"]


def test_backend_block_location_survives_semantic_chunking() -> None:
    blocks = canonical_source_blocks(
        document_id="doc-1",
        file_sha256="abc123",
        text_sha256="text123",
        blocks=[
            {"block_index": 0, "page": 3, "location": "p.3", "text": "3. 참가자격"},
            {"block_index": 1, "page": 3, "location": "p.3", "text": "3.1 최근 3년 실적 5억원 이상"},
        ],
    )
    chunks = chunk_source_blocks(blocks)

    assert chunks
    assert chunks[0]["source_blocks"][0]["document_id"] == "doc-1"
    assert chunks[0]["source_blocks"][0]["page"] == 3
    assert chunks[0]["source_blocks"][0]["source_sha256"] == "abc123"
    assert chunks[0]["source_blocks"][0]["extracted_text_sha256"] == "text123"


def test_legacy_performance_slot_maps_to_atomic_requirements() -> None:
    slot = {
        "유형": "실적요건",
        "raw": "최근 3년 실적 2건 이상, 합계 4억원 이상",
        "기간_norm": {"parse_status": "success", "value": 36},
        "금액_norm": {
            "parse_status": "success",
            "value": 400000000,
            "unit": "KRW",
            "op": ">=",
        },
    }

    requirements, diagnostics = adapt_legacy_slot(
        slot,
        notice_version_id="version-1",
        key_prefix="REQ-001",
    )

    assert diagnostics == []
    assert {requirement.type for requirement in requirements} == {
        "PERFORMANCE_AMOUNT",
        "PERFORMANCE_COUNT",
    }
    assert all(requirement.requirement_group_key == "REQ-001-GROUP" for requirement in requirements)


def test_performance_slot_can_add_experience_field_to_same_group() -> None:
    requirements, diagnostics = adapt_legacy_slot(
        {
            "유형": "실적요건",
            "raw": "최근 3년 공공기관 정보시스템 구축 실적 2건 이상",
            "기간_norm": {"parse_status": "success", "value": 36},
            "경험분야_raw": "공공기관 정보시스템 구축",
            "실적기관_raw": "공공기관",
        },
        notice_version_id="version-1",
        key_prefix="REQ-EXP",
    )

    assert diagnostics == []
    assert {requirement.type for requirement in requirements} == {
        "PERFORMANCE_COUNT",
        "EXPERIENCE_FIELD",
    }
    experience = next(item for item in requirements if item.type == "EXPERIENCE_FIELD")
    assert experience.value == "공공기관 정보시스템 구축"
    assert experience.operator == "MATCH"
    assert experience.period_months == 36
    assert experience.scope["client_requirement"] == "공공기관"
    assert all(item.requirement_group_key == "REQ-EXP-GROUP" for item in requirements)


def test_industry_slot_maps_to_canonical_industry_requirement() -> None:
    requirements, diagnostics = adapt_legacy_slot(
        {
            "유형": "업종요건",
            "raw": "소프트웨어사업자 업종으로 등록한 업체",
            "업종_raw": "소프트웨어사업자",
        },
        notice_version_id="version-1",
        key_prefix="REQ-IND",
    )

    assert diagnostics == []
    assert len(requirements) == 1
    assert requirements[0].type == "INDUSTRY"
    assert requirements[0].operator == "MATCH"
    assert requirements[0].value == "소프트웨어사업자"


def test_standalone_experience_field_slot_maps_to_canonical_requirement() -> None:
    requirements, diagnostics = adapt_legacy_slot(
        {
            "유형": "경험분야요건",
            "raw": "공공기관 정보시스템 구축 경험을 보유한 업체",
            "경험분야_raw": "공공기관 정보시스템 구축",
        },
        notice_version_id="version-1",
        key_prefix="REQ-FIELD",
    )

    assert diagnostics == []
    assert len(requirements) == 1
    assert requirements[0].type == "EXPERIENCE_FIELD"
    assert requirements[0].operator == "MATCH"
    assert requirements[0].value == "공공기관 정보시스템 구축"


def test_region_staff_certification_and_company_size_have_judgment_operands() -> None:
    cases = [
        (
            {
                "유형": "지역요건",
                "raw": "서울특별시 소재 업체",
                "지역_raw": "서울특별시",
            },
            "REGION",
            "서울특별시",
            "MATCH",
        ),
        (
            {
                "유형": "인력요건",
                "raw": "정보처리기사 2명 이상 보유",
                "인력역할_raw": "정보처리기사",
                "인원_norm": {
                    "parse_status": "success",
                    "value": 2,
                    "unit": "PERSON",
                    "op": ">=",
                },
            },
            "STAFF",
            2,
            ">=",
        ),
        (
            {
                "유형": "등록요건",
                "raw": "정보통신공사업 등록업체",
                "등록인증_raw": "정보통신공사업",
            },
            "REGISTRATION_CERTIFICATION",
            "정보통신공사업",
            "MATCH",
        ),
        (
            {
                "유형": "기업규모요건",
                "raw": "중소기업자만 참가 가능",
                "기업규모_raw": "중소기업",
            },
            "COMPANY_SIZE",
            "중소기업",
            "MATCH",
        ),
    ]

    for index, (slot, expected_type, expected_value, expected_operator) in enumerate(cases):
        requirements, diagnostics = adapt_legacy_slot(
            slot,
            notice_version_id="version-1",
            key_prefix=f"REQ-{index}",
        )
        assert diagnostics == []
        assert len(requirements) == 1
        requirement = requirements[0]
        assert requirement.type == expected_type
        assert requirement.value == expected_value
        assert requirement.operator == expected_operator


def test_amount_range_is_preserved_in_canonical_scope() -> None:
    requirements, diagnostics = adapt_legacy_slot(
        {
            "유형": "실적요건",
            "raw": "실적금액 2억원 이상 5억원 이하",
            "금액_norm": {
                "parse_status": "success",
                "value": None,
                "unit": "KRW",
                "op": None,
                "range": {
                    "min": 200000000,
                    "min_op": ">=",
                    "max": 500000000,
                    "max_op": "<=",
                },
            },
        },
        notice_version_id="version-1",
        key_prefix="REQ-RANGE",
    )

    assert diagnostics == []
    requirement = requirements[0]
    assert requirement.type == "PERFORMANCE_AMOUNT"
    assert requirement.operator == "RANGE"
    assert requirement.value is None
    assert requirement.scope["min"] == 200000000
    assert requirement.scope["max"] == 500000000


def test_legacy_other_requirement_stays_diagnostic() -> None:
    requirements, diagnostics = adapt_legacy_slot(
        {"유형": "기타요건", "raw": "자동 판정 범위 밖의 복합 조건"},
        notice_version_id="version-1",
        key_prefix="REQ-002",
    )

    assert requirements == []
    assert diagnostics[0]["code"] == "UNMAPPED_REQUIREMENT"
