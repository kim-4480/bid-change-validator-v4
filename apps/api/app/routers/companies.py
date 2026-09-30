from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ..auth import authorize_company_access, get_optional_current_user
from ..auth_models import AppUser
from ..database import get_db
from ..errors import ApiError
from ..models import (
    Company,
    CompanyCertification,
    CompanyIndustry,
    CompanyPerformance,
    CompanyPerformanceField,
    CompanyStaff,
    CompanyStaffRole,
    IndustryCode,
    InstitutionCode,
)
from ..schemas import (
    CertificationCreate,
    CertificationRead,
    CertificationUpdate,
    CompanyCreate,
    CompanyRead,
    CompanyUpdate,
    IndustryRead,
    PerformanceCreate,
    PerformanceRead,
    PerformanceUpdate,
    StaffRead,
    StaffRoleRead,
)


router = APIRouter(prefix="/api/v1/companies", tags=["companies"])

COMPANY_LOAD_OPTIONS = (
    selectinload(Company.industries).selectinload(CompanyIndustry.industry),
    selectinload(Company.staff),
    selectinload(Company.staff_roles),
    selectinload(Company.performances).selectinload(CompanyPerformance.experience_fields),
    selectinload(Company.certifications),
)


def _load_company(db: Session, company_id: UUID) -> Company:
    company = db.scalar(
        select(Company).where(Company.id == company_id).options(*COMPANY_LOAD_OPTIONS)
    )
    if company is None:
        raise ApiError(404, "COMPANY_NOT_FOUND", "회사를 찾을 수 없습니다.")
    return company


def _load_performance(db: Session, company_id: UUID, performance_id: UUID) -> CompanyPerformance:
    performance = db.scalar(
        select(CompanyPerformance)
        .where(
            CompanyPerformance.id == performance_id,
            CompanyPerformance.company_id == company_id,
        )
        .options(selectinload(CompanyPerformance.experience_fields))
    )
    if performance is None:
        raise ApiError(404, "PERFORMANCE_NOT_FOUND", "수행실적을 찾을 수 없습니다.")
    return performance


def _load_certification(
    db: Session, company_id: UUID, certification_id: UUID
) -> CompanyCertification:
    certification = db.scalar(
        select(CompanyCertification).where(
            CompanyCertification.id == certification_id,
            CompanyCertification.company_id == company_id,
        )
    )
    if certification is None:
        raise ApiError(404, "CERTIFICATION_NOT_FOUND", "인증정보를 찾을 수 없습니다.")
    return certification


def _validate_industry_codes(db: Session, codes: list[str]) -> dict[str, IndustryCode]:
    industries = {
        industry.code: industry
        for industry in db.scalars(
            select(IndustryCode).where(
                IndustryCode.code.in_(codes), IndustryCode.active.is_(True)
            )
        )
    }
    unknown = sorted(set(codes) - industries.keys())
    if unknown:
        raise ApiError(
            422,
            "INVALID_INDUSTRY_CODE",
            "존재하지 않거나 비활성화된 업종 코드가 있습니다.",
            {"codes": unknown},
        )
    return industries


def _validate_institution_code(db: Session, code: str | None) -> None:
    if code is None:
        return
    exists = db.scalar(
        select(InstitutionCode.code).where(
            InstitutionCode.code == code, InstitutionCode.active.is_(True)
        )
    )
    if exists is None:
        raise ApiError(
            422,
            "INVALID_INSTITUTION_CODE",
            "존재하지 않거나 비활성화된 기관 코드입니다.",
            {"code": code},
        )


def _performance_response(performance: CompanyPerformance) -> PerformanceRead:
    return PerformanceRead(
        id=performance.id,
        name=performance.name,
        client_name=performance.client_name,
        client_institution_code=performance.client_institution_code,
        amount=int(performance.amount),
        started_at=performance.started_at,
        completed_at=performance.completed_at,
        completed_year=performance.completed_year,
        description=performance.description,
        fields=sorted(field.field_name for field in performance.experience_fields),
        verified=performance.verified,
        created_at=performance.created_at,
        updated_at=performance.updated_at,
    )


def _certification_response(certification: CompanyCertification) -> CertificationRead:
    return CertificationRead.model_validate(certification)


