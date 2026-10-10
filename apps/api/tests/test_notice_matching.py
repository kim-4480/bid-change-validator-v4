from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from apps.api.app.analysis_models import QualificationAnalysisRun
from apps.api.app.database import SessionLocal
from apps.api.app.models import BidNotice, BidNoticeVersion, NoticeDocument
from apps.api.app.qualification.analysis import qualification_analysis_version_fingerprint
from apps.api.app.qualification.matching import (
    _load_latest_valid_analysis_runs,
    match_cached_notices,
)


def test_notice_matching_loads_runs_in_batch_without_per_notice_scalar_queries() -> None:
    company_id = uuid4()
    notice_id = uuid4()
    run_id = uuid4()
    notice = SimpleNamespace(
        id=notice_id,
        bid_notice_no="R26BK00000001",
        title="테스트 공고",
        announcing_institution_name="테스트 기관",
    )
    version = SimpleNamespace(id=uuid4(), version_number=1, documents=[])
    run = SimpleNamespace(
        id=run_id,
        notice_version_id=version.id,
        status="SUCCEEDED",
        created_at=datetime.now(timezone.utc),
    )
    analysis = SimpleNamespace(requirements=[], evidence=[], verdict_complete=None)
    evaluation = SimpleNamespace(overall_status="core_met", judgments=[])

    db = MagicMock()
    db.execute.return_value.all.return_value = [(notice, version)]
    db.scalars.return_value.all.return_value = [run]
    db.get.return_value = None

    with (
        patch("apps.api.app.qualification.matching._load_company", return_value=object()),
        patch("apps.api.app.qualification.matching._record_to_completeness", return_value=None),
        patch("apps.api.app.qualification.matching.build_company_profile_snapshot", return_value=object()),
        patch("apps.api.app.qualification.matching.qualification_analysis_version_fingerprint", return_value="a" * 64),
        patch("apps.api.app.qualification.matching.analysis_run_response", return_value=analysis),
        patch("apps.api.app.qualification.matching.judge_requirements", return_value=evaluation),
    ):
        result = match_cached_notices(db, company_id=company_id, limit=12)

    assert result.analyzed_notice_count == 1
    assert result.returned_count == 1
    assert result.items[0].analysis_run_id == run_id
    db.execute.assert_called_once()
    candidate_sql = str(db.execute.call_args.args[0])
    assert "EXISTS" in candidate_sql
    assert "input_fingerprint IS NOT NULL" in candidate_sql
    db.scalars.assert_called_once()
    db.scalar.assert_not_called()


def test_notice_matching_does_not_fingerprint_versions_with_only_legacy_runs() -> None:
    """Versions without lineage cannot match, so their documents need not be loaded."""
    db = MagicMock()
    db.execute.return_value.all.return_value = []
    db.get.return_value = None

    with (
        patch("apps.api.app.qualification.matching._load_company", return_value=object()),
        patch("apps.api.app.qualification.matching._record_to_completeness", return_value=None),
        patch("apps.api.app.qualification.matching.build_company_profile_snapshot", return_value=object()),
        patch("apps.api.app.qualification.matching.qualification_analysis_version_fingerprint") as fingerprint,
    ):
        result = match_cached_notices(db, company_id=uuid4())

    assert result.analyzed_notice_count == 0
    assert result.items == []
    assert "input_fingerprint IS NOT NULL" in str(db.execute.call_args.args[0])
    fingerprint.assert_not_called()
    db.scalars.assert_not_called()


def test_latest_valid_run_query_handles_multiple_notices_and_histories() -> None:
    """The SQL query ranks matching lineage only and preserves latest-valid failure."""
    db = SessionLocal()
    now = datetime.now(timezone.utc)
    notice_ids = [uuid4(), uuid4()]
    version_ids = [uuid4(), uuid4()]
    try:
        versions: list[BidNoticeVersion] = []
        for index, (notice_id, version_id) in enumerate(zip(notice_ids, version_ids)):
            notice = BidNotice(
                id=notice_id,
                bid_notice_no=f"TEST-LINEAGE-{notice_id}",
                title=f"lineage test {index}",
                business_type="SERVICE",
                first_seen_at=now,
                last_seen_at=now,
            )
            version = BidNoticeVersion(
                id=version_id,
                notice_id=notice_id,
                version_number=1,
                bid_notice_order="000",
                is_current=True,
                source_endpoint="pytest",
                payload_hash=f"{index + 1:064x}",
                raw_json={},
                collected_at=now,
            )
            document = NoticeDocument(
                id=uuid4(),
                notice_version_id=version_id,
                document_order=0,
                name="notice.pdf",
                url=f"https://example.invalid/{version_id}.pdf",
                source_field="stdNtceDocUrl",
                download_status="DOWNLOADED",
                extraction_status="EXTRACTED",
                extracted_text_sha256=f"{index + 10:064x}",
                extracted_blocks=[{"block_index": 0, "text": "참가자격"}],
            )
            version.documents = [document]
            db.add_all([notice, version])
            versions.append(version)
        db.flush()

        fingerprints = {
            version.id: qualification_analysis_version_fingerprint(version)
            for version in versions
        }
        stale_newer = QualificationAnalysisRun(
            id=uuid4(), notice_version_id=version_ids[0], contract_version="test",
            analysis_kind="QUALIFICATION_REQUIREMENTS", status="SUCCEEDED",
            input_fingerprint="f" * 64, created_at=now + timedelta(minutes=2),
        )
        valid_older = QualificationAnalysisRun(
            id=uuid4(), notice_version_id=version_ids[0], contract_version="test",
            analysis_kind="QUALIFICATION_REQUIREMENTS", status="SUCCEEDED",
            input_fingerprint=fingerprints[version_ids[0]], created_at=now,
        )
        valid_success = QualificationAnalysisRun(
            id=uuid4(), notice_version_id=version_ids[1], contract_version="test",
            analysis_kind="QUALIFICATION_REQUIREMENTS", status="SUCCEEDED",
            input_fingerprint=fingerprints[version_ids[1]], created_at=now,
        )
        valid_failed_newer = QualificationAnalysisRun(
            id=uuid4(), notice_version_id=version_ids[1], contract_version="test",
            analysis_kind="QUALIFICATION_REQUIREMENTS", status="FAILED",
            input_fingerprint=fingerprints[version_ids[1]], created_at=now + timedelta(minutes=1),
        )
        db.add_all([stale_newer, valid_older, valid_success, valid_failed_newer])
        db.commit()

        selected = _load_latest_valid_analysis_runs(db, fingerprints)

        assert selected[version_ids[0]].id == valid_older.id
        assert selected[version_ids[1]].id == valid_failed_newer.id
        assert len(selected) == 2
    finally:
        db.rollback()
        for notice_id in notice_ids:
            notice = db.get(BidNotice, notice_id)
            if notice is not None:
                db.delete(notice)
        db.commit()
        db.close()
