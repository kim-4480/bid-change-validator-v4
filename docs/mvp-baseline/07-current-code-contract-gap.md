# Stage 2 — Current Code ↔ Contract Gap Audit

> Baseline branch: `integration/mvp-baseline`
> Audit branch: `docs/mvp-contract-gap-audit`
> Audited: 2026-09-07
>
> Purpose: compare the current integrated repository, existing contracts, and the Notion page `LLM & RAG · 파이프라인 & 현재 진행현황` before implementing the MVP Integration Spine.

## 현재 상태 안내 — 과거 audit 보존

아래 본문은 **2026-09-07 Stage 2, Spine 구현 전 이력**이며 현재 미구현 목록으로 사용하지 않는다. 2026-09-08 PR #74 코드 `87b9a5f` 기준 업데이트:

| 과거 gap | 현재 상태 |
| --- | --- |
| Analysis API / Requirement·Evidence DB 미연결 | 구현됨 |
| Judgment / Answer / Revalidation 미연결 | 저장·API·Rule·lineage 구현됨 |
| Frontend reference 연결 필요 | Figma 01~07 route 및 02~06 Case workspace 연결됨 |
| 상태 mapping 미정 | qualification-rules-v0.2의 보수 aggregate 적용 |
| Evaluation | 계약 foundation 존재, 전용 extraction/제품 연결 미완료 |

현재 계약은 [04](04-contract-and-status-map.md), 검증 상태는 [11 audit](11-product-baseline-audit.md)를 따른다. G0 통과, G1 보류 동작 확인, G2 미확보로 Ready는 보류다. 기존 Proposal/문서 검증 기능은 유지되며 아래 과거 gap을 근거로 dead code라고 판단하지 않는다.

## 1. Executive summary

The repository is farther along than the earlier planning snapshot in one area and still intentionally incomplete in another.

### Already connected foundation

- G2B notice collection and normalized notice/version storage
- Notice document download and low-level text/block extraction
- Company Profile CRUD and qualification-relevant profile fields
- Preflight Case linking `company_id`, `baseline_version_id`, and `current_version_id`
- Proposal document upload/storage/extraction
- AI Core from backend `extracted_blocks` through Canonical Requirement + Evidence + `RequirementAnalysisResult`
- Canonical Requirement contract with 8 closed types

### Main missing product connection

The AI Core currently ends as an in-process analysis result. It is not yet exposed as a product-level API/DB workflow.

The missing integration spine is:

```text
NoticeVersion + extracted_blocks
        ↓
Requirement Analysis
        ↓
Requirement / Evidence persistence
        ↓
Company Profile
        ↓
Deterministic Qualification Judgment
        ↓
Judgment persistence / API
        ↓
UNKNOWN → Ask-back
        ↓
Answer → partial re-judgment
        ↓
Changed NoticeVersion
        ↓
Requirement Diff → affected-only Revalidation
```

## 2. Code / Contract status matrix

Legend:

- ✅ Implemented foundation
- 🔗 Implemented pieces exist but product integration is missing
- ❌ Not implemented in the current baseline
- 📝 Contract/document mismatch to reconcile

