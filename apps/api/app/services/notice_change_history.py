import hashlib
import json
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import BidNotice, BidNoticeVersion, NoticeChangeHistory
from .json_safety import sanitize_json_value


KST = ZoneInfo("Asia/Seoul")


def _text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _datetime(value: Any) -> datetime | None:
    normalized = _text(value)
    if normalized is None:
        return None
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y%m%d%H%M%S", "%Y%m%d%H%M"):
        try:
            return datetime.strptime(normalized, pattern).replace(tzinfo=KST)
        except ValueError:
            pass
    return None


def _normalized_order(value: str | None) -> str | None:
    if value is None:
        return None
    return str(int(value)) if value.isdigit() else value


def _payload_hash(item: dict[str, Any]) -> str:
    item = sanitize_json_value(item)
    canonical = json.dumps(
        item,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def upsert_notice_change_history(
    db: Session,
    *,
    notice: BidNotice,
    fallback_version: BidNoticeVersion,
    items: list[dict[str, Any]],
    source_endpoint: str,
    collected_at: datetime | None = None,
) -> int:
    """Persist exact upstream change rows and connect them to a known local version."""

    collected_at = collected_at or datetime.now(KST)
    versions = db.scalars(
        select(BidNoticeVersion)
        .where(BidNoticeVersion.notice_id == notice.id)
        .order_by(BidNoticeVersion.version_number.desc())
    ).all()
    version_by_order: dict[str, BidNoticeVersion] = {}
    for version in versions:
        normalized = _normalized_order(_text(version.bid_notice_order))
        if normalized is not None and normalized not in version_by_order:
            version_by_order[normalized] = version

    processed = 0
    for item in items:
        item = sanitize_json_value(item)
        if _text(item.get("bidNtceNo")) != notice.bid_notice_no:
            continue
        item_name = _text(item.get("chgItemNm"))
        if item_name is None:
            continue

        bid_notice_order = _text(item.get("bidNtceOrd"))
        version = version_by_order.get(_normalized_order(bid_notice_order) or "")
        if version is None and (
            bid_notice_order is None
            or _normalized_order(bid_notice_order)
            == _normalized_order(_text(fallback_version.bid_notice_order))
        ):
            version = fallback_version

        payload_hash = _payload_hash(item)
        row = db.scalar(
            select(NoticeChangeHistory).where(
                NoticeChangeHistory.notice_id == notice.id,
                NoticeChangeHistory.payload_hash == payload_hash,
            )
        )
        values = {
            "notice_version_id": version.id if version is not None else None,
            "bid_notice_order": bid_notice_order,
            "rebid_number": _text(item.get("rbidNo")),
            "changed_at": _datetime(item.get("chgDt")),
            "change_data_type": _text(item.get("chgDataDivNm")),
            "item_name": item_name,
            "before_value": _text(item.get("bfchgVal")),
            "after_value": _text(item.get("afchgVal")),
            "business_division_name": _text(item.get("bsnsDivNm")),
            "source_endpoint": source_endpoint,
            "raw_json": item,
            "collected_at": collected_at,
            "updated_at": collected_at,
        }
        if row is None:
            db.add(
                NoticeChangeHistory(
                    notice_id=notice.id,
                    payload_hash=payload_hash,
                    **values,
                )
            )
        else:
            for field, value in values.items():
                setattr(row, field, value)
        processed += 1

    db.flush()
    return processed
