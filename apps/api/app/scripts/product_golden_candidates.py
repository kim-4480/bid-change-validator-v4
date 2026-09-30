from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..database import SessionLocal
from ..models import BidNotice, BidNoticeVersion


@dataclass(frozen=True)
class CandidateMetrics:
    notice_id: str
    bid_notice_no: str
    title: str
    version_count: int
    current_version: int
    document_count: int
    extracted_document_count: int
    extracted_chars: int
    change_reason_count: int
    score: float


def candidate_score(
    *,
    version_count: int,
    document_count: int,
    extracted_document_count: int,
    extracted_chars: int,
    change_reason_count: int,
) -> float:
    """Prioritize notices useful for the changed-notice product story.

    Multi-version history is intentionally weighted most heavily, followed by
    usable extracted documents. This is a ranking aid, not an evaluation metric.
    """

    return round(
        max(version_count - 1, 0) * 300
        + change_reason_count * 25
        + extracted_document_count * 20
        + document_count * 5
        + min(extracted_chars / 10_000, 20),
        2,
    )


def collect_golden_candidates(
    db: Session,
    *,
    business_type: str = "SERVICE",
    limit: int = 10,
    pool_size: int = 500,
) -> list[CandidateMetrics]:
    notices = db.scalars(
        select(BidNotice)
        .options(selectinload(BidNotice.versions).selectinload(BidNoticeVersion.documents))
        .where(BidNotice.business_type == business_type)
        .order_by(BidNotice.last_seen_at.desc())
        .limit(pool_size)
    ).all()

    candidates: list[CandidateMetrics] = []
    for notice in notices:
        versions = sorted(notice.versions, key=lambda version: version.version_number)
        if not versions:
            continue

        documents = [document for version in versions for document in version.documents]
        extracted = [document for document in documents if document.extraction_status == "EXTRACTED"]
        extracted_chars = sum(document.extracted_char_count or 0 for document in extracted)
        change_reason_count = sum(1 for version in versions if (version.change_reason or "").strip())

        metrics = CandidateMetrics(
            notice_id=str(notice.id),
            bid_notice_no=notice.bid_notice_no,
            title=notice.title,
            version_count=len(versions),
            current_version=max(version.version_number for version in versions),
            document_count=len(documents),
            extracted_document_count=len(extracted),
            extracted_chars=extracted_chars,
            change_reason_count=change_reason_count,
            score=candidate_score(
                version_count=len(versions),
                document_count=len(documents),
                extracted_document_count=len(extracted),
                extracted_chars=extracted_chars,
                change_reason_count=change_reason_count,
            ),
        )
        candidates.append(metrics)

    candidates.sort(
        key=lambda item: (
            item.score,
            item.version_count,
            item.extracted_document_count,
            item.document_count,
        ),
        reverse=True,
    )
    return candidates[:limit]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rank real notices for the MVP Product Golden Dataset."
    )
    parser.add_argument("--business-type", default="SERVICE")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--pool-size", type=int, default=500)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        candidates = collect_golden_candidates(
            db,
            business_type=args.business_type.upper(),
            limit=args.limit,
            pool_size=args.pool_size,
        )
        print(
            json.dumps(
                [asdict(candidate) for candidate in candidates],
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
