from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ...auth import authorize_company_access, get_optional_current_user
from ...auth_models import AppUser
from ...database import get_db
from ...errors import ApiError
from ...matching_schemas import NoticeMatchSearchResponse
from ..judgment import QualificationJudgmentError
from ..matching import match_cached_notices


router = APIRouter(prefix="/api/v1", tags=["qualification matching"])


@router.get(
    "/companies/{company_id}/notice-matches",
    response_model=NoticeMatchSearchResponse,
)
def list_notice_matches(
    company_id: UUID,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    reference_date: date | None = None,
    db: Session = Depends(get_db),
    user: AppUser | None = Depends(get_optional_current_user),
) -> NoticeMatchSearchResponse:
    authorize_company_access(user, company_id)
    try:
        return match_cached_notices(
            db,
            company_id=company_id,
            reference_date=reference_date,
            limit=limit,
        )
    except QualificationJudgmentError as error:
        raise ApiError(error.status_code, error.code, error.message) from error