def _company_response(company: Company) -> CompanyRead:
    staff = None
    if company.staff is not None:
        staff = StaffRead(
            total_count=company.staff.total_count,
            verified=company.staff.verified,
            roles=[
                StaffRoleRead(
                    role_name=role.role_name,
                    headcount=role.headcount,
                    career_years=(
                        float(role.career_years)
                        if role.career_years is not None
                        else None
                    ),
                    verified=role.verified,
                )
                for role in sorted(company.staff_roles, key=lambda item: item.role_name)
            ],
        )

    return CompanyRead(
        id=company.id,
        name=company.name,
        business_registration_number=company.business_registration_number,
        region_code=company.region_code,
        region_name=company.region_name,
        company_size=company.company_size,
        industries=[
            IndustryRead(
                code=item.industry_code,
                name=item.industry.name,
                verified=item.verified,
            )
            for item in sorted(company.industries, key=lambda value: value.industry_code)
        ],
        staff=staff,
        performances=[
            _performance_response(performance)
            for performance in sorted(
                company.performances,
                key=lambda item: (
                    item.completed_at
                    or date(item.completed_year or 1900, 12, 31),
                    str(item.id),
                ),
                reverse=True,
            )
        ],
        certifications=[
            _certification_response(certification)
            for certification in sorted(
                company.certifications, key=lambda item: (item.name, str(item.id))
            )
        ],
        created_at=company.created_at,
        updated_at=company.updated_at,
    )


def _commit(db: Session, conflict_message: str) -> None:
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise ApiError(409, "DATA_CONFLICT", conflict_message) from error


@router.post("", response_model=CompanyRead, status_code=status.HTTP_201_CREATED)
def create_company(
    payload: CompanyCreate,
    db: Session = Depends(get_db),
    user: AppUser | None = Depends(get_optional_current_user),
) -> CompanyRead:
    if user is not None and user.role != "SYSTEM_ADMIN":
        raise ApiError(403, "COMPANY_CREATION_FORBIDDEN", "회사 생성 권한이 없습니다.")
    industries = _validate_industry_codes(db, payload.industry_codes)
    company = Company(
        name=payload.name,
        business_registration_number=payload.business_registration_number,
        region_code=payload.region_code,
        region_name=payload.region_name,
        company_size=payload.company_size.value,
    )
    db.add(company)
    try:
        db.flush()
    except IntegrityError as error:
        db.rollback()
        raise ApiError(409, "DATA_CONFLICT", "이미 등록된 사업자등록번호입니다.") from error

    company.industries = [
        CompanyIndustry(industry_code=code, industry=industries[code])
        for code in payload.industry_codes
    ]
    company.staff = CompanyStaff(
        total_count=payload.staff.total_count,
        verified=payload.staff.verified,
    )
    company.staff_roles = [
        CompanyStaffRole(
            role_name=role.role_name,
            headcount=role.headcount,
            career_years=role.career_years,
            verified=role.verified,
        )
        for role in payload.staff.roles
    ]
    _commit(db, "이미 등록된 사업자등록번호입니다.")
    return _company_response(_load_company(db, company.id))


@router.get("", response_model=list[CompanyRead])
def list_companies(
    db: Session = Depends(get_db),
    user: AppUser | None = Depends(get_optional_current_user),
) -> list[CompanyRead]:
    query = select(Company).options(*COMPANY_LOAD_OPTIONS).order_by(Company.created_at.desc())
    if user is not None and user.role != "SYSTEM_ADMIN":
        if user.company_id is None:
            return []
        query = query.where(Company.id == user.company_id)
    companies = db.scalars(query).all()
    return [_company_response(company) for company in companies]


@router.get("/{company_id}", response_model=CompanyRead)
def get_company(
    company_id: UUID,
    db: Session = Depends(get_db),
    user: AppUser | None = Depends(get_optional_current_user),
) -> CompanyRead:
    authorize_company_access(user, company_id)
    return _company_response(_load_company(db, company_id))


