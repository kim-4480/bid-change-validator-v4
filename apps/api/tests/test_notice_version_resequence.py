from datetime import datetime
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import inspect, select

from apps.api.app.database import SessionLocal
from apps.api.app.models import BidNotice, BidNoticeVersion, NoticeCollectionRun
from apps.api.app.schemas import BusinessType, NoticeInquiryType, NoticeSyncRequest
from apps.api.app.services.g2b import G2BPage
from apps.api.app.services.notices import (
    _resequence_notice_versions,
    run_notice_sync,
    save_notice_snapshot,
)


KST = ZoneInfo("Asia/Seoul")


def _history_item(notice_no: str, order: str) -> dict:
    return {
        "bidNtceNo": notice_no,
        "bidNtceOrd": order,
        "bidNtceNm": "이력 재정렬 테스트",
        "ntceKindNm": "변경공고" if order != "000" else "일반공고",
        "reNtceYn": "N",
        "presmptPrce": str(100_000_000 + int(order)),
    }


class _HistoryClient:
    def __init__(self, items: list[dict]) -> None:
        self.items = items

    def fetch_page(self, **kwargs) -> G2BPage:
        return G2BPage(
            items=self.items,
            total_count=len(self.items),
            page_number=kwargs["page_number"],
            page_size=kwargs["page_size"],
            endpoint="getBidPblancListInfoServc",
        )


def _save_existing_orders(db, notice_no: str, orders: list[str]) -> BidNotice:
    notice = None
    for order in orders:
        _, notice, _ = save_notice_snapshot(
            db,
            item=_history_item(notice_no, order),
            business_type=BusinessType.SERVICE,
            source_endpoint="getBidPblancListInfoServc",
        )
    db.commit()
    assert notice is not None
    return notice


def _run_history_backfill(db, notice_no: str, orders: list[str]) -> NoticeCollectionRun:
    return run_notice_sync(
        db,
        request=NoticeSyncRequest(
            business_type=BusinessType.SERVICE,
            inquiry_type=NoticeInquiryType.NOTICE_NUMBER,
            bid_notice_no=notice_no,
        ),
        client=_HistoryClient([_history_item(notice_no, order) for order in orders]),
    )


def _assert_sequence(db, notice_id: UUID, expected_orders: list[str]) -> None:
    versions = db.scalars(
        select(BidNoticeVersion)
        .where(BidNoticeVersion.notice_id == notice_id)
        .order_by(BidNoticeVersion.version_number)
    ).all()
    assert [version.bid_notice_order for version in versions] == expected_orders
    # version_number is intentionally 1-based by the existing DB check
    # constraint and application contract; G2B bidNtceOrd remains 000-based.
    assert [version.version_number for version in versions] == list(
        range(1, len(expected_orders) + 1)
    )
    assert [version.is_current for version in versions] == [
        *([False] * (len(expected_orders) - 1)),
        True,
    ]


def _cleanup(db, *, notice_id: UUID, run_ids: list[UUID]) -> None:
    db.rollback()
    notice = db.get(BidNotice, notice_id)
    if notice is not None:
        db.delete(notice)
        db.commit()
    for run_id in run_ids:
        run = db.get(NoticeCollectionRun, run_id)
        if run is not None:
            db.delete(run)
    db.commit()


def _version(
    *,
    version_id: UUID,
    notice_id: UUID,
    version_number: int,
    order: str,
    is_current: bool,
) -> BidNoticeVersion:
    return BidNoticeVersion(
        id=version_id,
        notice_id=notice_id,
        version_number=version_number,
        bid_notice_order=order,
        is_current=is_current,
        is_reannouncement=False,
        source_endpoint="pytest",
        payload_hash=f"{version_number:064x}",
        raw_json={"bidNtceOrd": order},
        collected_at=datetime(2026, 9, 1, tzinfo=KST),
    )


