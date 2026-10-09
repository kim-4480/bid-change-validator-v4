"""Real PostgreSQL 17 queue tests; writes are rolled back after each case."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.auth import get_current_user
from apps.api.app.auth_models import AppUser
from apps.api.app.database import engine, get_db
from apps.api.app.main import app
from apps.api.app.config import Settings
from apps.api.app.analysis_models import QualificationAnalysisRun
from apps.api.app.qualification.routers import analysis as analysis_router
from apps.api.app.models import (
    BidNotice, BidNoticeVersion, NoticeDocument, NoticeProcessingAttempt,
    NoticeProcessingJob, NoticeRecommendationFeature,
)
from apps.api.app.workers.notice_processing import _process, run_processing_batch
from apps.api.app.services.notice_processing import (
    claim_next_job, claim_approved_analysis_job, enqueue_version_job, finish_job,
)


@pytest.fixture
def state():
    connection = engine.connect()
    outer = connection.begin()
    db = Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)
    now = datetime.now(timezone.utc)
    notice = BidNotice(bid_notice_no=f"QUEUE-{uuid4().hex}", title="Queue tender",
                       business_type="SERVICE", first_seen_at=now, last_seen_at=now)
    db.add(notice)
    db.flush()
    version = BidNoticeVersion(notice_id=notice.id, version_number=1, bid_notice_order="000",
                               is_current=True, source_endpoint="test", payload_hash="a" * 64,
                               raw_json={}, collected_at=now)
    admin = AppUser(username=f"queue-admin-{uuid4().hex}", password_hash="unused",
                    role="SYSTEM_ADMIN", active=True)
    ordinary = AppUser(username=f"queue-user-{uuid4().hex}", password_hash="unused",
                       role="USER", active=True)
    db.add_all([version, admin, ordinary])
    db.flush()
    actor = {"user": admin}
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: actor["user"]
    try:
        yield db, notice, version, actor, TestClient(app), admin, ordinary
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)
        db.close()
        outer.rollback()
        connection.close()


def test_dedupe_input_drift_priority_and_aging(state):
    db, _, version, *_ = state
    first = enqueue_version_job(db, version_id=version.id, stage="EXTRACT")
    assert enqueue_version_job(db, version_id=version.id, stage="EXTRACT").id == first.id
    old_id = first.id
    version.payload_hash = "b" * 64
    db.flush()
    newer = enqueue_version_job(db, version_id=version.id, stage="EXTRACT", priority=5)
    assert newer.id != old_id
    assert db.get(NoticeProcessingJob, old_id).status == "SUPERSEDED"
    assert claim_next_job(db).id == newer.id
    assert db.scalar(select(NoticeProcessingAttempt).where(NoticeProcessingAttempt.job_id == newer.id)).outcome == "RUNNING"
    assert finish_job(db, newer.id, attempt_number=1).status == "COMPLETED"


def test_retry_backoff_lease_recovery_and_audit(state):
    db, _, version, _, client, *_ = state
    job = enqueue_version_job(db, version_id=version.id, stage="EXTRACT")
    first = claim_next_job(db)
    now = datetime.now(timezone.utc)
    failed = finish_job(db, job.id, attempt_number=first.attempts, error="parser failed", now=now)
    assert failed.status == "FAILED"
    assert failed.next_attempt_at > now
    assert claim_next_job(db, now=now + timedelta(minutes=1)) is None
    second = claim_next_job(db, now=now + timedelta(minutes=6))
    assert second.attempts == 2
    second.lease_until = now - timedelta(seconds=1)
    db.commit()
    third = claim_next_job(db, now=now + timedelta(minutes=7))
    assert third.id == job.id and third.attempts == 3
    assert db.scalar(select(NoticeProcessingAttempt).where(
        NoticeProcessingAttempt.job_id == job.id,
        NoticeProcessingAttempt.attempt_number == 2,
    )).outcome == "INTERRUPTED"
    with pytest.raises(ValueError, match="PROCESSING_JOB_NOT_RUNNING"):
        finish_job(db, job.id, attempt_number=2, error="stale worker")
    finish_job(db, job.id, attempt_number=3, error="still failed")
    assert claim_next_job(db, now=now + timedelta(hours=1)) is None
    retry = client.post(f"/api/v1/admin/processing-jobs/{job.id}/retry")
    assert retry.status_code == 200, retry.text
    assert retry.json()["retry_budget"] == 6 and retry.json()["attempts"] == 3
    fourth = claim_next_job(db, now=datetime.now(timezone.utc) + timedelta(minutes=1))
    assert fourth.attempts == 4
    assert finish_job(db, job.id, attempt_number=4).status == "COMPLETED"


def test_admin_approval_is_version_scoped_and_external_processing_opt_in(state):
    db, _, version, actor, client, admin, ordinary = state
    path = "/api/v1/admin/processing-jobs"
    actor["user"] = ordinary
    assert client.get(path).status_code == 403
    actor["user"] = admin
    assert client.post(f"{path}/versions/{version.id}/approve-analysis").status_code == 409
    document = NoticeDocument(notice_version_id=version.id, document_order=1, name="notice.pdf", url="https://example.invalid/notice.pdf",
                              source_field="test", download_status="DOWNLOADED", storage_key="test/file.pdf",
                              file_sha256="c" * 64, extraction_status="EXTRACTED", extracted_text="valid source",
                              extracted_text_sha256="d" * 64, extracted_char_count=12,
                              extracted_blocks=[{"text": "valid source"}])
    db.add(document)
    db.flush()
    approved = client.post(f"{path}/versions/{version.id}/approve-analysis")
    assert approved.status_code == 200, approved.text
    job_id = approved.json()["id"]
    assert claim_next_job(db, allow_external=False) is None
    claimed = claim_approved_analysis_job(db, version_id=version.id)
    assert str(claimed.id) == job_id and claimed.approved_by_id == admin.id
    uncommitted = QualificationAnalysisRun(
        notice_version_id=version.id, contract_version="test", analysis_kind="QUALIFICATION_REQUIREMENTS",
        status="SUCCEEDED", target_chunk_ids=[], diagnostics=[], dropped_requirements=[],
        input_fingerprint=claimed.input_fingerprint,
    )
    db.add(uncommitted)
    db.flush()
    uncommitted_id = uncommitted.id
    document.extracted_text_sha256 = "e" * 64
    assert finish_job(db, claimed.id, attempt_number=claimed.attempts).status == "SUPERSEDED"
    assert db.get(QualificationAnalysisRun, uncommitted_id) is None
    assert client.get(f"{path}/{job_id}/attempts").json()[0]["outcome"] == "SUPERSEDED"


def test_direct_analysis_never_calls_model_without_approved_version(state, monkeypatch):
    db, notice, version, _, client, *_ = state
    calls = []

    class AvailableExtractor:
        available = True

    monkeypatch.setattr(analysis_router, "OpenAIStructuredExtractor", AvailableExtractor)
    monkeypatch.setattr(analysis_router, "run_qualification_analysis", lambda *args, **kwargs: calls.append(kwargs))
    response = client.post(f"/api/v1/notices/{notice.id}/versions/1/qualification-analysis")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ANALYSIS_APPROVAL_REQUIRED"
    assert calls == []
    assert db.scalar(select(NoticeProcessingJob).where(NoticeProcessingJob.stage == "ANALYZE")) is None


def test_feature_stage_materializes_without_external_model(state):
    db, _, version, *_ = state
    job = enqueue_version_job(db, version_id=version.id, stage="FEATURES")
    claimed = claim_next_job(db, allow_external=False)
    assert claimed.id == job.id
    _process(db, claimed, Settings(processing_enable_external=False))
    assert finish_job(db, claimed.id, attempt_number=claimed.attempts).status == "COMPLETED"
    cached = db.get(NoticeRecommendationFeature, version.id)
    assert cached is not None
    assert cached.input_fingerprint == job.input_fingerprint
    assert "Queue tender" in cached.search_text


def test_extraction_input_drift_requeues_current_fingerprint(state, monkeypatch):
    db, _, version, *_ = state
    original = enqueue_version_job(db, version_id=version.id, stage="EXTRACT")
    db.commit()

    def update_download_identity(session, _job, _settings):
        version.payload_hash = "f" * 64
        session.commit()

    monkeypatch.setattr("apps.api.app.workers.notice_processing._process", update_download_identity)
    assert run_processing_batch(settings=Settings(processing_enable_external=False),
                                session_factory=lambda: db, limit=1) == 0
    jobs = db.scalars(select(NoticeProcessingJob).where(
        NoticeProcessingJob.notice_version_id == version.id,
        NoticeProcessingJob.stage == "EXTRACT",
    )).all()
    assert len(jobs) == 2
    assert db.get(NoticeProcessingJob, original.id).status == "SUPERSEDED"
    assert next(job for job in jobs if job.id != original.id).status == "PENDING"

def test_user_can_request_without_admin_approval(state):
    db, notice, version, actor, client, admin, ordinary = state
    actor["user"] = ordinary
    url = f"/api/v1/notices/{notice.id}/versions/1/qualification-analysis/request"
    first = client.post(url)
    assert first.status_code == 202, first.text
    assert first.json()["approved"] is False
    assert first.json()["job_status"] == "PENDING"
    assert client.post(url).json()["job_id"] == first.json()["job_id"]
    job = db.get(NoticeProcessingJob, first.json()["job_id"])
    assert job.approved_by_id is None
    assert claim_approved_analysis_job(db, version_id=version.id) is None

