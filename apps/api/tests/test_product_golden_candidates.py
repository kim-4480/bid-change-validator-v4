from apps.api.app.scripts.product_golden_candidates import candidate_score


def test_candidate_score_prioritizes_change_history() -> None:
    single_version = candidate_score(
        version_count=1,
        document_count=10,
        extracted_document_count=10,
        extracted_chars=100_000,
        change_reason_count=0,
    )
    changed_notice = candidate_score(
        version_count=2,
        document_count=2,
        extracted_document_count=2,
        extracted_chars=20_000,
        change_reason_count=1,
    )

    assert changed_notice > single_version


def test_candidate_score_rewards_extracted_documents() -> None:
    no_text = candidate_score(
        version_count=2,
        document_count=3,
        extracted_document_count=0,
        extracted_chars=0,
        change_reason_count=1,
    )
    with_text = candidate_score(
        version_count=2,
        document_count=3,
        extracted_document_count=3,
        extracted_chars=30_000,
        change_reason_count=1,
    )

    assert with_text > no_text
