"""System-admin controls for version-bound durable work and explicit LLM approval."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..auth_models import AppUser
from ..database import get_db
from ..errors import ApiError
from ..models import NoticeProcessingAttempt, NoticeProcessingJob
from ..services.notice_processing import enqueue_version_job, load_version, MAX_ATTEMPTS


router = APIRouter(prefix="/api/v1/admin/processing-jobs", tags=["admin processing jobs"])


class ProcessingJobRead(BaseModel):
    model_config = {"from_attributes": True}
    id: UUID
    notice_version_id: UUID
    stage: str
    status: str
    priority: int
    attempts: int
    retry_budget: int
    next_attempt_at: datetime
    last_error: str | None
    approved_by_id: UUID | None
    approved_at: datetime | None
    updated_at: datetime


class ProcessingAttemptRead(BaseModel):
    model_config = {"from_attributes": True}
    attempt_number: int
    outcome: str
    error: str | None
    started_at: datetime
    finished_at: datetime | None


def _admin(user: AppUser = Depends(get_current_user)) -> AppUser:
    if user.role != "SYSTEM_ADMIN":
        raise ApiError(403, "SYSTEM_ADMIN_REQUIRED", "작업 실행과 LLM 승인은 시스템 관리자만 할 수 있습니다.")
    return user


@router.get("", response_model=list[ProcessingJobRead])
def list_jobs(
    status: str | None = Query(default=None, pattern="^(PENDING|RUNNING|COMPLETED|FAILED|SUPERSEDED)$"),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db), _user: AppUser = Depends(_admin),
) -> list[ProcessingJobRead]:
    query = select(NoticeProcessingJob)
    if status:
        query = query.where(NoticeProcessingJob.status == status)
    return [ProcessingJobRead.model_validate(job) for job in db.scalars(
        query.order_by(NoticeProcessingJob.updated_at.desc()).limit(limit)
    )]


@router.get("/{job_id}/attempts", response_model=list[ProcessingAttemptRead])
def list_attempts(
    job_id: UUID, db: Session = Depends(get_db), _user: AppUser = Depends(_admin),
) -> list[ProcessingAttemptRead]:
    if db.get(NoticeProcessingJob, job_id) is None:
        raise ApiError(404, "PROCESSING_JOB_NOT_FOUND", "작업을 찾을 수 없습니다.")
    return [ProcessingAttemptRead.model_validate(attempt) for attempt in db.scalars(
        select(NoticeProcessingAttempt).where(NoticeProcessingAttempt.job_id == job_id)
        .order_by(NoticeProcessingAttempt.attempt_number)
    )]


@router.post("/{job_id}/retry", response_model=ProcessingJobRead)
def retry_job(
    job_id: UUID, db: Session = Depends(get_db), _user: AppUser = Depends(_admin),
) -> ProcessingJobRead:
    job = db.scalar(select(NoticeProcessingJob).where(NoticeProcessingJob.id == job_id).with_for_update())
    if job is None:
        raise ApiError(404, "PROCESSING_JOB_NOT_FOUND", "작업을 찾을 수 없습니다.")
    if job.status != "FAILED" or job.attempts < job.retry_budget:
        raise ApiError(409, "PROCESSING_RETRY_NOT_EXHAUSTED", "재시도 한도에 도달한 실패 작업만 재대기할 수 있습니다.")
    version = load_version(db, job.notice_version_id)
    if version is None:
        raise ApiError(409, "NOTICE_VERSION_NOT_FOUND", "공고 차수가 없어 재대기할 수 없습니다.")
    from ..services.notice_processing import input_fingerprint
    if input_fingerprint(version, job.stage) != job.input_fingerprint:
        raise ApiError(409, "PROCESSING_INPUT_CHANGED", "공고 입력이 변경되어 기존 작업을 재실행할 수 없습니다.")
    if job.stage == "ANALYZE" and (not job.approved_by_id or not job.approved_at):
        raise ApiError(409, "ANALYSIS_APPROVAL_REQUIRED", "이 차수의 LLM 분석 승인이 없습니다.")
    job.status = "PENDING"
    job.retry_budget += MAX_ATTEMPTS
    job.next_attempt_at = job.updated_at = datetime.now(timezone.utc)
    job.lease_until = None
    db.commit()
    db.refresh(job)
    return ProcessingJobRead.model_validate(job)


@router.post("/versions/{version_id}/approve-analysis", response_model=ProcessingJobRead)
def approve_analysis(
    version_id: UUID, db: Session = Depends(get_db), user: AppUser = Depends(_admin),
) -> ProcessingJobRead:
    version = load_version(db, version_id, lock=True)
    if version is None:
        raise ApiError(404, "NOTICE_VERSION_NOT_FOUND", "공고 차수를 찾을 수 없습니다.")
    if not version.documents or any(doc.download_status != "DOWNLOADED" or doc.extraction_status != "EXTRACTED"
                                    for doc in version.documents):
        raise ApiError(409, "DOCUMENTS_NOT_READY", "모든 첨부의 다운로드·추출 완료 후 승인할 수 있습니다.")
    enqueue_version_job(db, version_id=version_id, stage="INDEX", approved_by_id=user.id)
    job = enqueue_version_job(db, version_id=version_id, stage="ANALYZE", approved_by_id=user.id)
    if job.status == "RUNNING":
        raise ApiError(409, "ANALYSIS_ALREADY_RUNNING", "이 공고 차수의 분석 작업이 이미 실행 중입니다.")
    if job.status in {"COMPLETED", "FAILED"}:
        job.status = "PENDING"
        job.retry_budget = max(job.retry_budget, job.attempts + MAX_ATTEMPTS)
        job.next_attempt_at = datetime.now(timezone.utc)
        job.approved_by_id = user.id
        job.approved_at = job.updated_at = job.next_attempt_at
    db.commit()
    db.refresh(job)
    return ProcessingJobRead.model_validate(job)
