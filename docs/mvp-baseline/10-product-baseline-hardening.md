# Product Baseline Hardening

기준: 2026-09-08 / PR #74 코드 `87b9a5f`. 아래 안전 정책과 화면 연결은 구현되었으나 실제 G2와 추출 품질/전체 E2E가 부족하여 **Product Baseline Ready는 보류**다. 상세 실행 증거는 [audit](11-product-baseline-audit.md)를 따른다.

## Product definition

The Product Baseline is complete only when the following flow works with traceable data and conservative abstention:

```text
Company Profile
→ G2B notice discovery
→ source document parsing
→ Qualification Requirement extraction
→ Canonical Mapping
→ Evidence provenance
→ deterministic company comparison
→ SATISFIED / UNSATISFIED / UNKNOWN
→ ASKABLE UNKNOWN only → USER_ANSWER
→ affected Requirement partial re-judgment
→ changed notice diff
→ affected-only revalidation
```

LLM/RAG is responsible for document understanding, extraction and evidence grounding. Final qualification status is produced by deterministic rules. Unsupported or ambiguous source clauses must remain diagnostics/UNKNOWN rather than being forced into a supported canonical type.

## Golden Product Scenario

G0/G1/G2 세 검증 축을 유지한다. 합성 회귀 성공과 실제 제품 검증을 합치지 않는다.

### G0 — deterministic regression fixture

`apps/api/tests/test_mvp_golden_e2e.py` is the executable regression contract.

It covers:

- company profile facts: region / staff / performance
- baseline Requirement judgment
- one missing registration fact → UNKNOWN
- Ask-back answer with `apply_to_profile=false`
- `basis_type=USER_ANSWER`
- partial re-judgment
- changed notice Requirement Diff
- MODIFIED-only affected revalidation
- unchanged USER_ANSWER preservation across revalidation

This fixture is synthetic by design so CI is deterministic.

### G1 — actual collected notice reality check

The current local product validation used notice `R26BK01687395` (가덕도신공항 여객터미널 및 부대건물 설계단계 건설사업관리용역) as an extraction/evidence reality check.

Observed before hardening:

- analysis status: `PARTIAL`
- canonical Requirements: 3
- Evidence: 3
- all three mapped as `REGISTRATION_CERTIFICATION`
- multiple `UNMAPPED_REQUIREMENT` diagnostics
- initial judgment: UNKNOWN 3
- Ask-back could turn the three complex clauses into USER_ANSWER judgments

위 3건은 보강 전 이력이다. 현재 검증된 G1은 PARTIAL 2요건/2근거, 최종 Rule의 UNKNOWN 2 / insufficient_data, ASKABLE 0이다. 두 unsafe Yes는 모두 422로 거절했다. 저장 분석은 마지막 상동 guard 이전 실행이며 Rule/Ask-back의 차단을 확인했다. 실제 safe-answer는 실행하지 않았다. G1은 변경공고 Golden이 아니다.

### G2 — actual changed-notice Golden candidate

Run:

```bash
python -m apps.api.app.scripts.select_golden_product_scenario
```

selector 순위는 실제 자격변경을 입증하지 않는다. 실제 후보 10건의 차수별 문서/해시/추출문을 검산했으나 **meaningful Qualification Diff 미확보**다. R26BK01715087은 설명회 미개최 안내와 시간 변경, 동일 RFP 때문에 탈락했다. 나머지도 취소/문서 없음/가격·시간 변화 또는 미추출 XLSX여서 확정하지 못했다. [10건 결과](05-e2e-golden-path.md)를 재사용하며 코드로 변경을 만들어 G2를 대체하지 않는다.

Acceptance criteria for the final actual changed-notice Golden Case:

1. 2+ actual `NoticeVersion` rows.
2. Current and baseline source documents are downloaded and parsed.
3. At least one supported canonical Requirement is unchanged.
4. At least one canonical Requirement is MODIFIED or ADDED.
5. Requirement Diff revalidates only affected keys.
6. Evidence location remains traceable to each source version.

## 구현된 P0 hardening — qualification-rules-v0.2

### Requirement Extraction / Mapping

- Do not reduce joint-contract, representative-conflict, legal exception, negated or other composite clauses to a simple registration/certification fact.
- Prefer `기타요건 → UNMAPPED_REQUIREMENT` over an unsafe canonical mapping.
- Preserve raw source semantics verbatim.
- Expand fallback chunk recall while retaining source-grounding validation.

### Askability Guardrail

