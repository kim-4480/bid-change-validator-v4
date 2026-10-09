# Account 5: frontend integration handoff (2026-10-09)

Base branch: `origin/develop` (inspected SHA `03c0d3866185398c45ea8897157908ff2325157a`).

## ML recommendation API (account 4)

The combined integration branch uses `feat/ml-recommendations-training-20261009` at `287f9b7` and `feat/frontend-quality-e2e-20261009` at `18d303f`. The Backend contract is:

- `POST /api/v1/recommendations/ml` with JSON `{ "company_id": "<UUID>", "limit": 50 }`.
- Response: `model_version`, `dataset_version`, `scoring_source`, `input_sha256`, `fallback_reason`, `fallback_used`, `total_valid_candidates`, `note`, `items`, `needs_review_items`.
- Each item: `notice_id`, `title`, `rank`, `relevance_score`, `reason`, `version_number`, `analysis_run_id`, `analysis_version`, `analysis_status`, `qualification_state`, `qualification_reason`, `rule_version`, `is_stale`.
- `scoring_source === "lexical_fallback"` means a keyword-overlap **fallback**, not an ML model. Raw scores are not calibrated probabilities.
- The integration branch mounts the router inside the authenticated FastAPI router and uses the fixed same-origin path `/api/v1/recommendations/ml`; no build-time opt-in is needed. `items` contains only verified eligible notices. `needs_review_items` is displayed separately and cannot silently become an eligible recommendation.

**Still to verify after merging the prerequisite PRs:** Deploy the combined Backend and Frontend, configure an approved trained Champion, and run a live API↔UI inference check. Without an approved model, the response must remain clearly labeled `lexical_fallback`. The Backend scans all currently valid notices and excludes cancelled/expired notices; the separate legacy matching list remains capped at 50.

## Admin API (account 2)

The inspected `develop` had no confirmed authenticated job-list/status/retry or human-label-review contract. The `/admin` page only shows a role-gated, non-operational integration status. It makes **no** administrative mutation requests. Before enabling, obtain endpoint/payload/status/permission/CSRF/idempotency contracts from account 2 and require explicit confirmation before selected reprocessing or approving a label. Frontend gating is not a substitute for backend authorization.

## Test scope

- `pnpm test`: offline schema/pagination/contract checks.
- `pnpm test:e2e`: Playwright local route interception only; not a live Backend, AWS, trained ML, or RAG/Copilot correctness test.
- `pnpm lint`, `pnpm exec tsc --noEmit`, `pnpm build` verify static correctness.
- No AWS resource or deployed service was modified.
