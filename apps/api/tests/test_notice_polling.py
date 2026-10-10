from contextlib import nullcontext
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from apps.api.app.config import Settings
from apps.api.app.database import SessionLocal
from apps.api.app.models import (
    BidNotice,
    BidNoticeVersion,
    NoticeCollectionRun,
    NoticeHistoryBackfillJob,
)
from apps.api.app.schemas import BusinessType, NoticeInquiryType, NoticeSyncRequest
from apps.api.app.services import notices as notices_service
from apps.api.app.services.g2b import G2BPage
from apps.api.app.services.notice_history_backfill import (
    enqueue_notice_history_backfill,
)
from apps.api.app.services.notices import save_notice_snapshot
from apps.api.app.workers import notice_polling
from apps.api.app.workers.notice_polling import (
    MAX_RECOVERY_WINDOW,
    build_changed_notice_request,
    build_foreign_registered_request,
    build_registered_notice_request,
    run_history_backfill_batch,
)


KST = ZoneInfo("Asia/Seoul")


def test_first_foreign_registered_poll_seeds_30_days() -> None:
    settings = Settings(_env_file=None, notice_poll_page_size=25, notice_poll_max_pages=3)
    now = datetime(2026, 10, 8, 9, 0, tzinfo=KST)

    request = build_foreign_registered_request(
        settings, now=now, last_completed_window_end=None
    )

    assert request.business_type == BusinessType.FOREIGN
    assert request.inquiry_type == NoticeInquiryType.REGISTERED
    assert request.window_started_at == now - MAX_RECOVERY_WINDOW
    assert request.window_ended_at == now
    assert (request.page_size, request.max_pages) == (25, 3)


def test_registered_request_has_its_own_business_type_and_checkpoint() -> None:
    settings = Settings(_env_file=None, notice_poll_overlap_minutes=5)
    now = datetime(2026, 10, 11, 9, tzinfo=KST)

    for business_type in (BusinessType.SERVICE, BusinessType.GOODS, BusinessType.CONSTRUCTION):
        request = build_registered_notice_request(
            settings,
            business_type=business_type,
            now=now,
            last_completed_window_end=now - timedelta(minutes=20),
        )
        assert request.business_type == business_type
        assert request.inquiry_type == NoticeInquiryType.REGISTERED
        assert request.window_started_at == now - timedelta(minutes=25)
        assert request.window_ended_at == now

    first_attempt = build_registered_notice_request(
        settings, business_type=BusinessType.GOODS, now=now,
        last_completed_window_end=None,
    )
    assert first_attempt.window_started_at == now - timedelta(minutes=settings.notice_poll_lookback_minutes)
    retry = build_registered_notice_request(
        settings, business_type=BusinessType.GOODS, now=now + timedelta(days=2),
        last_completed_window_end=None,
        initial_window_start=first_attempt.window_started_at,
    )
    assert retry.window_started_at == first_attempt.window_started_at
    assert retry.window_ended_at == now + timedelta(days=2)


def test_foreign_registered_poll_resumes_with_overlap_and_caps_recovery() -> None:
    settings = Settings(_env_file=None, notice_poll_overlap_minutes=5)
    now = datetime(2026, 10, 8, 9, 0, tzinfo=KST)

    recent = build_foreign_registered_request(
        settings, now=now, last_completed_window_end=now - timedelta(minutes=10)
    )
    stale = build_foreign_registered_request(
        settings, now=now, last_completed_window_end=now - timedelta(days=45)
    )

    assert recent.window_started_at == now - timedelta(minutes=15)
    assert stale.window_started_at == now - timedelta(days=45, minutes=5)
    assert stale.window_ended_at == stale.window_started_at + MAX_RECOVERY_WINDOW

    # A failed first bootstrap must retain its original start across days.
    original_start = now - MAX_RECOVERY_WINDOW
    retry = build_foreign_registered_request(
        settings,
        now=now + timedelta(days=2),
        last_completed_window_end=None,
        initial_window_start=original_start,
    )
    assert retry.window_started_at == original_start
    assert retry.window_ended_at == now


