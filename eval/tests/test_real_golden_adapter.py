import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from bideval.golden.fixtures import load_dataset
from bideval.golden.spans import GoldenSpan
from bideval.real_adapter import evaluate_real_case, load_real_cases
from bideval.runner import chunk_and_select, evaluate_case
from bideval.scoring import score_case
from bidengine.document.backend_blocks import canonical_source_blocks
from bidengine.document.chunking import chunk_source_blocks
from bidengine.labeling.requirement_extraction import select_eligibility_chunks


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "eval/golden/qualification-real-v0.1"


@pytest.fixture(scope="module")
def cases():
    return load_real_cases(DATA, ("G2", "C04", "C01", "C02", "C03"))


def test_product_versions_preserve_db_identity(cases):
    g2 = [c for c in cases if c.spec.case_id == "G2"]
    assert [str(c.version.notice_version_id) for c in g2] == [
        "f44f265d-f1a3-4463-99ac-399aef98d69b", "c9d11d84-816b-4a95-ae9c-90e73f5de7e7"]
    assert [c.version.version_number for c in g2] == [1, 2]
    assert len(g2[0].documents) == len(g2[1].documents) == 4
    assert {d["document_id"] for d in g2[0].documents}.isdisjoint(d["document_id"] for d in g2[1].documents)
    for c in cases:
        if c.spec.golden_class != "PRODUCT_GOLDEN":
            continue
        assert c.analysis_input.notice_id == str(c.spec.notice_id)
        assert c.analysis_input.notice_version_id == str(c.version.notice_version_id)
        assert [d.document_id for d in c.analysis_input.documents] == [d["document_id"] for d in c.documents]
        assert all(d["notice_version_id"] == str(c.version.notice_version_id) for d in c.documents)


def test_source_mapping_and_selection_has_no_db_id_substitution(cases):
    for c in cases:
        if c.spec.golden_class != "SOURCE_GOLDEN":
            continue
        assert c.analysis_input is None
        assert c.spec.notice_id is c.version.notice_version_id is None
        assert all(d["document_id"] is d["notice_version_id"] is None for d in c.documents)
        report = evaluate_real_case(c)
        assert report["selected_chunks"]
        assert report["notice_id"] is report["notice_version_id"] is None
        keys = {d["document_key"] for d in c.documents}
        for chunk in report["selected_chunks"]:
            assert len({b["document_key"] for b in chunk["source_blocks"]}) == 1
            assert all(b["document_id"] is None and b["document_key"] in keys for b in chunk["source_blocks"])
        assert "dataset:" not in json.dumps(report)


def test_exact_text_blocks_and_hashes_preserved(cases):
    different_join_hash = 0
    for c in cases:
        originals = {d.document_key: d for d in c.spec.documents}
        for d in c.documents:
            original = originals[d["document_key"]]
            assert d["extracted_text"].encode("utf-8") == (DATA / original.text.path).read_bytes()
            assert hashlib.sha256(d["extracted_text"].encode("utf-8")).hexdigest() == d["extracted_text_sha256"] == original.extracted_text_sha256
            assert d["source_file_sha256"] == original.source_file_sha256
            assert d["blocks_file_sha256"] == hashlib.sha256((DATA / original.blocks.path).read_bytes()).hexdigest()
            assert d["extracted_blocks"] == json.loads((DATA / original.blocks.path).read_bytes())
            joined = "\n".join(b["text"] for b in d["extracted_blocks"])
            different_join_hash += hashlib.sha256(joined.encode()).hexdigest() != d["extracted_text_sha256"]
    assert different_join_hash == 20


def test_selection_never_promotes_observations(cases):
    for c in cases:
        report = evaluate_real_case(c)
        assert report["mode"] == "selection-only"
        assert report["extractor_calls"] == report["ground_truth_labels"] == 0
        assert report["model_quality_claim"] is False
        assert report["spans"] == []
        assert report["metrics"]["selection_precision"]["value"] is None
        assert "expected_change_type" not in json.dumps(report)


def test_precision_distinguishes_unlabeled_from_wrong_selection():
    wrong = {"text": "무관한 문장", "source_blocks": [{"document_id": "doc"}]}
    label = GoldenSpan(span_id="p", document_id="doc", span_kind="POSITIVE", quote="참가자격")
    assert score_case([], [wrong], [wrong])["metrics"]["selection_precision"] == {
        "numerator": None, "denominator": None, "value": None, "reason": "no ground truth labels"}
    assert score_case([label], [wrong], [wrong])["metrics"]["selection_precision"] == {
        "numerator": 0, "denominator": 1, "value": 0, "reason": None}
    trap = label.model_copy(update={"span_kind": "TRAP"})
    assert score_case([trap], [wrong], [wrong])["metrics"]["selection_precision"]["value"] == 0


def test_synthetic_selection_and_metrics_match_original_loop():
    dataset = load_dataset(ROOT / "eval/golden/qualification-quality-v0.1")
    for case in dataset.cases:
        blocks_by_doc = [canonical_source_blocks(
            document_id=d.document_id, blocks=d.extracted_blocks,
            file_sha256=d.file_sha256, text_sha256=d.extracted_text_sha256)
            for d in case.analysis_input.documents]
        chunks = []
        for blocks in blocks_by_doc:
            for chunk in chunk_source_blocks(blocks):
                chunks.append({**chunk, "chunk_id": f"CHUNK-{len(chunks):04d}"})
        selected = select_eligibility_chunks(chunks)
        assert chunk_and_select(blocks_by_doc) == (chunks, selected)
        expected = score_case(case.spans, chunks, selected)
        actual = evaluate_case(case)
        assert all(actual[k] == v for k, v in expected.items())
        positives = [s for s in case.spans if s.span_kind == "POSITIVE"]
        count = sum(any(s.document_id in {b["document_id"] for b in c["source_blocks"]}
                        and s.is_in(c["text"]) for s in positives) for c in selected)
        assert actual["metrics"]["selection_precision"]["value"] == count / len(selected)


def test_real_cli_is_offline_and_defaults_to_g1_g2():
    code = '''
import runpy, sys
def deny_network(event, args):
    if event in {"socket.connect", "socket.getaddrinfo"}:
        raise AssertionError("network attempted")
sys.addaudithook(deny_network)
sys.argv = ["real_adapter", "--dataset", "eval/golden/qualification-real-v0.1"]
runpy.run_module("bideval.real_adapter", run_name="__main__")
assert not any("sqlalchemy" in n or "fastapi" in n for n in sys.modules)
'''
    result = subprocess.run([sys.executable, "-B", "-c", code], cwd=ROOT,
                            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    reports = json.loads(result.stdout)
    assert {r["version_key"] for r in reports} == {"G2-v1", "G2-v2", "C01-source-order-000"}


def test_unknown_case_is_rejected():
    with pytest.raises(ValueError, match="Unknown"):
        load_real_cases(DATA, ("G1",))
