"""Local, manually approved model registry; never contacts AWS.

MLflow tracks experiments and files. This registry owns an atomic, explicitly
approved runtime pointer so MLflow runs cannot accidentally auto-deploy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from .champion import choose_champion


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def validate_for_promotion(model_dir, *, minimum_queries=20):
    model_dir = Path(model_dir).resolve()
    evaluation = _read(model_dir / "evaluation.json")
    manifest = _read(model_dir / "reviewed_manifest.json")
    if evaluation.get("evaluation_scope") != "HUMAN_REVIEWED_HOLDOUT":
        raise ValueError("Model is not evaluated on human reviewed holdout")
    if evaluation.get("leakage", {}).get("passed") is not True:
        raise ValueError("Leakage audit did not pass")
    if not manifest.get("valid_company_family_holdout"):
        raise ValueError("Company/family/time holdout is not validated")
    if manifest.get("label_counts", {}).get("human_reviewed", 0) < minimum_queries:
        raise ValueError("Insufficient verified human reviewed labels")
    if evaluation.get("reviewed_labels_sha256") != manifest.get("reviewed_labels_sha256"):
        raise ValueError("Reviewed labels checksum mismatch")
    decision = choose_champion(manifest, evaluation.get("metrics", {}),
                               minimum_test_queries=minimum_queries)
    if not decision["deploy_ml"] or decision["champion"] != "lightgbm":
        raise ValueError("LightGBM did not pass human-reviewed Champion criteria: " + decision["reason"])
    model = model_dir / "lightgbm.txt"
    expected = evaluation.get("model_sha256", {}).get("lightgbm.txt")
    if not expected or file_sha256(model) != expected:
        raise ValueError("Model SHA256 mismatch")
    return evaluation, manifest, decision


def _atomic_json(path: Path, content: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix="."+path.name+".", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(content, stream, sort_keys=True, indent=2, ensure_ascii=False)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def register_and_promote(registry_dir, model_dir, *, approved_by: str, minimum_queries=20):
    """Immutable, content-addressed local copy and explicit champion switch."""
    if not approved_by or not approved_by.strip():
        raise ValueError("Human approver required")
    evaluation, manifest, decision = validate_for_promotion(
        model_dir, minimum_queries=minimum_queries
    )
    origin = Path(model_dir).resolve()
    root = Path(registry_dir).resolve()
    digest = evaluation["model_sha256"]["lightgbm.txt"]
    version = "lightgbm-" + digest[:16]
    target = root / "models" / version
    target.mkdir(parents=True, exist_ok=True)
    for filename in ("lightgbm.txt", "evaluation.json", "reviewed_manifest.json"):
        src = origin / filename
        dst = target / filename
        if dst.exists() and file_sha256(dst) != file_sha256(src):
            raise ValueError("Immutable registered model changed: " + filename)
        if not dst.exists():
            shutil.copyfile(src, dst)
    if file_sha256(target / "lightgbm.txt") != digest:
        raise ValueError("Copied model checksum mismatch")
    entry = {
        "schema": "bidcheck-ml-champion-v1",
        "model_version": version, "dataset_version": evaluation["dataset_version"],
        "relative_dir": "models/" + version,
        "model_sha256": digest,
        "evaluation_sha256": file_sha256(target / "evaluation.json"),
        "reviewed_manifest_sha256": file_sha256(target / "reviewed_manifest.json"),
        "approved_by": approved_by.strip(),
        "decision": decision,
    }
    _atomic_json(root / "champion.json", entry)
    return entry


def active_model_dir(registry_dir):
    """Check pointer, file integrity and approval every time; fail closed."""
    root = Path(registry_dir).resolve()
    entry = _read(root / "champion.json")
    relative = entry["relative_dir"]
    target = (root / relative).resolve()
    if not target.is_relative_to(root / "models"):
        raise ValueError("Invalid model registry path")
    if entry.get("decision", {}).get("deploy_ml") is not True:
        raise ValueError("Unapproved model")
    if not entry.get("approved_by"):
        raise ValueError("Missing model approver")
    if (file_sha256(target / "lightgbm.txt") != entry["model_sha256"]
        or file_sha256(target / "evaluation.json") != entry["evaluation_sha256"]
        or file_sha256(target / "reviewed_manifest.json") != entry["reviewed_manifest_sha256"]):
        raise ValueError("Registry artifact integrity mismatch")
    validate_for_promotion(target)
    return target


def main():
    parser = argparse.ArgumentParser(description="Manual local-only Champion approval")
    parser.add_argument("--registry", required=True)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--approved-by", required=True)
    args = parser.parse_args()
    print(json.dumps(register_and_promote(args.registry, args.model_dir,
                                          approved_by=args.approved_by), ensure_ascii=False))


if __name__ == "__main__":
    main()
