"""HTTP endpoints for login, current-user lookup, and logout."""

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import (
    get_current_session,
    get_current_user,
    get_optional_current_user,
    hash_password,
    login,
    revoke_session,
)
from ..auth_models import AppUser, AuthSession
from ..auth_schemas import AuthUserCreate, AuthUserRead, LoginRequest, LoginResponse
from ..config import get_settings
from ..database import get_db
from ..errors import ApiError
from ..models import Company


router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _user_response(user: AppUser) -> AuthUserRead:
    return AuthUserRead(
        id=user.id,
        username=user.username,
        role=user.role,
        company_id=user.company_id,
        company_name=user.company.name if user.company is not None else None,
    )


@router.post("/login", response_model=LoginResponse)
def login_user(
    payload: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> LoginResponse:
    raw_token, session = login(
        db, username=payload.username, password=payload.password
    )
    settings = get_settings()
    response.set_cookie(
        key="bidcheck_session",
        value=raw_token,
        httponly=True,
        secure=settings.auth_cookie_secure or settings.app_environment == "production",
        samesite="lax",
        max_age=settings.auth_session_ttl_hours * 3600,
        path="/",
    )
    return LoginResponse(
        access_token=raw_token,
        expires_at=session.expires_at,
        user=_user_response(session.user),
    )


@router.get("/me", response_model=AuthUserRead | None)
def current_user(
    user: AppUser | None = Depends(get_optional_current_user),
) -> AuthUserRead | None:
    # Optional-auth 개발 환경에서는 비로그인도 정상 상태다. 200/null로
    # 응답해 프론트가 인증 만료(401), API 장애(5xx)와 구분할 수 있게 한다.
    return _user_response(user) if user is not None else None


@router.get("/users", response_model=list[AuthUserRead])
def list_users(
    current: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[AuthUserRead]:
    if current.role not in {"SYSTEM_ADMIN", "ADMIN"}:
        raise ApiError(403, "USER_MANAGEMENT_FORBIDDEN", "사용자 관리 권한이 없습니다.")
    query = select(AppUser).order_by(AppUser.created_at)
    if current.role != "SYSTEM_ADMIN":
        query = query.where(AppUser.company_id == current.company_id)
    return [_user_response(user) for user in db.scalars(query)]


@router.post("/users", response_model=AuthUserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: AuthUserCreate,
    current: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AuthUserRead:
    if current.role not in {"SYSTEM_ADMIN", "ADMIN"}:
        raise ApiError(403, "USER_MANAGEMENT_FORBIDDEN", "사용자 관리 권한이 없습니다.")
    if current.role == "ADMIN":
        if current.company_id != payload.company_id:
            raise ApiError(403, "COMPANY_ACCESS_DENIED", "다른 회사 사용자를 만들 수 없습니다.")
        if payload.role == "ADMIN":
            raise ApiError(403, "ADMIN_CREATION_FORBIDDEN", "회사 관리자는 일반 사용자만 추가할 수 있습니다.")
    if db.get(Company, payload.company_id) is None:
        raise ApiError(404, "COMPANY_NOT_FOUND", "회사를 찾을 수 없습니다.")
    user = AppUser(
        username=payload.username,
        password_hash=hash_password(payload.password),
        company_id=payload.company_id,
        role=payload.role,
        active=True,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise ApiError(409, "USERNAME_ALREADY_EXISTS", "이미 사용 중인 아이디입니다.") from error
    db.refresh(user)
    return _user_response(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout_user(
    response: Response,
    session: AuthSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> Response:
    revoke_session(db, session)
    response.delete_cookie("bidcheck_session", path="/")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
