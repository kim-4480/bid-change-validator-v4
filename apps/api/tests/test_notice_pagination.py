from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest

from apps.api.app.routers.notices import search_notices
from apps.api.app.schemas import BusinessType


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self, total: int, rows):
        self.total = total
        self.rows = rows
        self.count_statement = None
        self.list_statement = None

    def scalar(self, statement):
        self.count_statement = statement
        return self.total

    def execute(self, statement):
        self.list_statement = statement
        return FakeResult(self.rows)


def _notice(index: int):
    notice = SimpleNamespace(
        id=UUID(int=index + 1),
        bid_notice_no=f"TEST-{index:04d}",
        title=f"alpha {index}",
        business_type="GOODS",
        notice_kind=None,
        announcing_institution_code=None,
        announcing_institution_name="Test",
        demanding_institution_code=None,
        demanding_institution_name=None,
        first_seen_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        last_seen_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )
    version = SimpleNamespace(version_number=1)
    return (notice, version)


@pytest.mark.parametrize(
    "total,offset,expected",
    [(0, 0, 0), (10, 0, 10), (100, 90, 10), (101, 100, 1), (1234, 1230, 4)],
)
def test_notice_pagination_counts_and_limit_offset(total, offset, expected):
    db = FakeSession(total, [_notice(index) for index in range(offset, offset + expected)])
    result = search_notices(q="alpha", business_type=BusinessType.GOODS, limit=10, offset=offset, db=db)
    assert result.total == total
    assert result.offset == offset
    assert result.limit == 10
    assert len(result.items) == expected
    assert len({row.id for row in result.items}) == expected

    list_sql = str(db.list_statement.compile(compile_kwargs={"literal_binds": True})).lower()
    count_sql = str(db.count_statement.compile(compile_kwargs={"literal_binds": True})).lower()
    assert "order by bid_notices.last_seen_at desc, bid_notices.id desc" in list_sql
    assert f"offset {offset}" in list_sql
    assert "limit 10" in list_sql
    assert "bid_notices.business_type = 'goods'" in list_sql
    assert "bid_notices.business_type = 'goods'" in count_sql
    assert "join bid_notice_versions" in count_sql
    assert "join bid_notice_versions" in list_sql


def test_other_business_type_is_valid_and_company_tenant_is_checked():
    from types import SimpleNamespace
    from uuid import uuid4
    from apps.api.app.errors import ApiError
    assert BusinessType("OTHER") == BusinessType.OTHER
    company_a, company_b = uuid4(), uuid4()
    with pytest.raises(ApiError) as exc:
        search_notices(
            q=None, business_type=BusinessType.OTHER, limit=10, offset=0,
            company_id=company_b, qualification_status="eligible",
            db=FakeSession(0, []),
            user=SimpleNamespace(role="MEMBER", company_id=company_a),
        )
    assert exc.value.status_code == 403

def test_notice_api_rejects_invalid_page_and_filter_parameters():
    from fastapi.testclient import TestClient
    from apps.api.app.main import app
    http = TestClient(app)
    for parameters in (
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
        {"business_type": "UNKNOWN"},
        {"qualification_status": "eligible"},
        {"company_id": "not-a-uuid"},
    ):
        response = http.get("/api/v1/notices", params=parameters)
        assert response.status_code == 422, (parameters, response.text)
