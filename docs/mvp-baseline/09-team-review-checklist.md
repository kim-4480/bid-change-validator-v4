# 09. MVP Integration Baseline — Team Review Checklist

> 목적: `integration/mvp-baseline → develop` PR 전 팀이 공통으로 확인할 최종 Review 기준입니다.

현재 snapshot: 2026-09-08, PR #74 코드 `87b9a5f`, Draft/미merge. **Product Baseline Ready 보류**다. 아래 체크박스는 reviewer sign-off 항목이며 테스트 실행 결과와 구분한다. PR #74 안전성 변경 검토가 곧 develop/main merge 승인이나 Ready 선언은 아니다.

## 1. Review decision

이 Review에서 결정할 것은 “모든 기능이 완성됐는가?”가 아닙니다.

다음을 판단합니다.

> **각 담당자가 이후 병렬 고도화할 수 있을 정도로 제품 전체 연결 기준선이 실제로 작동하는가?**

Go 조건:

- 핵심 Golden Path가 실제 제품 경로로 연결됨
- Contract / Status / ID 의미가 명확함
- fresh DB migration + regression CI 통과
- 담당별 Handoff가 가능함
- 남은 기능이 명시적 Known Gap으로 분리됨

---

## 2. G0 합성 회귀 Golden Path

```text
Notice v1 / Company Profile
→ Requirement Analysis
→ Deterministic Judgment
→ REGION / STAFF / PERFORMANCE SATISFIED
→ REGISTRATION UNKNOWN
→ Ask-back yes
→ USER_ANSWER SATISFIED
→ overall eligible
→ Notice v2
→ Canonical Requirement Diff
→ PERFORMANCE_AMOUNT 400M → 600M MODIFIED
→ affected-only Revalidation
→ PERFORMANCE_AMOUNT UNSATISFIED
→ overall ineligible
```

G1은 PARTIAL 2요건/UNKNOWN 2·unsafe 답변 422까지 확인했다. G2는 10건 원문 검산 후에도 meaningful Qualification Diff 미확보다. R26BK01715087은 설명회 안내/시간 변경뿐이고 RFP가 같아 탈락했다. [상세 결과](05-e2e-golden-path.md)를 따른다.

### Review

- [ ] 위 흐름이 서비스 정의와 일치한다
- [ ] `UNKNOWN`을 LLM 실패나 `UNSATISFIED`와 혼동하지 않는다
- [ ] Ask-back이 전체 분석 재실행 없이 해당 조건만 재판정하는 방향에 동의한다
- [ ] 변경공고는 Canonical Requirement 단위 diff/revalidation하는 방향에 동의한다

---

## 3. Automated verification

PR #74 CI [#58 성공](https://github.com/gyuniverse-hq/bid-change-validator/actions/runs/34178537233), 코드 `87b9a5f` 기준:

```text
PostgreSQL 16
→ Alembic 001 → 009
→ Backend full pytest: 102 passed

Frontend
→ frozen install
→ production build success
```

로컬 별도 검증: Node 회귀 3개, tsc, 수정 파일 oxlint, build 통과. CI는 Node/tsc/수정 파일 lint를 실행하지 않으며 전체 lint는 기존 27개 오류가 있는 non-blocking 단계다.

Golden E2E:

```text
apps/api/tests/test_mvp_golden_e2e.py
```

- [ ] fresh PostgreSQL migration chain 통과 확인
- [ ] Backend full regression 통과 확인
- [ ] Golden E2E 통과 확인
- [ ] Frontend production build 통과 확인
- [ ] 기존 Frontend lint debt는 현재 baseline blocker가 아니라 별도 개선 항목으로 관리하는 데 동의

---

# Frontend Review

## 4. Frontend reviewer checklist

현재 01~07 화면 및 02~06 공유 Case 구현:

```text
/qualification
apps/web/lib/qualification-api.ts
```

- [ ] 01~07 화면과 동일 Case 탭 이동/현재 analysis·rule 결과 연결을 재검증했다
- [ ] `SATISFIED / UNSATISFIED / UNKNOWN`을 UI 상태로 충분히 표현할 수 있다
- [ ] `eligible / ineligible / insufficient_data` 종합 상태가 UI 요구와 맞는다
- [ ] Ask-back API가 필요한 입력 UX를 지원한다
- [ ] 변경공고 `UNCHANGED / MODIFIED / ADDED / REMOVED`를 화면에 표현할 수 있다
- [ ] Figma 7개 화면을 Product IA Source of Truth로 유지한다

### Frontend Known Gap

- [ ] Evidence 모바일/키보드·자동 스크롤 검증
- [ ] 프로필 갱신 후 역사판정/현재 회사값 표시 검증
- [ ] 전체 lint debt 정리
- [ ] Proposal RAG 결과 UI

우선순위와 완료 기준을 팀이 확인합니다. 현재 화면 연결은 완료했지만 전체 실제 제품 E2E는 별도 gate입니다.

---

# Backend / DB Review

## 5. Backend reviewer checklist

핵심 lineage:

```text
Notice → Version → Document → extracted_blocks
Company
PreflightCase
AnalysisRun → Requirement / Evidence
JudgmentRun → Judgment
Answer → source/result Judgment
RevalidationRun → baseline/current Analysis + source/result Judgment
```

