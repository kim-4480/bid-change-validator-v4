from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select

from apps.api.app.config import Settings
from apps.api.app.database import SessionLocal
from apps.api.app.models import (
    BidNotice,
    BidNoticeVersion,
    NoticeCollectionRun,
    NoticeHistoryBackfillJob,
)
from apps.api.app.schemas import BusinessType, NoticeInquiryType
from apps.api.app.services.g2b import G2BPage
from apps.api.app.services.notice_history_backfill import (
    enqueue_notice_history_backfill,
)
from apps.api.app.services.notices import save_notice_snapshot
from apps.api.app.workers.notice_polling import (
    MAX_RECOVERY_WINDOW,
    build_changed_notice_request,
    run_history_backfill_batch,
)


KST = ZoneInfo("Asia/Seoul")


def test_first_changed_poll_uses_configured_lookback() -> None:
    settings = Settings(
        _env_file=None,
        notice_poll_lookback_minutes=90,
        notice_poll_overlap_minutes=7,
    )
    now = datetime(2026, 9, 6, 15, 0, tzinfo=KST)

    request = build_changed_notice_request(
        settings,
        business_type=BusinessType.SERVICE,
        now=now,
        last_completed_window_end=None,
    )

    assert request.inquiry_type == NoticeInquiryType.CHANGED
    assert request.window_started_at == now - timedelta(minutes=90)
    assert request.window_ended_at == now


def test_changed_poll_overlaps_last_completed_window_and_caps_recovery() -> None:
    settings = Settings(
        _env_file=None,
        notice_poll_lookback_minutes=60,
        notice_poll_overlap_minutes=5,
    )
    now = datetime(2026, 9, 6, 15, 0, tzinfo=KST)

    recent = build_changed_notice_request(
        settings,
        business_type=BusinessType.GOODS,
        now=now,
        last_completed_window_end=now - timedelta(minutes=10),
    )
    stale = build_changed_notice_request(
        settings,
        business_type=BusinessType.GOODS,
        now=now,
        last_completed_window_end=now - timedelta(days=45),
    )

    assert recent.window_started_at == now - timedelta(minutes=15)
    assert stale.window_started_at == now - MAX_RECOVERY_WINDOW


def test_history_backfill_worker_completes_a_queued_notice() -> None:
    notice_no = f"TEST-WORKER-{uuid4()}"
    db = SessionLocal()
    notice_id = None
    existing_run_ids: set = set()
    try:
        item = {
            "bidNtceNo": notice_no,
            "bidNtceOrd": "003",
            "bidNtceNm": "전체 이력 백필 테스트",
            "ntceKindNm": "변경공고",
            "reNtceYn": "N",
        }
        _, notice, _ = save_notice_snapshot(
            db,
            item=item,
            business_type=BusinessType.SERVICE,
            source_endpoint="getBidPblancListInfoServc",
        )
        notice_id = notice.id
        job = enqueue_notice_history_backfill(
            db,
            notice_id=notice.id,
            queued_at=datetime(2026, 9, 13, 9, tzinfo=KST),
        )
        job_id = job.id
        db.commit()
        existing_run_ids = set(db.scalars(select(NoticeCollectionRun.id)).all())

        history = []
        for order in range(6):
            history.append(
                {
                    **item,
                    "bidNtceOrd": f"{order:03d}",
                    "ntceKindNm": "취소공고" if order == 5 else "변경공고",
                }
            )

        class FakeHistoryClient:
            def fetch_page(self, **kwargs) -> G2BPage:
                return G2BPage(
                    items=list(reversed(history)),
                    total_count=6,
                    page_number=kwargs["page_number"],
                    page_size=kwargs["page_size"],
                    endpoint="getBidPblancListInfoServc",
                )

        completed = run_history_backfill_batch(
            Settings(_env_file=None, notice_history_backfill_batch_size=1),
            client=FakeHistoryClient(),
            document_downloader=None,
            now=datetime(2026, 9, 13, 10, tzinfo=KST),
        )

        db.expire_all()
        assert completed == 1
        assert db.get(NoticeHistoryBackfillJob, job_id).status == "COMPLETED"
        versions = db.scalars(
            select(BidNoticeVersion)
            .where(BidNoticeVersion.notice_id == notice.id)
            .order_by(BidNoticeVersion.version_number)
        ).all()
        assert [version.bid_notice_order for version in versions] == [
            "000", "001", "002", "003", "004", "005"
        ]
        assert versions[-1].is_current is True
    finally:
        if notice_id is not None:
            notice = db.get(BidNotice, notice_id)
            if notice is not None:
                db.delete(notice)
        for run in db.scalars(select(NoticeCollectionRun)).all():
            if run.id not in existing_run_ids:
                db.delete(run)
        db.commit()
        db.close()


