"""Password hashing, revocable sessions, and FastAPI authentication dependencies."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Cookie, Depends, Header
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from .auth_models import AppUser, AuthSession
from .config import get_settings
from .database import get_db
from .errors import ApiError


_PASSWORD_ITERATIONS = 210_000
_LOCK_AFTER_FAILURES = 5
_LOCK_MINUTES = 15


def _now() -> datetime:
    return datetime.now(timezone.utc)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PASSWORD_ITERATIONS
    )
    return f"pbkdf2_sha256${_PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_hex, expected_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iterations),
        )
        return hmac.compare_digest(actual.hex(), expected_hex)
    except (ValueError, TypeError):
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def ensure_bootstrap_admin(db: Session) -> None:
    settings = get_settings()
    username = settings.auth_bootstrap_admin_username.strip().casefold()
    password = settings.auth_bootstrap_admin_password
    if not username or not password:
        return
    if settings.app_environment == "production" and (
        password == "admin" or len(password) < 12
    ):
        raise ApiError(
            503,
            "INSECURE_BOOTSTRAP_PASSWORD",
            "운영환경의 초기 관리자 비밀번호는 12자 이상이어야 하며 기본값을 사용할 수 없습니다.",
        )
    if db.scalar(select(AppUser.id).where(AppUser.username == username)) is not None:
        return
    db.add(
        AppUser(
            username=username,
            password_hash=hash_password(password),
            role="SYSTEM_ADMIN",
            active=True,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()


def login(db: Session, *, username: str, password: str) -> tuple[str, AuthSession]:
    ensure_bootstrap_admin(db)
    now = _now()
    user = db.scalar(select(AppUser).where(AppUser.username == username))
    if user is None or not user.active:
        raise ApiError(401, "INVALID_CREDENTIALS", "아이디 또는 비밀번호가 올바르지 않습니다.")
    if user.locked_until is not None and user.locked_until > now:
        raise ApiError(
            429,
            "ACCOUNT_TEMPORARILY_LOCKED",
            "로그인 실패 횟수를 초과했습니다. 잠시 후 다시 시도해 주세요.",
        )
    if not verify_password(password, user.password_hash):
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= _LOCK_AFTER_FAILURES:
            user.locked_until = now + timedelta(minutes=_LOCK_MINUTES)
            user.failed_login_attempts = 0
        db.commit()
        raise ApiError(401, "INVALID_CREDENTIALS", "아이디 또는 비밀번호가 올바르지 않습니다.")

    user.failed_login_attempts = 0
    user.locked_until = None
    raw_token = secrets.token_urlsafe(32)
    session = AuthSession(
        user_id=user.id,
        token_hash=_token_hash(raw_token),
        expires_at=now + timedelta(hours=get_settings().auth_session_ttl_hours),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    session.user = user
    return raw_token, session


def _extract_token(authorization: str | None, session_cookie: str | None) -> str:
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.casefold() == "bearer" and token:
            return token
    if session_cookie:
        return session_cookie
    raise ApiError(401, "AUTHENTICATION_REQUIRED", "로그인이 필요합니다.")


def get_current_session(
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias="bidcheck_session"),
    db: Session = Depends(get_db),
) -> AuthSession:
    raw_token = _extract_token(authorization, session_cookie)
    return _load_session(db, raw_token)


def _load_session(db: Session, raw_token: str) -> AuthSession:
    session = db.scalar(
        select(AuthSession)
        .where(AuthSession.token_hash == _token_hash(raw_token))
        .options(joinedload(AuthSession.user))
    )
    if (
        session is None
        or session.revoked_at is not None
        or session.expires_at <= _now()
        or not session.user.active
    ):
        raise ApiError(401, "INVALID_SESSION", "로그인 세션이 만료되었거나 유효하지 않습니다.")
    return session


def require_authentication_if_enabled(
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias="bidcheck_session"),
    db: Session = Depends(get_db),
) -> AppUser | None:
    """Protect business APIs in deployments that enable authentication."""

    if not get_settings().auth_required:
        return None
    raw_token = _extract_token(authorization, session_cookie)
    return _load_session(db, raw_token).user


def get_current_user(session: AuthSession = Depends(get_current_session)) -> AppUser:
    return session.user


def get_optional_current_user(
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias="bidcheck_session"),
    db: Session = Depends(get_db),
) -> AppUser | None:
    """Return the signed-in user while preserving unauthenticated local development."""

    if authorization is None and session_cookie is None:
        if get_settings().auth_required:
            raise ApiError(401, "AUTHENTICATION_REQUIRED", "로그인이 필요합니다.")
        return None
    return _load_session(db, _extract_token(authorization, session_cookie)).user


def authorize_company_access(
    user: AppUser | None,
    company_id,
    *,
    write: bool = False,
) -> None:
    """Enforce company tenancy whenever authentication is active for the request."""

    if user is None or user.role == "SYSTEM_ADMIN":
        return
    if user.company_id != company_id:
        raise ApiError(403, "COMPANY_ACCESS_DENIED", "다른 회사 정보에는 접근할 수 없습니다.")
    if write and user.role != "ADMIN":
        raise ApiError(403, "COMPANY_WRITE_FORBIDDEN", "회사 프로필 수정 권한이 없습니다.")


def authorize_case_access(db: Session, user: AppUser | None, case_id):
    from .models import PreflightCase

    case = db.get(PreflightCase, case_id)
    if case is None:
        raise ApiError(404, "PREFLIGHT_CASE_NOT_FOUND", "검토 건을 찾을 수 없습니다.")
    if user is not None and user.role != "SYSTEM_ADMIN":
        if user.company_id is None or case.company_id != user.company_id:
            raise ApiError(403, "COMPANY_ACCESS_DENIED", "다른 회사의 검토 건에는 접근할 수 없습니다.")
    return case


def revoke_session(db: Session, session: AuthSession) -> None:
    session.revoked_at = _now()
    db.commit()
