"""Isolated retrieval comparison on *human-reviewed* holdout only.

OpenSearch/Nori is opt-in localhost-only and uses _analyze (read-only).
Dense embeddings require a pre-downloaded local SentenceTransformer model.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
from urllib.parse import urlsplit

from .human_training import load_verified_reviews
from .trainer import grouped, rank_metrics, baseline_score, terms


def bm25_map(groups, *, tokenize=terms):
    output = {}
    for group in groups:
        docs = [tokenize(row["notice_text"]) for row in group]
        lengths = [len(d) for d in docs]
        avgdl = sum(lengths) / max(1, len(lengths))
        freq = Counter(token for doc in docs for token in set(doc))
        tokens = set(tokenize(group[0]["query_text"]))
        n = len(docs)
        for row, doc, dl in zip(group, docs, lengths):
            tf = Counter(doc)
            score = 0.
            for term in tokens:
                f = tf[term]
                if not f:
                    continue
                idf = math.log(1 + (n - freq[term] + .5) / (freq[term] + .5))
                score += idf * f * (1.2 + 1) / (f + 1.2 * (.25 + .75 * dl / max(1, avgdl)))
            output[row["pair_id"]] = score
    return output


def dense_map(groups, model_dir):
    from sentence_transformers import SentenceTransformer
    import numpy as np
    model_dir = Path(model_dir).resolve()
    if not model_dir.is_dir():
        raise ValueError("Dense model must be available locally (no model download)")
    model = SentenceTransformer(str(model_dir), local_files_only=True, device="cpu")
    output = {}
    for group in groups:
        texts = [group[0]["query_text"]] + [r["notice_text"] for r in group]
        embeddings = model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
        for row, emb in zip(group, embeddings[1:]):
            output[row["pair_id"]] = float(np.dot(embeddings[0], emb))
    return output


def rrf_map(groups, maps, k=60):
    combined = defaultdict(float)
    for group in groups:
        for scores in maps:
            ranked = sorted(group, key=lambda row: (-scores[row["pair_id"]], row["notice_id"]))
            for rank, row in enumerate(ranked, 1):
                combined[row["pair_id"]] += 1 / (k + rank)
    return dict(combined)


def _local_nori_map(groups, endpoint):
    parsed = urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("OpenSearch Nori comparison is strictly localhost only")
    import httpx
    cache = {}
    def tokenize(s):
        if s not in cache:
            response = httpx.post(endpoint.rstrip("/") + "/_analyze",
                                  json={"analyzer": "nori", "text": s},
                                  timeout=2, follow_redirects=False)
            response.raise_for_status()
            cache[s] = [token["token"] for token in response.json()["tokens"]]
        return cache[s]
    return bm25_map(groups, tokenize=tokenize)


def compare(reviewed, source_manifest, validation_report, *, dense_model_dir=None,
            nori_local_url=None, k=10):
    rows, manifest, validation, audit = load_verified_reviews(
        reviewed, source_manifest, validation_report
    )
    test = grouped(rows, "test")
    baseline = {row["pair_id"]: baseline_score(row) for g in test for row in g}
    bm25 = bm25_map(test)
    maps = {"sql_keyword": baseline, "bm25": bm25}
    status = {"sql_keyword": "PASS", "bm25": "PASS",
              "dense": "NOT_RUN", "hybrid_rrf": "NOT_RUN", "opensearch_nori": "NOT_RUN"}
    if dense_model_dir:
        maps["dense"] = dense_map(test, dense_model_dir)
        maps["hybrid_rrf"] = rrf_map(test, [bm25, maps["dense"]])
        status["dense"] = status["hybrid_rrf"] = "PASS"
    if nori_local_url:
        maps["opensearch_nori"] = _local_nori_map(test, nori_local_url)
        status["opensearch_nori"] = "PASS"
    scores = {name: rank_metrics(test, lambda row, data=data: data[row["pair_id"]],
                                 k=k, min_label=2)
              for name, data in maps.items()}
    return {
        "evaluation_scope": "HUMAN_REVIEWED_HOLDOUT",
        "source_review_sha256": validation["sha256"],
        "holdout_queries": len(test),
        "metrics": scores, "status": status,
        "notes": {
            "dense": "Needs pre-downloaded local SentenceTransformer" if not dense_model_dir else "",
            "opensearch_nori": "Requires an existing localhost OpenSearch Nori analyzer; no new AWS resources",
            "metric_definition": "grades 2/3 relevant; rank quality is not eligibility probability",
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reviewed", required=True)
    parser.add_argument("--source-manifest", required=True)
    parser.add_argument("--validation-report", required=True)
    parser.add_argument("--dense-model-dir")
    parser.add_argument("--nori-local-url")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    report = compare(args.reviewed, args.source_manifest, args.validation_report,
                     dense_model_dir=args.dense_model_dir, nori_local_url=args.nori_local_url)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
