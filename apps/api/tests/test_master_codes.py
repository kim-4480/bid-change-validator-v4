import pytest
from fastapi.testclient import TestClient

from apps.api.app.main import app


pytestmark = pytest.mark.usefixtures("seed_required_master_codes")
client = TestClient(app)


def test_search_industry_codes_by_name() -> None:
    response = client.get(
        "/api/v1/master-codes/industries",
        params={"q": "토목공사업", "limit": 5},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["type"] == "industries"
    assert body["total"] >= 1
    assert body["items"][0] == {
        "code": "0001",
        "name": "토목공사업",
        "active": True,
    }


def test_search_product_codes_by_exact_code() -> None:
    response = client.get(
        "/api/v1/master-codes/products",
        params={"q": "1010150201"},
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["code"] == "1010150201"


def test_inactive_code_is_available_when_requested() -> None:
    hidden_response = client.get(
        "/api/v1/master-codes/institutions",
        params={"q": "1011052"},
    )
    assert hidden_response.status_code == 200
    assert hidden_response.json()["total"] == 0

    visible_response = client.get(
        "/api/v1/master-codes/institutions",
        params={"q": "1011052", "active_only": False},
    )
    assert visible_response.status_code == 200
    assert visible_response.json()["items"][0]["active"] is False


def test_get_master_code_and_not_found_error() -> None:
    response = client.get("/api/v1/master-codes/institutions/1011052")
    assert response.status_code == 200
    assert response.json()["name"] == "대통령실 경호처"

    missing_response = client.get("/api/v1/master-codes/products/NOT-FOUND")
    assert missing_response.status_code == 404
    assert missing_response.json()["error"]["code"] == "MASTER_CODE_NOT_FOUND"


def test_master_code_pagination_limit() -> None:
    response = client.get(
        "/api/v1/master-codes/industries",
        params={"limit": 3, "offset": 1},
    )
    assert response.status_code == 200
    assert len(response.json()["items"]) == 3
    assert response.json()["limit"] == 3
    assert response.json()["offset"] == 1
