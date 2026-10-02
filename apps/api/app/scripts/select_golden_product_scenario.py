"""Rank real collected notices for the Product Golden Scenario.

Run from the repository root with the API environment configured:

    python -m apps.api.app.scripts.select_golden_product_scenario

The selector never mutates data.  It prefers notices that can demonstrate the
whole product story: multiple versions, extracted source documents, meaningful
raw change fields, and enough text to run qualification analysis.
"""

from __future__ import annotations

import json
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..database import SessionLocal
from ..models import BidNotice, BidNoticeVersion


def _score(versions: list[BidNoticeVersion]) -> tuple[int, dict[str, int | bool]]:
    current = next((item for item in versions if item.is_current), versions[-1])
    extracted_documents = sum(
        1
        for version in versions
        for document in version.documents
        if document.extraction_status == "EXTRACTED" and (document.extracted_char_count or 0) > 0
    )
    current_extracted = sum(
        1
        for document in current.documents
        if document.extraction_status == "EXTRACTED" and (document.extracted_char_count or 0) > 0
    )
    changed_versions = sum(1 for item in versions if item.version_number > 1)
    has_change_reason = any(bool(item.change_reason) for item in versions[1:])
    has_price_or_deadline = any(
        item.bid_closed_at is not None or item.estimated_price is not None or item.allocated_budget is not None
        for item in versions
    )

    score = 0
    score += min(changed_versions, 3) * 30
    score += min(current_extracted, 5) * 8
    score += min(extracted_documents, 10) * 2
    score += 10 if has_change_reason else 0
    score += 10 if has_price_or_deadline else 0

    return score, {
        "version_count": len(versions),
        "changed_versions": changed_versions,
        "current_extracted_documents": current_extracted,
        "extracted_documents": extracted_documents,
        "has_change_reason": has_change_reason,
        "has_price_or_deadline": has_price_or_deadline,
    }


def main(limit: int = 10) -> None:
    db = SessionLocal()
    try:
        notices = db.scalars(
            select(BidNotice)
            .options(selectinload(BidNotice.versions).selectinload(BidNoticeVersion.documents))
            .order_by(BidNotice.last_seen_at.desc())
        ).all()

        candidates = []
        for notice in notices:
            versions = sorted(notice.versions, key=lambda item: item.version_number)
            if len(versions) < 2:
                continue
            score, signals = _score(versions)
            candidates.append(
                {
                    "score": score,
                    "notice_id": str(notice.id),
                    "bid_notice_no": notice.bid_notice_no,
                    "title": notice.title,
                    "institution": notice.announcing_institution_name,
                    "business_type": notice.business_type,
                    **signals,
                }
            )

        candidates.sort(key=lambda item: (item["score"], item["version_count"]), reverse=True)
        print(json.dumps(candidates[:limit], ensure_ascii=False, indent=2, default=str))
    finally:
        db.close()


if __name__ == "__main__":
    main()