@pytest.mark.parametrize(
    ("business_type", "inquiry_type"),
    (
        (BusinessType.FOREIGN, NoticeInquiryType.REGISTERED),
        (BusinessType.SERVICE, NoticeInquiryType.REGISTERED),
        (BusinessType.GOODS, NoticeInquiryType.REGISTERED),
        (BusinessType.CONSTRUCTION, NoticeInquiryType.REGISTERED),
        (BusinessType.SERVICE, NoticeInquiryType.CHANGED),
    ),
)
def test_page_limit_does_not_mark_window_completed(monkeypatch, business_type, inquiry_type) -> None:
    class FakeSession:
        def add(self, run):
            for field in (
                "api_calls",
                "fetched_count",
                "created_count",
                "new_version_count",
                "unchanged_count",
                "failed_item_count",
            ):
                setattr(run, field, 0)

        def commit(self):
            pass

        def refresh(self, _run):
            pass

        def begin_nested(self):
            return nullcontext()

    class FakeClient:
        def fetch_page(self, **kwargs):
            return G2BPage(
                items=[{"bidNtceNo": f"foreign-{kwargs['page_number']}"}],
                total_count=3,
                page_number=kwargs["page_number"],
                page_size=1,
                endpoint="getBidPblancListInfoFrgcpt",
            )

    monkeypatch.setattr(
        notices_service,
        "save_notice_snapshot",
        lambda *_args, **_kwargs: ("UNCHANGED", object(), object()),
    )
    now = datetime(2026, 10, 8, 9, tzinfo=KST)
    request = NoticeSyncRequest(
        business_type=business_type,
        inquiry_type=inquiry_type,
        window_started_at=now - timedelta(days=1),
        window_ended_at=now,
        page_size=1,
        max_pages=2,
    )
    run = notices_service.run_notice_sync(
        FakeSession(), request=request, client=FakeClient()
    )

    assert run.fetched_count == 2
    assert run.status == "FAILED"
    assert run.error_message.startswith(f"{inquiry_type.value}_PAGE_LIMIT:")


@pytest.mark.parametrize("business_type", (BusinessType.FOREIGN, BusinessType.SERVICE))
def test_registered_page_limit_splits_oldest_first_without_gaps(monkeypatch, business_type) -> None:
    settings = Settings(
        _env_file=None, g2b_service_key="dummy", notice_poll_business_types=business_type.value
    )
    now = datetime(2026, 10, 8, 9, tzinfo=KST)
    completed = []
    calls = []

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def fake_sync(_db, *, request, **_kwargs):
        calls.append(request)
        if request.inquiry_type == NoticeInquiryType.REGISTERED:
            over_limit = (
                request.window_ended_at - request.window_started_at
            ) > timedelta(days=9)
            if not over_limit:
                completed.append(request)
            status = "FAILED" if over_limit else "COMPLETED"
            error_message = (
                "REGISTERED_PAGE_LIMIT: 1000 of 4000" if over_limit else None
            )
        else:
            status, error_message = "COMPLETED", None
        return SimpleNamespace(
            status=status,
            error_message=error_message,
            fetched_count=0,
            created_count=0,
            new_version_count=0,
            unchanged_count=0,
        )

    monkeypatch.setattr(notice_polling, "G2BClient", lambda **_kwargs: object())
    monkeypatch.setattr(notice_polling, "build_document_downloader", lambda _settings: None)
    monkeypatch.setattr(notice_polling, "SessionLocal", FakeSession)
    monkeypatch.setattr(notice_polling, "_last_completed_window_end", lambda *_args: None)
    monkeypatch.setattr(notice_polling, "_first_registered_window_start", lambda _type, **_kwargs: None)
    monkeypatch.setattr(notice_polling, "run_notice_sync", fake_sync)
    monkeypatch.setattr(notice_polling, "run_history_backfill_batch", lambda *_args, **_kwargs: 0)

    notice_polling.run_poll_cycle(settings, now=now)

    assert len(completed) == (4 if business_type == BusinessType.FOREIGN else 1)
    assert completed[0].window_started_at == now - (
        MAX_RECOVERY_WINDOW
        if business_type == BusinessType.FOREIGN
        else timedelta(minutes=settings.notice_poll_lookback_minutes)
    )
    assert completed[-1].window_ended_at == now
    for previous, following in zip(completed, completed[1:]):
        assert following.window_started_at == previous.window_ended_at + timedelta(minutes=1)
    assert calls[-1].inquiry_type == NoticeInquiryType.CHANGED


