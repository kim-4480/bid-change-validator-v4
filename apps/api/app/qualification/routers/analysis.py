"""HTTP boundary for persisted qualification Requirement analysis runs."""

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from bidengine.providers.openai import OpenAIStructuredExtractor
from ...analysis_schemas import QualificationAnalysisRunRead, QualificationAnalysisRunSummary
from ...database import get_db
from ...errors import ApiError
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
    try:
        run = run_qualification_analysis(
            db,
            notice_id=notice_id,
            version_number=version_number,
            structured_extract=extractor,
        )
    except QualificationAnalysisError as error:
        raise _analysis_error(error) from error
    except RuntimeError as error:
        raise ApiError(502, "AI_ANALYSIS_FAILED", str(error)) from error
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
