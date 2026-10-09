"""Real PostgreSQL queue-admin contract; no G2B calls or production writes."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from apps.api.app.auth import get_current_user
from apps.api.app.auth_models import AppUser
from apps.api.app.config import Settings
from apps.api.app.database import SessionLocal
from apps.api.app.main import app
from apps.api.app.models import NoticeHistoryBackfillJob
from apps.api.app.workers.notice_polling import run_history_backfill_batch
from apps.api.tests.test_mvp_golden_e2e import _cleanup, _seed_golden_case


def test_system_admin_lists_and_requeues_only_failed_history_job():
    seed = _seed_golden_case()
    job_id = uuid4()
    try:
        with SessionLocal() as db:
            db.add(NoticeHistoryBackfillJob(
                id=job_id, notice_id=seed["notice_id"], status="FAILED", attempts=3,
                next_attempt_at=datetime.now(timezone.utc) + timedelta(days=1),
                last_error="transient failure",
            ))
            db.commit()
        admin = AppUser(id=uuid4(), username="isolated-admin", password_hash="unused",
                        role="SYSTEM_ADMIN", active=True)
        user = AppUser(id=uuid4(), username="isolated-user", password_hash="unused",
                       role="USER", active=True)
        with TestClient(app) as client:
            app.dependency_overrides[get_current_user] = lambda: user
            assert client.get("/api/v1/admin/history-jobs").status_code == 403
            assert client.post(f"/api/v1/admin/history-jobs/{job_id}/retry").status_code == 403
            app.dependency_overrides[get_current_user] = lambda: admin
            rows = client.get("/api/v1/admin/history-jobs", params={"status": "FAILED"})
            assert rows.status_code == 200, rows.text
            assert any(item["id"] == str(job_id) for item in rows.json())
            retry = client.post(f"/api/v1/admin/history-jobs/{job_id}/retry")
            assert retry.status_code == 200, retry.text
            assert retry.json()["status"] == "PENDING"
            assert retry.json()["attempts"] == 0
            assert client.post(f"/api/v1/admin/history-jobs/{job_id}/retry").status_code == 409
        with SessionLocal() as db:
            assert db.get(NoticeHistoryBackfillJob, job_id).last_error == "transient failure"
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        _cleanup(seed)


def test_exhausted_history_job_is_not_automatically_retried():
    seed = _seed_golden_case()
    job_id = uuid4()
    try:
        with SessionLocal() as db:
            db.add(NoticeHistoryBackfillJob(
                id=job_id, notice_id=seed["notice_id"], status="FAILED", attempts=3,
                next_attempt_at=datetime.now(timezone.utc) - timedelta(days=1),
                last_error="third failure",
            ))
            db.commit()

        class NoExternalCalls:
            def fetch_page(self, **_kwargs):
                raise AssertionError("exhausted job must not call G2B")

        completed = run_history_backfill_batch(
            Settings(_env_file=None, notice_history_backfill_batch_size=1),
            client=NoExternalCalls(), document_downloader=None,
            now=datetime.now(timezone.utc),
        )
        assert completed == 0
        with SessionLocal() as db:
            job = db.get(NoticeHistoryBackfillJob, job_id)
            assert (job.status, job.attempts, job.last_error) == ("FAILED", 3, "third failure")
    finally:
        _cleanup(seed)


def test_interrupted_exhausted_job_becomes_failed_for_manual_retry():
    seed = _seed_golden_case()
    job_id = uuid4()
    now = datetime.now(timezone.utc)
    try:
        with SessionLocal() as db:
            db.add(NoticeHistoryBackfillJob(
                id=job_id, notice_id=seed["notice_id"], status="RUNNING", attempts=3,
                started_at=now - timedelta(hours=2), next_attempt_at=now - timedelta(days=1),
            ))
            db.commit()

        class NoExternalCalls:
            def fetch_page(self, **_kwargs):
                raise AssertionError("exhausted job must not call G2B")

        completed = run_history_backfill_batch(
            Settings(_env_file=None, notice_history_backfill_batch_size=1),
            client=NoExternalCalls(), document_downloader=None, now=now,
        )
        assert completed == 0
        with SessionLocal() as db:
            job = db.get(NoticeHistoryBackfillJob, job_id)
            assert (job.status, job.attempts) == ("FAILED", 3)
            assert job.last_error == "Retry limit reached after worker interruption"
    finally:
        _cleanup(seed)