def test_foreign_split_stops_before_newer_windows_on_failure(monkeypatch) -> None:
    now = datetime(2026, 10, 8, 9, 3, tzinfo=KST)
    attempted = []

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def fake_sync(_db, *, request, **_kwargs):
        start, end = request.window_started_at, request.window_ended_at
        attempted.append((start, end))
        if start < end:
            status, error = "FAILED", "REGISTERED_PAGE_LIMIT: overflow"
        elif start.minute == 1:
            status, error = "FAILED", "temporary API failure"
        else:
            status, error = "COMPLETED", None
        return SimpleNamespace(
            status=status, error_message=error, fetched_count=0, created_count=0
        )

    monkeypatch.setattr(notice_polling, "SessionLocal", FakeSession)
    monkeypatch.setattr(notice_polling, "run_notice_sync", fake_sync)
    request = NoticeSyncRequest(
        business_type=BusinessType.FOREIGN,
        inquiry_type=NoticeInquiryType.REGISTERED,
        window_started_at=now - timedelta(minutes=3),
        window_ended_at=now,
    )
    success = notice_polling._sync_foreign_registered_window(
        request, client=object(), document_downloader=None
    )

    assert success is False
    assert attempted[-1] == (now - timedelta(minutes=2), now - timedelta(minutes=2))
    assert all(start <= now - timedelta(minutes=2) for start, _ in attempted)


def test_changed_page_limit_splits_without_advancing_past_failure(monkeypatch) -> None:
    now = datetime(2026, 10, 11, 9, 4, tzinfo=KST)
    attempted = []

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def fake_sync(_db, *, request, **_kwargs):
        attempted.append(request)
        if request.window_started_at < request.window_ended_at:
            status, error = "FAILED", "CHANGED_PAGE_LIMIT: overflow"
        elif request.window_started_at.minute == 2:
            status, error = "FAILED", "temporary API failure"
        else:
            status, error = "COMPLETED", None
        return SimpleNamespace(
            status=status, error_message=error, fetched_count=0, created_count=0
        )

    monkeypatch.setattr(notice_polling, "SessionLocal", FakeSession)
    monkeypatch.setattr(notice_polling, "run_notice_sync", fake_sync)
    request = NoticeSyncRequest(
        business_type=BusinessType.SERVICE,
        inquiry_type=NoticeInquiryType.CHANGED,
        window_started_at=now - timedelta(minutes=4),
        window_ended_at=now,
    )
    assert notice_polling._sync_poll_window(
        request, client=object(), document_downloader=None
    ) is False
    assert attempted[-1].window_started_at.minute == 2
    assert all(item.window_started_at.minute <= 2 for item in attempted)


