from __future__ import annotations

from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import NoticeHistoryBackfillJob


KST = ZoneInfo("Asia/Seoul")


def enqueue_notice_history_backfill(
    db: Session,
    *,
    notice_id: UUID,
    queued_at: datetime | None = None,
) -> NoticeHistoryBackfillJob:
    """Create the one durable full-history job assigned to a notice."""

    existing = db.scalar(
        select(NoticeHistoryBackfillJob).where(
            NoticeHistoryBackfillJob.notice_id == notice_id
        )
    )
    if existing is not None:
        return existing

    queued_at = queued_at or datetime.now(KST)
    job = NoticeHistoryBackfillJob(
        notice_id=notice_id,
        status="PENDING",
        attempts=0,
        next_attempt_at=queued_at,
        updated_at=queued_at,
    )
    db.add(job)
    db.flush()
    return job
