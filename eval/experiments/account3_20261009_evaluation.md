Account 3 Evaluation 2026-10-09
Base: 03c0d3866185398c45ea8897157908ff2325157a
Real Golden source dataset: qualification-real-v0.1 (five cases G2/C04/C01/C02/C03)
Approved semantic labels: 0, semantic_labels is empty in manifest.json
Synthetic qualification-quality-v0.1 is NOT real-model performance evidence
Engine suite: 580 PASS
Evaluation suite: 60 PASS
Copilot v3.1 tests: 45 PASS in independent branch
Full API suite: NOT_PASS; missing olefile at collection
Real extraction precision/recall/F1: NOT_MEASURED; no approved truth
Real retrieval Recall@K: NOT_MEASURED; no approved relevance labels
Real Copilot citation accuracy/success: NOT_MEASURED; no reviewed outputs
OpenAI vs GLM: NOT_RUN; no approved model calls
AWS E2E: NOT_RUN; operations restricted
Retrieval metrics refuse unverified labels, duplicate hits, and cross-version hits
Future: approve notice/version/document SHA and human clause relevance labels, then compare section baseline, BM25, Dense, Hybrid RRF and Copilot scenario outcomes
Dependencies: PR15 external author read-only, PR21 follows PR20, Account4 owns ML API contract
No AWS writes, paid LLM calls, or PR merges performed
