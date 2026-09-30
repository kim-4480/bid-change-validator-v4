import hashlib
import json
import shutil
from pathlib import Path

import pytest

from bideval.golden.fixtures import load_dataset

ROOT = Path(__file__).resolve().parents[2] / "eval/golden/qualification-quality-v0.1"


@pytest.fixture
def dataset_dir(tmp_path):
    shutil.copytree(ROOT, tmp_path, dirs_exist_ok=True)
    return tmp_path


def update(root, name, change):
    path = root / name
    payload = json.loads(path.read_text(encoding="utf-8"))
    change(payload)
    data = json.dumps(payload, ensure_ascii=False).encode()
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def test_load_pins_provenance_and_keeps_original_hash_null():
    case = load_dataset(ROOT).cases[0]
    assert case.spec.provenance == "synthetic"
    assert case.analysis_input.documents[0].file_sha256 is None
    assert len(case.spans) == 2


def test_corrupted_file_is_rejected(dataset_dir):
    (dataset_dir / "labels/synthetic.json").write_text("{}")
    with pytest.raises(ValueError, match="hash mismatch"):
        load_dataset(dataset_dir)


@pytest.mark.parametrize("kind", ["version", "document", "quote", "duplicate_span"])
def test_invalid_label_links_even_with_updated_hash(dataset_dir, kind):
    def change(payload):
        if kind == "version":
            payload["notice_version_id"] = "wrong-version"
        elif kind == "duplicate_span":
            payload["spans"].append(payload["spans"][0])
        else:
            payload["spans"][0]["document_id" if kind == "document" else "quote"] = "missing"
    sha = update(dataset_dir, "labels/synthetic.json", change)
    update(dataset_dir, "manifest.json", lambda m: m["cases"][0]["labels"].update(sha256=sha))
    with pytest.raises(ValueError):
        load_dataset(dataset_dir)


@pytest.mark.parametrize("kind", ["case", "document", "escape"])
def test_duplicate_ids_and_path_escape(dataset_dir, kind):
    def change(m):
        if kind == "case":
            m["cases"].append(m["cases"][0])
        elif kind == "document":
            m["cases"][0]["documents"].append(m["cases"][0]["documents"][0])
        else:
            m["cases"][0]["labels"]["path"] = "../outside.json"
    update(dataset_dir, "manifest.json", change)
    with pytest.raises(ValueError):
        load_dataset(dataset_dir)
