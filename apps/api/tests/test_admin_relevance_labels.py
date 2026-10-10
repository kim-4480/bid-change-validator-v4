"""Real PostgreSQL review/approval boundary; every write rolls back at test end."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from apps.api.app.auth import get_current_user
from apps.api.app.auth_models import AppUser
from apps.api.app.database import engine, get_db
from apps.api.app.main import app
from apps.api.app.models import BidNotice, BidNoticeVersion, Company


@pytest.fixture
def review_state():
    connection = engine.connect()
    transaction = connection.begin()
    db = Session(bind=connection, join_transaction_mode="create_savepoint", autoflush=False, expire_on_commit=False)
    now = datetime.now(timezone.utc)
    company = Company(name="Independent review company", company_size="SMALL")
    other = Company(name="Other company", company_size="SMALL")
    notice = BidNotice(bid_notice_no=f"REVIEW-{uuid4().hex}", title="Relevant service tender",
                       business_type="SERVICE", first_seen_at=now, last_seen_at=now)
    db.add_all([company, other, notice])
    db.flush()
    version = BidNoticeVersion(notice_id=notice.id, version_number=1, bid_notice_order="000",
                               is_current=True, source_endpoint="test", payload_hash="a" * 64,
                               raw_json={}, collected_at=now)
    reviewer = AppUser(username=f"reviewer-{uuid4().hex}", password_hash="unused", role="ADMIN",
                       company_id=company.id, active=True)
    outsider = AppUser(username=f"outsider-{uuid4().hex}", password_hash="unused", role="ADMIN",
                       company_id=other.id, active=True)
    approver = AppUser(username=f"approver-{uuid4().hex}", password_hash="unused", role="SYSTEM_ADMIN", active=True)
    ordinary = AppUser(username=f"ordinary-{uuid4().hex}", password_hash="unused", role="USER",
                       company_id=company.id, active=True)
    db.add_all([version, reviewer, outsider, approver, ordinary])
    db.flush()
    app.dependency_overrides[get_db] = lambda: db
    actor = {"user": reviewer}
    app.dependency_overrides[get_current_user] = lambda: actor["user"]
    try:
        yield TestClient(app), db, actor, company, version, reviewer, outsider, approver, ordinary
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_db, None)
        db.close()
        transaction.rollback()
        connection.close()


def _payload(company, version, *, origin="REAL"):
    return {
        "company_id": str(company.id), "notice_version_id": str(version.id),
        "grade": 3, "rationale": "Company capability explicitly matches this service scope.",
        "subject_origin": origin,
    }


def test_independent_approval_audit_export_and_unchanged_inputs(review_state):
    client, db, actor, company, version, reviewer, outsider, approver, ordinary = review_state
    path = "/api/v1/admin/relevance-labels"
    payload = _payload(company, version)
    actor["user"] = ordinary
    assert client.post(path, json=payload).status_code == 403
    actor["user"] = outsider
    assert client.post(path, json=payload).status_code == 403
    actor["user"] = reviewer
    created = client.post(path, json=payload)
    assert created.status_code == 200, created.text
    label_id = created.json()["id"]
    assert created.json()["status"] == "DRAFT"
    assert client.get(path).json()[0]["id"] == label_id
    assert client.post(f"{path}/{label_id}/approve").status_code == 403
    actor["user"] = approver
    company.name = "Changed after review"
    db.flush()
    changed = client.post(f"{path}/{label_id}/approve")
    assert changed.status_code == 409 and changed.json()["error"]["code"] == "REVIEW_INPUT_CHANGED"
    company.name = "Independent review company"
    db.flush()
    approved = client.post(f"{path}/{label_id}/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "APPROVED"
    assert client.get(f"{path}/{label_id}/events").json()[1]["action"] == "APPROVED"
    export = client.get(f"{path}/approved-export")
    assert export.status_code == 200
    assert export.json()["approved_count"] == 1
    assert export.json()["items"][0]["label"] == 3
    actor["user"] = reviewer
    assert client.post(path, json={**payload, "grade": 0}).status_code == 409
    assert client.get(f"{path}/approved-export").status_code == 403
    actor["user"] = approver
    reopened = client.post(f"{path}/{label_id}/reopen")
    assert reopened.status_code == 200 and reopened.json()["status"] == "REOPENED"
    assert client.get(f"{path}/approved-export").json()["approved_count"] == 0
    assert client.post(f"{path}/{label_id}/approve").status_code == 409
    actor["user"] = reviewer
    assert client.post(path, json={**payload, "grade": 2}).json()["status"] == "DRAFT"
    actor["user"] = approver
    assert client.post(f"{path}/{label_id}/approve").json()["grade"] == 2
    assert [event["action"] for event in client.get(f"{path}/{label_id}/events").json()] == [
        "REVIEWED", "APPROVED", "REOPENED", "REVIEWED", "APPROVED",
    ]


def test_synthetic_label_never_becomes_training_approved(review_state):
    client, _, actor, company, version, _, _, approver, _ = review_state
    path = "/api/v1/admin/relevance-labels"
    created = client.post(path, json=_payload(company, version, origin="SYNTHETIC"))
    assert created.status_code == 200
    actor["user"] = approver
    denied = client.post(f"{path}/{created.json()['id']}/approve")
    assert denied.status_code == 409
    assert denied.json()["error"]["code"] == "REAL_COMPANY_REQUIRED"
    assert client.get(f"{path}/approved-export").json()["approved_count"] == 0
