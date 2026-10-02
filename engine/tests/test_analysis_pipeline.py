from bidengine.pipeline.analysis_pipeline import (
    QualificationAnalysisInput,
    QualificationDocumentInput,
    analyze_qualification_documents,
)


def _input():
    return QualificationAnalysisInput(
        notice_id="notice-1",
        notice_version_id="version-2",
        documents=[
            QualificationDocumentInput(
                document_id="doc-1",
                file_sha256="file-sha-1",
                extracted_text_sha256="sha-1",
                extracted_blocks=[
                    {
                        "block_index": 0,
                        "page": 3,
                        "location": "p.3",
                        "text": "3. 입찰 참가자격\n3.1 최근 3년 실적 2건 이상, 합계 4억원 이상",
                    }
                ],
            )
        ],
    )


def _fake_extract(system, body, schema):
    return {
        "requirements": [
            {
                "유형": "실적요건",
                "raw": "최근 3년 실적 2건 이상, 합계 4억원 이상",
                "기간_raw": "최근 3년",
                "금액_raw": "4억원 이상",
                "건수_raw": "2건 이상",
                "근거조항": "3.1",
            }
        ]
    }


def test_pipeline_returns_canonical_requirement_and_evidence():
    def fake_normalize(raw):
        if "4억원" in raw:
            return {
                "raw": raw,
                "value": 400000000,
                "unit": "KRW",
                "op": ">=",
                "parse_status": "success",
            }
        if "3년" in raw:
            return {
                "raw": raw,
                "value": 36,
                "unit": "MONTH",
                "op": None,
                "parse_status": "success",
            }
        raise AssertionError(raw)

    result = analyze_qualification_documents(
        _input(),
        structured_extract=_fake_extract,
        normalize_value=fake_normalize,
    )

    assert result.status == "SUCCEEDED"
    assert result.notice_id == "notice-1"
    assert result.notice_version_id == "version-2"
    assert result.document_ids == ["doc-1"]
    assert {item.type for item in result.requirements} == {
        "PERFORMANCE_AMOUNT",
        "PERFORMANCE_COUNT",
    }
    assert result.evidence[0].document_id == "doc-1"
    assert result.evidence[0].location.page == 3
    assert result.evidence[0].quote == "최근 3년 실적 2건 이상, 합계 4억원 이상"
    assert result.evidence[0].source_sha256 == "file-sha-1"
    assert result.evidence[0].extracted_text_sha256 == "sha-1"
    assert all(item.evidence_keys == [result.evidence[0].evidence_key] for item in result.requirements)


def test_pipeline_uses_internal_normalizer_by_default():
    result = analyze_qualification_documents(
        _input(),
        structured_extract=_fake_extract,
    )

    amount = next(item for item in result.requirements if item.type == "PERFORMANCE_AMOUNT")
    count = next(item for item in result.requirements if item.type == "PERFORMANCE_COUNT")

    assert result.status == "SUCCEEDED"
    assert amount.value == 400000000
    assert amount.unit == "KRW"
    assert amount.operator == ">="
    assert amount.period_months == 36
    assert count.value == 2
    assert count.period_months == 36


def test_pipeline_normalizes_staff_headcount():
    analysis_input = QualificationAnalysisInput(
        notice_id="notice-1",
        notice_version_id="version-1",
        documents=[
            QualificationDocumentInput(
                document_id="doc-staff",
                extracted_blocks=[
                    {
                        "block_index": 0,
                        "page": 1,
                        "location": "p.1",
                        "text": "3. 입찰 참가자격\n3.1 정보처리기사 2명 이상 보유",
                    }
                ],
            )
        ],
    )

    def fake_extract(system, body, schema):
        return {
            "requirements": [
                {
                    "유형": "인력요건",
                    "raw": "정보처리기사 2명 이상 보유",
                    "인원_raw": "2명 이상",
                    "인력역할_raw": "정보처리기사",
                    "근거조항": "3.1",
                }
            ]
        }

    result = analyze_qualification_documents(analysis_input, structured_extract=fake_extract)

    assert result.status == "SUCCEEDED"
    assert len(result.requirements) == 1
    staff = result.requirements[0]
    assert staff.type == "STAFF"
    assert staff.value == 2
    assert staff.unit == "PERSON"
    assert staff.operator == ">="
    assert staff.scope["role"] == "정보처리기사"