@router.patch("/{company_id}", response_model=CompanyRead)
def update_company(
    company_id: UUID,
    payload: CompanyUpdate,
    db: Session = Depends(get_db),
    user: AppUser | None = Depends(get_optional_current_user),
) -> CompanyRead:
    authorize_company_access(user, company_id, write=True)
    company = _load_company(db, company_id)
    supplied = payload.model_fields_set

    for field in (
        "name",
        "business_registration_number",
        "region_code",
        "region_name",
        "company_size",
    ):
        if field not in supplied:
            continue
        value = getattr(payload, field)
        if field in {"name", "company_size"} and value is None:
            raise ApiError(422, "INVALID_REQUEST", f"{field} cannot be null")
        if field == "company_size" and value is not None:
            value = value.value
        setattr(company, field, value)

    if "industry_codes" in supplied:
        if payload.industry_codes is None:
            raise ApiError(422, "INVALID_REQUEST", "industry_codes cannot be null")
        industries = _validate_industry_codes(db, payload.industry_codes)
        existing = {item.industry_code: item for item in company.industries}
        company.industries = [
            existing.get(code)
            or CompanyIndustry(industry_code=code, industry=industries[code])
            for code in payload.industry_codes
        ]

    if "staff" in supplied:
        if payload.staff is None:
            raise ApiError(422, "INVALID_REQUEST", "staff cannot be null")
        if company.staff is None:
            company.staff = CompanyStaff(total_count=0, verified=False)
        if "total_count" in payload.staff.model_fields_set:
            if payload.staff.total_count is None:
                raise ApiError(422, "INVALID_REQUEST", "staff.total_count cannot be null")
            company.staff.total_count = payload.staff.total_count
        if "verified" in payload.staff.model_fields_set:
            if payload.staff.verified is None:
                raise ApiError(422, "INVALID_REQUEST", "staff.verified cannot be null")
            company.staff.verified = payload.staff.verified
        if "roles" in payload.staff.model_fields_set:
            if payload.staff.roles is None:
                raise ApiError(422, "INVALID_REQUEST", "staff.roles cannot be null")
            company.staff_roles = [
                CompanyStaffRole(
                    role_name=role.role_name,
                    headcount=role.headcount,
                    career_years=role.career_years,
                    verified=role.verified,
                )
                for role in payload.staff.roles
            ]

    _commit(db, "이미 등록된 사업자등록번호입니다.")
    return _company_response(_load_company(db, company_id))


@router.delete("/{company_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_company(
    company_id: UUID,
    db: Session = Depends(get_db),
    user: AppUser | None = Depends(get_optional_current_user),
) -> Response:
    authorize_company_access(user, company_id, write=True)
    if user is not None and user.role != "SYSTEM_ADMIN":
        raise ApiError(403, "COMPANY_DELETION_FORBIDDEN", "회사 삭제 권한이 없습니다.")
    company = _load_company(db, company_id)
    db.delete(company)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/{company_id}/industries/{industry_code}", response_model=CompanyRead)
def set_company_industry_verification(
    company_id: UUID,
    industry_code: str,
    verified: bool,
    db: Session = Depends(get_db),
    user: AppUser | None = Depends(get_optional_current_user),
) -> CompanyRead:
    authorize_company_access(user, company_id, write=True)
    company = _load_company(db, company_id)
    industry = next(
        (item for item in company.industries if item.industry_code == industry_code), None
    )
    if industry is None:
        raise ApiError(404, "COMPANY_INDUSTRY_NOT_FOUND", "회사 업종 정보를 찾을 수 없습니다.")
    industry.verified = verified
    db.commit()
    return _company_response(_load_company(db, company_id))


@router.post(
    "/{company_id}/performances",
    response_model=PerformanceRead,
    status_code=status.HTTP_201_CREATED,
)
def create_performance(
    company_id: UUID,
    payload: PerformanceCreate,
    db: Session = Depends(get_db),
    user: AppUser | None = Depends(get_optional_current_user),
) -> PerformanceRead:
    authorize_company_access(user, company_id, write=True)
    _load_company(db, company_id)
    _validate_institution_code(db, payload.client_institution_code)
    performance = CompanyPerformance(
        company_id=company_id,
        name=payload.name,
        client_name=payload.client_name,
        client_institution_code=payload.client_institution_code,
        amount=payload.amount,
        started_at=payload.started_at,
        completed_at=payload.completed_at,
        completed_year=payload.completed_year,
        description=payload.description,
        verified=payload.verified,
        experience_fields=[
            CompanyPerformanceField(field_name=field) for field in payload.fields
        ],
    )
    db.add(performance)
    db.commit()
    return _performance_response(_load_performance(db, company_id, performance.id))


