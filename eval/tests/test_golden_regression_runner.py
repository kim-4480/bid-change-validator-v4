import hashlib
import json

import pytest

from run_golden_regression import verify_checksums


def _write_frozen_fixture(tmp_path, *, summary_sha: str) -> None:
    fixture = tmp_path / "fixture_bundle.json"
    baseline = tmp_path / "baseline_993e5cf.json"
    fixture.write_text('{"cases": []}', encoding="utf-8")
    baseline.write_text('{"rows": []}', encoding="utf-8")
    fixture_sha = hashlib.sha256(fixture.read_bytes()).hexdigest()
    baseline_sha = hashlib.sha256(baseline.read_bytes()).hexdigest()
    (tmp_path / "checksums.sha256").write_text(
        f"{fixture_sha} *fixture_bundle.json\n{baseline_sha} *baseline_993e5cf.json\n",
        encoding="utf-8",
    )
    (tmp_path / "summary.json").write_text(
        json.dumps({"fixture_sha256": summary_sha}),
        encoding="utf-8",
    )


def test_frozen_fixture_rejects_a_stale_summary_sha(tmp_path) -> None:
    _write_frozen_fixture(tmp_path, summary_sha="0" * 64)

    with pytest.raises(SystemExit, match="summary.json 의 fixture_sha256"):
        verify_checksums(tmp_path)


def test_frozen_fixture_accepts_matching_checksums_and_summary(tmp_path) -> None:
    fixture = tmp_path / "fixture_bundle.json"
    fixture.write_text('{"cases": []}', encoding="utf-8")
    fixture_sha = hashlib.sha256(fixture.read_bytes()).hexdigest()
    _write_frozen_fixture(tmp_path, summary_sha=fixture_sha)

    verify_checksums(tmp_path)
