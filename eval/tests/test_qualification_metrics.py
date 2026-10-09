import pytest
from bideval.qualification_metrics import extraction_prf, verdict_quality, retrieval_recall_at_k


def test_precision_recall_f1_on_verified_fixture():
    result = extraction_prf({"A", "B"}, {"A", "C"}, labels_verified=True)
    assert (result["true_positive"], result["false_positive"], result["false_negative"]) == (1, 1, 1)
    assert result["precision"] == result["recall"] == result["f1"] == 0.5


def test_unreviewed_g2_observation_does_not_generate_fake_f1():
    result = extraction_prf({"G2_region_removed"}, set(), labels_verified=False)
    assert result["f1"] is result["recall"] is result["precision"] is None


def test_no_divisor_does_not_imply_perfect_or_zero_precision():
    result = extraction_prf(set(), set(), labels_verified=True)
    assert result["f1"] is result["recall"] is result["precision"] is None


def test_verdict_metrics_flag_false_positive_and_unknown():
    report = verdict_quality(
        {"A": "SATISFIED", "B": "UNKNOWN", "C": "UNSATISFIED"},
        {"A": "UNSATISFIED", "B": "SATISFIED", "C": "UNSATISFIED"},
        labels_verified=True,
    )
    assert report == {
        "unknown_rate": 1 / 3, "false_satisfied": 1, "false_unsatisfied": 0,
        "missing_predictions": 0, "evaluated": 3,
    }


def test_unreviewed_label_metrics_remain_null():
    report = verdict_quality({"A": "SATISFIED"}, {"A": "UNKNOWN"}, labels_verified=False)
    assert all(value is None for value in report.values())


def test_verified_disjoint_extraction_has_zero_f1():
    result = extraction_prf({"pred"}, {"gold"}, labels_verified=True)
    assert result["precision"] == 0.0
    assert result["recall"] == 0.0
    assert result["f1"] == 0.0


def test_retrieval_recall_at_k_uses_approved_versioned_chunk_ids():
    hits = [("chunk-a", "version-1"), ("chunk-b", "version-1"), ("chunk-c", "version-1")]
    report = retrieval_recall_at_k(hits, {"chunk-b", "chunk-d"}, notice_version_id="version-1",
                                  k=2, labels_verified=True)
    assert report == {"recall_at_k": 0.5, "retrieved_relevant": 1, "relevant": 2}


def test_retrieval_unreviewed_or_empty_truth_never_reports_quality():
    hits = [("chunk-a", "version-1")]
    for verified, gold in ((False, {"chunk-a"}), (True, set())):
        report = retrieval_recall_at_k(hits, gold, notice_version_id="version-1",
                                      k=1, labels_verified=verified)
        assert all(value is None for value in report.values())


@pytest.mark.parametrize("hits", [
    [("chunk-a", "version-1"), ("chunk-b", "version-2")],
    [("chunk-a", "version-1"), ("chunk-a", "version-1")],
    [("", "version-1")],
])
def test_retrieval_refuses_cross_version_duplicate_or_empty_hits(hits):
    with pytest.raises(ValueError):
        retrieval_recall_at_k(hits, {"chunk-a"}, notice_version_id="version-1",
                              k=2, labels_verified=True)
