import hashlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from apps.api.app.auth_models import AppUser, AuthSession
from apps.api.app import auth as auth_service
from apps.api.app.auth import hash_password
from apps.api.app.config import get_settings
from apps.api.app.database import SessionLocal
from apps.api.app.main import app
from apps.api.app.models import Company


pytestmark = pytest.mark.usefixtures("seed_required_master_codes")


def test_current_user_allows_anonymous_when_authentication_is_optional() -> None:
    response = TestClient(app).get("/api/v1/auth/me")

    assert response.status_code == 200
    assert response.json() is None


def test_development_admin_login_session_and_logout() -> None:
    client = TestClient(app)
    login_response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "admin"},
    )

    assert login_response.status_code == 200, login_response.text
    body = login_response.json()
    token = body["access_token"]
    assert body["token_type"] == "bearer"
    assert body["user"]["username"] == "admin"
    assert body["user"]["role"] == "SYSTEM_ADMIN"
    assert body["user"]["company_id"] is None
    assert "HttpOnly" in login_response.headers["set-cookie"]

    db = SessionLocal()
    try:
        session = db.scalar(
            select(AuthSession).where(
                AuthSession.token_hash
                == hashlib.sha256(token.encode("utf-8")).hexdigest()
            )
        )
        assert session is not None
        assert session.token_hash != token
    finally:
        db.close()

    me_response = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert me_response.status_code == 200
    assert me_response.json()["username"] == "admin"

    logout_response = client.post(
        "/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"}
    )
    assert logout_response.status_code == 204
    assert (
        client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
        ).status_code
        == 401
    )

    db = SessionLocal()
    try:
        user = db.scalar(select(AppUser).where(AppUser.username == "admin"))
        if user is not None:
            db.delete(user)
            db.commit()
    finally:
        db.close()


def test_invalid_login_does_not_reveal_which_credential_failed() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "not-the-password"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_business_apis_require_session_when_enabled(monkeypatch) -> None:
    protected_settings = get_settings().model_copy(update={"auth_required": True})
    monkeypatch.setattr(auth_service, "get_settings", lambda: protected_settings)
    protected_client = TestClient(app)

    unauthorized = protected_client.get("/api/v1/companies")
    assert unauthorized.status_code == 401
    assert unauthorized.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"
    me_response = protected_client.get("/api/v1/auth/me")
    assert me_response.status_code == 401
    assert me_response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"
    assert protected_client.get("/health").status_code == 200

    login_response = protected_client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "admin"},
    )
    assert login_response.status_code == 200
    token = login_response.json()["access_token"]
    authorized = protected_client.get(
        "/api/v1/companies",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert authorized.status_code == 200

    db = SessionLocal()
    try:
        user = db.scalar(select(AppUser).where(AppUser.username == "admin"))
        if user is not None:
            db.delete(user)
            db.commit()
    finally:
        db.close()


def test_company_user_is_scoped_to_own_company() -> None:
    db = SessionLocal()
    try:
        own_company = Company(name="소속 회사", company_size="SMALL")
        other_company = Company(name="다른 회사", company_size="SMALL")
        db.add_all([own_company, other_company])
        db.flush()
        user = AppUser(
            username="company-user",
            password_hash=hash_password("company-pass"),
            company_id=own_company.id,
            role="USER",
            active=True,
        )
        db.add(user)
        db.commit()
        own_company_id = own_company.id
        other_company_id = other_company.id
    finally:
        db.close()

    client = TestClient(app)
    login_response = client.post(
        "/api/v1/auth/login",
        json={"username": "company-user", "password": "company-pass"},
    )
    assert login_response.status_code == 200
    assert login_response.json()["user"]["company_id"] == str(own_company_id)
    assert login_response.json()["user"]["company_name"] == "소속 회사"

    companies_response = client.get("/api/v1/companies")
    assert companies_response.status_code == 200
    assert [item["id"] for item in companies_response.json()] == [str(own_company_id)]
    assert client.get(f"/api/v1/companies/{own_company_id}").status_code == 200

    denied = client.get(f"/api/v1/companies/{other_company_id}")
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "COMPANY_ACCESS_DENIED"

    read_only = client.patch(
        f"/api/v1/companies/{own_company_id}",
        json={"name": "수정 시도"},
    )
    assert read_only.status_code == 403
    assert read_only.json()["error"]["code"] == "COMPANY_WRITE_FORBIDDEN"

    db = SessionLocal()
    try:
        user = db.scalar(select(AppUser).where(AppUser.username == "company-user"))
        if user is not None:
            db.delete(user)
        for company_id in (own_company_id, other_company_id):
            company = db.get(Company, company_id)
            if company is not None:
                db.delete(company)
        db.commit()
    finally:
        db.close()
