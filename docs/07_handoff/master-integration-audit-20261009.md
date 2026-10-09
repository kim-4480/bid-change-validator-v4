# MASTER integration audit — 2026-10-09

Account 1 / MASTER. Base `origin/develop 03c0d3866185398c45ea8897157908ff2325157a`. Existing integration tree `8183ccd` contains changes from many PRs; **do not push/merge its entire history**. No PR Merge or AWS write without explicit user approval.

## Open PR status

| PR | Changed files / dependencies | Latest CI |
|---|---|---|
| #7 | 19; qualification lineage, migration 025, 2 web libs | CI / Copilot / Zone PASS |
| #14 | 5; local PG17 compose, README (overlap #16) | all PASS |
| #15 | 9; Engine/Eval conservative verdict | all PASS |
| #16 | 4; Zone guard becomes advisory; **HOLD / policy weakening** | all PASS |
| #20 | 10; Hybrid Engine/Eval; #21 parent | all PASS |
| #21 | 2; API adapter stacked onto #20 | only Zone guard PASS; full CI NOT_RUN |
| #22 | 3; dynamic image Alembic HEAD schema guard | all PASS |
| #24 | 2; PG17 CI + strict Frontend lint | Backend/Engine/Eval PASS, Frontend FAIL |
| #2 | develop → main separate PR | not in feature sequence |

#16's success does **not** justify disabling ownership enforcement. #24 fails Frontend lint, with unit/build steps skipped. The AWS manual-only build change is **already merged in PR #25** (develop commit `a690f86`). A separately retained branch `f7bda44` is historical work; never create another PR for it.

**Tentative sequence, subject to explicit per-PR approval:** #14 → #22 → #7 → #15 → #20 → #21 (retarget develop after #20) → #24 after account 5 lint fix. #16 HOLD. Confirm branch updates against latest develop and rerun CI after each combination. PR #7's 025 migration never applied to RDS without approval.

## Provisional 22 integration tracks

**Important:** Repository roadmap marks itself Proposed and states that Issues/Projects are the source of truth. The original *official numbered 22-item decision list was not verified*. These 22 rows are **temporary audit tracks, not a replacement for that list**.

| Track | Evidence | State |
|---|---|---|
| 01 Notice/poller | existing collector | AWS NOT_VERIFIED |
| 02 Institution master | independent worktree | WORKTREE |
| 03 PG17 persistence | #14 | OPEN_PR |
| 04 S3 storage | develop AWS code | AWS NOT_VERIFIED |
| 05 AES PDF extraction | merged #12 | DEVELOP |
| 06 HWPX/ZIP | merged #26 | DEVELOP |
| 07 Reprocessing history | pending branch / #7 | PENDING |
| 08 Ingestion stability | merged fixes #23/#25/#26 | DEVELOP |
| 09 Pagination | merged #13 | DEVELOP |
| 10 Fingerprint lineage | #7 (025) | OPEN_PR |
| 11 Safe verdict | #15 | OPEN_PR |
| 12 Analysis coverage | develop migration 024 | DEVELOP |
| 13 Hybrid extraction | #20 | OPEN_PR |
| 14 Version impact plan | #20/#21 | STACKED_PR |
| 15 Qualification UI/API | #7 + frontend | PENDING |
| 16 RAG index quality | engine modules | NOT_VERIFIED |
| 17 Golden/Eval | existing CI + #15 | PARTIAL |
| 18 ML training | ML worktree | WORKTREE |
| 19 ML API inference | unregistered route | BLOCKED |
| 20 Frontend E2E | frontend worktree | WORKTREE |
| 21 PG17/zone CI | #24/#16 | BLOCKED |
| 22 IaC/OTEL/rollback | deploy files; no live verification | NOT_VERIFIED |

**Ownership:** account 4 = `apps/api/app/ml_recommendations/**`, account 5 = `apps/web/**`; accounts 2/3 coordinate shared Backend, DB, extraction and Alembic files with MASTER. Current develop HEAD is Alembic 024; **reserve 025 exclusively for PR #7**, do not independently reuse revision number. ML integration details: [contract](../04_contracts/ml-recommendation-integration-20261009.md).

## AWS evidence

Configuration from Git only: ap-northeast-2 EC2/API/Web, RDS PG17, S3, ECR, SSM. **Not evidence of live state.** AWS CLI absent. boto3 login CRT dependency was initially missing; after installing dependency the read-only auth request was security-blocked. No bypass attempted.

| Live audit | State |
|---|---|
| EC2 deployment SHA vs develop | BLOCKED / unknown |
| RDS schema/select/RLS | BLOCKED / unknown |
| S3 HEAD, ECR tags | BLOCKED / unknown |
| SSM, CloudWatch logs/traces | BLOCKED / unknown |
| Terraform plan/drift | NOT_RUN; CLI missing and state not verified |
| API/worker/model recovery; rollback | NOT_RUN in AWS |
| All-E2E with real ML + UI | NOT_RUN |

Current develop `aws-deploy.yml` is **manual-only** after merged PR #25; the older integration worktree still contains an auto-build/ECR/S3-publish workflow delta. **Never copy that stale integration change back into develop.** Offline audit passes manual AWS gates, and blocks old PG16 / lax lint. Zero AWS mutations performed.

## Approvals and verification

No merges, RDS migration, EC2/SSM restart, ECR/S3 writes, Terraform apply or deployment authorized. Require PR-by-PR explicit approval. Keep #16 blocked, fix #24 lint, establish account 4↔5 same API contract, run isolated PG17/full E2E, prove real model inference versus mock/fallback, resolve active-notice and stale-lineage security.

Local offline commands (zero AWS side effects):
```powershell
py -3.12 -m unittest discover -s scripts/tests -p "test_master_release_audit.py" -v
py -3.12 scripts/master_release_audit.py --json
```
Exit 2 from release audit indicates a real blocked release policy, not a passing run.

## Local test evidence (MASTER branch)

- Release policy checker unit tests: **6 PASS** (stdlib unittest).
- Engine: **555 PASS** with `PYTHONPATH=engine;eval`.
- Eval: **49 PASS** with `PYTHONPATH=engine;eval` and `PYTHONIOENCODING=utf-8`. The initial CP949 run had 48 PASS / 1 UnicodeEncodeError; re-run passed with valid UTF-8.
- Backend DB tests: **NOT_RUN** (no isolated PG17 container prepared in this Worktree). Frontend lint/test/build: **NOT_RUN** (pnpm CLI unavailable here; open PR #24 shows lint FAIL). Full E2E: **NOT_RUN**.
- Offline checker on develop: **4 PASS / 3 BLOCKED** (PG17 Backend CI, strict Frontend lint, Copilot PG17 CI); this is expected until PR #24 is integrated.
- Draft PR creation attempt via GitHub connector: **BLOCKED (403 Resource not accessible by integration)**. Commit and push succeeded; this link is the PR creation page, NOT an opened PR: https://github.com/skn-34-jaehyunkim4480/bid-change-validator-v4/pull/new/docs/master-integration-contract-20261009
