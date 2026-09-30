"""Re-upload notice originals to the configured object storage backend.

The command intentionally processes one document per transaction. A failed
download leaves the existing database storage metadata untouched so a retry
cannot make a previously healthy document look unavailable.
"""

from __future__ import annotations

import argparse
import json

from sqlalchemy import select

from ..config import get_settings
from ..database import SessionLocal
from ..models import BidNotice, BidNoticeVersion, NoticeDocument
from ..services.document_storage import build_document_downloader


def backfill(*, limit: int = 0, notice_no: str | None = None) -> dict[str, object]:
    settings = get_settings()
    if settings.document_storage_backend.strip().upper() != "S3":
        raise RuntimeError("DOCUMENT_STORAGE_BACKEND=S3 is required for this backfill")

    downloader = build_document_downloader(settings)
    with SessionLocal() as db:
        statement = (
            select(NoticeDocument, BidNoticeVersion, BidNotice)
            .join(BidNoticeVersion, NoticeDocument.notice_version_id == BidNoticeVersion.id)
            .join(BidNotice, BidNoticeVersion.notice_id == BidNotice.id)
            .order_by(BidNotice.bid_notice_no, BidNoticeVersion.version_number, NoticeDocument.document_order)
        )
        if notice_no:
            statement = statement.where(BidNotice.bid_notice_no == notice_no)
        if limit > 0:
            statement = statement.limit(limit)

        rows = db.execute(statement).all()
        counts = {"selected": len(rows), "uploaded": 0, "failed": 0}
        failures: list[dict[str, str]] = []
        known_storage_by_hash: dict[str, str] = {}

        for document, version, notice in rows:
            previous = {
                "download_status": document.download_status,
                "storage_key": document.storage_key,
                "content_type": document.content_type,
                "file_size_bytes": document.file_size_bytes,
                "file_sha256": document.file_sha256,
                "downloaded_at": document.downloaded_at,
                "download_error": document.download_error,
            }
            try:
                downloader.download(
                    document,
                    notice_no=notice.bid_notice_no,
                    version_number=version.version_number,
                    known_storage_by_hash=known_storage_by_hash,
                    extract_document=False,
                )
                if document.download_status != "DOWNLOADED":
                    raise RuntimeError(document.download_error or "download failed")
                db.commit()
                counts["uploaded"] += 1
            except Exception as error:
                db.rollback()
                for field, value in previous.items():
                    setattr(document, field, value)
                counts["failed"] += 1
                failures.append(
                    {
                        "notice_no": notice.bid_notice_no,
                        "version_number": str(version.version_number),
                        "document_id": str(document.id),
                        "error": f"{type(error).__name__}: {error}"[:500],
                    }
                )

        return {"counts": counts, "failures": failures}


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill notice originals into S3-compatible storage.")
    parser.add_argument("--limit", type=int, default=0, help="maximum documents to process (0 = all)")
    parser.add_argument("--notice-no", help="process one bid notice number only")
    args = parser.parse_args()
    print(json.dumps(backfill(limit=args.limit, notice_no=args.notice_no), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
