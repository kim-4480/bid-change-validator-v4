from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ..config import get_settings
from ..database import SessionLocal
from ..schemas import BusinessType, NoticeInquiryType, NoticeSyncRequest
from ..services.document_extraction import extract_pending_documents
from ..services.document_storage import build_document_downloader
from ..services.g2b import G2BClient
from ..services.notices import run_notice_sync
from .product_data_inventory import collect_product_data_inventory


KST = ZoneInfo("Asia/Seoul")


def build_collection_requests(
    *,
    now: datetime,
    business_type: BusinessType = BusinessType.SERVICE,
    registered_days: int = 3,
    changed_days: int = 30,
    page_size: int = 100,
    max_pages: int = 2,
) -> list[NoticeSyncRequest]:
    if now.tzinfo is None:
        now = now.replace(tzinfo=KST)
    else:
        now = now.astimezone(KST)
    if not 1 <= registered_days <= 31:
        raise ValueError("registered_days must be between 1 and 31")
    if not 1 <= changed_days <= 31:
        raise ValueError("changed_days must be between 1 and 31")

    return [
        NoticeSyncRequest(
            business_type=business_type,
            inquiry_type=NoticeInquiryType.REGISTERED,
            window_started_at=now - timedelta(days=registered_days),
            window_ended_at=now,
            page_size=page_size,
            max_pages=max_pages,
        ),
        NoticeSyncRequest(
            business_type=business_type,
            inquiry_type=NoticeInquiryType.CHANGED,
            window_started_at=now - timedelta(days=changed_days),
            window_ended_at=now,
            page_size=page_size,
            max_pages=max_pages,
        ),
    ]


def bootstrap_product_data(
    *,
    registered_days: int = 3,
    changed_days: int = 30,
    page_size: int = 100,
    max_pages: int = 2,
    extract_limit: int = 500,
) -> dict[str, object]:
    settings = get_settings()
    service_key = settings.decoded_g2b_service_key
    if service_key is None:
        raise RuntimeError("G2B_SERVICE_KEY is not configured")

    client = G2BClient(
        service_key=service_key,
        base_url=settings.g2b_base_url,
        timeout_seconds=settings.g2b_request_timeout_seconds,
    )
    downloader = build_document_downloader(settings)
    requests = build_collection_requests(
        now=datetime.now(KST),
        registered_days=registered_days,
        changed_days=changed_days,
        page_size=page_size,
        max_pages=max_pages,
    )

    db = SessionLocal()
    try:
        runs: list[dict[str, object]] = []
        for request in requests:
            run = run_notice_sync(
                db,
                request=request,
                client=client,
                document_downloader=downloader,
            )
            runs.append(
                {
                    "id": str(run.id),
                    "inquiry_type": run.inquiry_type,
                    "status": run.status,
                    "api_calls": run.api_calls,
                    "fetched_count": run.fetched_count,
                    "created_count": run.created_count,
                    "new_version_count": run.new_version_count,
                    "unchanged_count": run.unchanged_count,
                }
            )

        extraction = extract_pending_documents(
            db,
            settings=settings,
            limit=extract_limit,
            retry_failed=False,
        )
        inventory = collect_product_data_inventory(db)
        return {
            "runs": runs,
            "extraction": extraction,
            "inventory": inventory,
        }
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect a small real G2B dataset for the MVP Product Baseline."
    )
    parser.add_argument("--registered-days", type=int, default=3)
    parser.add_argument("--changed-days", type=int, default=30)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--max-pages", type=int, default=2)
    parser.add_argument("--extract-limit", type=int, default=500)
    args = parser.parse_args()

    result = bootstrap_product_data(
        registered_days=args.registered_days,
        changed_days=args.changed_days,
        page_size=args.page_size,
        max_pages=args.max_pages,
        extract_limit=args.extract_limit,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
