# 08. Team Handoff — Current Integration State

> 기준: 2026-09-08, `fix/product-baseline-audit` / PR #74 코드 `87b9a5f` (Draft, merge 전). 이 문서는 설계 원칙이 아니라 **현재 실제 구현 상태와 다음 담당 작업 시작점**을 전달하는 snapshot입니다.

## 담당자별 인계 시작점

README의 기존 역할 배분을 기준으로 연결한다. 새로운 개인별 역할 합의를 가정하지 않는다.

| 팀원 / 기존 역할 | 인계할 다음 작업 |
| --- | --- |
| 황수빈 — Frontend Main | 7개 IA/Case identity 유지, 접근성 lint, profile 변경·역사판정 UX와 전체 클릭 E2E |
| 전진환 — Backend / Overall Structure | AnalysisRun validation/cache 정책, 동시성 검증, merge 후 rebuild·재분석 운영 절차 |
| 정예린 — DB / Data | meaningful G2 실제 원문 쌍 수집, 10건 검산 후 후보 확대·보험 XLSX 확인, version/hash 보존 |
| 김재현·이홍규 — LLM / RAG | 표/예외 문맥·recall 라벨링 회귀, grounding 유지, Evaluation 전용 extraction 후속 연결 |
| 이홍규 — Collaboration / Frontend Sub | PR/CI·문서 동기화와 프런트엔드 보조, 담당자와 G0/G1/G2 재검증 결과 공유 |

Integration Ready 판단은 팀 리뷰로 결정하며 G2 미확보를 완료로 전환하지 않는다.

## 1. Current product baseline

현재 통합 기준선의 핵심 vertical slice는 다음입니다.

```text
나라장터 Notice / Version / Document
→ Backend extracted_blocks
→ Semantic Chunking
→ Requirement Extraction + Guardrail
→ Deterministic Normalization
→ Canonical Requirement 8종 + Evidence
→ Analysis persistence
→ Company Profile deterministic Judgment
→ SATISFIED / UNSATISFIED / UNKNOWN
→ ASKABLE UNKNOWN만 Ask-back
→ USER_ANSWER partial re-judgment
→ Changed Notice Canonical Diff
→ affected-only Revalidation
→ Figma 01~07 Product UI (02~06 shared Case)
```

G0 합성 회귀 흐름(실제 LLM/근거 검증을 대신하지 않음):

```text
v1
REGION / STAFF / PERFORMANCE_AMOUNT = SATISFIED
REGISTRATION = UNKNOWN
→ Ask-back yes
→ REGISTRATION = SATISFIED (USER_ANSWER)
→ overall eligible

v2
PERFORMANCE_AMOUNT 400M → 600M
→ MODIFIED
→ PERFORMANCE_AMOUNT만 재판정
→ UNSATISFIED
→ overall ineligible
```

## 2. Contract / status baseline

### AI execution status

```text
SUCCEEDED / PARTIAL / FAILED
```

문서 분석 실행 자체의 상태입니다. Qualification 판단 결과와 섞지 않습니다.

### Requirement judgment status

```text
SATISFIED / UNSATISFIED / UNKNOWN
```

- `SATISFIED`: 비교 가능한 사실이 조건 충족
- `UNSATISFIED`: 해당 profile 영역이 complete이고 비교 결과 불일치
- `UNKNOWN`: 사실 부족 또는 profile 영역 incomplete

### Product overall status

```text
eligible / ineligible / insufficient_data
```

필수 그룹의 확정 미달은 ineligible, 나머지 UNKNOWN/그룹 부재/분석 비SUCCEEDED는 insufficient_data, 나머지만 eligible입니다. ALL_OF/ANY_OF의 세부 집계는 [04](04-contract-and-status-map.md)를 따릅니다. PARTIAL은 답변 후 자동 eligible이 되지 않습니다. Rule은 `qualification-rules-v0.2`입니다.

### Changed-notice diff

```text
UNCHANGED / MODIFIED / ADDED / REMOVED
```

