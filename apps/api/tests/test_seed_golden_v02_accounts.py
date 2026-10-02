import json
from pathlib import Path
from uuid import uuid4

import pytest

from apps.api.app.scripts.seed_golden_v02_accounts import (
    _preserved_baseline_id,
    golden_business_number,
    golden_username,
    load_golden_bundle,
    synthetic_industry_code,
)
from apps.api.app.models import BidNoticeVersion


def test_golden_account_identifiers_are_stable() -> None:
    assert golden_username("J01") == "golden-j01"
    assert golden_username("J32") == "golden-j32"
    assert golden_business_number("J01") == "9902000001"
    assert golden_business_number("J32") == "9902000032"
    assert synthetic_industry_code("J09", 1) == "GOLDEN-J09-01"


def test_golden_username_rejects_non_product_case() -> None:
    with pytest.raises(ValueError):
        golden_username("CH01-BEFORE")


def test_seed_preserves_only_an_earlier_baseline_from_the_same_notice() -> None:
    notice_id = uuid4()
    current = BidNoticeVersion(id=uuid4(), notice_id=notice_id, version_number=2)
    earlier = BidNoticeVersion(id=uuid4(), notice_id=notice_id, version_number=1)
    same = BidNoticeVersion(id=current.id, notice_id=notice_id, version_number=2)
    later = BidNoticeVersion(id=uuid4(), notice_id=notice_id, version_number=3)
    other_notice = BidNoticeVersion(id=uuid4(), notice_id=uuid4(), version_number=1)

    assert _preserved_baseline_id(earlier, current=current) == earlier.id
    assert _preserved_baseline_id(None, current=current) is None
    assert _preserved_baseline_id(same, current=current) is None
    assert _preserved_baseline_id(later, current=current) is None
    assert _preserved_baseline_id(other_notice, current=current) is None


def test_load_golden_bundle_keeps_current_company_cases(tmp_path: Path) -> None:
    (tmp_path / "sources").mkdir()
    (tmp_path / "fixture_bundle.json").write_text(
        json.dumps(
            {
                "cases": [
                    {"case_id": "J02"},
                    {"case_id": "CH01-BEFORE"},
                    {"case_id": "J01"},
                ]
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "sources" / "evidence_all.json").write_text(
        json.dumps([{"evidence_id": "E001"}]),
        encoding="utf-8",
    )

    cases, evidence = load_golden_bundle(tmp_path)

    assert [item["case_id"] for item in cases] == ["J01", "J02"]
    assert evidence == {"E001": {"evidence_id": "E001"}}
