"""Storage integrity tests; no quality_eval execution or semantic label claims."""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from bideval.validate_real_golden_dataset import validate_dataset


DATASET = Path(__file__).resolve().parents[2] / "eval/golden/qualification-real-v0.1"


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def reseal(root):
    """Refresh envelopes so negative tests exercise content rules, not stale hashes."""
    manifest = json.loads((root / "manifest.json").read_bytes())
    for ref in manifest["cases"]:
        case_path = root / ref["path"]
        case = json.loads(case_path.read_bytes())
        for observation in case["observations"]:
            observation["sha256"] = hashlib.sha256((root / observation["path"]).read_bytes()).hexdigest()
        write_json(case_path, case)
        ref["sha256"] = hashlib.sha256(case_path.read_bytes()).hexdigest()
    write_json(root / "manifest.json", manifest)
    files = sorted(p for p in root.rglob("*") if p.is_file() and p.name != "checksums.sha256")
    (root / "checksums.sha256").write_text("".join(
        f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(root).as_posix()}\n"
        for p in files), encoding="utf-8")


def test_committed_real_dataset():
    assert validate_dataset(DATASET) == {
        "cases": 5, "documents": 23, "product_cases": 2, "source_cases": 3,
        "ground_truth_labels": 0, "observations": 1, "text_files": 19,
        "blocks_files": 19, "external_originals_verified": 0,
    }


@pytest.mark.parametrize("fault,match", [
    ("source_uuid", "Invalid notice identity"),
    ("product_null", "Invalid notice identity"),
    ("duplicate_doc", "Duplicate document key"),
    ("duplicate_id", "Duplicate document ID"),
    ("wrong_version", "Document version mismatch"),
    ("path_escape", "Path escape"),
    ("windows_path", "Unsafe path"),
    ("missing_file", "Missing file"),
    ("text_hash", "Original text hash mismatch"),
    ("approved", "DRAFT"),
    ("g2_link", "G2 baseline linkage"),
    ("ground_truth", "Extra inputs"),
    ("unreferenced", "Unreferenced file"),
])
def test_rejects_invalid_storage(tmp_path, fault, match):
    root = tmp_path / "dataset"
    shutil.copytree(DATASET, root)
    case_path = root / "cases/G2/case.json"
    if fault == "source_uuid":
        case_path = root / "cases/C01/case.json"
    case = json.loads(case_path.read_bytes())
    doc = case["documents"][0]
    if fault == "source_uuid":
        case["notice_id"] = "9a3ca6d6-52c5-40b0-b236-57f570a93ccf"
    elif fault == "product_null":
        case["notice_id"] = None
    elif fault == "duplicate_doc":
        case["documents"].append(doc.copy())
    elif fault == "duplicate_id":
        case["documents"][1]["document_id"] = doc["document_id"]
        case["documents"][1]["metadata"]["id"] = doc["document_id"]
    elif fault == "wrong_version":
        doc["notice_version_id"] = case["versions"][1]["notice_version_id"]
    elif fault in {"path_escape", "windows_path", "missing_file"}:
        doc["text"]["path"] = {"path_escape": "../outside.txt", "windows_path": "C:\\outside.txt", "missing_file": "absent.txt"}[fault]
    elif fault == "text_hash":
        doc["extracted_text_sha256"] = "0" * 64
    elif fault in {"approved", "ground_truth"}:
        observation_path = root / case["observations"][0]["path"]
        observation = json.loads(observation_path.read_bytes())
        if fault == "approved":
            observation["review_status"] = "APPROVED"
        else:
            observation["expected_change_type"] = "REMOVED"
        write_json(observation_path, observation)
    elif fault == "g2_link":
        source = next(d for d in case["documents"] if d["document_id"] == "c17fc7f6-eca6-4ca0-afef-86efe376a431")
        source["version_key"] = case["versions"][1]["version_key"]
        source["notice_version_id"] = case["versions"][1]["notice_version_id"]
    elif fault == "unreferenced":
        (root / "labels/accidental.json").write_text("{}", encoding="utf-8")
    write_json(case_path, case)
    reseal(root)
    with pytest.raises(ValueError, match=match):
        validate_dataset(root)


def test_rejects_changed_bytes_and_duplicate_cases(tmp_path):
    root = tmp_path / "dataset"
    shutil.copytree(DATASET, root)
    text = next(root.rglob("*.txt"))
    text.write_bytes(text.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="Hash mismatch"):
        validate_dataset(root)
    shutil.copyfile(DATASET / text.relative_to(root), text)
    manifest = json.loads((root / "manifest.json").read_bytes())
    manifest["cases"][1] = manifest["cases"][0].copy()
    write_json(root / "manifest.json", manifest)
    reseal(root)
    with pytest.raises(ValueError, match="Duplicate case ID"):
        validate_dataset(root)