`MODIFIED` / `ADDED`는 재판정합니다. `UNCHANGED`도 승계할 유효 source record가 없으면 재판정합니다. source analysis/reference_date/rule/profile snapshot과 최신 baseline judgment가 일치해야 합니다.

## 3. Canonical Requirement 8 types

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

현재 GitHub 기준은 8종입니다. 이전 Notion snapshot의 `Canonical 7종`, `feat/llm-rag-integration / PR·Merge 전` 표기는 과거 상태로 봅니다.

---

# Frontend handoff

## 4. Current frontend product

Figma 7개 화면이 Product IA Source of Truth다. `/notices`, `/qualification`, `/ask-back`, `/evidence`, `/evaluation`, `/changes`, `/company`가 연결되어 있고 02~06은 같은 `caseId`를 공유한다. `apps/web/lib/qualification-api.ts`와 `apps/web/lib/case-workspace.ts`를 재사용한다.

현재 analysis/version/company/rule이 일치하는 judgment와 질문을 사용하고, 잘못된 Case는 오류로 남긴다. 7개 화면 navigation smoke와 원문 문서 전환은 확인했다. 전체 실제 G2 클릭 E2E 및 Figma 픽셀 대조 완료를 의미하지 않는다. [화면별 범위](03-screen-system-map.md)를 따른다.

## 5. Frontend API surface

### Company / Case

```text
GET  /api/v1/companies
POST /api/v1/preflight-cases
```

### Requirement Analysis

```text
GET  /api/v1/notices/{notice_id}/versions/{version_number}/qualification-analyses
POST /api/v1/notices/{notice_id}/versions/{version_number}/qualification-analysis
GET  /api/v1/qualification-analyses/{run_id}
```

### Judgment

```text
POST /api/v1/preflight-cases/{case_id}/qualification-judgments
GET  /api/v1/preflight-cases/{case_id}/qualification-judgment-runs
GET  /api/v1/qualification-judgment-runs/{run_id}
```

`analysis_run_id`를 명시하면 해당 PreflightCase의 baseline 또는 current NoticeVersion 분석 결과를 판정할 수 있습니다.

### Ask-back

```text
GET  /api/v1/preflight-cases/{case_id}/qualification-questions
POST /api/v1/preflight-cases/{case_id}/qualification-answers
```

Answer 결과는 `basis_type=USER_ANSWER`로 남고 문서 분석/RAG를 다시 실행하지 않습니다.

### Change Revalidation

```text
POST /api/v1/preflight-cases/{case_id}/qualification-revalidation
```

Response 핵심:

```text
changes[]
revalidated_keys[]
result (new QualificationJudgmentRun)
```

## 6. Frontend next actions

1. P1: 기존 전체 lint 오류 27개(접근성/React Compiler 등)와 profile 갱신 후 현재 회사값/역사판정 표시를 검증한다.
2. P1: 실제 safe-answer와 meaningful G2를 포함한 전체 클릭 E2E를 수행한다.
3. P2: 모바일/키보드, Evidence 자동 스크롤, 역사 차수 링크/요약을 검증한다.

판정→근거→해결, ASKABLE UNKNOWN만 답변, USER_ANSWER/PROFILE 구분을 유지한다. Evaluation 화면은 자격요건 참고자료이며 전용 extraction 미완료를 계속 표시한다.

---

# Backend / DB handoff

## 7. Migration chain

현재 fresh PostgreSQL에서 CI로 검증한 migration chain:

```text
001 company profile
002 bid notices
003 notice document storage
004 document text extraction
005 preflight cases
006 qualification analysis persistence
007 qualification judgment persistence
008 qualification answers
009 qualification revalidation lineage
```

PR #74 CI에서 `alembic upgrade head` 전체 chain이 실제 통과했습니다.

## 8. Main persistence trace

