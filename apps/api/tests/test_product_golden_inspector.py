from types import SimpleNamespace

from apps.api.app.scripts.product_golden_inspector import find_snippets


def test_find_snippets_groups_product_categories() -> None:
    document = SimpleNamespace(
        id="doc-1",
        name="제안요청서.pdf",
        extracted_text=(
            "입찰참가자격은 서울 소재 업체이며 최근 3년 실적을 보유해야 한다. "
            "제안서 평가는 정량평가와 정성평가로 구성한다. "
            "제출서류에는 사업자등록증과 실적증명서를 포함한다. "
            "계약기간은 착수일로부터 90일이며 변경사항은 별도 공지한다."
        ),
    )

    snippets = find_snippets(version_number=2, document=document, max_per_category=1, radius=30)
    categories = {snippet.category for snippet in snippets}

    assert "qualification" in categories
    assert "evaluation" in categories
    assert "documents" in categories
    assert "contract" in categories
    assert "change" in categories
    assert all(snippet.version_number == 2 for snippet in snippets)
    assert all(snippet.document_name == "제안요청서.pdf" for snippet in snippets)
