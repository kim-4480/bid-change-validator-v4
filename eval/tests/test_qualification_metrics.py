from bideval.qualification_metrics import extraction_prf, verdict_quality


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
