from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..database import SessionLocal
from ..models import BidNotice, BidNoticeVersion, NoticeDocument

KEYWORDS = {
    "qualification": ["참가자격", "입찰참가자격", "자격요건", "등록", "면허", "실적", "인력", "지역"],
    "evaluation": ["평가", "배점", "정량", "정성", "제안서", "발표", "협상"],
    "documents": ["제출서류", "구비서류", "증빙", "서류", "제출"],
    "contract": ["계약", "대금", "보증", "지체상금", "하자", "과업", "기간"],
    "change": ["변경", "정정", "수정", "변경사항", "변경사유"],
}


@dataclass(frozen=True)
class Snippet:
    category: str
    version_number: int
    document_id: str
    document_name: str
    keyword: str
    text: str


def _normalize(value: str) -> str:
    return " ".join(value.split())


def find_snippets(
    *,
    version_number: int,
    document: NoticeDocument,
    max_per_category: int = 2,
    radius: int = 180,
) -> list[Snippet]:
    text = document.extracted_text or ""
    if not text:
        return []

    snippets: list[Snippet] = []
    lowered = text.lower()
    for category, keywords in KEYWORDS.items():
        found = 0
        seen_spans: set[tuple[int, int]] = set()
        for keyword in keywords:
            start_at = 0
            while found < max_per_category:
                index = lowered.find(keyword.lower(), start_at)
                if index < 0:
                    break
                start = max(0, index - radius)
                end = min(len(text), index + len(keyword) + radius)
                span = (start, end)
                start_at = index + len(keyword)
                if span in seen_spans:
                    continue
                seen_spans.add(span)
                snippets.append(
                    Snippet(
                        category=category,
                        version_number=version_number,
                        document_id=str(document.id),
                        document_name=document.name,
                        keyword=keyword,
                        text=_normalize(text[start:end]),
                    )
                )
                found += 1
            if found >= max_per_category:
                break
    return snippets


def inspect_notice(
    db: Session,
    *,
    bid_notice_no: str,
    max_snippets_per_category: int = 2,
) -> dict[str, object]:
    notice = db.scalar(
        select(BidNotice)
        .options(selectinload(BidNotice.versions).selectinload(BidNoticeVersion.documents))
        .where(BidNotice.bid_notice_no == bid_notice_no)
    )
    if notice is None:
        raise ValueError(f"notice not found: {bid_notice_no}")

    versions = sorted(notice.versions, key=lambda item: item.version_number)
    version_rows: list[dict[str, object]] = []
    all_snippets: list[Snippet] = []

    for version in versions:
        documents = sorted(version.documents, key=lambda item: item.document_order)
        version_rows.append(
            {
                "version_number": version.version_number,
                "is_current": version.is_current,
                "bid_notice_order": version.bid_notice_order,
                "notice_kind": version.notice_kind,
                "registration_type": version.registration_type,
                "posted_at": version.posted_at,
                "changed_at": version.changed_at,
                "change_reason": version.change_reason,
                "contract_method": version.contract_method,
                "allocated_budget": version.allocated_budget,
                "estimated_price": version.estimated_price,
                "documents": [
                    {
                        "id": str(document.id),
                        "order": document.document_order,
                        "name": document.name,
                        "download_status": document.download_status,
                        "extraction_status": document.extraction_status,
                        "extracted_char_count": document.extracted_char_count,
                        "viewer_type": document.viewer_type,
                    }
                    for document in documents
                ],
            }
        )
        for document in documents:
            if document.extraction_status != "EXTRACTED":
                continue
            all_snippets.extend(
                find_snippets(
                    version_number=version.version_number,
                    document=document,
                    max_per_category=max_snippets_per_category,
                )
            )

    snippets_by_category: dict[str, list[dict[str, object]]] = {key: [] for key in KEYWORDS}
    for snippet in all_snippets:
        snippets_by_category[snippet.category].append(asdict(snippet))

    return {
        "notice": {
            "id": str(notice.id),
            "bid_notice_no": notice.bid_notice_no,
            "title": notice.title,
            "business_type": notice.business_type,
            "announcing_institution_name": notice.announcing_institution_name,
            "demanding_institution_name": notice.demanding_institution_name,
            "version_count": len(versions),
        },
        "versions": version_rows,
        "snippets": snippets_by_category,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect a Product Golden notice in detail.")
    parser.add_argument("bid_notice_no")
    parser.add_argument("--max-snippets-per-category", type=int, default=2)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        result = inspect_notice(
            db,
            bid_notice_no=args.bid_notice_no,
            max_snippets_per_category=max(1, args.max_snippets_per_category),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    finally:
        db.close()


if __name__ == "__main__":
    main()
