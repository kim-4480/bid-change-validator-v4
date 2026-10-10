from apps.api.app.main import app
from fastapi.testclient import TestClient


def test_ml_recommendation_route_is_mounted_once() -> None:
    path = app.openapi()["paths"]["/api/v1/recommendations/ml"]
    assert list(path) == ["post"]
    assert path["post"]["operationId"]


def test_ml_recommendation_request_uses_mounted_router() -> None:
    response = TestClient(app).post(
        "/api/v1/recommendations/ml",
        json={"query": "software maintenance", "limit": 5},
    )
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["items"], list)
    assert isinstance(body["needs_review_items"], list)
    assert body["scoring_source"] in {
        "local_lightgbm", "local_hf", "remote_inference", "lexical_fallback"
    }
