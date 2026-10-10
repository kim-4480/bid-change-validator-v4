from __future__ import annotations

import logging
import signal
from datetime import datetime, timedelta
from threading import Event
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select, text

from ..config import Settings, get_settings
from ..database import SessionLocal, engine
from ..models import BidNotice, NoticeCollectionRun, NoticeHistoryBackfillJob
from ..schemas import BusinessType, NoticeInquiryType, NoticeSyncRequest
from ..services.document_storage import (
    NoticeDocumentDownloader,
    build_document_downloader,
)
from ..services.g2b import G2BClient
from ..services.notices import run_notice_sync


KST = ZoneInfo("Asia/Seoul")
WORKER_LOCK_KEY = 7_040_021_615
MAX_RECOVERY_WINDOW = timedelta(days=30)
MAX_HISTORY_BACKFILL_ATTEMPTS = 3
logger = logging.getLogger("notice-polling")


def build_changed_notice_request(
    settings: Settings,
    *,
    business_type: BusinessType,
    now: datetime,
    last_completed_window_end: datetime | None,
) -> NoticeSyncRequest:
    if now.tzinfo is None:
        now = now.replace(tzinfo=KST)
    else:
        now = now.astimezone(KST)

    if last_completed_window_end is None:
        window_start = now - timedelta(minutes=settings.notice_poll_lookback_minutes)
    else:
        completed_at = last_completed_window_end.astimezone(KST)
        window_start = completed_at - timedelta(
            minutes=settings.notice_poll_overlap_minutes
        )

    window_start = max(window_start, now - MAX_RECOVERY_WINDOW)
    window_start = min(window_start, now)
    return NoticeSyncRequest(
        business_type=business_type,
        inquiry_type=NoticeInquiryType.CHANGED,
        window_started_at=window_start,
        window_ended_at=now,
        page_size=settings.notice_poll_page_size,
        max_pages=settings.notice_poll_max_pages,
    )


