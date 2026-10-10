"""HTTP boundary for persisted qualification Requirement analysis runs."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from bidengine.providers.openai import OpenAIStructuredExtractor
from ...analysis_schemas import QualificationAnalysisRunRead, QualificationAnalysisRunSummary
from ...auth import get_current_user, get_optional_current_user
from ...auth_models import AppUser
from ...database import get_db
from ...config import get_settings
from ...errors import ApiError
from ...models import BidNoticeVersion, NoticeProcessingAttempt, NoticeProcessingJob
from ...services.notice_processing import claim_approved_analysis_job, enqueue_version_job, finish_job
from ..analysis import (
    QualificationAnalysisError,
    analysis_run_response,
    list_qualification_analysis_runs,
    load_latest_current_qualification_analysis_run,
    load_qualification_analysis_run,
    run_qualification_analysis,
)


router = APIRouter(tags=["qualification analysis"])


def _analysis_error(error: QualificationAnalysisError) -> ApiError:
    status_code = 404 if error.code in {"NOTICE_VERSION_NOT_FOUND", "ANALYSIS_RUN_NOT_FOUND"} else 422
    return ApiError(status_code, error.code, error.message)


class QualificationAnalysisRequestRead(BaseModel):
    notice_version_id: UUID
    job_id: UUID
    job_status: str
    approved: bool
    documents_ready: bool


@router.post(
    "/api/v1/notices/{notice_id}/versions/{version_number}/qualification-analysis/request",
    response_model=QualificationAnalysisRequestRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def request_qualification_analysis(
    notice_id: UUID,
    version_number: int,
    db: Session = Depends(get_db),
    _user: AppUser = Depends(get_current_user),
) -> QualificationAnalysisRequestRead:
    """Request review without granting permission to spend tokens or run an LLM."""
    version = db.scalar(select(BidNoticeVersion).where(
        BidNoticeVersion.notice_id == notice_id,
        BidNoticeVersion.version_number == version_number,
    ))
    if version is None:
        raise ApiError(404, "NOTICE_VERSION_NOT_FOUND", "공고 차수를 찾을 수 없습니다.")
    ready = bool(version.documents) and all(
        doc.download_status == "DOWNLOADED" and doc.extraction_status == "EXTRACTED"
        for doc in version.documents
    )
    if not ready:
        enqueue_version_job(db, version_id=version.id, stage="EXTRACT")
    job = enqueue_version_job(
        db, version_id=version.id, stage="ANALYZE", allow_unapproved_analysis=True,
    )
    db.commit()
    return QualificationAnalysisRequestRead(
        notice_version_id=version.id, job_id=job.id, job_status=job.status,
        approved=bool(job.approved_by_id and job.approved_at), documents_ready=ready,
    )


@router.post(
    "/api/v1/notices/{notice_id}/versions/{version_number}/qualification-analysis",
    response_model=QualificationAnalysisRunRead,
    status_code=status.HTTP_201_CREATED,
)
def trigger_qualification_analysis(
    notice_id: UUID,
    version_number: int,
    force: bool = Query(default=False),
    db: Session = Depends(get_db),
    user: AppUser | None = Depends(get_optional_current_user),
) -> QualificationAnalysisRunRead:
    version = db.scalar(select(BidNoticeVersion).where(
        BidNoticeVersion.notice_id == notice_id,
        BidNoticeVersion.version_number == version_number,
    ))
    if version is None:
        raise ApiError(404, "NOTICE_VERSION_NOT_FOUND", "공고 차수를 찾을 수 없습니다.")
    settings = get_settings()
    self_service = settings.qualification_self_service_enabled
    if self_service:
        if user is None:
            raise ApiError(401, "AUTHENTICATION_REQUIRED", "로그인 후 분석을 실행할 수 있습니다.")
        if not force:
            existing = load_latest_current_qualification_analysis_run(
                db, notice_version_id=version.id, include_failed=True,
            )
            if existing is not None and existing.status != "FAILED":
                return analysis_run_response(existing)
        if not version.documents or any(
            doc.download_status != "DOWNLOADED" or doc.extraction_status != "EXTRACTED"
            for doc in version.documents
        ):
            raise ApiError(409, "DOCUMENTS_NOT_READY", "첨부파일 추출 완료 후 분석할 수 있습니다.")
    extractor = OpenAIStructuredExtractor()
    if not extractor.available:
        raise ApiError(
            503,
            "AI_PROVIDER_NOT_CONFIGURED",
            "OPENAI_API_KEY가 설정되지 않아 자격요건 분석을 실행할 수 없습니다.",
        )
    if self_service:
        # Serialize the development-only spend cap until _start_job commits its
        # attempt row. Existing same-input results return above without spending.
        db.execute(text("SELECT pg_advisory_xact_lock(2146300410)"))
        attempts_today = db.scalar(
            select(func.count(NoticeProcessingAttempt.id))
            .join(NoticeProcessingJob, NoticeProcessingAttempt.job_id == NoticeProcessingJob.id)
            .where(
                NoticeProcessingJob.stage == "ANALYZE",
                NoticeProcessingJob.approved_by_id.is_(None),
                NoticeProcessingAttempt.started_at >= datetime.now(timezone.utc) - timedelta(days=1),
            )
        ) or 0
        if attempts_today >= settings.qualification_self_service_daily_limit:
            raise ApiError(429, "ANALYSIS_DAILY_LIMIT", "개발 환경의 오늘 AI 분석 한도에 도달했습니다.")
        job = enqueue_version_job(
            db, version_id=version.id, stage="ANALYZE", allow_unapproved_analysis=True,
        )
        if job.status == "RUNNING":
            raise ApiError(409, "ANALYSIS_ALREADY_RUNNING", "이 공고 차수는 이미 분석 중입니다.")
        if job.status in {"COMPLETED", "FAILED"}:
            job.status = "PENDING"
            job.next_attempt_at = job.updated_at = datetime.now(timezone.utc)
            job.retry_budget = max(job.retry_budget, job.attempts + 1)
        db.flush()
    job = claim_approved_analysis_job(db, version_id=version.id, allow_unapproved=self_service)
    if job is None:
        if self_service:
            raise ApiError(409, "ANALYSIS_ALREADY_RUNNING", "이 공고 차수의 분석이 이미 실행 중이거나 잠시 후 재시도할 수 있습니다.")
        raise ApiError(409, "ANALYSIS_APPROVAL_REQUIRED", "현재 공고 차수·문서 입력에 대한 관리자 승인 또는 실행 가능한 작업이 없습니다.")
    try:
        run = run_qualification_analysis(
            db,
            notice_id=notice_id,
            version_number=version_number,
            structured_extract=extractor,
            commit=False,
        )
        finished = finish_job(db, job.id, attempt_number=job.attempts)
        if finished.status != "COMPLETED":
            raise ApiError(409, "ANALYSIS_INPUT_CHANGED", "분석 중 문서 입력이 변경되어 결과를 최신 판정에 사용할 수 없습니다.")
    except QualificationAnalysisError as error:
        db.rollback()
        finish_job(db, job.id, attempt_number=job.attempts, error=error.code)
        raise _analysis_error(error) from error
    except ApiError:
        raise
    except RuntimeError as error:
        db.rollback()
        finish_job(db, job.id, attempt_number=job.attempts, error=type(error).__name__)
        raise ApiError(502, "AI_ANALYSIS_FAILED", "AI 분석이 실패했습니다. 관리자 작업 이력을 확인해 주세요.") from error
    except Exception as error:
        db.rollback()
        finish_job(db, job.id, attempt_number=job.attempts, error=type(error).__name__)
        raise ApiError(502, "AI_ANALYSIS_FAILED", "AI 분석이 실패했습니다. 관리자 작업 이력을 확인해 주세요.") from error
    return analysis_run_response(run)


@router.get(
    "/api/v1/notices/{notice_id}/versions/{version_number}/qualification-analyses",
    response_model=list[QualificationAnalysisRunSummary],
)
def list_version_qualification_analyses(
    notice_id: UUID,
    version_number: int,
    db: Session = Depends(get_db),
) -> list[QualificationAnalysisRunSummary]:
    try:
        return list_qualification_analysis_runs(
            db, notice_id=notice_id, version_number=version_number
        )
    except QualificationAnalysisError as error:
        raise _analysis_error(error) from error


@router.get(
    "/api/v1/qualification-analyses/{run_id}",
    response_model=QualificationAnalysisRunRead,
)
def get_qualification_analysis(
    run_id: UUID,
    db: Session = Depends(get_db),
) -> QualificationAnalysisRunRead:
    try:
        return analysis_run_response(load_qualification_analysis_run(db, run_id))
    except QualificationAnalysisError as error:
        raise _analysis_error(error) from error