| Area | Current status | Evidence in current repository | Integration gap |
| --- | --- | --- | --- |
| Company Profile | ✅ / 🔗 | `Company`, Industry, Staff, StaffRole, Performance, PerformanceField, Certification models and CRUD APIs exist | No canonical Profile → Judgment adapter yet |
| Notice collection | ✅ | G2B sync, changed-notice polling, snapshot persistence | Keep as source-of-truth input |
| Notice Version | ✅ | Same notice payload change creates sequential `BidNoticeVersion`; current version flag maintained | Explicit cross-notice reannouncement/relation model is not present |
| Notice document extraction | ✅ | `NoticeDocument.extracted_blocks` and text/file hashes exist | Feed these blocks into AI service path |
| Proposal document input | ✅ | `ProposalDocument` upload/storage/extraction exists | Proposal RAG / compliance comparison not implemented |
| Preflight Case | ✅ / 🔗 | `company_id`, `baseline_version_id`, `current_version_id` already modeled | No analysis/judgment run ownership or results attached yet |
| Semantic Chunking | ✅ | `app/ai/backend_blocks.py`, `chunking.py` | Product service invocation missing |
| Requirement Extraction | ✅ | `requirement_extraction.py`, OpenAI provider, guardrail path | Real service/API invocation and persistence missing |
| Deterministic Normalization | ✅ | `app/ai/normalization/` | No additional gap before persistence |
| Canonical Requirement | ✅ | `QualificationRequirement` contract | Persisted Requirement entity/table missing |
| Evidence | ✅ / 🔗 | Canonical `Evidence`, source locators and hashes implemented | Persisted Evidence entity/table + API response connection missing |
| AI execution status | ✅ | `SUCCEEDED / PARTIAL / FAILED` | Must remain separate from qualification judgment |
| Requirement Judgment contract | ✅ / 🔗 | `Judgment` contract exists with `SATISFIED / UNSATISFIED / UNKNOWN` | Judgment engine, persistence and API are missing |
| Overall UI decision | 📝 | Draft Frontend↔Backend doc uses `eligible / ineligible / needs_review / insufficient_data` | Need explicit aggregation/mapping from requirement-level judgments |
| Ask-back | ❌ | No dedicated model/router/service in current tree | Missing-field question generation, answer storage, profile/user-answer basis, partial re-run required |
| Requirement Diff | ❌ | Baseline/current notice versions are available | No canonical Requirement comparison engine |
| Revalidation | ❌ | Changed version detection foundation exists | No affected-requirement selection or re-judgment workflow |
| AI result API | ❌ | FastAPI currently exposes companies/master-codes/notices/preflight-cases | No qualification/analysis/judgment endpoint in current OpenAPI |
| AI result DB persistence | ❌ | Alembic migrations currently cover company, notice/doc, extraction, preflight case | Requirement/Evidence/AnalysisRun/Judgment/Answer persistence missing |

## 3. Canonical contract baseline

### Requirement types — current code has 8

```text
PERFORMANCE_AMOUNT
PERFORMANCE_COUNT
INDUSTRY
REGION
STAFF
REGISTRATION_CERTIFICATION
EXPERIENCE_FIELD
COMPANY_SIZE
```

This 8-type list in `apps/api/app/ai/contracts.py` is the current code baseline.

### Requirement judgment

```text
SATISFIED
UNSATISFIED
UNKNOWN
```

Interpretation for the MVP baseline:

- `SATISFIED`: profile/user-answer data deterministically satisfies the requirement.
- `UNSATISFIED`: available data deterministically violates the requirement.
- `UNKNOWN`: the requirement is understood but required company/user data is absent or cannot be safely compared.

`UNKNOWN` is the Ask-back trigger. It is not an AI execution failure.

### AI analysis execution

```text
SUCCEEDED
PARTIAL
FAILED
```

These values describe Requirement Analysis execution quality, not company eligibility.

Do not collapse these two state domains.

## 4. Existing draft status mismatch

`docs/contracts/frontend-backend.md` currently suggests overall values:

```text
eligible
ineligible
needs_review
insufficient_data
```

These are useful UI/API aggregate states, but they are not replacements for the canonical requirement-level Judgment values.

Recommended layering:

```text
Analysis execution
SUCCEEDED / PARTIAL / FAILED
          ↓
Requirement judgments
SATISFIED / UNSATISFIED / UNKNOWN
          ↓
Overall API/UI status
eligible / ineligible / needs_review / insufficient_data
```

The exact aggregation rule should be frozen before Frontend integration.

Minimum proposed aggregation for the MVP:

- any required `UNSATISFIED` → `ineligible`
- no `UNSATISFIED` and one or more required `UNKNOWN` → `insufficient_data`
- all required requirements `SATISFIED` → `eligible`
- analysis `PARTIAL`, unsupported requirement, or explicit manual-review diagnostic → `needs_review`
- analysis `FAILED` → analysis error, not a qualification result

## 5. Notice change / revalidation boundary

The current Backend already provides the key versioning foundation:

1. Lookup by `bid_notice_no`.
2. If payload hash is unchanged, reuse the existing version.
3. If payload hash changes, mark the old version non-current.
4. Create the next sequential `BidNoticeVersion`.
5. Preserve `changed_at`, `change_reason`, `is_reannouncement`, raw JSON and documents.

`PreflightCase` can also point to a baseline and current version simultaneously.

Therefore the next implementation should **not** rebuild notice change tracking. It should start from the version pair and add:

