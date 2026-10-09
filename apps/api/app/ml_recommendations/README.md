# BidCheck v4 / Account 4 – ML Recommendations & MLOps

## API contract (integrated in Draft PR #30; not deployed)

POST /api/v1/recommendations/ml
Request: {"company_id":"authorized-company-uuid","limit":20}
Request (without verified eligibility): {"query":"사업 적합도 검색어","limit":20}

Response fields: model_version, dataset_version, scoring_source, fallback_used, fallback_reason, input_sha256, total_valid_candidates, items, needs_review_items.

- items: ONLY deterministically confirmed eligible notices for the authorized company.
- needs_review_items: UNKNOWN / insufficient_data / stale, separately. Query-only requests have no eligible items.
- Ineligible notices never appear in either list.
- Each item includes notice id, current notice version, analysis status/id, rule version, deadline_source and effective_deadline, and reason.
- Relevance score is business relevance, NOT qualification, win probability, or financial advice.
- All current notices are scanned, with bounded SQL batches and qualification batches. Cancelled/expired notices excluded.
- Explicit close time wins. When absent, posted_at + 40 days is the candidate validity proxy and must be visibly marked assumed_40_days. Without posted_at, exclude.
- No LLM analyses, AWS writes, automatic model training, migration, or production deployment.

Draft PR #30 mounts this router in the protected FastAPI app and connects the Frontend to the same-origin API. It also rejects stale qualification analyses when ranking eligible notices. This is local/CI integration, not an AWS deployment or a verified learned-model release.

## Human review, ML training, and MLflow (local machine only)

Run the following from apps/api using an isolated Python 3.12 environment.

1. python -m app.ml_recommendations.real_dataset --help
   Prepare real unlabelled company/notice candidates from read-only LOCAL PostgreSQL.
2. People annotate review_template.csv with grades 0..3, reviewer ID, time with timezone and rationale. No generated/oracle labels.
3. python -m app.ml_recommendations.review --dataset LOCAL_DATASET --reviewed-csv LOCAL_CSV --out LOCAL_REVIEWED.jsonl
   Outputs a verified .validation.json provenance report.
4. python -m app.ml_recommendations.human_training --reviewed LOCAL_REVIEWED.jsonl --source-manifest LOCAL_DATASET/manifest.json --validation-report LOCAL_REVIEWED.jsonl.validation.json --out LOCAL_MODELS --seed 42 --mlflow-local
   Optional: --train-encoders --device cuda, using LOCAL GPU.
5. python -m app.ml_recommendations.search_compare --reviewed LOCAL_REVIEWED.jsonl --source-manifest LOCAL_DATASET/manifest.json --validation-report LOCAL_REVIEWED.jsonl.validation.json --out LOCAL_SEARCH.json
   Optional --dense-model-dir LOCAL_PRE_DOWNLOADED_SENTENCE_TRANSFORMER and --nori-local-url http://127.0.0.1:9200. Nori uses read-only _analyze on LOCALHOST only, no new AWS resources.
6. Inspect human-only nDCG@K, Recall@K, MRR and p50/p95 latency, baseline, LightGBM, optional Bi/Cross Encoder.

MLflow is LOCAL ONLY and records the dataset hash, human label hash, seed, hyperparameters, git SHA, metrics and immutable artifacts. MLflow experimentation does not automatically select Champion.

Manual Champion transition for approved LightGBM or Bi/Cross-Encoder.
For a local approved LightGBM registry, runtime reads BIDCHECK_ML_REGISTRY_DIR.
For an independently approved PyTorch remote worker, configure BIDCHECK_DL_REGISTRY_DIR and BIDCHECK_DL_KIND; the worker checks approval/checksums on every request and advertises champion_approved only when valid. A registry may hold one active model type; use separate registry directories for LightGBM and Encoder.

Manual LightGBM Champion transition:

python -m app.ml_recommendations.registry --registry LOCAL_REGISTRY --model-dir LOCAL_MODELS --approved-by REVIEWER
For approved Encoder candidates, append --kind bi_encoder or --kind cross_encoder.

Requires independently reviewed and leak-free company/family/temporal holdout, >=20 test queries, >=20 reviewed labels, nDCG improvement >0.01 over keyword baseline, non-regressing MRR, and p95 <=200 ms. Uses content-addressed artifacts, checksum verification, atomic champion.json. Runtime reads BIDCHECK_ML_REGISTRY_DIR and safely falls back to lexical on missing/corrupt/unapproved model.

Only isolated experiments may set BIDCHECK_ML_ALLOW_SYNTHETIC=1 or BIDCHECK_ML_ALLOW_UNREGISTERED=1; never set them on AWS.

## Release blockers

- No independently confirmed human-reviewed training/holdout corpus has been provided; real performance metrics and Champion approval remain NOT_RUN.
- AWS deployment and real Browser → API → approved model inference remain unverified. Draft PR #30 covers route registration and Frontend API wiring, but its Playwright tests use API mocks.
- Real-data full-corpus performance, unknown deadline policy, OpenSearch/Nori availability, and model rollout still require validation.
- This PR must not be merged without explicit user approval.
