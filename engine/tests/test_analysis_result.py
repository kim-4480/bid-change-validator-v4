import pytest
from pydantic import ValidationError

from bidengine.pipeline.analysis_result import RequirementAnalysisResult, build_requirement_analysis_result
from bidengine.contracts import Evidence, EvidenceLocation, QualificationRequirement


def _requirement(evidence_keys=None):
    return QualificationRequirement(
        requirement_key="REQ-001-AMOUNT",
        requirement_group_key="REQ-001-GROUP",
        group_operator="ALL_OF",
        notice_version_id="version-1",
        type="PERFORMANCE_AMOUNT",
        operator=">=",
        value=400000000,
        unit="KRW",
        raw="최근 3년 실적 합계 4억원 이상",
        evidence_keys=list(evidence_keys or ["REQ-001-EVD"]),
    )


def _evidence(document_id="doc-1", notice_version_id="version-1"):
    return Evidence(
        evidence_key="REQ-001-EVD",
        source_type="NOTICE_DOCUMENT",
        document_id=document_id,
        notice_version_id=notice_version_id,
        chunk_id="CHUNK-0001",
        location=EvidenceLocation(page=14, clause_label="3.1", display="p.14"),
        quote="최근 3년 실적 합계 4억원 이상",
        source_sha256="sha",
        extracted_text_sha256="text-sha",
    )


def test_build_successful_analysis_result():
    result = build_requirement_analysis_result(
        notice_id="notice-1",
        notice_version_id="version-1",
        document_ids=["doc-1"],
        target_chunk_ids=["CHUNK-0000", "CHUNK-0001"],
        canonicalized={
            "requirements": [_requirement()],
            "evidence": [_evidence()],
            "diagnostics": [],
        },
    )

    assert result.contract_version == "ai-analysis-v0.2"
    assert result.analysis_kind == "QUALIFICATION_REQUIREMENTS"
    assert result.status == "SUCCEEDED"
    assert result.notice_id == "notice-1"
    assert result.requirements[0].evidence_keys == ["REQ-001-EVD"]
    assert result.evidence[0].document_id == "doc-1"
    assert result.evidence[0].extracted_text_sha256 == "text-sha"


def test_notice_fact_diagnostic_does_not_degrade_analysis_status():
    result = build_requirement_analysis_result(
        notice_id="notice-1",
        notice_version_id="version-1",
        document_ids=["doc-1"],
        canonicalized={
            "requirements": [_requirement()],
            "evidence": [_evidence()],
            "diagnostics": [{"code": "UNMAPPED_REQUIREMENT", "raw": "복합조건"}],
        },
    )

    assert result.status == "SUCCEEDED"
    assert result.diagnostics[0].code == "UNMAPPED_REQUIREMENT"
    assert result.diagnostics[0].kind == "NOTICE_FACT"
    assert result.diagnostics[0].severity == "INFO"
    assert result.requirements


def test_extraction_failure_without_results_is_failed_and_empty():
    result = build_requirement_analysis_result(
        notice_id="notice-1",
        notice_version_id="version-1",
        document_ids=["doc-1"],
        extraction_status="failed",
        extraction_notes="model unavailable",
        canonicalized={"requirements": [], "evidence": [], "diagnostics": []},
    )

    assert result.status == "FAILED"
    assert result.requirements == []
    assert result.evidence == []
    assert result.diagnostics[0].code == "EXTRACTION_FAILED"


def test_partial_extraction_keeps_unmapped_evidence_and_warning():
    result = build_requirement_analysis_result(
        notice_id="notice-1", notice_version_id="version-1", document_ids=["doc-1"],
        extraction_status="partial", extraction_notes="입력 길이 제한",
        canonicalized={
            "requirements": [], "evidence": [_evidence()],
            "diagnostics": [{"code": "UNMAPPED_REQUIREMENT", "raw": "복합조건",
                             "evidence_keys": ["REQ-001-EVD"]}],
        },
    )
    assert result.status == "PARTIAL"
    assert result.requirements == []
    assert len(result.evidence) == 1
    diagnostic = result.diagnostics[1]
    assert diagnostic.severity == "INFO"
    assert diagnostic.evidence_keys == [result.evidence[0].evidence_key]


def test_result_rejects_unresolved_evidence_reference():
    with pytest.raises(ValidationError):
        RequirementAnalysisResult(
            status="SUCCEEDED",
            notice_id="notice-1",
            notice_version_id="version-1",
            document_ids=["doc-1"],
            requirements=[_requirement(["missing-evidence"])],
            evidence=[_evidence()],
        )


def test_result_rejects_evidence_from_outside_document_scope():
    with pytest.raises(ValidationError):
        RequirementAnalysisResult(
            status="SUCCEEDED",
            notice_id="notice-1",
            notice_version_id="version-1",
            document_ids=["doc-1"],
            requirements=[_requirement()],
            evidence=[_evidence(document_id="doc-2")],
        )


def test_result_rejects_mixed_notice_versions():
    with pytest.raises(ValidationError):
        RequirementAnalysisResult(
            status="SUCCEEDED",
            notice_id="notice-1",
            notice_version_id="version-1",
            document_ids=["doc-1"],
            requirements=[_requirement()],
            evidence=[_evidence(notice_version_id="version-2")],
        )
