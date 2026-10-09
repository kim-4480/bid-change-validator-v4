# ML Recommendation ↔ Frontend integration contract — MASTER 2026-10-09

Status: **PROPOSED; accounts 4 and 5 must acknowledge. Not integrated/deployed.** Based on branch heads `76fb714` (ML) and `1a06874` (Frontend), against `develop 03c0d386`.

## Verified breaking mismatch

| Element | Backend (account 4) | Frontend (account 5) |
|---|---|---|
| Route | `POST /api/v1/recommendations/ml` | `GET /api/v1/ml/recommendations?company_id=...` |
| Request | JSON `{company_id?: UUID, query?: string, limit?: 1..50}` | query string `company_id` |
| Response root | `model_version, dataset_version, scoring_source, input_sha256, fallback_reason, note, items` | requires `company_id, items` |
| Item | `notice_id,title,rank,relevance_score,reason,version_number,analysis_run_id,analysis_version,analysis_status,qualification_state,qualification_reason,rule_version,is_stale` | requires `notice_id,bid_notice_no,title,rank,relevance_score,model_version,reasons[],evidence_href?` |
| Registration | Router module exists, **not registered** in `apps/api/app/main.py` | Mock endpoint configured by `NEXT_PUBLIC_ML_RECOMMENDATIONS_PATH` |

The Frontend validator rejects Backend's actual response. Mock E2E does not establish integration.

## Canonical integration decision (minimum-change proposal)

1. **Use the Backend's existing POST endpoint** `/api/v1/recommendations/ml`, JSON `{ "company_id": "<uuid>", "limit": 20 }`, same-origin, under existing API auth/company-access enforcement. Account 4 registers router **once** with the protected API router, and verifies an authenticated call. Account 5 updates client to POST and typed schema matching actual response.
2. Keep `model_version` at the response root (nullable), `reason` singular per item, `version_number` required, `is_stale` explicit. Frontend **must not require** `bid_notice_no`, per-item `model_version`, `reasons[]`, or `evidence_href` until Backend explicitly and safely implements them. No fabricated citation URL.
3. Show separate **relevance score** and **qualification status**. A relevance rank is neither eligibility probability nor win probability; do not claim a calibrated 0–100% score unless verified. Qualification adapter mapping: `eligible`→ELIGIBLE only with valid deterministic evidence, `ineligible`→INELIGIBLE only with valid deterministic evidence, `insufficient_data`/`UNKNOWN`/`stale`→UNKNOWN. Keep raw `qualification_state` available for diagnosis.
4. Server must enforce company isolation, current notice/version, validity/closing-date eligibility, and analysis input lineage before returning eligible/ineligible. Existing `candidates()` only checks `is_current`; **active-only deadline filter remains unverified**. Existing ML `candidates()` selects the latest analysis without checking PR #7 fingerprint; this is **a release blocker** until joined/tested with #7.
5. Before production integration require one real model artifact loaded and exercised by API; distinguish `local_lightgbm`, `local_hf`, `remote_inference`, `lexical_fallback`. Fallback and synthetic-label training are **not** real-data accuracy evidence. Do not trigger LLM qualification analysis except approved Golden/demo notice+version.
6. Include error/empty/loading/no-model/stale tests and authenticated E2E for this same route. No unapproved AWS writes.

## Acceptance tests, owned by accounts 4 and 5

- Request/response contract from a *real* FastAPI TestClient (not a fake frontend response) matches Frontend schema.
- Unauthorized or cross-company request is denied; no-company query does not leak company data.
- Stale/missing analysis and expired notice are not shown as ELIGIBLE or an active recommendation.
- Scores display as relevance only; fallback and model version are clearly visible.
- Real trained-model inference is distinguishable from lexical fallback; no model success claim on unreviewed or synthetic labels.

**Ownership:** account 4 owns `apps/api/app/ml_recommendations/**` and controlled registration; account 5 owns `apps/web/**`. MASTER owns this contract/release gate, not either implementation. Do not resolve cross-account conflicts by silently modifying their files.