def test_resequence_demotes_current_before_promoting_latest_order() -> None:
    """Reproduce the production failure with deterministic ORM update order."""

    db = SessionLocal()
    notice_id = uuid4()
    try:
        notice = BidNotice(
            id=notice_id,
            bid_notice_no=f"TEST-RESEQUENCE-{notice_id}",
            title="재정렬 current 충돌 회귀",
            business_type="SERVICE",
            first_seen_at=datetime(2026, 9, 1, tzinfo=KST),
            last_seen_at=datetime(2026, 9, 1, tzinfo=KST),
        )
        db.add(notice)
        db.add_all(
            [
                # The lower primary key is updated first by the ORM.  Promoting it
                # before the current row below is demoted violates the partial
                # unique index in the old implementation.
                _version(
                    version_id=UUID(int=1),
                    notice_id=notice_id,
                    version_number=1,
                    order="001",
                    is_current=False,
                ),
                _version(
                    version_id=UUID(int=2),
                    notice_id=notice_id,
                    version_number=2,
                    order="000",
                    is_current=True,
                ),
            ]
        )
        db.commit()

        _resequence_notice_versions(db, notice_id=notice_id)
        db.commit()

        versions = db.scalars(
            select(BidNoticeVersion)
            .where(BidNoticeVersion.notice_id == notice_id)
            .order_by(BidNoticeVersion.version_number)
        ).all()
        assert [version.bid_notice_order for version in versions] == ["000", "001"]
        assert [version.version_number for version in versions] == [1, 2]
        assert [version.is_current for version in versions] == [False, True]
    finally:
        _cleanup(db, notice_id=notice_id, run_ids=[])
        db.close()


@pytest.mark.parametrize(
    ("existing_orders", "history_orders", "expected_orders"),
    [
        (["001"], ["001", "000"], ["000", "001"]),
        (["003"], ["003", "002", "001", "000"], ["000", "001", "002", "003"]),
    ],
)
def test_history_backfill_inserts_earlier_orders_and_keeps_latest_current(
    existing_orders: list[str],
    history_orders: list[str],
    expected_orders: list[str],
) -> None:
    notice_no = f"TEST-HISTORY-EARLIER-{uuid4()}"
    db = SessionLocal()
    notice_id = None
    run_ids: list[UUID] = []
    try:
        notice = _save_existing_orders(db, notice_no, existing_orders)
        notice_id = notice.id

        run = _run_history_backfill(db, notice_no, history_orders)
        run_ids.append(run.id)

        assert run.status == "COMPLETED"
        _assert_sequence(db, notice.id, expected_orders)
    finally:
        if notice_id is not None:
            _cleanup(db, notice_id=notice_id, run_ids=run_ids)
        db.close()


def test_history_backfill_inserts_middle_order_and_is_idempotent() -> None:
    notice_no = f"TEST-HISTORY-MIDDLE-{uuid4()}"
    db = SessionLocal()
    notice_id = None
    run_ids: list[UUID] = []
    try:
        notice = _save_existing_orders(db, notice_no, ["000", "002", "003"])
        notice_id = notice.id
        reverse_history = ["003", "002", "001", "000"]

        first_run = _run_history_backfill(db, notice_no, reverse_history)
        run_ids.append(first_run.id)
        assert first_run.status == "COMPLETED"
        _assert_sequence(db, notice.id, ["000", "001", "002", "003"])

        repeated_run = _run_history_backfill(db, notice_no, reverse_history)
        run_ids.append(repeated_run.id)
        assert repeated_run.status == "COMPLETED"
        _assert_sequence(db, notice.id, ["000", "001", "002", "003"])
    finally:
        if notice_id is not None:
            _cleanup(db, notice_id=notice_id, run_ids=run_ids)
        db.close()


def test_postgresql_resequence_constraints_are_present() -> None:
    db = SessionLocal()
    try:
        inspector = inspect(db.get_bind())
        assert inspector.dialect.name == "postgresql"

        unique_constraints = {
            constraint["name"]
            for constraint in inspector.get_unique_constraints("bid_notice_versions")
        }
        indexes = {
            index["name"]: index
            for index in inspector.get_indexes("bid_notice_versions")
        }

        assert "uq_notice_version_number" in unique_constraints
        assert indexes["uq_bid_notice_versions_current"]["unique"] is True
        assert (
            str(
                indexes["uq_bid_notice_versions_current"]["dialect_options"][
                    "postgresql_where"
                ]
            ).lower()
            == "is_current"
        )
    finally:
        db.close()
