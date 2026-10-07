from uuid import uuid4

from apps.api.app.models import BidNoticeVersion, NoticeDocument
from apps.api.app.qualification.analysis import build_qualification_analysis_input


def test_analysis_input_uses_only_extracted_backend_blocks() -> None:
    version = BidNoticeVersion(
        id=uuid4(),
        notice_id=uuid4(),
        version_number=1,
        bid_notice_order="00",
        is_current=True,
        source_endpoint="fixture",
        payload_hash="a" * 64,
        raw_json={},
    )
    extracted = NoticeDocument(
        id=uuid4(),
        notice_version_id=version.id,
        document_order=0,
        name="공고문.pdf",
        url="https://example.invalid/notice.pdf",
        source_field="stdNtceDocUrl",
        download_status="DOWNLOADED",
        extraction_status="EXTRACTED",
        file_sha256="b" * 64,
        extracted_text_sha256="c" * 64,
        extracted_blocks=[
            {
                "block_index": 0,
                "page": 3,
                "location": "p.3",
                "text": "3. 참가자격\n서울특별시 소재 업체",
            }
        ],
    )
    pending = NoticeDocument(
        id=uuid4(),
        notice_version_id=version.id,
        document_order=1,
        name="미추출.hwp",
        url="https://example.invalid/pending.hwp",
        source_field="ntceSpecDocUrl1",
        download_status="DOWNLOADED",
        extraction_status="PENDING",
        extracted_blocks=None,
    )
    version.documents = [extracted, pending]

    payload = build_qualification_analysis_input(version)

    assert payload.notice_id == str(version.notice_id)
    assert payload.notice_version_id == str(version.id)
    assert len(payload.documents) == 1
    assert payload.documents[0].document_id == str(extracted.id)
    assert payload.documents[0].file_sha256 == "b" * 64
    assert payload.documents[0].extracted_text_sha256 == "c" * 64
    assert payload.documents[0].extracted_blocks[0]["page"] == 3


def test_analysis_input_allows_no_extracted_documents_for_failed_run_diagnostic() -> None:
    version = BidNoticeVersion(
        id=uuid4(),
        notice_id=uuid4(),
        version_number=1,
        bid_notice_order="00",
        is_current=True,
        source_endpoint="fixture",
        payload_hash="d" * 64,
        raw_json={},
    )
    version.documents = []

    payload = build_qualification_analysis_input(version)

    assert payload.documents == []


def test_analysis_response_carries_coverage_tiers_and_verdict_completeness() -> None:
    """2026-10-07: 종합 판정은 닫힌 값만 본다. 화면은 확인 항목(공백·이름 요건)과 참고 정보를 따로 보여 준다."""
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from bidengine.pipeline.analysis_result import AnalysisCoverage, CoverageGap

    from apps.api.app.qualification.analysis import analysis_run_response

    def record(key, type_, value):
        return SimpleNamespace(
            requirement_key=key, requirement_group_key=f"{key}-G", group_operator="ALL_OF", type=type_, operator="MATCH",
            value_json=value, unit=None, period_months=None, scope={}, requirement_role="mandatory",
            condition_complexity="simple", required=True, raw=str(value), confidence=None, evidence_keys=[],
        )

    coverage = AnalysisCoverage(
        section_selection="anchored", unclassified=1,
        gaps=[CoverageGap(kind="UNCLASSIFIED", raw="다. 생산시설을 갖춘 자")],
        ignored=[CoverageGap(kind="IGNORED", raw="공동수급 불가", reason="GAP_JOINT_CONTRACT_NOTE")],
    )
    run = SimpleNamespace(
        id=uuid4(), notice_version=SimpleNamespace(id=uuid4(), notice_id=uuid4(), version_number=1),
        contract_version="ai-analysis-v0.2", analysis_kind="QUALIFICATION_REQUIREMENTS", status="PARTIAL",
        target_chunk_ids=[], diagnostics=[], dropped_requirements=[], evidence=[], created_at=datetime.now(timezone.utc),
        requirements=[record("REQ-REGION", "REGION", "강릉시"), record("REQ-CERT", "REGISTRATION_CERTIFICATION", "Solar A Mark 인증서")],
        coverage=coverage.model_dump(mode="json"),
    )
    response = analysis_run_response(run)
    assert response.verdict_complete is True
    assert response.requirement_tiers == {"REQ-CERT": "CHECKLIST", "REQ-REGION": "VERDICT"}
    assert [gap.raw for gap in response.coverage.checklist_gaps] == ["다. 생산시설을 갖춘 자"]
    assert [gap.raw for gap in response.coverage.notes] == ["공동수급 불가"]

    run.coverage = None  # 2026-10-07 이전 실행 — 예전처럼 분석 상태로 판단한다.
    assert analysis_run_response(run).verdict_complete is None