@router.patch(
    "/{company_id}/performances/{performance_id}", response_model=PerformanceRead
)
def update_performance(
    company_id: UUID,
    performance_id: UUID,
    payload: PerformanceUpdate,
    db: Session = Depends(get_db),
    user: AppUser | None = Depends(get_optional_current_user),
) -> PerformanceRead:
    authorize_company_access(user, company_id, write=True)
    performance = _load_performance(db, company_id, performance_id)
    supplied = payload.model_fields_set

    if "client_institution_code" in supplied:
        _validate_institution_code(db, payload.client_institution_code)

    completion_fields = {"completed_at", "completed_year"} & supplied
    if completion_fields:
        completed_at = (
            payload.completed_at
            if "completed_at" in supplied
            else performance.completed_at
        )
        completed_year = (
            payload.completed_year
            if "completed_year" in supplied
            else performance.completed_year
        )
        if payload.completed_at is not None and "completed_year" not in supplied:
            completed_year = None
        if payload.completed_year is not None and "completed_at" not in supplied:
            completed_at = None
        if (completed_at is None) == (completed_year is None):
            raise ApiError(
                422,
                "INVALID_COMPLETION_DATE",
                "completed_at 또는 completed_year 중 하나만 입력해야 합니다.",
            )
        performance.completed_at = completed_at
        performance.completed_year = completed_year

    for field in (
        "name",
        "client_name",
        "client_institution_code",
        "amount",
        "started_at",
        "description",
        "verified",
    ):
        if field not in supplied:
            continue
        value = getattr(payload, field)
        if field in {"name", "amount", "verified"} and value is None:
            raise ApiError(422, "INVALID_REQUEST", f"{field} cannot be null")
        setattr(performance, field, value)

    if (
        performance.started_at
        and performance.completed_at
        and performance.started_at > performance.completed_at
    ):
        raise ApiError(
            422,
            "INVALID_DATE_RANGE",
            "started_at은 completed_at보다 늦을 수 없습니다.",
        )
    if (
        performance.started_at
        and performance.completed_year
        and performance.started_at.year > performance.completed_year
    ):
        raise ApiError(
            422,
            "INVALID_DATE_RANGE",
            "started_at 연도는 completed_year보다 늦을 수 없습니다.",
        )

    if "fields" in supplied:
        if payload.fields is None:
            raise ApiError(422, "INVALID_REQUEST", "fields cannot be null")
        performance.experience_fields = [
            CompanyPerformanceField(field_name=field) for field in payload.fields
        ]

    db.commit()
    return _performance_response(_load_performance(db, company_id, performance_id))


@router.delete(
    "/{company_id}/performances/{performance_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_performance(
    company_id: UUID,
    performance_id: UUID,
    db: Session = Depends(get_db),
    user: AppUser | None = Depends(get_optional_current_user),
) -> Response:
    authorize_company_access(user, company_id, write=True)
    performance = _load_performance(db, company_id, performance_id)
    db.delete(performance)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{company_id}/certifications",
    response_model=CertificationRead,
    status_code=status.HTTP_201_CREATED,
)
def create_certification(
    company_id: UUID,
    payload: CertificationCreate,
    db: Session = Depends(get_db),
    user: AppUser | None = Depends(get_optional_current_user),
) -> CertificationRead:
    authorize_company_access(user, company_id, write=True)
    _load_company(db, company_id)
    certification = CompanyCertification(company_id=company_id, **payload.model_dump())
    db.add(certification)
    db.commit()
    db.refresh(certification)
    return _certification_response(certification)


@router.patch(
    "/{company_id}/certifications/{certification_id}",
    response_model=CertificationRead,
)
def update_certification(
    company_id: UUID,
    certification_id: UUID,
    payload: CertificationUpdate,
    db: Session = Depends(get_db),
    user: AppUser | None = Depends(get_optional_current_user),
) -> CertificationRead:
    authorize_company_access(user, company_id, write=True)
    certification = _load_certification(db, company_id, certification_id)
    for field in payload.model_fields_set:
        value = getattr(payload, field)
        if field in {"name", "verified"} and value is None:
            raise ApiError(422, "INVALID_REQUEST", f"{field} cannot be null")
        setattr(certification, field, value)

    if (
        certification.issued_at
        and certification.expires_at
        and certification.issued_at > certification.expires_at
    ):
        raise ApiError(
            422,
            "INVALID_DATE_RANGE",
            "issued_at은 expires_at보다 늦을 수 없습니다.",
        )

    db.commit()
    db.refresh(certification)
    return _certification_response(certification)


@router.delete(
    "/{company_id}/certifications/{certification_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_certification(
    company_id: UUID,
    certification_id: UUID,
    db: Session = Depends(get_db),
    user: AppUser | None = Depends(get_optional_current_user),
) -> Response:
    authorize_company_access(user, company_id, write=True)
    certification = _load_certification(db, company_id, certification_id)
    db.delete(certification)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
