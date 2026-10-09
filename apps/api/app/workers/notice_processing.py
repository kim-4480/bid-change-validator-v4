"""Optional PostgreSQL worker for post-collection processing.

The worker is opt-in. EXTRACT/FEATURES never call an LLM. INDEX/ANALYZE
require PROCESSING_ENABLE_EXTERNAL=true; ANALYZE additionally requires an
admin-approved job for the exact document fingerprint.
"""

from __future__ import annotations

import logging
import os
import signal
from datetime import datetime, timezone
from threading import Event
from typing import Callable

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..database import SessionLocal
from ..document_rag.service import load_or_build_version_index
from ..models import NoticeDocument, NoticeProcessingJob, NoticeRecommendationFeature
from ..qualification.analysis import run_qualification_analysis
from ..services.document_reprocessing import extract_pending_documents
from ..services.notice_processing import claim_next_job, enqueue_version_job, feature_text, finish_job, load_version, input_fingerprint
from bidengine.providers.openai import OpenAIStructuredExtractor
from bidengine.rag.store import create_openai_embeddings


logger = logging.getLogger("notice-processing")


def _process(db: Session, job: NoticeProcessingJob, settings: Settings) -> None:
    version = load_version(db, job.notice_version_id)
    if version is None or input_fingerprint(version, job.stage) != job.input_fingerprint:
        return
    if job.stage == "EXTRACT":
        extract_pending_documents(db, settings=settings, limit=1000, retry_failed=True,
                                  notice_version_id=version.id)
        remaining = db.scalars(select(NoticeDocument).where(
            NoticeDocument.notice_version_id == version.id,
            NoticeDocument.extraction_status.in_(("PENDING", "FAILED")),
        )).all()
        if remaining:
            raise RuntimeError(f"EXTRACTION_INCOMPLETE:{len(remaining)}")
    elif job.stage == "INDEX":
        if not settings.processing_enable_external or not job.approved_by_id or not job.approved_at:
            raise RuntimeError("EXTERNAL_PROCESSING_DISABLED")
        load_or_build_version_index(
            db, notice_version_id=version.id,
            index_root=os.getenv("DOCUMENT_RAG_INDEX_ROOT", "data/document-rag"),
            embeddings=create_openai_embeddings(),
        )
    elif job.stage == "FEATURES":
        search_text = feature_text(version)
        db.execute(pg_insert(NoticeRecommendationFeature).values(
            notice_version_id=version.id, input_fingerprint=job.input_fingerprint,
            search_text=search_text, updated_at=datetime.now(timezone.utc),
        ).on_conflict_do_update(
            index_elements=[NoticeRecommendationFeature.notice_version_id],
            set_={"input_fingerprint": job.input_fingerprint, "search_text": search_text,
                  "updated_at": datetime.now(timezone.utc)},
        ))
        db.commit()
    elif job.stage == "ANALYZE":
        if not settings.processing_enable_external or not job.approved_by_id or not job.approved_at:
            raise RuntimeError("ANALYSIS_APPROVAL_REQUIRED")
        run_qualification_analysis(
            db, notice_id=version.notice_id, version_number=version.version_number,
            structured_extract=OpenAIStructuredExtractor(),
            commit=False,
        )
    else:
        raise RuntimeError("UNKNOWN_PROCESSING_STAGE")


def run_processing_batch(
    *, settings: Settings, session_factory: Callable[[], Session] = SessionLocal,
    limit: int = 10,
) -> int:
    """Claim with SKIP LOCKED, then execute without holding the claim lock."""
    completed = 0
    for _ in range(limit):
        with session_factory() as db:
            job = claim_next_job(db, allow_external=settings.processing_enable_external)
            if job is None:
                break
            job_id, attempt, stage, version_id = job.id, job.attempts, job.stage, job.notice_version_id
            try:
                _process(db, job, settings)
                finished = finish_job(db, job_id, attempt_number=attempt)
                if finished.status == "COMPLETED":
                    completed += 1
                    if stage == "EXTRACT":
                        enqueue_version_job(db, version_id=version_id, stage="FEATURES")
                        enqueue_version_job(db, version_id=version_id, stage="INDEX")
                        db.commit()
                elif finished.status == "SUPERSEDED" and stage in {"EXTRACT", "FEATURES"}:
                    # Extraction can legitimately fill a missing file hash.
                    # Preserve the old attempt, then continue with the new
                    # fingerprint rather than silently stranding this version.
                    enqueue_version_job(db, version_id=version_id, stage=stage)
                    db.commit()
            except Exception as error:
                db.rollback()
                # Never persist raw provider/S3 errors (credentials may occur in them).
                safe_error = f"{type(error).__name__}:{str(error).split(':', 1)[0]}"[:200]
                try:
                    finish_job(db, job_id, attempt_number=attempt, error=safe_error)
                except ValueError:
                    db.rollback()  # a later worker owns this lease
                logger.exception("processing failed job_id=%s stage=%s", job_id, stage)
    return completed


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    stopping = Event()
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    signal.signal(signal.SIGINT, lambda *_: stopping.set())
    while not stopping.is_set():
        completed = run_processing_batch(settings=settings, limit=settings.processing_batch_size)
        if completed == 0:
            stopping.wait(settings.processing_poll_interval_seconds)


if __name__ == "__main__":
    main()