- [ ] ID / FK 관계가 향후 API 고도화에 충분하다
- [ ] `extracted_blocks`를 AI input Source of Truth로 유지하는 데 동의한다
- [ ] migration `006~009` 역할이 명확하다
- [ ] baseline/current Version을 같은 PreflightCase에서 추적하는 구조가 적절하다
- [ ] Profile completeness로 UNKNOWN을 구분하는 정책이 안전하다
- [ ] Profile 변경 시 affected-only revalidation을 거부하는 guard가 적절하다

### Backend / DB Known Gap

- [ ] idempotency / duplicate run 정책
- [ ] USER_ANSWER → Profile 승격 provenance
- [ ] retry / async job orchestration
- [ ] production auth / authorization
- [ ] observability / audit

위 항목이 develop merge blocker인지 이후 운영성 고도화인지 구분합니다.

---

# LLM / RAG Review

## 6. LLM / RAG reviewer checklist

현재 AI boundary:

```text
extracted_blocks
→ chunking
→ requirement extraction
→ guardrail
→ deterministic normalization
→ Canonical Requirement + Evidence
→ AnalysisResult
```

- [ ] Canonical Requirement 8종이 현재 MVP 자격판정 범위를 충분히 커버한다
- [ ] LLM은 source-grounded extraction에 집중하고 Judgment는 deterministic code로 분리하는 방향에 동의한다
- [ ] Evidence provenance contract가 후속 Eval에 사용 가능하다
- [ ] `SUCCEEDED / PARTIAL / FAILED`와 Judgment 상태 분리가 적절하다
- [ ] unsupported/ambiguous requirement를 억지 판정하지 않는 방향에 동의한다

### LLM / RAG Known Gap

- [ ] 실제 OpenAI E2E
- [ ] 실공고 extraction 품질 평가
- [ ] Precision / Recall / Evidence grounding 평가
- [ ] Proposal RAG
- [ ] stable semantic requirement identity 고도화

특히 **Stage 9 Golden E2E는 모델 품질 평가가 아니라 제품 integration regression**임을 공통 인식합니다.

---

# Contract Review

## 7. Canonical Requirement 8 types

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

- [ ] 현재 8종을 Baseline contract로 채택
- [ ] 확장이 필요하면 기존 의미를 깨지 않고 명시적 contract version으로 변경

## 8. Status layers

### AI execution

```text
SUCCEEDED / PARTIAL / FAILED
```

### Requirement judgment

```text
SATISFIED / UNSATISFIED / UNKNOWN
```

### Overall product

```text
eligible / ineligible / insufficient_data
```

### Change diff

```text
UNCHANGED / MODIFIED / ADDED / REMOVED
```

- [ ] 네 상태 계층을 서로 섞지 않는 데 동의

---

# Known Gap Review

## 9. Blocker와 후속 backlog 구분

Ready blocker는 meaningful 실제 G2 미확보, 실공고 추출 완전성 부족, safe-answer부터 변경공고까지 전체 E2E 미완료입니다. 이를 자동 non-blocker로 분류하지 않습니다. 다음은 추가 검토할 backlog입니다.

- 실제 OpenAI / 실공고 Quality Eval
- Proposal RAG / 제안서 대응 누락검사
- 명시적 provenance를 갖춘 Policy B (현재 Policy A 유지)
- Evidence 모바일/키보드 최종 UX
- Frontend lint debt
- Production auth
- Retry / queue / observability
- 배포 환경 E2E

각 항목에 대해 팀 Review에서 다음 중 하나를 선택합니다.

```text
A. develop merge blocker
B. 병렬 고도화 backlog
C. MVP scope 밖
```

안전·실행 불가능 문제가 아니라면 자동으로 범위에서 제거하지 않고 팀이 결정합니다.

---

# Develop PR Gate

## 10. Required before `integration/mvp-baseline → develop`

- [ ] PR #74 이후 적용 코드 CI green
- [ ] Backend 코드 반영 시 `docker compose up -d --build api` 수행
- [ ] 기존 Demo/Golden baseline/current full re-analysis 및 새 run/근거 검증 (기존 AnalysisRun의 자동 validation 충족을 가정하지 않음)
- [ ] 실제 meaningful G2와 safe-answer 포함 전체 E2E 확보
- [ ] Evaluation 전용 extraction 미완료와 기존 Proposal 기능의 별도 범위를 확인
- [ ] Handoff snapshot review
- [ ] Frontend reviewer 확인
- [ ] Backend / DB reviewer 확인
- [ ] LLM / RAG reviewer 확인
- [ ] Contract blocker 없음
- [ ] develop merge blocker로 분류된 Known Gap 처리 또는 명시적 합의
- [ ] main / develop에 직접 커밋하지 않았음

## 11. Go / No-Go record

### Go

```text
integration/mvp-baseline이 공통 제품 기준선으로 충분하다.
각 담당자가 Contract를 유지하면서 병렬 고도화할 수 있다.
→ develop PR 진행
```

### Conditional Go

```text
Baseline은 유효하지만 develop merge 전에 해결할 blocker가 소수 존재한다.
→ blocker 명시 후 해결 → develop PR
```

### No-Go

```text
핵심 Golden Path / Contract / persistence lineage 중 하나가 실제로 연결되지 않았다.
→ 해당 Stage로 돌아가 수정
```

---

## 12. Review output

팀 Review가 끝나면 최소 아래를 남깁니다.

```text
Decision: GO / CONDITIONAL GO / NO-GO
Blockers: ...
Parallel backlog: ...
Owner: ...
Next: integration/mvp-baseline → develop PR 여부
```

이 결과와 [merge 후 재분석 절차](06-handoff-and-merge.md)를 기준으로 다음 통합 여부를 결정합니다.