def test_foreign_registers_before_changed_and_retries_failed_registration(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        g2b_service_key="dummy",
        notice_poll_business_types="SERVICE,FOREIGN",
    )
    now = datetime(2026, 10, 8, 9, 0, tzinfo=KST)
    calls = []
    failure = {"registered": False}

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def fake_sync(_db, *, request, **_kwargs):
        calls.append((request.business_type, request.inquiry_type))
        status = (
            "FAILED"
            if failure["registered"] and request.inquiry_type == NoticeInquiryType.REGISTERED
            else "COMPLETED"
        )
        return SimpleNamespace(
            status=status,
            error_message="temporary failure" if status == "FAILED" else None,
            fetched_count=0,
            created_count=0,
            new_version_count=0,
            unchanged_count=0,
        )

    monkeypatch.setattr(notice_polling, "G2BClient", lambda **_kwargs: object())
    monkeypatch.setattr(notice_polling, "build_document_downloader", lambda _settings: None)
    monkeypatch.setattr(notice_polling, "SessionLocal", FakeSession)
    monkeypatch.setattr(notice_polling, "_last_completed_window_end", lambda *_args: None)
    monkeypatch.setattr(notice_polling, "_first_registered_window_start", lambda _type, **_kwargs: None)
    monkeypatch.setattr(notice_polling, "run_notice_sync", fake_sync)
    monkeypatch.setattr(notice_polling, "run_history_backfill_batch", lambda *_args, **_kwargs: 0)

    expected = [
        (BusinessType.SERVICE, NoticeInquiryType.REGISTERED),
        (BusinessType.SERVICE, NoticeInquiryType.CHANGED),
        (BusinessType.FOREIGN, NoticeInquiryType.REGISTERED),
        (BusinessType.FOREIGN, NoticeInquiryType.CHANGED),
    ]
    notice_polling.run_poll_cycle(settings, now=now)
    assert calls == expected

    calls.clear()
    failure["registered"] = True
    notice_polling.run_poll_cycle(settings, now=now)
    assert calls == expected

    # The failed registration is independently attempted again next cycle.
    calls.clear()
    notice_polling.run_poll_cycle(settings, now=now + timedelta(minutes=5))
    assert calls == expected


def test_old_manual_registration_is_not_automatically_recovered(monkeypatch) -> None:
    settings = Settings(
        _env_file=None, g2b_service_key="dummy", notice_poll_business_types="SERVICE"
    )
    now = datetime(2026, 10, 11, 9, tzinfo=KST)
    calls = []

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def fake_last(_business_type, inquiry_type=NoticeInquiryType.CHANGED):
        return now - timedelta(days=45) if inquiry_type == NoticeInquiryType.REGISTERED else now

    def fake_sync(_db, *, request, **_kwargs):
        calls.append(request)
        return SimpleNamespace(
            status="COMPLETED", error_message=None, fetched_count=0, created_count=0
        )

    monkeypatch.setattr(notice_polling, "G2BClient", lambda **_kwargs: object())
    monkeypatch.setattr(notice_polling, "build_document_downloader", lambda _settings: None)
    monkeypatch.setattr(notice_polling, "SessionLocal", FakeSession)
    monkeypatch.setattr(notice_polling, "_last_completed_window_end", fake_last)
    monkeypatch.setattr(
        notice_polling, "_first_registered_window_start", lambda _type, **_kwargs: None
    )
    monkeypatch.setattr(notice_polling, "run_notice_sync", fake_sync)
    monkeypatch.setattr(notice_polling, "run_history_backfill_batch", lambda *_args, **_kwargs: 0)

    notice_polling.run_poll_cycle(settings, now=now)

    assert [call.inquiry_type for call in calls] == [
        NoticeInquiryType.REGISTERED, NoticeInquiryType.CHANGED
    ]
    assert calls[0].window_started_at == now - timedelta(
        minutes=settings.notice_poll_lookback_minutes
    )


