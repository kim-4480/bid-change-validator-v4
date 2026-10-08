"""Real PostgreSQL pagination regression on the isolated CI service only.

Never executes against developer/local restored DBs. The fixture inserts within
one uncommitted transaction and rolls back every row even if assertions fail.
"""
import os
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from bidengine.judgment.rules import RULE_VERSION
from apps.api.app.analysis_models import QualificationAnalysisRun
from apps.api.app.database import SessionLocal
from apps.api.app.judgment_models import QualificationJudgmentRun
from apps.api.app.models import BidNotice, BidNoticeVersion, Company, PreflightCase
from apps.api.app.routers.notices import search_notices
from apps.api.app.schemas import BusinessType

pytestmark = pytest.mark.skipif(
    os.getenv("GITHUB_ACTIONS") != "true",
    reason="Must use the disposable PostgreSQL service created by GitHub Actions; never seed a restored DB.",
)


@pytest.fixture
def populated_db():
    db = SessionLocal()
    token = "PR13" + uuid4().hex[:16]
    now = datetime(2026, 10, 8, tzinfo=timezone.utc)
    try:
        # A CI job starts its own PostgreSQL service. This transaction never commits.
        a = Company(name=token + "A", company_size="SMALL")
        b = Company(name=token + "B", company_size="SMALL")
        db.add_all([a, b])
        db.flush()

        notices = [
            BidNotice(
                bid_notice_no=f"{token}-{i:04d}", title=f"{token} notice {i}",
                business_type="GOODS" if i < 200 else ("OTHER" if i == 300 else "SERVICE"),
                first_seen_at=now, last_seen_at=now,
            ) for i in range(1011)
        ]
        db.add_all(notices)
        db.flush()
        # One notice intentionally lacks a current version.
        versions = [
            BidNoticeVersion(
                notice_id=notice.id, version_number=1, bid_notice_order="00",
                is_current=True, source_endpoint="pr13-fixture",
                payload_hash=f"{i:064x}", raw_json={}, collected_at=now,
            ) for i, notice in enumerate(notices[:-1])
        ]
        db.add_all(versions)
        db.flush()

        # One notice has multiple versions, but only one is current.
        extra = BidNoticeVersion(
            notice_id=notices[4].id, version_number=2, bid_notice_order="01",
            is_current=False, source_endpoint="pr13-fixture",
            payload_hash="f" * 64, raw_json={}, collected_at=now,
        )
        # An old case must not count as the current-version judgment.
        old_version = BidNoticeVersion(
            notice_id=notices[201].id, version_number=2, bid_notice_order="01",
            is_current=False, source_endpoint="pr13-fixture",
            payload_hash="e" * 64, raw_json={}, collected_at=now,
        )
        db.add_all([extra, old_version])
        db.flush()

        cases = [
            PreflightCase(
                company_id=a.id, notice_id=notices[i].id,
                current_version_id=versions[i].id, title=f"Case {i}",
                status="DRAFT", created_at=now + timedelta(seconds=i),
            ) for i in range(141)
        ]
        cases.append(
            PreflightCase(
                company_id=a.id, notice_id=notices[201].id,
                current_version_id=old_version.id, title="Old version case", status="DRAFT",
            )
        )
        # A different company's valid judgment must not leak into A.
        case_b = PreflightCase(
            company_id=b.id, notice_id=notices[400].id,
            current_version_id=versions[400].id, title="Other company case", status="DRAFT",
        )
        cases.append(case_b)
        db.add_all(cases)
        db.flush()

        # A second case on the same notice exercises duplicate/case selection.
        duplicate = PreflightCase(
            company_id=a.id, notice_id=notices[101].id,
            current_version_id=versions[101].id, title="newer case", status="DRAFT",
            created_at=now + timedelta(days=1),
        )
        db.add(duplicate)
        db.flush()

        analyses = {}
        for index in (101, 202, 250, 400):
            analysis = QualificationAnalysisRun(
                notice_version_id=versions[index].id,
                contract_version="v1", analysis_kind="QUALIFICATION",
                status="SUCCEEDED", created_at=now,
            )
            db.add(analysis)
            analyses[index] = analysis
        db.flush()
        # Cases for 202/250 have valid statuses too.
        more = []
        for index in (202, 250):
            more.append(PreflightCase(
                company_id=a.id, notice_id=notices[index].id,
                current_version_id=versions[index].id, title=f"Case {index}", status="DRAFT",
            ))
        db.add_all(more)
        db.flush()
        for index, selected_case, company_id, status in (
            (101, cases[101], a.id, "eligible"),
            (202, more[0], a.id, "insufficient_data"),
            (250, more[1], a.id, "ineligible"),
            (400, case_b, b.id, "eligible"),
        ):
            db.add(QualificationJudgmentRun(
                preflight_case_id=selected_case.id,
                analysis_run_id=analyses[index].id,
                company_id=company_id,
                notice_version_id=versions[index].id,
                overall_status=status, rule_version=RULE_VERSION,
                reference_date=date(2026, 10, 8), profile_snapshot={},
                analysis_status="SUCCEEDED", created_at=now,
            ))
        db.flush()
        yield db, token, a, b, notices, versions, analyses
    finally:
        db.rollback()
        db.close()