def test_pipeline_keeps_documents_separate_and_chunk_ids_unique():
    analysis_input = QualificationAnalysisInput(
        notice_id="notice-1",
        notice_version_id="version-1",
        documents=[
            QualificationDocumentInput(
                document_id="doc-a",
                extracted_blocks=[
                    {
                        "block_index": 0,
                        "page": 1,
                        "location": "p.1",
                        "text": "1. 개요",
                    }
                ],
            ),
            QualificationDocumentInput(
                document_id="doc-b",
                extracted_blocks=[
                    {
                        "block_index": 0,
                        "page": 2,
                        "location": "p.2",
                        "text": "2. 입찰 참가자격\n2.1 서울 소재 업체",
                    }
                ],
            ),
        ],
    )

    captured = {}

    def fake_extract(system, body, schema):
        captured["body"] = body
        return {
            "requirements": [
                {
                    "유형": "지역요건",
                    "raw": "서울 소재 업체",
                    "지역_raw": "서울",
                    "근거조항": "2.1",
                }
            ]
        }

    result = analyze_qualification_documents(
        analysis_input,
        structured_extract=fake_extract,
    )

    assert result.status == "SUCCEEDED"
    assert result.document_ids == ["doc-a", "doc-b"]
    assert result.requirements[0].type == "REGION"
    assert result.requirements[0].value == "서울"
    assert result.evidence[0].document_id == "doc-b"
    assert len(set(result.target_chunk_ids)) == len(result.target_chunk_ids)
    assert "서울 소재 업체" in captured["body"]


def test_pipeline_fails_cleanly_when_no_usable_blocks():
    result = analyze_qualification_documents(
        QualificationAnalysisInput(
            notice_id="notice-1",
            notice_version_id="version-1",
            documents=[
                QualificationDocumentInput(
                    document_id="doc-empty",
                    extracted_blocks=[{"block_index": 0, "text": "   "}],
                )
            ],
        ),
        structured_extract=lambda system, body, schema: {"requirements": []},
    )

    assert result.status == "FAILED"
    assert result.requirements == []
    assert result.evidence == []
    assert result.diagnostics[0].code == "EXTRACTION_FAILED"


def test_pipeline_rejects_duplicate_backend_document_ids():
    try:
        QualificationAnalysisInput(
            notice_id="notice-1",
            notice_version_id="version-1",
            documents=[
                QualificationDocumentInput(document_id="dup"),
                QualificationDocumentInput(document_id="dup"),
            ],
        )
    except ValueError as error:
        assert "document_id values must be unique" in str(error)
    else:
        raise AssertionError("duplicate document ids should be rejected")


def test_rejected_slot_preserves_partial_analysis_status():
    def extract(*args):
        result = _fake_extract(*args)
        result["requirements"].append({"유형": "지역요건", "raw": "원문에 없는 부산 소재 업체", "지역_raw": "부산"})
        return result
    result = analyze_qualification_documents(_input(), structured_extract=extract)
    assert result.status == "PARTIAL"
    assert result.requirements
    assert result.diagnostics[0].code == "EXTRACTION_PARTIAL"


def test_composite_registration_cannot_be_canonicalized_into_simple_fact():
    from bidengine.requirements.legacy_slots import adapt_legacy_slot
    requirements, diagnostics = adapt_legacy_slot({"유형": "등록요건", "raw": "공동수급체 구성원 모두 정보통신공사업 등록업체이어야 한다.", "등록인증_raw": "정보통신공사업"}, notice_version_id="v", key_prefix="r")
    assert requirements == []
    assert diagnostics[0]["code"] == "UNMAPPED_REQUIREMENT"


