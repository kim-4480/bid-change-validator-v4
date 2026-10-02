"""HTTP endpoints for contract-clause review persistence."""

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from ..clause_review_schemas import (
    ContractClauseReviewCreate,
    ContractClauseReviewRead,
    ContractClauseReviewSummary,
)
from ..database import get_db
from ..errors import ApiError
from ..services.clause_reviews import (
    ContractClauseReviewError,
    contract_clause_review_response,
    create_contract_clause_review,
    list_contract_clause_reviews,
    load_contract_clause_review,
)


router = APIRouter(tags=["contract clause reviews"])


def _api_error(error: ContractClauseReviewError) -> ApiError:
    return ApiError(error.status_code, error.code, error.message)


@router.post(
    "/api/v1/notices/{notice_id}/versions/{version_number}/contract-clause-reviews",
    response_model=ContractClauseReviewRead,
    status_code=status.HTTP_201_CREATED,
)
def save_contract_clause_review(
    notice_id: UUID,
    version_number: int,
    payload: ContractClauseReviewCreate,
    db: Session = Depends(get_db),
) -> ContractClauseReviewRead:
    try:
        run = create_contract_clause_review(
            db,
            notice_id=notice_id,
            version_number=version_number,
            payload=payload,
        )
        return contract_clause_review_response(run)
    except ContractClauseReviewError as error:
        db.rollback()
        raise _api_error(error) from error


@router.get(
    "/api/v1/notices/{notice_id}/versions/{version_number}/contract-clause-reviews",
    response_model=list[ContractClauseReviewSummary],
)
def get_version_contract_clause_reviews(
    notice_id: UUID,
    version_number: int,
    db: Session = Depends(get_db),
) -> list[ContractClauseReviewSummary]:
    try:
        return list_contract_clause_reviews(
            db, notice_id=notice_id, version_number=version_number
        )
    except ContractClauseReviewError as error:
        raise _api_error(error) from error


@router.get(
    "/api/v1/contract-clause-reviews/{run_id}",
    response_model=ContractClauseReviewRead,
)
def get_contract_clause_review(
    run_id: UUID,
    db: Session = Depends(get_db),
) -> ContractClauseReviewRead:
    try:
        return contract_clause_review_response(load_contract_clause_review(db, run_id))
    except ContractClauseReviewError as error:
        raise _api_error(error) from error
