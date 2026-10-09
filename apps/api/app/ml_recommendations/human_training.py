"""Train/evaluate only genuinely reviewed company-notice pairs in isolated local environments.

This workflow cannot manufacture labels, approve a model or deploy to AWS.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
from datetime import datetime
from collections import defaultdict

import numpy as np

from .dataset import audit
from .trainer import grouped, rank_metrics, baseline_score, lgb_fit, lgb_score, deep_fit, deep_scorer, load_deep
from .champion import choose_champion
from .registry import file_sha256


def load_verified_reviews(reviewed_path, source_manifest, validation_report):
    reviewed_path = Path(reviewed_path)
    source_manifest = Path(source_manifest)
    validation_report = Path(validation_report)
    original = json.loads(source_manifest.read_text(encoding="utf-8"))
    validation = json.loads(validation_report.read_text(encoding="utf-8"))
    digest = file_sha256(reviewed_path)
    if digest != validation.get("sha256") or validation.get("evaluation_permitted") is not True:
        raise ValueError("Reviewed labels are missing verified human holdout provenance")
    if validation.get("source_dataset_sha256") != original.get("sha256", {}).get("company_notice_pairs.jsonl"):
        raise ValueError("Review source dataset checksum mismatch")
    if not original.get("valid_company_family_holdout"):
        raise ValueError("No independent company/notice family holdout")
    rows = [json.loads(x) for x in reviewed_path.read_text(encoding="utf-8").splitlines() if x.strip()]
    if not rows or any(
        row.get("label_source") != "human_reviewed"
        or not isinstance(row.get("label"), int)
        or isinstance(row.get("label"), bool)
        or not (0 <= row["label"] <= 3)
        or not row.get("reviewer_id")
        or len(row.get("rationale", "")) < 10
        for row in rows
    ):
        raise ValueError("Unreviewed/invalid labels cannot be evaluated")
    if len({row["pair_id"] for row in rows}) != len(rows):
        raise ValueError("Duplicate reviewed pairs")
    check = audit(rows)
    if not check["passed"]:
        raise ValueError("Company/family leakage: " + str(check))
    parts = {split: [r for r in rows if r["split"] == split]
             for split in ("train", "validation", "test")}
    if any(not rs for rs in parts.values()):
        raise ValueError("All chronological partitions need human reviews")
    for split, group in parts.items():
        if not any(r["label"] >= 2 for r in group):
            raise ValueError("No relevant reviewed positives in " + split)
    if any(r["split"] not in parts for r in rows):
        raise ValueError("Unallocated review_only labels cannot enter holdout")
    for a, b in (("train", "validation"), ("train", "test"), ("validation", "test")):
        for name in ("company_id", "candidate_family_id"):
            if {r[name] for r in parts[a]} & {r[name] for r in parts[b]}:
                raise ValueError(name + " leaked across " + a + "/" + b)
    def timestamp(row):
        stamp = row.get("posted_at")
        if not stamp:
            raise ValueError("Missing posting timestamp invalidates chronological holdout")
        dt = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            raise ValueError("Posting timestamp requires timezone")
        return dt.timestamp()
    if max(map(timestamp, parts["train"])) > min(map(timestamp, parts["validation"])):
        raise ValueError("Training/validation temporal leakage")
    if max(map(timestamp, parts["validation"])) > min(map(timestamp, parts["test"])):
        raise ValueError("Validation/test temporal leakage")
    return rows, original, validation, check


def run_training(reviewed_path, source_manifest, validation_report, out,
                 *, seed=42, epochs=2, device="cpu", train_encoders=False,
                 track_mlflow=False):
    rows, original, validation, leakage = load_verified_reviews(
        reviewed_path, source_manifest, validation_report
    )
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    random.seed(seed)
    np.random.seed(seed)
    model, curve = lgb_fit(rows, out, seed)
    tests = grouped(rows, "test")
    # Real business relevance labels: 2/3 count as relevant, 0/1 do not.
    def relevance_metrics(scorer):
        return rank_metrics(tests, scorer, k=10, min_label=2)
    scores = {
        "baseline_rule": relevance_metrics(baseline_score),
        "lightgbm": relevance_metrics(lambda r: lgb_score(model, r)),
    }
    training = {"lightgbm": {"validation_curve": curve}}
    hashes = {"lightgbm.txt": file_sha256(out / "lightgbm.txt")}
    if train_encoders:
        training["encoders"] = deep_fit(rows, out, seed, device=device, epochs=epochs)
        for name in ("bi_encoder", "cross_encoder"):
            scores[name] = relevance_metrics(deep_scorer(load_deep(out, name), device=device))
            hashes[name + ".pt"] = file_sha256(out / (name + ".pt"))
    code_version = subprocess.run(["git", "rev-parse", "HEAD"],
                                  capture_output=True, text=True, check=False).stdout.strip() or "unavailable"
    reviewed_sha = file_sha256(Path(reviewed_path))
    manifest = {
        "schema": "bidcheck-ml-reviewed-holdout-v1",
        "dataset_version": original["dataset_version"],
        "valid_company_family_holdout": True,
        "label_counts": {"human_reviewed": len(rows)},
        "reviewed_labels_sha256": reviewed_sha,
        "source_dataset_sha256": validation["source_dataset_sha256"],
        "splits": {s: len([r for r in rows if r["split"] == s])
                   for s in ("train", "validation", "test")},
        "seed": seed, "code_version": code_version,
    }
    (out / "reviewed_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8"
    )
    report = {
        "evaluation_scope": "HUMAN_REVIEWED_HOLDOUT",
        "dataset_version": original["dataset_version"],
        "dataset_sha256": validation["source_dataset_sha256"],
        "reviewed_labels_sha256": reviewed_sha,
        "leakage": leakage,
        "seed": seed, "epochs": epochs, "device": device,
        "hyperparameters": {"lightgbm_estimators": 35, "lightgbm_learning_rate": 0.07,
                            "lightgbm_num_leaves": 7},
        "code_version": code_version, "model_sha256": hashes,
        "metrics": scores, "training": training,
        "encoder_status": "PASS" if train_encoders else "NOT_RUN",
        "aws_requests": 0,
    }
    report["champion_decision"] = choose_champion(manifest, scores)
    (out / "evaluation.json").write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8"
    )
    if track_mlflow:
        import mlflow
        uri = "sqlite:///" + (out / "mlflow.db").as_posix()
        mlflow.set_tracking_uri(uri)
        mlflow.set_experiment("BidCheck-v4-human-reviewed")
        with mlflow.start_run(run_name="local-reviewed-ranking") as run:
            mlflow.log_params({
                "dataset_sha256": validation["source_dataset_sha256"],
                "reviewed_labels_sha256": reviewed_sha,
                "code_version": code_version, "seed": seed,
                "epochs": epochs, "device": device, "encoder_training": train_encoders,
                "lightgbm_estimators": 35, "lightgbm_learning_rate": 0.07,
                "lightgbm_num_leaves": 7, "evaluation_scope": "HUMAN_REVIEWED_HOLDOUT",
            })
            for name, metrics in scores.items():
                for key, value in metrics.items():
                    if isinstance(value, (int, float)) and value is not None:
                        mlflow.log_metric(name + "_" + key.replace("@", "_"), value)
            for filename in ("evaluation.json", "reviewed_manifest.json", "lightgbm.txt"):
                mlflow.log_artifact(str(out / filename), artifact_path="offline_artifacts")
            if train_encoders:
                for name in ("bi_encoder.pt", "cross_encoder.pt"):
                    mlflow.log_artifact(str(out / name), artifact_path="offline_artifacts")
            report["mlflow_run_id"] = run.info.run_id
        (out / "evaluation.json").write_text(
            json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8"
        )
    return report


def main():
    parser = argparse.ArgumentParser(description="Local HUMAN-only evaluation; no AWS writes")
    parser.add_argument("--reviewed", required=True)
    parser.add_argument("--source-manifest", required=True)
    parser.add_argument("--validation-report", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--epochs", type=int, default=2)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--train-encoders", action="store_true")
    parser.add_argument("--mlflow-local", action="store_true")
    args = parser.parse_args()
    result = run_training(
        args.reviewed, args.source_manifest, args.validation_report, args.out,
        seed=args.seed, epochs=args.epochs, device=args.device,
        train_encoders=args.train_encoders, track_mlflow=args.mlflow_local
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