```text
baseline Requirement set
        vs
current Requirement set
        ↓
ADDED / REMOVED / MODIFIED / UNCHANGED
        ↓
affected requirement keys
        ↓
re-judge only affected conditions
```

An explicit relation between separate reannouncement notice numbers can be added later if needed; it is not required to prove the same-notice version E2E path.

## 6. Ask-back boundary

Ask-back should originate only from a Requirement-level `UNKNOWN` where the missing comparison input is representable.

Recommended minimum record:

```text
Question
- question_id
- preflight_case_id
- requirement_key
- field / profile_ref target
- prompt
- status: OPEN / ANSWERED

Answer
- question_id
- value
- answered_at
- apply_to_profile: bool
```

After an answer:

```text
Answer
→ convert to USER_ANSWER basis or update Company Profile
→ re-run only the linked requirement
→ preserve previous judgment/run history
```

Do not re-run extraction/RAG for unchanged notice requirements when only company information changed.

## 7. Persistence spine recommended for Stage 4

The smallest useful persistent model is:

```text
AnalysisRun
├─ notice_version_id
├─ status
├─ contract_version
└─ timestamps

QualificationRequirementRecord
├─ analysis_run_id
├─ requirement_key
├─ type/operator/value/scope
└─ raw/confidence

EvidenceRecord
├─ analysis_run_id
├─ evidence_key
├─ document/source identity
├─ location
└─ quote/hash provenance

JudgmentRun
├─ preflight_case_id
├─ company_id
├─ notice_version_id
└─ timestamps

JudgmentRecord
├─ judgment_run_id
├─ requirement_key
├─ status
├─ basis_type
├─ reason_code
└─ profile/evidence refs
```

Ask-back records can follow after the first Judgment Run is persisted.

## 8. Notion snapshot reconciliation

Reference page: `LLM & RAG · 파이프라인 & 현재 진행현황`.

The high-level pipeline remains valid, but several snapshot fields are now stale relative to the integration baseline.

| Notion snapshot | Current code baseline | Reconciliation |
| --- | --- | --- |
| `feat/llm-rag-integration` is current integration branch | AI Core is already present in `integration/mvp-baseline` base commit | 📝 Update Notion status |
| PR / Merge before | Merge commit `118bdb3...` contains the AI Core / canonical contract | 📝 Update Notion status |
| Canonical Requirement 7 types | Current contract has 8, including `COMPANY_SIZE` | 📝 Update Notion contract count |
| Company Profile “basic structure” | CRUD + industries/staff/performance/certification fields already exist | 📝 Mark Backend foundation stronger; AI adapter still missing |
| Qualification Judgment engine missing | Still missing | ✅ Notion direction remains correct |
| Proposal RAG missing | Still missing | ✅ Notion direction remains correct |
| Change Revalidation missing | Still missing | ✅ Notion direction remains correct |
| Ask-back missing | Still missing | ✅ Notion direction remains correct |

The historical `41/41 passed` statement is useful evidence of the AI Core branch verification, but this audit does not claim a fresh test run on the current integration branch.

## 9. Stage 2 conclusion

### Confirmed implemented

- Company Profile data foundation
- Notice / Version / Document foundation
- Proposal upload/extraction foundation
- Preflight Case baseline/current version linkage
- AI Requirement Analysis Core
- Canonical Requirement 8 types
- Evidence contract
- Judgment contract

### Confirmed integration gaps

1. AI Core service invocation from Backend product flow
2. Requirement / Evidence persistence
3. Deterministic Qualification Judgment engine
4. Judgment persistence and API
5. Aggregate Frontend status mapping
6. Ask-back and answer persistence
7. Requirement Diff
8. affected-only Revalidation
9. Proposal RAG / proposal compliance analysis

## 10. Next action

Stage 2 is sufficiently understood to move into the implementation sequence.

Recommended dependency order:

```text
A. Analysis persistence + service boundary
        ↓
B. Judgment engine + Judgment persistence/API
        ↓
C. Ask-back → partial re-judgment
        ↓
D. Requirement Diff → Revalidation
        ↓
E. Frontend qualification/change screens
        ↓
F. Proposal RAG / submission preflight expansion
```

This order uses the code that already exists instead of rebuilding the AI Core or Backend collection foundation.