def test_history_backfill_retries_and_rolls_back_when_last_order_fails() -> None:
    notice_no = f"TEST-WORKER-PARTIAL-{uuid4()}"
    db = SessionLocal()
    notice_id = None
    existing_run_ids: set = set()
    try:
        current_item = {
            "bidNtceNo": notice_no,
            "bidNtceOrd": "003",
            "bidNtceNm": "전체 이력 원자성 테스트",
            "ntceKindNm": "변경공고",
            "reNtceYn": "N",
        }
        _, notice, original_version = save_notice_snapshot(
            db,
            item=current_item,
            business_type=BusinessType.SERVICE,
            source_endpoint="getBidPblancListInfoServc",
        )
        notice_id = notice.id
        job = enqueue_notice_history_backfill(
            db,
            notice_id=notice.id,
            queued_at=datetime(2026, 9, 13, 9, tzinfo=KST),
        )
        job_id = job.id
        db.commit()
        existing_run_ids = set(db.scalars(select(NoticeCollectionRun.id)).all())

        history = []
        for order in range(6):
            item = {
                **current_item,
                "bidNtceOrd": f"{order:03d}",
                "ntceKindNm": "취소공고" if order == 5 else "변경공고",
            }
            if order == 5:
                item.pop("bidNtceNm")
            history.append(item)

        class PartialHistoryClient:
            def fetch_page(self, **kwargs) -> G2BPage:
                return G2BPage(
                    items=history,
                    total_count=6,
                    page_number=kwargs["page_number"],
                    page_size=kwargs["page_size"],
                    endpoint="getBidPblancListInfoServc",
                )

        cycle_time = datetime(2026, 9, 13, 10, tzinfo=KST)
        completed = run_history_backfill_batch(
            Settings(
                _env_file=None,
                notice_history_backfill_batch_size=1,
                notice_history_backfill_retry_minutes=15,
            ),
            client=PartialHistoryClient(),
            document_downloader=None,
            now=cycle_time,
        )

        db.expire_all()
        failed_job = db.get(NoticeHistoryBackfillJob, job_id)
        assert completed == 0
        assert failed_job.status == "FAILED"
        assert failed_job.attempts == 1
        assert failed_job.next_attempt_at == cycle_time + timedelta(minutes=15)
        assert "1개 항목 저장 실패" in (failed_job.last_error or "")

        versions = db.scalars(
            select(BidNoticeVersion).where(BidNoticeVersion.notice_id == notice.id)
        ).all()
        assert len(versions) == 1
        assert versions[0].id == original_version.id
        assert versions[0].bid_notice_order == "003"
        assert versions[0].version_number == 1
        assert versions[0].is_current is True

        failed_run = db.scalar(
            select(NoticeCollectionRun)
            .where(NoticeCollectionRun.id.not_in(existing_run_ids))
            .order_by(NoticeCollectionRun.started_at.desc())
        )
        assert failed_run is not None
        assert failed_run.status == "FAILED"
        assert failed_run.fetched_count == 6
        assert failed_run.failed_item_count == 1
    finally:
        if notice_id is not None:
            notice = db.get(BidNotice, notice_id)
            if notice is not None:
                db.delete(notice)
        for run in db.scalars(select(NoticeCollectionRun)).all():
            if run.id not in existing_run_ids:
                db.delete(run)
        db.commit()
        db.close()
