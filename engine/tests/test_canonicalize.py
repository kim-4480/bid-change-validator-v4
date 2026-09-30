from bidengine.requirements.canonicalize import canonicalize_validated_slot


def test_validated_slot_becomes_atomic_requirements_with_shared_evidence() -> None:
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
        "근거조항": "3.1",
        "_source_chunk_id": "CHUNK-0001",
        "_source_blocks": [
            {
                "document_id": "doc-1",
                "block_index": 4,
                "page": 14,
                "section_index": None,
                "paragraph_index": None,
                "location": "p.14",
                "source_line_start": 3,
                "source_line_end": 4,
                "source_sha256": "sha-1",
                "extracted_text_sha256": "text-sha-1",
                "text": "3.1 최근 3년 실적 2건 이상, 합계 4억원 이상",
            }
        ],
    }

    requirements, evidence, diagnostics = canonicalize_validated_slot(
        slot,
        notice_version_id="version-2",
        key_prefix="REQ-001",
    )

    assert diagnostics == []
    assert {requirement.type for requirement in requirements} == {
        "PERFORMANCE_AMOUNT",
        "PERFORMANCE_COUNT",
    }
    assert len(evidence) == 1
    assert evidence[0].evidence_key == "REQ-001-EVD"
    assert evidence[0].document_id == "doc-1"
    assert evidence[0].chunk_id == "CHUNK-0001"
    assert evidence[0].location.page == 14
    assert evidence[0].location.block_start == 4
    assert evidence[0].location.source_line_start == 3
    assert evidence[0].quote == slot["raw"]
    assert evidence[0].source_sha256 == "sha-1"
    assert evidence[0].extracted_text_sha256 == "text-sha-1"
    assert all(requirement.evidence_keys == ["REQ-001-EVD"] for requirement in requirements)


def test_hwpx_evidence_keeps_section_and_paragraph_without_fake_page() -> None:
    slot = {
        "유형": "지역요건",
        "raw": "서울특별시 소재 업체",
        "지역_raw": "서울특별시",
        "근거조항": "3.2",
        "_source_chunk_id": "CHUNK-0002",
        "_source_blocks": [
            {
                "document_id": "doc-hwpx",
                "block_index": 8,
                "page": None,
                "section_index": 1,
                "paragraph_index": 7,
                "location": "section 2 · paragraph 8",
                "source_sha256": "sha-hwpx",
                "extracted_text_sha256": "text-sha-hwpx",
                "text": "3.2 서울특별시 소재 업체",
            }
        ],
    }

    requirements, evidence, diagnostics = canonicalize_validated_slot(
        slot,
        notice_version_id="version-2",
        key_prefix="REQ-002",
    )

    assert diagnostics == []
    assert [requirement.type for requirement in requirements] == ["REGION"]
    assert requirements[0].value == "서울특별시"
    assert evidence[0].location.page is None
    assert evidence[0].location.section_index == 1
    assert evidence[0].location.paragraph_start == 7
    assert evidence[0].location.paragraph_end == 7
    assert evidence[0].location.display == "section 2 · paragraph 8"
    assert evidence[0].extracted_text_sha256 == "text-sha-hwpx"


def test_unmapped_slot_keeps_evidence_linked_to_diagnostic() -> None:
    requirements, evidence, diagnostics = canonicalize_validated_slot(
        {
            "유형": "기타요건",
            "raw": "자동 판정 범위 밖 조건",
            "_source_chunk_id": "CHUNK-0003",
            "_source_blocks": [
                {
                    "document_id": "doc-1",
                    "block_index": 9,
                    "page": 15,
                    "location": "p.15",
                    "source_sha256": "sha-1",
                    "text": "자동 판정 범위 밖 조건",
                }
            ],
        },
        notice_version_id="version-2",
        key_prefix="REQ-003",
    )

    assert requirements == []
    assert len(evidence) == 1
    assert evidence[0].quote == "자동 판정 범위 밖 조건"
    assert evidence[0].document_id == "doc-1"
    assert evidence[0].location.page == 15
    assert diagnostics[0]["code"] == "UNMAPPED_REQUIREMENT"
    assert diagnostics[0]["evidence_keys"] == [evidence[0].evidence_key]


def test_industry_and_registration_slots_use_the_same_explicit_code():
    from bidengine.requirements.legacy_slots import adapt_legacy_slot

    for slot_type in ("업종요건", "등록요건"):
        requirements, diagnostics = adapt_legacy_slot(
            {"유형": slot_type, "raw": "소프트웨어사업(업종코드: 1468) 등록업체",
             "업종_raw": "소프트웨어사업", "등록인증_raw": "소프트웨어사업"},
            notice_version_id="v", key_prefix="r",
        )
        assert diagnostics == []
        assert [(item.type, item.value) for item in requirements] == [("INDUSTRY", "1468")]
        assert requirements[0].scope["industry_name"] == "소프트웨어사업"


def test_industry_mapping_does_not_guess_codes_or_collapse_multiple_conditions():
    from bidengine.requirements.legacy_slots import adapt_legacy_slot

    for slot_type in ("업종요건", "등록요건"):
        for raw in (
            "업종코드: 1468 및 업종코드: 0036 등록업체",
            "업종코드: 1468, 0036 등록업체",
            "업종코드: 1468/0036 등록업체",
            "업종코드: 1468 또는 업종코드: 0036 등록업체",
            "공동수급체 구성원 모두 업종코드: 1468 등록업체",
        ):
            requirements, diagnostics = adapt_legacy_slot(
                {"유형": slot_type, "raw": raw}, notice_version_id="v", key_prefix="r",
            )
            assert requirements == []
            assert diagnostics

    for raw in ("소프트웨어사업 등록업체", "업종코드: 14680 등록업체"):
        requirements, _ = adapt_legacy_slot(
            {"유형": "등록요건", "raw": raw, "등록인증_raw": "소프트웨어사업"},
            notice_version_id="v", key_prefix="r",
        )
        assert requirements[0].type == "REGISTRATION_CERTIFICATION"
        assert requirements[0].value == "소프트웨어사업"


def test_certification_is_not_replaced_by_an_industry_code():
    from bidengine.requirements.legacy_slots import adapt_legacy_slot

    requirements, _ = adapt_legacy_slot(
        {"유형": "인증요건", "raw": "업종코드: 1468 업체는 ISO 27001 인증 보유",
         "등록인증_raw": "ISO 27001"}, notice_version_id="v", key_prefix="r",
    )
    assert requirements[0].type == "REGISTRATION_CERTIFICATION"
    assert requirements[0].value == "ISO 27001"
