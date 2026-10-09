"""HTTP boundary for persisted qualification Requirement analysis runs."""

from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from bidengine.providers.openai import OpenAIStructuredExtractor
from ...analysis_schemas import QualificationAnalysisRunRead, QualificationAnalysisRunSummary
from ...auth import get_current_user
from ...auth_models import AppUser
from ...database import get_db
from ...errors import ApiError
from ...models import BidNoticeVersion
from ...services.notice_processing import claim_approved_analysis_job, enqueue_version_job, finish_job
from ..analysis import (
    QualificationAnalysisError,
    analysis_run_response,
    list_qualification_analysis_runs,
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
    db: Session = Depends(get_db),
) -> QualificationAnalysisRunRead:
    extractor = OpenAIStructuredExtractor()
    if not extractor.available:
        raise ApiError(
            503,
            "AI_PROVIDER_NOT_CONFIGURED",
            "OPENAI_API_KEY가 설정되지 않아 자격요건 분석을 실행할 수 없습니다.",
        )
    version = db.scalar(select(BidNoticeVersion).where(
        BidNoticeVersion.notice_id == notice_id,
        BidNoticeVersion.version_number == version_number,
    ))
    if version is None:
        raise ApiError(404, "NOTICE_VERSION_NOT_FOUND", "공고 차수를 찾을 수 없습니다.")
    job = claim_approved_analysis_job(db, version_id=version.id)
    if job is None:
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
