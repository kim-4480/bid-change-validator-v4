from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from apps.api.app.main import app


pytestmark = pytest.mark.usefixtures("seed_required_master_codes")
client = TestClient(app)


def _business_number() -> str:
    return f"{uuid4().int % 10_000_000_000:010d}"


def test_company_profile_crud() -> None:
    create_response = client.post(
        "/api/v1/companies",
        json={
            "name": "테스트 주식회사",
            "business_registration_number": _business_number(),
            "region_code": "11",
            "region_name": "서울특별시",
            "company_size": "SMALL",
            "industry_codes": ["0001"],
            "staff": {
                "total_count": 5,
                "verified": True,
                "roles": [
                    {"role_name": "PM", "headcount": 2, "verified": True}
                ],
            },
        },
    )
    assert create_response.status_code == 201, create_response.text
    company = create_response.json()
    company_id = company["id"]

    try:
        assert company["name"] == "테스트 주식회사"
        assert company["business_registration_number"].isdigit()
        assert company["industries"][0]["code"] == "0001"
        assert company["staff"]["total_count"] == 5

        get_response = client.get(f"/api/v1/companies/{company_id}")
        assert get_response.status_code == 200

        update_response = client.patch(
            f"/api/v1/companies/{company_id}",
            json={
                "name": "수정된 주식회사",
                "industry_codes": ["0001"],
                "staff": {
                    "total_count": 8,
                    "roles": [
                        {"role_name": "PM", "headcount": 3, "verified": True},
                        {
                            "role_name": "개발",
                            "headcount": 5,
                            "career_years": 4.5,
                            "verified": False,
                        },
                    ],
                },
            },
        )
        assert update_response.status_code == 200, update_response.text
        assert update_response.json()["name"] == "수정된 주식회사"
        assert update_response.json()["staff"]["total_count"] == 8
        assert len(update_response.json()["staff"]["roles"]) == 2
        assert update_response.json()["staff"]["roles"][1]["career_years"] == 4.5

        performance_response = client.post(
            f"/api/v1/companies/{company_id}/performances",
            json={
                "name": "창업지원 플랫폼 구축",
                "client_name": "테스트 발주처",
                "amount": 500000000,
                "started_at": "2025-01-01",
                "completed_year": 2025,
                "fields": ["창업지원", "플랫폼"],
                "verified": True,
            },
        )
        assert performance_response.status_code == 201, performance_response.text
        performance = performance_response.json()
        assert performance["amount"] == 500000000
        assert performance["completed_at"] is None
        assert performance["completed_year"] == 2025
        assert performance["fields"] == ["창업지원", "플랫폼"]

        performance_update_response = client.patch(
            f"/api/v1/companies/{company_id}/performances/{performance['id']}",
            json={"amount": 600000000},
        )
        assert performance_update_response.status_code == 200
        assert performance_update_response.json()["amount"] == 600000000

        certification_response = client.post(
            f"/api/v1/companies/{company_id}/certifications",
            json={
                "name": "벤처기업확인서",
                "certification_code": "venture",
                "certificate_number": "TEST-001",
                "issued_at": "2026-01-01",
                "expires_at": "2028-01-01",
                "verified": True,
            },
        )
        assert certification_response.status_code == 201, certification_response.text
        certification = certification_response.json()
        assert certification["certification_code"] == "VENTURE"

        full_profile_response = client.get(f"/api/v1/companies/{company_id}")
        assert full_profile_response.status_code == 200
        full_profile = full_profile_response.json()
        assert len(full_profile["performances"]) == 1
        assert len(full_profile["certifications"]) == 1

        assert (
            client.delete(
                f"/api/v1/companies/{company_id}/performances/{performance['id']}"
            ).status_code
            == 204
        )
        assert (
            client.delete(
                f"/api/v1/companies/{company_id}/certifications/{certification['id']}"
            ).status_code
            == 204
        )
    finally:
        client.delete(f"/api/v1/companies/{company_id}")

    missing_response = client.get(f"/api/v1/companies/{company_id}")
    assert missing_response.status_code == 404
    assert missing_response.json()["error"]["code"] == "COMPANY_NOT_FOUND"


def test_unknown_industry_code_is_rejected() -> None:
    response = client.post(
        "/api/v1/companies",
        json={
            "name": "잘못된 업종 테스트",
            "region_code": "11",
            "company_size": "SMALL",
            "industry_codes": ["NOT-A-REAL-CODE"],
            "staff": {"total_count": 1},
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_INDUSTRY_CODE"


def test_performance_requires_exact_date_or_year_but_not_both() -> None:
    payload = {
        "name": "잘못된 완료일",
        "amount": 1,
        "completed_at": "2025-06-30",
        "completed_year": 2025,
    }
    response = client.post(f"/api/v1/companies/{uuid4()}/performances", json=payload)

    assert response.status_code == 422


def test_duplicate_business_number_is_rejected() -> None:
    business_number = _business_number()
    payload = {
        "name": "중복 사업자번호 테스트",
        "business_registration_number": business_number,
        "region_code": "11",
        "company_size": "SMALL",
        "industry_codes": ["0001"],
        "staff": {"total_count": 1},
    }
    first_response = client.post("/api/v1/companies", json=payload)
    assert first_response.status_code == 201, first_response.text
    company_id = first_response.json()["id"]

    try:
        duplicate_response = client.post("/api/v1/companies", json=payload)
        assert duplicate_response.status_code == 409
        assert duplicate_response.json()["error"]["code"] == "DATA_CONFLICT"
    finally:
        client.delete(f"/api/v1/companies/{company_id}")


def test_health_check_uses_database() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
