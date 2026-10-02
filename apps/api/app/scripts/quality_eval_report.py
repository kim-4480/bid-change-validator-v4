"""Report offline fixture quality; synthetic responses are never model scores."""

import argparse
import copy
import json
from pathlib import Path

from bideval.golden.fixtures import load_dataset
from bideval.runner import evaluate_case


def build_report(root: Path, *, synthetic_extraction=False):
    dataset = load_dataset(root)
    reports = []
    for case in dataset.cases:
        extractor = None
        if synthetic_extraction:
            if case.spec.provenance != "synthetic":
                raise ValueError("synthetic extraction only supports synthetic cases")
            def extractor(_system, _body, _schema):
                return {"requirements": copy.deepcopy(case.spec.synthetic_slots)}
        reports.append(evaluate_case(case, structured_extract=extractor))
    return {"dataset_id": dataset.manifest.dataset_id,
            "manifest_sha256": dataset.manifest_sha256,
            "mode": "synthetic-harness-check" if synthetic_extraction else "selection-only",
            "model_quality_claim": False, "cases": reports}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--synthetic-extraction", action="store_true")
    args = parser.parse_args()
    print(json.dumps(build_report(args.dataset, synthetic_extraction=args.synthetic_extraction),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
