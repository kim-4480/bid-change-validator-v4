# Account 5: frontend integration handoff (2026-10-09)

Base branch: `origin/develop` (inspected SHA `03c0d3866185398c45ea8897157908ff2325157a`).

## ML recommendation API (account 4)

Inspected `feat/ml-recommendations-training-20261009` at `76fb714`. Its contract is:

- `POST /api/v1/recommendations/ml` with JSON `{ "company_id": "<UUID>", "limit": 50 }`.
- Response: `model_version`, `dataset_version`, `scoring_source`, `input_sha256`, `fallback_reason`, `note`, `items`.
- Each item: `notice_id`, `title`, `rank`, `relevance_score`, `reason`, `version_number`, `analysis_run_id`, `analysis_version`, `analysis_status`, `qualification_state`, `qualification_reason`, `rule_version`, `is_stale`.
- `scoring_source === "lexical_fallback"` means a keyword-overlap **fallback**, not an ML model. Raw scores are not calibrated probabilities.
- Only configure `NEXT_PUBLIC_ML_RECOMMENDATIONS_PATH=/api/v1/recommendations/ml` after the router is merged, explicitly mounted in the FastAPI app, and deployed. No other path is accepted by the adapter.

**Backend integration blockers:** The inspected `develop` did not mount the account 4 router. Its candidate selection is capped to the latest 150 current notice versions and does not filter expired notices. Account 4 / MASTER must address these before claiming full valid-candidate coverage. No automatic LLM notice analysis is called by the frontend recommendation page.

## Admin API (account 2)

The inspected `develop` had no confirmed authenticated job-list/status/retry or human-label-review contract. The `/admin` page only shows a role-gated, non-operational integration status. It makes **no** administrative mutation requests. Before enabling, obtain endpoint/payload/status/permission/CSRF/idempotency contracts from account 2 and require explicit confirmation before selected reprocessing or approving a label. Frontend gating is not a substitute for backend authorization.

## Test scope

- `pnpm test`: offline schema/pagination/contract checks.
- `pnpm test:e2e`: Playwright local route interception only; not a live Backend, AWS, trained ML, or RAG/Copilot correctness test.
- `pnpm lint`, `pnpm exec tsc --noEmit`, `pnpm build` verify static correctness.
- No AWS resource or deployed service was modified.