```text
BidNotice
└─ BidNoticeVersion
   └─ NoticeDocument
      └─ extracted_blocks

Company
└─ Staff / StaffRole / Performance / Certification / Industry

PreflightCase
├─ company_id
├─ baseline_version_id
└─ current_version_id

QualificationAnalysisRun
├─ QualificationRequirementRecord
└─ QualificationEvidenceRecord

QualificationJudgmentRun
└─ QualificationJudgmentRecord

QualificationAnswer
└─ source judgment → result judgment

QualificationRevalidationRun
└─ baseline/current analysis + source/result judgment lineage
```

## 9. Backend ownership boundaries

- Low-level document parsing / `extracted_blocks`: Backend Source of Truth
- AI Core는 `extracted_blocks`를 입력으로 사용
- AI 실행 상태와 Judgment 상태는 별도 관리
- Company Profile 값 부재를 곧바로 미달로 해석하지 않음
- Profile completeness가 false이면 필요한 경우 `UNKNOWN`
- Ask-back의 `apply_to_profile=true`는 현재 지원하지 않음
- 변경공고 affected-only Revalidation은 source judgment의 profile snapshot과 현재 profile이 같을 때만 허용
- profile이 달라졌으면 `PROFILE_CHANGED_FULL_REJUDGMENT_REQUIRED`

## 10. Backend / DB / Data next actions

1. Backend P1: 기존 AnalysisRun의 validation revision/cache 무효화 정책을 마련한다. 현재는 자동 충족을 가정하지 않고 [merge 후 full re-analysis](06-handoff-and-merge.md)를 수행한다.
2. Backend P1: 행 잠금·stale 검사 이후 실제 동시성/중복 실행을 검증한다. 순차 회귀 통과를 부하 검증으로 확대 해석하지 않는다.
3. DB/Data blocker: meaningful 지역/업종/실적 등 자격조건이 바뀐 실제 원문 쌍을 확보한다. 10건 후보 검산은 [G2 결과](05-e2e-golden-path.md)를 재사용하고 R26BK01716110 보험 XLSX를 확인한다.
4. Backend P2: Matching 요청/쿼리 수를 측정한 뒤 N+1을 batch로 개선한다.
5. 운영 고도화: auth, observability/retry, 배포 E2E는 별도 검증한다. Policy B는 후속 설계이며 현재 Profile 자동 승격은 금지다.

Backend 코드 변경 후 `docker compose up -d --build api`가 필요하다.

---

# LLM / RAG handoff

## 11. Current AI boundary

```text
Backend extracted_blocks
→ canonical source blocks
→ semantic chunks
→ requirement extraction
→ guardrail
→ deterministic normalization
→ Canonical Requirement + Evidence
→ RequirementAnalysisResult
```

현재 실제 코드가 있는 영역:

```text
apps/api/app/ai/backend_blocks.py
apps/api/app/ai/chunking.py
apps/api/app/ai/requirement_extraction.py
apps/api/app/ai/normalization/
apps/api/app/ai/canonicalize.py
apps/api/app/ai/evidence_adapter.py
apps/api/app/ai/analysis_result.py
apps/api/app/ai/providers/openai.py
```

Judgment는 LLM이 아니라 deterministic code입니다.

```text
apps/api/app/ai/judgment.py
```

Changed-notice diff도 deterministic code입니다.

```text
apps/api/app/ai/requirement_diff.py
```

## 12. LLM / RAG next actions

현재 가장 큰 미구현/고도화 영역은 다음입니다.

### A. Actual model quality evaluation

- 실제 OpenAI E2E
- 실제 나라장터 공고 샘플
- Requirement extraction precision / recall
- Evidence grounding 정확도
- unsupported / ambiguous clause 평가
- abstention / PARTIAL / diagnostic 품질

G0는 합성 제품 연결 회귀입니다. 실제 G1은 PARTIAL 2요건, UNKNOWN 2, unsafe Yes 422를 확인했지만 extraction 품질 완료는 아닙니다. 표/인접 예외/중복 chunk/긴 문서 recall을 실제 라벨링으로 검증해야 합니다.

