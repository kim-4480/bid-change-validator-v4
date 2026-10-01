import pytest


@pytest.fixture(autouse=True)
def _legacy_extraction_by_default(monkeypatch):
    """대부분의 추출 테스트는 legacy 응답 모양을 쓴다. 배포 설정과 무관하게 같게 돈다.

    조항 방식 테스트는 extraction_mode="clause" 를 명시한다.
    """
    monkeypatch.setenv("BIDENGINE_EXTRACTION_MODE", "legacy")