`UNKNOWN != ASKABLE`.

ASKABLE is restricted to one user-known fact that can deterministically resolve one canonical Requirement. Complex legal/procedural clauses remain `NOT_ASKABLE` and must be reviewed in Evidence.

Backend enforcement is mandatory: even if a client manually posts an answer for a `NOT_ASKABLE` Requirement, the API must reject it.

### Question semantic preservation

An askable question includes both a readable canonical prompt and the original raw source condition. A short canonical value must never silently replace source semantics.

### USER_ANSWER provenance

Policy A remains the Product Baseline contract:

```text
USER_ANSWER
→ current Case judgment basis only
→ partial re-judgment
→ Company Profile unchanged
→ apply_to_profile=false
```

UI must distinguish `PROFILE` from `USER_ANSWER`; a row must not look as if an empty profile value magically produced SATISFIED/UNSATISFIED.

### Regression

The existing Golden E2E test is the baseline regression for Ask-back partial re-judgment. New Askability unit tests cover unsafe clause classes and question semantic preservation.

## 구현된 화면/Matching과 남은 P1/P2

Figma 7개 화면이 Product IA Source of Truth다. 최초 차수 빈 상태, 02 공고 요약/첨부/위험·미매핑/근거/액션, 07 실적·인증 CRUD, 02~06 같은 Case의 current analysis/judgment 연결이 구현되어 있다. [화면별 검증 범위](03-screen-system-map.md)를 따른다.

Matching은 분석된 현재 공고 후보에 deterministic 회사 비교를 적용한다. 미분석 `조회된 공고`를 매칭 완료로 부르지 않는다. 자동 후보 분석/ranking 확대와 N+1 batch 최적화는 완료로 표시하지 않는다.

- Ready blocker: meaningful 실제 G2, 추출 완전성, safe-answer부터 변경공고까지 전체 클릭 E2E.
- P1 LLM/RAG: 표/주변 예외/중복 chunk/긴 문서 recall, 라벨링 기반 precision/recall 평가.
- P1 Backend: 기존 AnalysisRun validation revision/cache 정책, 실제 동시성 검증.
- P1 Frontend: 기존 전체 lint 27개, profile 변경 후 역사판정/현재 회사값 표시.
- P2: Matching 비용 측정 후 batch, Evaluation 전용 extraction, Policy B, Proposal RAG 제품 통합 범위, 모바일/키보드와 운영 배포 검증.

담당별 시작점은 [팀 Handoff](08-team-handoff-current-state.md)를 따른다. 전체 Backend 102개/Frontend Node 3개 및 타입·수정 파일 lint·build는 코드 `87b9a5f`에서 통과했고 제품 Ready와 별도로 관리한다.

## P2 Evaluation Contract

`apps/api/app/ai/evaluation_contracts.py`에 `EvaluationCriterion` / `EvaluationAnalysisResult` foundation이 존재한다. **Evaluation 전용 extraction/API/제품 연결은 미완료**다. 현재 05는 자격요건 기반 회사 참고자료이며 평가항목/배점 추출 완료로 표시하지 않는다. 점수 예측은 하지 않는다.

기존 Proposal 업로드/추출/문서 검증 기능은 존재하며 dead code로 단정하지 않는다. 해당 기능의 workspace 통합과 제안서 대응 근거 검증은 별도 범위다.

## 기존 Demo / Golden 재분석

전체 raw 및 세부 필드의 source grounding, source-local reference, 복합/상동 guard가 강화되었다. 부분 거절/잘림은 PARTIAL로 남기고 UNKNOWN은 Askability를 따로 판단한다. PARTIAL은 답변 후 자동 eligible이 되지 않으며 필수 그룹의 확정 미달은 ineligible이다.

기존 AnalysisRun은 `ai-analysis-v0.2`/SUCCEEDED여도 새 validation을 자동 충족하지 않는다. PR #74 merge 이후 기존 Demo/Golden baseline/current **full re-analysis**가 필요하다. Backend 변경 후 `docker compose up -d --build api`로 이미지를 반영하고 [운영 절차](06-handoff-and-merge.md)에 따라 새 분석/판정/근거를 검증한다. 자동 cache 무효화는 아직 없다.

## P2 USER_ANSWER → Profile Promotion (Policy B)

Deferred enhancement after Product Baseline stabilization.

Promotion requires a Requirement-type-specific workflow, enough structured fields for the destination Company schema, provenance, user confirmation and evidence handling. A bare yes/no answer must never silently mutate the reusable Company Profile.
