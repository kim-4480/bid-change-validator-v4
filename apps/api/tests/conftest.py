from datetime import datetime, timezone

import pytest

from apps.api.app.database import SessionLocal
from apps.api.app.models import IndustryCode, InstitutionCode, ProductCode


@pytest.fixture(autouse=True)
def no_participation_limits_lookup(monkeypatch):
    """분석 경로의 테스트가 실제 나라장터(면허제한·참가가능지역 조회)를 부르지 않게 한다.

    개발자 PC 의 .env 에는 나라장터 키가 있어, 그대로 두면 분석 테스트마다 네트워크 호출이 나간다.
    조회 자체의 테스트는 조회 함수를 직접 넘겨서 한다(test_participation_limits.py).
    """
    monkeypatch.setattr("apps.api.app.qualification.routers.analysis.participation_limits_fetcher", lambda settings: None)
    monkeypatch.setattr("apps.api.app.workers.notice_processing.participation_limits_fetcher", lambda settings: None)


@pytest.fixture(scope="session")
def seed_required_master_codes():
    """Make backend tests reproducible on a freshly migrated database.

    Existing API tests historically relied on master-code rows already present in
    the developer's local database. CI starts from an empty PostgreSQL database,
    so seed only the rows the tests explicitly require and remove only rows that
    this fixture inserted.
    """

    db = SessionLocal()
    now = datetime.now(timezone.utc)
    inserted: list[tuple[type, str]] = []

    required = [
        (IndustryCode, "0001", "토목공사업", True),
        (IndustryCode, "0002", "건축공사업", True),
        (IndustryCode, "0003", "전기공사업", True),
        (IndustryCode, "0004", "정보통신공사업", True),
        (ProductCode, "1010150201", "Golden 테스트 품목", True),
        (InstitutionCode, "1011052", "대통령실 경호처", False),
    ]

    try:
        for model, code, name, active in required:
            if db.get(model, code) is not None:
                continue
            db.add(
                model(
                    code=code,
                    name=name,
                    active=active,
                    changed_at=None,
                    source_window="pytest",
                    collected_at=now,
                    raw_json={"source": "pytest"},
                )
            )
            inserted.append((model, code))
        db.commit()
        yield
    finally:
        db.rollback()
        for model, code in reversed(inserted):
            row = db.get(model, code)
            if row is not None:
                db.delete(row)
        db.commit()
        db.close()
