from apps.api.app.scripts.seed_product_golden_demo import (
    DEFAULT_NOTICE_NO,
    DEMO_BUSINESS_NO,
    DEMO_COMPANY_NAME,
    DEMO_CASE_TITLE,
    DEMO_PASSWORD,
    DEMO_USERNAME,
    PROPOSAL_TEXT,
)


def test_product_golden_demo_contract_is_stable() -> None:
    assert DEFAULT_NOTICE_NO == "R26BK01715087"
    assert DEMO_COMPANY_NAME
    assert len(DEMO_BUSINESS_NO) == 10
    assert DEMO_CASE_TITLE.startswith("Golden Demo")
    assert DEMO_USERNAME == "golden-demo"
    assert DEMO_PASSWORD == "golden-demo"


def test_demo_proposal_covers_product_workflow() -> None:
    assert "해외진출" in PROPOSAL_TEXT
    assert "수행 조직" in PROPOSAL_TEXT
    assert "수행 실적" in PROPOSAL_TEXT
    assert "정성제안서" in PROPOSAL_TEXT
    assert "정량제안서" in PROPOSAL_TEXT
    assert "확인 필요" in PROPOSAL_TEXT
