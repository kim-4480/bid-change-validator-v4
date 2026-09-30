from datetime import datetime, timezone

import pytest

from apps.api.app.database import SessionLocal
from apps.api.app.models import IndustryCode, InstitutionCode, ProductCode


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
