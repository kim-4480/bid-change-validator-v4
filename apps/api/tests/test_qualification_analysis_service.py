from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from apps.api.app.models import BidNoticeVersion, NoticeDocument
from apps.api.app.qualification.analysis import (
    analysis_run_response,
    build_qualification_analysis_input,
    is_qualification_analysis_run_stale,
    load_latest_current_qualification_analysis_run,
    qualification_analysis_input_fingerprint,
)
from apps.api.app.qualification.judgment import (
    QualificationJudgmentError,
    _select_analysis_run,
)


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
        id=uuid4(), notice_version=SimpleNamespace(id=uuid4(), notice_id=uuid4(), version_number=1, documents=[]),
        contract_version="ai-analysis-v0.2", analysis_kind="QUALIFICATION_REQUIREMENTS", status="PARTIAL",
        target_chunk_ids=[], diagnostics=[], dropped_requirements=[], evidence=[], created_at=datetime.now(timezone.utc),
        requirements=[record("REQ-REGION", "REGION", "강릉시"), record("REQ-CERT", "REGISTRATION_CERTIFICATION", "Solar A Mark 인증서")],
        coverage=coverage.model_dump(mode="json"),
        input_fingerprint=qualification_analysis_input_fingerprint(
            build_qualification_analysis_input(SimpleNamespace(notice_id=uuid4(), id=uuid4(), documents=[]))
        ),
    )
    response = analysis_run_response(run)
    assert response.verdict_complete is True
    assert response.requirement_tiers == {"REQ-CERT": "CHECKLIST", "REQ-REGION": "VERDICT"}
    assert [gap.raw for gap in response.coverage.checklist_gaps] == ["다. 생산시설을 갖춘 자"]
    assert [gap.raw for gap in response.coverage.notes] == ["공동수급 불가"]

    run.coverage = None  # 2026-10-07 이전 실행 — 예전처럼 분석 상태로 판단한다.
    assert analysis_run_response(run).verdict_complete is None


def test_analysis_lineage_same_hash_is_valid_and_changed_hash_is_stale() -> None:
    from types import SimpleNamespace

    version = _version_with_extracted_document("a" * 64)
    fingerprint = qualification_analysis_input_fingerprint(
        build_qualification_analysis_input(version)
    )
    run = SimpleNamespace(input_fingerprint=fingerprint, notice_version=version)

    assert is_qualification_analysis_run_stale(run) is False

    legacy_run = SimpleNamespace(input_fingerprint=None, notice_version=version)
    assert is_qualification_analysis_run_stale(legacy_run) is True

    version.documents[0].extracted_text_sha256 = "b" * 64
    assert is_qualification_analysis_run_stale(run) is True


def test_new_analysis_after_reextraction_is_valid_again() -> None:
    from types import SimpleNamespace

    version = _version_with_extracted_document("a" * 64)
    old_run = SimpleNamespace(
        input_fingerprint=qualification_analysis_input_fingerprint(
            build_qualification_analysis_input(version)
        ),
        notice_version=version,
    )
    version.documents[0].extracted_text_sha256 = "b" * 64
    new_run = SimpleNamespace(
        input_fingerprint=qualification_analysis_input_fingerprint(
            build_qualification_analysis_input(version)
        ),
        notice_version=version,
    )

    assert is_qualification_analysis_run_stale(old_run) is True
    assert is_qualification_analysis_run_stale(new_run) is False


def test_document_addition_and_removal_make_existing_analysis_stale() -> None:
    from types import SimpleNamespace

    version = _version_with_extracted_document("a" * 64)
    original_document = version.documents[0]
    run = SimpleNamespace(
        input_fingerprint=qualification_analysis_input_fingerprint(
            build_qualification_analysis_input(version)
        ),
        notice_version=version,
    )
    added_document = NoticeDocument(
        id=uuid4(),
        notice_version_id=version.id,
        document_order=1,
        name="추가문서.pdf",
        url="https://example.invalid/added.pdf",
        source_field="ntceSpecDocUrl1",
        download_status="DOWNLOADED",
        extraction_status="EXTRACTED",
        file_sha256="d" * 64,
        extracted_text_sha256="e" * 64,
        extracted_blocks=[{"block_index": 0, "text": "추가 자격"}],
    )

    version.documents = [original_document, added_document]
    assert is_qualification_analysis_run_stale(run) is True

    version.documents = []
    assert is_qualification_analysis_run_stale(run) is True


def test_latest_current_analysis_skips_newer_stale_history() -> None:
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    version = _version_with_extracted_document("a" * 64)
    current_fingerprint = qualification_analysis_input_fingerprint(
        build_qualification_analysis_input(version)
    )
    stale = SimpleNamespace(
        id=uuid4(),
        status="SUCCEEDED",
        input_fingerprint="0" * 64,
        notice_version=version,
    )
    current = SimpleNamespace(
        id=uuid4(),
        status="SUCCEEDED",
        input_fingerprint=current_fingerprint,
        notice_version=version,
    )
    db = MagicMock()
    db.scalars.return_value.all.return_value = [stale, current]

    selected = load_latest_current_qualification_analysis_run(
        db, notice_version_id=version.id
    )

    assert selected is current


def test_explicit_stale_analysis_cannot_be_used_for_judgment() -> None:
    from types import SimpleNamespace

    version = _version_with_extracted_document("a" * 64)
    stale_run = SimpleNamespace(
        id=uuid4(),
        notice_version_id=version.id,
        status="SUCCEEDED",
        input_fingerprint="0" * 64,
        notice_version=version,
    )
    case = SimpleNamespace(current_version_id=version.id)

    with patch(
        "apps.api.app.qualification.judgment.load_judgment_analysis",
        return_value=stale_run,
    ):
        with pytest.raises(QualificationJudgmentError) as error:
            _select_analysis_run(MagicMock(), case, stale_run.id)

    assert error.value.code == "QUALIFICATION_ANALYSIS_STALE"


def _version_with_extracted_document(text_hash: str) -> BidNoticeVersion:
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
    version.documents = [
        NoticeDocument(
            id=uuid4(),
            notice_version_id=version.id,
            document_order=0,
            name="공고문.pdf",
            url="https://example.invalid/notice.pdf",
            source_field="stdNtceDocUrl",
            download_status="DOWNLOADED",
            extraction_status="EXTRACTED",
            file_sha256="c" * 64,
            extracted_text_sha256=text_hash,
            extracted_blocks=[{"block_index": 0, "text": "참가자격"}],
        )
    ]
    return version
