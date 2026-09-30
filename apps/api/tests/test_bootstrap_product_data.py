from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from apps.api.app.schemas import BusinessType, NoticeInquiryType
from apps.api.app.scripts.bootstrap_product_data import build_collection_requests


KST = ZoneInfo("Asia/Seoul")


def test_build_collection_requests_for_product_baseline() -> None:
    now = datetime(2026, 9, 8, 1, 30, tzinfo=KST)

    requests = build_collection_requests(
        now=now,
        registered_days=3,
        changed_days=30,
        page_size=100,
        max_pages=2,
    )

    assert len(requests) == 2
    registered, changed = requests

    assert registered.business_type == BusinessType.SERVICE
    assert registered.inquiry_type == NoticeInquiryType.REGISTERED
    assert registered.window_ended_at == now
    assert (registered.window_ended_at - registered.window_started_at).days == 3
    assert registered.page_size == 100
    assert registered.max_pages == 2

    assert changed.business_type == BusinessType.SERVICE
    assert changed.inquiry_type == NoticeInquiryType.CHANGED
    assert changed.window_ended_at == now
    assert (changed.window_ended_at - changed.window_started_at).days == 30


def test_build_collection_requests_rejects_window_over_31_days() -> None:
    now = datetime(2026, 9, 8, 1, 30, tzinfo=KST)

    with pytest.raises(ValueError, match="changed_days"):
        build_collection_requests(now=now, changed_days=32)