def _page(db, *, q=None, business_type=None, status=None, company=None, offset=0, limit=10):
    return search_notices(
        q=q, business_type=business_type, company_id=company,
        qualification_status=status, limit=limit, offset=offset, db=db, user=None,
    )


def test_postgres_1010_pages_boundaries_count_and_stable_order(populated_db):
    db, token, a, _, notices, _, _ = populated_db
    actual = []
    for offset in range(0, 1010, 10):
        page = _page(db, q=token, offset=offset)
        assert page.total == 1010
        assert len(page.items) == 10
        actual.extend(item.id for item in page.items)
    expected = sorted((notice.id for notice in notices[:1010]), reverse=True)
    assert actual == expected
    assert len(set(actual)) == 1010
    assert actual[100] == expected[100]  # previously inaccessible 101st notice
    assert _page(db, q=token, offset=1010).items == []
    for limit in (1, 10, 100):
        last_offset = ((1010 - 1) // limit) * limit
        assert len(_page(db, q=token, limit=limit, offset=last_offset).items) == (1010-last_offset)
    assert _page(db, q=token+"NO_MATCH", company=a.id).total == 0
    # EXPLAIN runs on the real disposable PostgreSQL service, not compiled SQL text.
    from sqlalchemy import event
    connection = db.connection()
    statements = []
    def capture(conn, cursor, statement, params, context, executemany):
        if statement.lstrip().startswith("SELECT") and "bid_notice_versions" in statement:
            statements.append((statement, params))
    event.listen(connection, "before_cursor_execute", capture)
    _page(db, q=token, offset=100)
    event.remove(connection, "before_cursor_execute", capture)
    assert statements
    plan = [
        row[0] for row in connection.exec_driver_sql(
            "EXPLAIN (ANALYZE, BUFFERS) " + statements[-1][0], statements[-1][1]
        )
    ]
    assert any("Execution Time:" in row for row in plan)
    assert any("Buffers:" in row for row in plan)


def test_postgres_company_status_search_filters_and_case_over_100(populated_db):
    db, token, a, b, notices, versions, analyses = populated_db
    assert _page(db, q=token, company=a.id, status="eligible").total == 1
    needs_review_total = _page(db, q=token, company=a.id, status="needs_review").total
    assert needs_review_total > 100
    needs_review_ids = []
    for offset in range(0, needs_review_total, 10):
        result = _page(db, q=token, company=a.id, status="needs_review", offset=offset)
        needs_review_ids.extend(item.id for item in result.items)
    assert len(needs_review_ids) == needs_review_total
    assert len(set(needs_review_ids)) == needs_review_total
    eligible = _page(db, q=token, company=a.id, status="eligible").items[0]
    assert eligible.id == notices[101].id
    assert eligible.current_case_id is not None
    assert eligible.current_case_id == db.scalar(select(PreflightCase.id).where(PreflightCase.notice_id == notices[101].id).order_by(PreflightCase.created_at.asc()).limit(1))
    old_140 = _page(db, q=f'{token}-0140', company=a.id).items[0]
    assert old_140.current_case_id is not None
    assert old_140.qualification_status == 'needs_review'
    for status, index in (("insufficient_data", 202), ("ineligible", 250)):
        row = _page(db, q=token, company=a.id, status=status).items[0]
        assert row.id == notices[index].id
    assert _page(db, q=token, company=b.id, status="eligible").items[0].id == notices[400].id
    assert _page(db, q=token, company=a.id, status="eligible", business_type=BusinessType.SERVICE).total == 0
    assert _page(db, q=token, company=a.id, status="eligible", business_type=BusinessType.GOODS).total == 1
    assert _page(db, q=token, company=a.id, business_type=BusinessType.OTHER).total == 1
    old = _page(db, q=f"{token}-0201", company=a.id).items[0]
    assert old.qualification_status == "needs_review" and old.current_case_id is None
    assert _page(db, q=f"{token}-0400", company=a.id).items[0].qualification_status == "unreviewed"
    # A later analysis invalidates the earlier eligible judgment without mislabeling it unreviewed.
    db.add(QualificationAnalysisRun(
        notice_version_id=versions[101].id,
        contract_version="v2", analysis_kind="QUALIFICATION",
        status="SUCCEEDED", created_at=datetime(2026, 10, 9, tzinfo=timezone.utc),
    ))
    db.flush()
    assert _page(db, q=f"{token}-0101", company=a.id).items[0].qualification_status == "needs_review"
    assert _page(db, q=token, company=a.id, status="eligible").total == 0