### B. Proposal RAG

Proposal 업로드·추출·원문 및 기존 문서 검증 기능은 존재하며 dead code로 분류하지 않습니다. 현재 자격판정 workspace와의 Proposal RAG 대응 근거 통합 범위/완료 여부는 별도 검증해야 합니다.

목표 후보:

```text
Canonical Requirement / 제출 요구사항
+
ProposalDocument extracted_blocks
→ retrieval
→ 대응 근거
→ 누락 / 충족 / 확인 필요
```

이 영역은 최종 MVP 범위와 팀 역할을 확인해 병렬 고도화하면 됩니다.

### C. Requirement key stability

현재 Requirement key는 extraction order 영향을 받습니다. Stage 7에서 semantic fallback으로 변경공고 diff 오판을 줄였지만, 장기적으로는 stable semantic identity 전략을 별도 검토할 가치가 있습니다.

---

# Verification / CI handoff

## 13. Automated baseline verification

코드 `87b9a5f` 기준 GitHub Actions [#58 성공](https://github.com/gyuniverse-hq/bid-change-validator/actions/runs/34178537233):

```text
.github/workflows/mvp-integration-baseline.yml
```

Backend gate:

```text
PostgreSQL 16
→ alembic upgrade head
→ pytest apps/api/tests
```

검증 결과:

```text
102 passed
```

Frontend gate:

```text
pnpm install --frozen-lockfile
→ existing lint debt inventory (non-blocking)
→ vinext build (blocking)
```

production build 통과를 확인했습니다. 별도 로컬 검증은 Node 회귀 3개, tsc, 수정 파일 oxlint, build 통과입니다. Node/tsc/수정 파일 lint는 위 CI가 실행하는 항목이 아닙니다. 전체 lint는 기존 27개 오류로 실패하며 CI에서는 non-blocking입니다.

Golden E2E:

```text
apps/api/tests/test_mvp_golden_e2e.py
```

Master Code 테스트는 fresh DB에서도 재현 가능하도록:

```text
apps/api/tests/conftest.py
```

에서 테스트에 필요한 최소 seed를 자체 관리합니다.

## 14. Known gaps / non-goals

Baseline 완성 여부와 별개로 다음은 이후 고도화 대상입니다.

- 실제 OpenAI + 실공고 품질 Eval
- Proposal RAG / 제출서류 누락 검사 제품 연결
- USER_ANSWER → Company Profile 영구 반영
- Evidence 자동 스크롤/모바일·키보드 최종 UX
- Frontend 전체 lint debt
- production auth / authorization
- production observability / retry / job orchestration
- 배포 환경 E2E

이 항목들은 **현재 Qualification integration baseline이 연결됐다는 사실과 분리**해 관리합니다.

## 15. Handoff completion checkpoint

현재 팀원이 다음 기준으로 병렬 고도화를 시작할 수 있습니다.

### Frontend

```text
현재 7개 화면의 identity/Policy A를 유지하고 접근성·전체 E2E 보강
```

### Backend / DB

```text
NoticeVersion / Company / AnalysisRun / JudgmentRun / Answer / RevalidationRun lineage를 신뢰하고 운영성 고도화
```

### LLM / RAG

```text
extracted_blocks → RequirementAnalysisResult contract를 신뢰하고 모델 품질/Eval/Proposal RAG 고도화
```

### Integration

```text
G0 + CI를 회귀 기준으로 사용; merge 후 기존 Demo/Golden full re-analysis, 실제 G1 safe-answer/G2/전체 클릭 검증 후 Ready 재평가
```

현재 Product Baseline Ready는 G2 미확보와 실공고 추출 품질/전체 E2E 미완료로 보류입니다. 아래는 blocker 해소와 팀 Review 이후의 절차이며 현재 merge 승인이 아닙니다:

```text
integration/mvp-baseline
→ PR to develop
→ CI / 통합 검증
→ merge
→ develop → main release review
```