def test_pipeline_keeps_grounded_requirements_when_location_is_wrong():
    def extract(*args):
        result = _fake_extract(*args)
        result["requirements"][0]["근거조항"] = "9.9"
        return result

    result = analyze_qualification_documents(_input(), structured_extract=extract)
    assert result.status == "SUCCEEDED"
    assert len(result.requirements) == 2
    assert result.evidence[0].location.clause_label is None
    assert result.evidence[0].location.page == 3


def test_pipeline_keeps_unmapped_evidence_even_with_rejected_candidates():
    def extract(*args):
        return {"requirements": [
            {"유형": "기타요건", "raw": "최근 3년 실적 2건 이상, 합계 4억원 이상"},
            {"유형": "지역요건", "raw": "원문에 없는 부산 소재 업체"},
        ]}

    result = analyze_qualification_documents(_input(), structured_extract=extract)
    assert result.status == "PARTIAL"
    assert result.requirements == []
    assert len(result.evidence) == 1
    diagnostic = next(item for item in result.diagnostics if item.code == "UNMAPPED_REQUIREMENT")
    assert diagnostic.severity == "INFO"
    assert diagnostic.evidence_keys == [result.evidence[0].evidence_key]


def test_pipeline_does_not_report_empty_retry_as_success():
    answers = iter([
        {"requirements": [{"유형": "지역요건", "raw": "원문에 없는 부산 소재 업체"}]},
        {"requirements": []},
    ])
    result = analyze_qualification_documents(_input(), structured_extract=lambda *args: next(answers))
    assert result.status == "FAILED"
    assert result.diagnostics[0].code == "EXTRACTION_PARTIAL"
    assert [item.model_dump() for item in result.dropped_requirements] == [
        {
            "raw": "원문에 없는 부산 소재 업체",
            "reason_code": "RAW_NOT_FOUND_IN_SOURCE",
            # raw 자체를 못 찾은 경우라 세부 조건 자리는 비어 있다.
            # 채워지는 것은 DETAIL_NOT_FOUND_IN_SOURCE 일 때뿐이다.
            "detail_field": None,
            "detail_value": None,
        }
    ]


def test_extracted_industry_code_reaches_existing_deterministic_judge():
    from datetime import date
    from bidengine.judgment.rules import CompanyProfileSnapshot, judge_requirement

    raw = "소프트웨어사업(업종코드: 1468) 등록업체"
    analysis_input = QualificationAnalysisInput(
        notice_id="notice-1", notice_version_id="version-1",
        documents=[QualificationDocumentInput(
            document_id="doc-1", extracted_blocks=[{
                "block_index": 0, "page": 1, "text": "2. 입찰 참가자격\n2.1 " + raw,
            }],
        )],
    )
    for slot_type in ("업종요건", "등록요건"):
        result = analyze_qualification_documents(
            analysis_input, structured_extract=lambda *args: {"requirements": [{
                "유형": slot_type, "raw": raw, "업종_raw": "소프트웨어사업",
                "등록인증_raw": "소프트웨어사업", "근거조항": "2.1",
            }]},
        )
        assert result.status == "SUCCEEDED"
        assert len(result.requirements) == 1
        assert result.requirements[0].evidence_keys == [result.evidence[0].evidence_key]
        for code, expected in (("1468", "SATISFIED"), ("0036", "UNSATISFIED")):
            profile = CompanyProfileSnapshot(
                company_id="company-1", industries=[{"code": code, "name": "등록 업종"}],
                completeness={"industries": True},
            )
            judgment = judge_requirement(
                result.requirements[0], profile, preflight_case_id="case-1",
                reference_date=date(2026, 9, 10),
            )
            assert judgment.status == expected