@pytest.mark.parametrize(
    "business_type",
    (BusinessType.SERVICE, BusinessType.GOODS, BusinessType.CONSTRUCTION),
)
def test_registered_changed_and_repeat_are_idempotent_in_postgres(business_type) -> None:
    """Exercise actual constraints and inquiry-specific checkpoints in PostgreSQL."""
    notice_no = f"TEST-POLL-{uuid4()}"
    now = datetime(2026, 10, 11, 9, tzinfo=KST)
    current_order = {"value": "000"}
    db = SessionLocal()
    created_run_ids = []

    class FakeClient:
        def fetch_page(self, **kwargs):
            item = {
                "bidNtceNo": notice_no,
                "bidNtceOrd": current_order["value"],
                "bidNtceNm": "등록 및 변경공고 회귀 테스트",
                "ntceKindNm": "변경공고" if current_order["value"] == "001" else "일반공고",
                "reNtceYn": "N",
            }
            return G2BPage(
                items=[item], total_count=1, page_number=kwargs["page_number"],
                page_size=kwargs["page_size"], endpoint="test-registered-changed",
            )

        def fetch_change_history_page(self, **kwargs):
            return G2BPage(items=[], total_count=0, page_number=1,
                           page_size=kwargs["page_size"], endpoint="test-history")

    try:
        for inquiry_type, expected_created, expected_new_version in (
            (NoticeInquiryType.REGISTERED, 1, 0),
            (NoticeInquiryType.REGISTERED, 0, 0),
            (NoticeInquiryType.CHANGED, 0, 1),
            (NoticeInquiryType.CHANGED, 0, 0),
        ):
            if inquiry_type == NoticeInquiryType.CHANGED:
                current_order["value"] = "001"
            run = notices_service.run_notice_sync(
                db,
                request=NoticeSyncRequest(
                    business_type=business_type, inquiry_type=inquiry_type,
                    window_started_at=now - timedelta(minutes=5),
                    window_ended_at=now, page_size=10, max_pages=1,
                ),
                client=FakeClient(),
            )
            created_run_ids.append(run.id)
            assert run.status == "COMPLETED"
            assert run.created_count == expected_created
            assert run.new_version_count == expected_new_version

        notice = db.scalar(select(BidNotice).where(BidNotice.bid_notice_no == notice_no))
        versions = db.scalars(
            select(BidNoticeVersion).where(BidNoticeVersion.notice_id == notice.id)
            .order_by(BidNoticeVersion.version_number)
        ).all()
        assert [version.bid_notice_order for version in versions] == ["000", "001"]
        assert sum(version.is_current for version in versions) == 1
        assert versions[-1].is_current
        assert notice_polling._last_completed_window_end(
            business_type, NoticeInquiryType.REGISTERED
        ) is not None
        assert notice_polling._last_completed_window_end(
            business_type, NoticeInquiryType.CHANGED
        ) is not None
    finally:
        db.rollback()
        notice = db.scalar(select(BidNotice).where(BidNotice.bid_notice_no == notice_no))
        if notice is not None:
            db.delete(notice)
        for run_id in created_run_ids:
            run = db.get(NoticeCollectionRun, run_id)
            if run is not None:
                db.delete(run)
        db.commit()
        db.close()


def test_failed_registered_page_limit_does_not_advance_postgres_checkpoint() -> None:
    business_type = BusinessType.GOODS
    notice_no = f"TEST-POLL-LIMIT-{uuid4()}"
    now = datetime(2026, 10, 11, 9, tzinfo=KST)
    db = SessionLocal()
    created_run_ids = []

    class FakeClient:
        total_count = 1

        def fetch_page(self, **kwargs):
            return G2BPage(
                items=[{
                    "bidNtceNo": notice_no, "bidNtceOrd": "000",
                    "bidNtceNm": "페이지 제한 체크포인트 테스트", "reNtceYn": "N",
                }],
                total_count=self.total_count,
                page_number=kwargs["page_number"], page_size=kwargs["page_size"],
                endpoint="test-page-limit",
            )

    client = FakeClient()
    try:
        for offset, expected_status in ((0, "COMPLETED"), (5, "FAILED")):
            client.total_count = 3 if offset else 1
            run = notices_service.run_notice_sync(
                db,
                request=NoticeSyncRequest(
                    business_type=business_type,
                    inquiry_type=NoticeInquiryType.REGISTERED,
                    window_started_at=now + timedelta(minutes=offset),
                    window_ended_at=now + timedelta(minutes=offset + 1),
                    page_size=1, max_pages=1,
                ),
                client=client,
            )
            created_run_ids.append(run.id)
            assert run.status == expected_status
        assert run.error_message.startswith("REGISTERED_PAGE_LIMIT:")
        assert notice_polling._last_completed_window_end(
            business_type, NoticeInquiryType.REGISTERED
        ) == now + timedelta(minutes=1)
        assert db.scalar(
            select(BidNotice).where(BidNotice.bid_notice_no == notice_no)
        ) is not None
    finally:
        db.rollback()
        notice = db.scalar(select(BidNotice).where(BidNotice.bid_notice_no == notice_no))
        if notice is not None:
            db.delete(notice)
        for run_id in created_run_ids:
            run = db.get(NoticeCollectionRun, run_id)
            if run is not None:
                db.delete(run)
        db.commit()
        db.close()


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