def build_registered_notice_request(
    settings: Settings,
    *,
    business_type: BusinessType,
    now: datetime,
    last_completed_window_end: datetime | None,
    initial_window_start: datetime | None = None,
) -> NoticeSyncRequest:
    """Resume each business type's registration cursor independently of CHANGED."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=KST)
    else:
        now = now.astimezone(KST)

    if last_completed_window_end is None:
        initial_lookback = (
            MAX_RECOVERY_WINDOW
            if business_type == BusinessType.FOREIGN
            else timedelta(minutes=settings.notice_poll_lookback_minutes)
        )
        window_start = initial_window_start or now - initial_lookback
    else:
        window_start = last_completed_window_end.astimezone(KST) - timedelta(
            minutes=settings.notice_poll_overlap_minutes
        )
    if window_start.tzinfo is None:
        window_start = window_start.replace(tzinfo=KST)
    else:
        window_start = window_start.astimezone(KST)
    window_start = min(window_start, now)

    return NoticeSyncRequest(
        business_type=business_type,
        inquiry_type=NoticeInquiryType.REGISTERED,
        window_started_at=window_start,
        window_ended_at=min(now, window_start + MAX_RECOVERY_WINDOW),
        page_size=settings.notice_poll_page_size,
        max_pages=settings.notice_poll_max_pages,
    )


def build_foreign_registered_request(
    settings: Settings,
    *,
    now: datetime,
    last_completed_window_end: datetime | None,
    initial_window_start: datetime | None = None,
) -> NoticeSyncRequest:
    return build_registered_notice_request(
        settings,
        business_type=BusinessType.FOREIGN,
        now=now,
        last_completed_window_end=last_completed_window_end,
        initial_window_start=initial_window_start,
    )


def _last_completed_window_end(
    business_type: BusinessType,
    inquiry_type: NoticeInquiryType = NoticeInquiryType.CHANGED,
) -> datetime | None:
    with SessionLocal() as db:
        return db.scalar(
            select(NoticeCollectionRun.window_ended_at)
            .where(
                NoticeCollectionRun.business_type == business_type.value,
                NoticeCollectionRun.inquiry_type == inquiry_type.value,
                NoticeCollectionRun.status == "COMPLETED",
            )
            .order_by(NoticeCollectionRun.window_ended_at.desc())
            .limit(1)
        )


def _first_registered_window_start(
    business_type: BusinessType, *, not_before: datetime | None = None
) -> datetime | None:
    # Anchor initial retries to the first persisted attempt, not moving now-30d.
    with SessionLocal() as db:
        conditions = [
            NoticeCollectionRun.business_type == business_type.value,
            NoticeCollectionRun.inquiry_type == NoticeInquiryType.REGISTERED.value,
            NoticeCollectionRun.status.in_(("FAILED", "RUNNING")),
            NoticeCollectionRun.window_started_at.is_not(None),
        ]
        if not_before is not None:
            conditions.append(NoticeCollectionRun.window_started_at >= not_before)
        return db.scalar(
            select(NoticeCollectionRun.window_started_at)
            .where(*conditions)
            .order_by(NoticeCollectionRun.window_started_at.asc())
            .limit(1)
    )


def _first_foreign_registered_window_start() -> datetime | None:
    return _first_registered_window_start(BusinessType.FOREIGN)


def _sync_poll_window(
    request: NoticeSyncRequest,
    *,
    client: G2BClient,
    document_downloader: NoticeDocumentDownloader | None,
) -> bool:
    with SessionLocal() as db:
        run = run_notice_sync(
            db,
            request=request,
            client=client,
            document_downloader=document_downloader,
        )
    logger.info(
        "poll window business_type=%s inquiry_type=%s status=%s start=%s end=%s fetched=%s created=%s",
        request.business_type.value,
        request.inquiry_type.value,
        run.status,
        request.window_started_at,
        request.window_ended_at,
        run.fetched_count,
        run.created_count,
    )
    if run.status == "COMPLETED":
        return True
    if not (run.error_message or "").startswith(
        f"{request.inquiry_type.value}_PAGE_LIMIT:"
    ):
        logger.error("poll window failed: %s", run.error_message)
        return False

    # G2B's date parameters are minute precision and inclusive. Split into
    # consecutive minute ranges so there is neither a gap nor an endless split.
    start = request.window_started_at.astimezone(KST).replace(second=0, microsecond=0)
    end = request.window_ended_at.astimezone(KST).replace(second=0, microsecond=0)
    minutes = int((end - start).total_seconds() // 60)
    if minutes < 1:
        logger.error("poll page limit exceeded at minute resolution")
        return False
    midpoint = start + timedelta(minutes=minutes // 2)
    left = request.model_copy(
        update={"window_started_at": start, "window_ended_at": midpoint}
    )
    right = request.model_copy(
        update={
            "window_started_at": midpoint + timedelta(minutes=1),
            "window_ended_at": end,
        }
    )
    # Short-circuit on the first incomplete segment: later windows must not
    # advance the completed-window checkpoint past missing notices.
    return _sync_poll_window(
        left, client=client, document_downloader=document_downloader
    ) and _sync_poll_window(
        right, client=client, document_downloader=document_downloader
    )


def _sync_registered_window(
    request: NoticeSyncRequest,
    *,
    client: G2BClient,
    document_downloader: NoticeDocumentDownloader | None,
) -> bool:
    return _sync_poll_window(
        request, client=client, document_downloader=document_downloader
    )


def _sync_foreign_registered_window(
    request: NoticeSyncRequest,
    *,
    client: G2BClient,
    document_downloader: NoticeDocumentDownloader | None,
) -> bool:
    return _sync_registered_window(
        request, client=client, document_downloader=document_downloader
    )


def run_poll_cycle(settings: Settings, *, now: datetime | None = None) -> None:
    service_key = settings.decoded_g2b_service_key
    if service_key is None:
        raise RuntimeError("G2B_SERVICE_KEY is not configured")

    cycle_time = now or datetime.now(KST)
    client = G2BClient(
        service_key=service_key,
        base_url=settings.g2b_base_url,
        timeout_seconds=settings.g2b_request_timeout_seconds,
    )
    downloader = build_document_downloader(settings)

    for business_type in settings.notice_poll_business_type_list:
        try:
            last_registered = _last_completed_window_end(
                business_type, NoticeInquiryType.REGISTERED
            )
            # Pre-existing manual registration runs may be very old. Do not
            # silently launch an unbounded historical crawl on first rollout.
            # Older gaps require an explicit, operator-approved backfill.
            if (
                business_type != BusinessType.FOREIGN
                and last_registered is not None
                and cycle_time.astimezone(KST) - last_registered.astimezone(KST)
                > MAX_RECOVERY_WINDOW
            ):
                logger.warning(
                    "ignoring old registered checkpoint business_type=%s end=%s; "
                    "historical recovery requires a separate backfill",
                    business_type.value,
                    last_registered,
                )
                last_registered = None
            initial_start = (
                _first_registered_window_start(
                    business_type,
                    not_before=(
                        cycle_time.astimezone(KST) - MAX_RECOVERY_WINDOW
                        if business_type != BusinessType.FOREIGN
                        else None
                    ),
                )
                if last_registered is None
                else None
            )
            request = build_registered_notice_request(
                settings,
                business_type=business_type,
                now=cycle_time,
                last_completed_window_end=last_registered,
                initial_window_start=initial_start,
            )
            _sync_registered_window(
                request, client=client, document_downloader=downloader
            )
        except Exception:
            logger.exception(
                "registered poll failed business_type=%s", business_type.value
            )

        # CHANGED has an independent checkpoint and always runs, even when
        # REGISTERED failed or stopped on an incomplete page window.
        try:
            request = build_changed_notice_request(
                settings,
                business_type=business_type,
                now=cycle_time,
                last_completed_window_end=_last_completed_window_end(business_type),
            )
            _sync_poll_window(
                request, client=client, document_downloader=downloader
            )
        except Exception:
            logger.exception(
                "poll failed business_type=%s inquiry_type=CHANGED", business_type.value
            )

    run_history_backfill_batch(
        settings,
        client=client,
        document_downloader=downloader,
        now=cycle_time,
    )


def run_history_backfill_batch(
    settings: Settings,
    *,
    client: G2BClient,
    document_downloader: NoticeDocumentDownloader | None,
    now: datetime | None = None,
) -> int:
    """Consume a bounded number of durable full-history jobs."""

    cycle_time = now or datetime.now(KST)
    stale_before = cycle_time - timedelta(hours=1)
    with SessionLocal() as db:
        job_ids = db.scalars(
            select(NoticeHistoryBackfillJob.id)
            .where(
                or_(
                    and_(
                        NoticeHistoryBackfillJob.status.in_(("PENDING", "FAILED")),
                        NoticeHistoryBackfillJob.next_attempt_at <= cycle_time,
                        NoticeHistoryBackfillJob.attempts < MAX_HISTORY_BACKFILL_ATTEMPTS,
                    ),
                    and_(
                        NoticeHistoryBackfillJob.status == "RUNNING",
                        NoticeHistoryBackfillJob.started_at < stale_before,
                    ),
                )
            )
            .order_by(NoticeHistoryBackfillJob.next_attempt_at)
            .limit(settings.notice_history_backfill_batch_size)
        ).all()

    completed = 0
    for job_id in job_ids:
        with SessionLocal() as db:
            job = db.get(NoticeHistoryBackfillJob, job_id)
            if job is None:
                continue
            if (
                job.status == "RUNNING"
                and job.attempts >= MAX_HISTORY_BACKFILL_ATTEMPTS
            ):
                job.status = "FAILED"
                job.last_error = "Retry limit reached after worker interruption"
                job.updated_at = cycle_time
                db.commit()
                continue
            notice = db.get(BidNotice, job.notice_id)
            if notice is None:
                db.delete(job)
                db.commit()
                continue

            job.status = "RUNNING"
            job.attempts += 1
            job.started_at = cycle_time
            job.completed_at = None
            job.last_error = None
            job.updated_at = cycle_time
            db.commit()

            try:
                run = run_notice_sync(
                    db,
                    request=NoticeSyncRequest(
                        business_type=BusinessType(notice.business_type),
                        inquiry_type=NoticeInquiryType.NOTICE_NUMBER,
                        bid_notice_no=notice.bid_notice_no,
                        page_size=settings.notice_poll_page_size,
                        max_pages=settings.notice_poll_max_pages,
                    ),
                    client=client,
                    document_downloader=document_downloader,
                )
                if run.status != "COMPLETED" or run.failed_item_count > 0:
                    raise RuntimeError(
                        run.error_message
                        or f"notice history sync ended with status={run.status}"
                    )
                job = db.get(NoticeHistoryBackfillJob, job_id)
                if job is not None:
                    job.status = "COMPLETED"
                    job.completed_at = datetime.now(KST)
                    job.updated_at = job.completed_at
                    db.commit()
                completed += 1
            except Exception as error:
                db.rollback()
                job = db.get(NoticeHistoryBackfillJob, job_id)
                if job is not None:
                    retry_factor = min(2 ** max(job.attempts - 1, 0), 96)
                    job.status = "FAILED"
                    job.next_attempt_at = cycle_time + timedelta(
                        minutes=(
                            settings.notice_history_backfill_retry_minutes
                            * retry_factor
                        )
                    )
                    job.last_error = f"{type(error).__name__}: {str(error)}"[:2000]
                    job.updated_at = datetime.now(KST)
                    db.commit()
                logger.exception("notice history backfill failed job_id=%s", job_id)

    if job_ids:
        logger.info(
            "notice history backfill batch selected=%s completed=%s",
            len(job_ids),
            completed,
        )
    return completed


def _run_cycle_with_lock(settings: Settings) -> bool:
    with engine.connect() as lock_connection:
        acquired = bool(
            lock_connection.scalar(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": WORKER_LOCK_KEY}
            )
        )
        if not acquired:
            logger.info("another notice polling worker owns the database lock")
            return False
        try:
            run_poll_cycle(settings)
            return True
        finally:
            lock_connection.execute(
                text("SELECT pg_advisory_unlock(:key)"), {"key": WORKER_LOCK_KEY}
            )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = get_settings()
    if settings.decoded_g2b_service_key is None:
        raise SystemExit("G2B_SERVICE_KEY is required for notice polling")

    stopped = Event()

    def stop(_signum, _frame) -> None:
        stopped.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    logger.info(
        "worker started interval=%ss business_types=%s",
        settings.notice_poll_interval_seconds,
        ",".join(item.value for item in settings.notice_poll_business_type_list),
    )
    while not stopped.is_set():
        try:
            _run_cycle_with_lock(settings)
        except Exception:
            logger.exception("poll cycle failed")
        stopped.wait(settings.notice_poll_interval_seconds)
    logger.info("worker stopped")


if __name__ == "__main__":
    main()
