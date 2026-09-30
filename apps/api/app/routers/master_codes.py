from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import ApiError
from ..models import IndustryCode, InstitutionCode, ProductCode
from ..schemas import (
    MasterCodeRead,
    MasterCodeSearchResponse,
    MasterCodeType,
)


router = APIRouter(prefix="/api/v1/master-codes", tags=["master codes"])

MODEL_BY_TYPE = {
    MasterCodeType.INDUSTRIES: IndustryCode,
    MasterCodeType.PRODUCTS: ProductCode,
    MasterCodeType.INSTITUTIONS: InstitutionCode,
}


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("/{code_type}", response_model=MasterCodeSearchResponse)
def search_master_codes(
    code_type: MasterCodeType,
    q: Annotated[str | None, Query(max_length=100)] = None,
    active_only: bool = True,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
) -> MasterCodeSearchResponse:
    model = MODEL_BY_TYPE[code_type]
    filters = []
    if active_only:
        filters.append(model.active.is_(True))

    normalized_query = q.strip() if q is not None else None
    if normalized_query == "":
        normalized_query = None

    relevance = None
    if normalized_query is not None:
        escaped = _escape_like(normalized_query)
        contains_pattern = f"%{escaped}%"
        prefix_pattern = f"{escaped}%"
        filters.append(
            or_(
                model.code.ilike(contains_pattern, escape="\\"),
                model.name.ilike(contains_pattern, escape="\\"),
            )
        )
        relevance = case(
            (func.lower(model.code) == normalized_query.lower(), 0),
            (model.code.ilike(prefix_pattern, escape="\\"), 1),
            (func.lower(model.name) == normalized_query.lower(), 2),
            (model.name.ilike(prefix_pattern, escape="\\"), 3),
            else_=4,
        )

    total = db.scalar(select(func.count()).select_from(model).where(*filters)) or 0
    statement = select(model).where(*filters)
    if relevance is not None:
        statement = statement.order_by(relevance, func.length(model.name), model.code)
    else:
        statement = statement.order_by(model.code)
    rows = db.scalars(statement.offset(offset).limit(limit)).all()

    return MasterCodeSearchResponse(
        type=code_type,
        query=normalized_query,
        active_only=active_only,
        total=total,
        limit=limit,
        offset=offset,
        items=[MasterCodeRead.model_validate(row) for row in rows],
    )


@router.get("/{code_type}/{code}", response_model=MasterCodeRead)
def get_master_code(
    code_type: MasterCodeType,
    code: str,
    db: Session = Depends(get_db),
) -> MasterCodeRead:
    model = MODEL_BY_TYPE[code_type]
    row = db.get(model, code)
    if row is None:
        raise ApiError(
            404,
            "MASTER_CODE_NOT_FOUND",
            "마스터 코드를 찾을 수 없습니다.",
            {"type": code_type.value, "code": code},
        )
    return MasterCodeRead.model_validate(row)
