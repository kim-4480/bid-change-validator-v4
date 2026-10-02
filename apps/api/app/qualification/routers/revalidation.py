"""HTTP route for changed-notice qualification revalidation."""

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...auth import authorize_case_access, get_optional_current_user
from ...auth_models import AppUser
from ...database import get_db
from ...errors import ApiError
from ..judgment import QualificationJudgmentError
from ..revalidation import run_qualification_revalidation
from ...revalidation_schemas import QualificationRevalidationCreate, QualificationRevalidationRead


router = APIRouter(prefix="/api/v1", tags=["qualification revalidation"])


def _as_api_error(error: QualificationJudgmentError) -> ApiError:
    return ApiError(error.status_code, error.code, error.message)


@router.post(
    "/preflight-cases/{case_id}/qualification-revalidation",
    response_model=QualificationRevalidationRead,
)
def trigger_qualification_revalidation(
    case_id: UUID,
    payload: QualificationRevalidationCreate,
    db: Session = Depends(get_db),
    user: AppUser | None = Depends(get_optional_current_user),
) -> QualificationRevalidationRead:
    authorize_case_access(db, user, case_id)
    try:
        return run_qualification_revalidation(db, case_id=case_id, payload=payload)
    except QualificationJudgmentError as error:
        raise _as_api_error(error) from error
