"""Durable post-collection work, scoped to one published notice version.

No model call is made by enqueueing a job. Analysis jobs require an explicit
system-admin approval for the exact current document fingerprint.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, selectinload

from ..models import BidNoticeVersion, NoticeProcessingAttempt, NoticeProcessingJob
from ..qualification.analysis import qualification_analysis_version_fingerprint


MAX_ATTEMPTS = 3
LEASE = timedelta(hours=2)
BACKOFF = timedelta(minutes=5)


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), default=str).encode()).hexdigest()


def load_version(db: Session, version_id: UUID, *, lock: bool = False) -> BidNoticeVersion | None:
    stmt = select(BidNoticeVersion).where(BidNoticeVersion.id == version_id).options(
        selectinload(BidNoticeVersion.documents), selectinload(BidNoticeVersion.notice)
    ).execution_options(populate_existing=True)
    if lock:
        stmt = stmt.with_for_update(of=BidNoticeVersion)
    return db.scalar(stmt)


def input_fingerprint(version: BidNoticeVersion, stage: str, *, notice=None) -> str:
    if stage == "EXTRACT":
        return _hash({
            "version_id": str(version.id), "payload_hash": version.payload_hash,
            "documents": sorted((str(doc.id), doc.storage_key, doc.file_sha256, doc.download_status)
                                for doc in version.documents),
        })
    if stage in {"INDEX", "ANALYZE"}:
        return qualification_analysis_version_fingerprint(version)
    if stage == "FEATURES":
        notice = notice or version.notice
        return _hash((str(version.id), version.payload_hash, notice.title, notice.business_type,
                      notice.announcing_institution_name, notice.demanding_institution_name,
                      version.contract_method))
    raise ValueError(f"Unknown processing stage: {stage}")


def feature_text(version: BidNoticeVersion, *, notice=None) -> str:
    notice = notice or version.notice
    return " ".join(str(value) for value in (
        notice.title, notice.business_type, notice.announcing_institution_name,
        notice.demanding_institution_name, version.contract_method,
    ) if value)


def enqueue_version_job(
    db: Session, *, version_id: UUID, stage: str, priority: int = 0,
    approved_by_id: UUID | None = None, allow_unapproved_analysis: bool = False,
) -> NoticeProcessingJob:
    version = load_version(db, version_id, lock=True)
    if version is None:
        raise ValueError("NOTICE_VERSION_NOT_FOUND")
    if stage == "ANALYZE" and approved_by_id is None and not allow_unapproved_analysis:
        raise ValueError("ANALYSIS_APPROVAL_REQUIRED")
    fingerprint = input_fingerprint(version, stage)
    now = datetime.now(timezone.utc)
    # Locking the version serializes enqueues; ON CONFLICT also protects callers
    # which did not enter through the API/poller transaction.
    db.execute(
        pg_insert(NoticeProcessingJob).values(
            notice_version_id=version_id, stage=stage, input_fingerprint=fingerprint,
            status="PENDING", priority=priority, next_attempt_at=now,
            approved_by_id=approved_by_id, approved_at=now if approved_by_id else None,
            created_at=now, updated_at=now,
        ).on_conflict_do_nothing(constraint="uq_notice_processing_input")
    )
    job = db.scalar(select(NoticeProcessingJob).where(
        NoticeProcessingJob.notice_version_id == version_id,
        NoticeProcessingJob.stage == stage,
        NoticeProcessingJob.input_fingerprint == fingerprint,
    ))
    assert job is not None
    if approved_by_id is not None and job.approved_by_id is None:
        job.approved_by_id = approved_by_id
        job.approved_at = now
        job.updated_at = now
    # Historical jobs remain visible, but obsolete pending/failed work is never run.
    for old in db.scalars(select(NoticeProcessingJob).where(
        NoticeProcessingJob.notice_version_id == version_id,
        NoticeProcessingJob.stage == stage,
        NoticeProcessingJob.id != job.id,
        NoticeProcessingJob.status.in_(("PENDING", "FAILED")),
    )):
        old.status = "SUPERSEDED"
        old.updated_at = now
    return job


def claim_next_job(db: Session, *, now: datetime | None = None, allow_external: bool = False) -> NoticeProcessingJob | None:
    now = now or datetime.now(timezone.utc)
    stages = ("EXTRACT", "FEATURES", "INDEX", "ANALYZE") if allow_external else ("EXTRACT", "FEATURES")
    effective_priority = NoticeProcessingJob.priority + func.floor(
        func.extract("epoch", now - NoticeProcessingJob.created_at) / 3600
    )
    while True:
        job = db.scalar(select(NoticeProcessingJob).where(
            NoticeProcessingJob.stage.in_(stages),
            or_(NoticeProcessingJob.stage.in_(("EXTRACT", "FEATURES")),
                and_(NoticeProcessingJob.approved_by_id.is_not(None), NoticeProcessingJob.approved_at.is_not(None))),
            or_(
                and_(NoticeProcessingJob.status.in_(("PENDING", "FAILED")),
                     NoticeProcessingJob.next_attempt_at <= now,
                     NoticeProcessingJob.attempts < NoticeProcessingJob.retry_budget),
                and_(NoticeProcessingJob.status == "RUNNING", NoticeProcessingJob.lease_until < now),
            ),
        ).order_by(effective_priority.desc(), NoticeProcessingJob.created_at, NoticeProcessingJob.id)
            .with_for_update(skip_locked=True).limit(1))
        if job is None:
            return None
        if job.status != "RUNNING":
            break
        previous = db.scalar(select(NoticeProcessingAttempt).where(
            NoticeProcessingAttempt.job_id == job.id,
            NoticeProcessingAttempt.attempt_number == job.attempts,
            NoticeProcessingAttempt.finished_at.is_(None),
        ).with_for_update())
        if previous:
            previous.outcome = "INTERRUPTED"
            previous.finished_at = now
            previous.error = "Worker lease expired before completion"
        if job.attempts >= job.retry_budget:
            job.status = "FAILED"
            job.last_error = "Worker lease expired after retry budget was exhausted"
            job.lease_until = None
            job.updated_at = now
            db.commit()
            continue
        break
    return _start_job(db, job, now)


def claim_approved_analysis_job(
    db: Session, *, version_id: UUID, allow_unapproved: bool = False,
) -> NoticeProcessingJob | None:
    """Reserve one analysis; only an explicit development opt-in permits self-service."""
    version = load_version(db, version_id)
    if version is None:
        return None
    fingerprint = input_fingerprint(version, "ANALYZE")
    now = datetime.now(timezone.utc)
    conditions = [
        NoticeProcessingJob.notice_version_id == version_id,
        NoticeProcessingJob.stage == "ANALYZE",
        NoticeProcessingJob.input_fingerprint == fingerprint,
        NoticeProcessingJob.status.in_(("PENDING", "FAILED")),
        NoticeProcessingJob.next_attempt_at <= now,
        NoticeProcessingJob.attempts < NoticeProcessingJob.retry_budget,
    ]
    if not allow_unapproved:
        conditions.extend((
            NoticeProcessingJob.approved_by_id.is_not(None),
            NoticeProcessingJob.approved_at.is_not(None),
        ))
    job = db.scalar(select(NoticeProcessingJob).where(
        *conditions,
    ).with_for_update(skip_locked=True).limit(1))
    return _start_job(db, job, now) if job is not None else None


def _start_job(db: Session, job: NoticeProcessingJob, now: datetime) -> NoticeProcessingJob:
    job.status = "RUNNING"
    job.attempts += 1
    job.lease_until = now + LEASE
    job.updated_at = now
    db.add(NoticeProcessingAttempt(job_id=job.id, attempt_number=job.attempts,
                                    outcome="RUNNING", started_at=now))
    db.commit()
    return job


def finish_job(
    db: Session, job_id: UUID, *, attempt_number: int, error: str | None = None,
    superseded: bool = False, now: datetime | None = None,
) -> NoticeProcessingJob:
    now = now or datetime.now(timezone.utc)
    job = db.scalar(select(NoticeProcessingJob).where(NoticeProcessingJob.id == job_id).with_for_update())
    if job is None or job.status != "RUNNING" or job.attempts != attempt_number:
        raise ValueError("PROCESSING_JOB_NOT_RUNNING")
    attempt = db.scalar(select(NoticeProcessingAttempt).where(
        NoticeProcessingAttempt.job_id == job.id,
        NoticeProcessingAttempt.attempt_number == job.attempts,
    ).with_for_update())
    assert attempt is not None
    version = load_version(db, job.notice_version_id)
    superseded = superseded or version is None or input_fingerprint(version, job.stage) != job.input_fingerprint
    if superseded and job.stage == "ANALYZE":
        # The analysis and its clause memories may still be uncommitted in this
        # session. Never commit them while recording a superseded attempt.
        db.rollback()
        job = db.scalar(select(NoticeProcessingJob).where(NoticeProcessingJob.id == job_id).with_for_update())
        if job is None or job.status != "RUNNING" or job.attempts != attempt_number:
            raise ValueError("PROCESSING_JOB_NOT_RUNNING")
        attempt = db.scalar(select(NoticeProcessingAttempt).where(
            NoticeProcessingAttempt.job_id == job.id,
            NoticeProcessingAttempt.attempt_number == job.attempts,
        ).with_for_update())
        assert attempt is not None
    job.lease_until = None
    job.updated_at = now
    attempt.finished_at = now
    if superseded:
        job.status = attempt.outcome = "SUPERSEDED"
        job.last_error = None
    elif error:
        job.status = attempt.outcome = "FAILED"
        job.last_error = error[:2000]
        attempt.error = job.last_error
        job.next_attempt_at = now + BACKOFF * (2 ** min((job.attempts - 1) % MAX_ATTEMPTS, 2))
    else:
        job.status = attempt.outcome = "COMPLETED"
        job.last_error = None
    db.commit()
    return job
