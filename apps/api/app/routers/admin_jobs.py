"""System-admin inspection and explicit retry of the durable notice-history queue."""

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
from ..models import NoticeHistoryBackfillJob


router = APIRouter(prefix="/api/v1/admin/history-jobs", tags=["admin jobs"])


class HistoryJobRead(BaseModel):
    id: UUID
    notice_id: UUID
    status: str
    attempts: int
    next_attempt_at: datetime
    last_error: str | None
    updated_at: datetime


def _require_system_admin(user: AppUser = Depends(get_current_user)) -> AppUser:
    if user.role != "SYSTEM_ADMIN":
        raise ApiError(403, "SYSTEM_ADMIN_REQUIRED", "전체 수집 작업은 시스템 관리자만 관리할 수 있습니다.")
    return user


@router.get("", response_model=list[HistoryJobRead])
def list_history_jobs(
    status: str | None = Query(default=None, pattern="^(PENDING|RUNNING|COMPLETED|FAILED)$"),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: AppUser = Depends(_require_system_admin),
) -> list[HistoryJobRead]:
    query = select(NoticeHistoryBackfillJob)
    if status is not None:
        query = query.where(NoticeHistoryBackfillJob.status == status)
    jobs = db.scalars(query.order_by(NoticeHistoryBackfillJob.updated_at.desc()).limit(limit)).all()
    return [HistoryJobRead.model_validate(job, from_attributes=True) for job in jobs]


@router.post("/{job_id}/retry", response_model=HistoryJobRead)
def retry_history_job(
    job_id: UUID,
    db: Session = Depends(get_db),
    _user: AppUser = Depends(_require_system_admin),
) -> HistoryJobRead:
    """Queue one failed job; never execute an external G2B request in the API."""
    job = db.scalar(select(NoticeHistoryBackfillJob).where(NoticeHistoryBackfillJob.id == job_id).with_for_update())
    if job is None:
        raise ApiError(404, "HISTORY_JOB_NOT_FOUND", "수집 작업을 찾을 수 없습니다.")
    if job.status != "FAILED":
        raise ApiError(409, "HISTORY_JOB_NOT_FAILED", "실패한 작업만 재시도할 수 있습니다.")
    now = datetime.now(timezone.utc)
    job.status = "PENDING"
    job.attempts = 0
    job.next_attempt_at = now
    job.started_at = None
    job.completed_at = None
    job.updated_at = now
    db.commit()
    db.refresh(job)
    return HistoryJobRead.model_validate(job, from_attributes=True)
