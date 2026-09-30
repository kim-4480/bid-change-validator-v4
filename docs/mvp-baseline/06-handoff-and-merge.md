# 06. Handoff and Merge

현재 작업은 `fix/product-baseline-audit` → [Draft PR #74](https://github.com/gyuniverse-hq/bid-change-validator/pull/74) → `integration/mvp-baseline`이다. 2026-09-08 코드 기준 `87b9a5f`, 아직 merge 전이다. 아래 develop/main 흐름은 향후 팀 승인 절차이며 현재 실행 지시가 아니다. 안전성 PR merge와 Product Baseline Ready는 별도 판단이다.

## 1. Branch model

MVP Integration Baseline 작업 중 `main`과 `develop`은 직접 수정하지 않습니다.

```text
main
└─ develop
   └─ integration/mvp-baseline
      ├─ docs/mvp-baseline-foundation
      ├─ feat/mvp-backend-spine-...
      ├─ feat/mvp-qualification-...
      ├─ feat/mvp-askback-...
      ├─ feat/mvp-revalidation-...
      └─ feat/mvp-frontend-...
```

하위 브랜치 이름은 실제 작업 내용에 맞게 조정할 수 있지만, PR base는 Baseline 완료 전까지 원칙적으로 `integration/mvp-baseline`입니다.

## 2. Integration principle

Baseline branch는 팀원 작업을 대체하는 장기 개발 브랜치가 아니라 **공통 제품 연결 기준선**입니다.

따라서 다음을 지킵니다.

- 다른 담당자의 내부 구현을 이유 없이 대규모 재작성하지 않는다.
- 연결에 필요한 최소 adapter/contract를 우선한다.
- 공통 contract 변경은 관련 담당자가 바로 알 수 있게 PR에 명시한다.
- 이미 동작하는 경로를 새 추상화 때문에 깨뜨리지 않는다.
- Baseline에 들어온 코드는 담당자가 이후 자유롭게 고도화할 수 있어야 한다.

## 3. Domain handoff

### Frontend handoff

필수 전달 내용:

- 사용하는 API endpoint
- Request/Response sample
- Status mapping
- loading / empty / error 상태
- Evidence 원문 이동 방식
- Ask-back 입력 contract
- 변경 전/후 표시 데이터

Baseline 기대 결과:

```text
공고 선택
→ 회사 프로필
→ 참가자격 판정
→ 원문 근거
→ 확인 필요 답변
→ 변경공고 영향
```

### Backend / DB handoff

필수 전달 내용:

- DB migration/model 변경
- stable ID와 foreign key 관계
- API endpoint / schema
- document/source ownership
- persistence lifecycle
- transaction / idempotency 고려사항
- 로컬 실행 및 seed/fixture 방법

Baseline 기대 결과:

```text
Notice/Version/Document
+ Company Profile
+ Requirement/Evidence
+ Judgment/Answer
+ Revalidation state
```

가 하나의 trace로 이어져야 합니다.

### LLM / RAG handoff

필수 전달 내용:

- AI input/output contract version
- 지원 Requirement Type
- Evidence provenance 규칙
- model/provider 설정
- deterministic normalization 경계
- diagnostic / failure behavior
- evaluation fixture와 실행법

Baseline 기대 결과:

```text
Backend extracted blocks
→ RequirementAnalysisResult
```

경계가 안정적이어야 하며 Backend DB를 AI 내부에서 직접 소유하지 않습니다.

### Judgment / Guardrail handoff

필수 전달 내용:

- Requirement type별 비교 규칙
- Company Profile mapping
- `SATISFIED / UNSATISFIED / UNKNOWN` 조건
- reason_code
- Answer basis 처리
- unsupported/insufficient-data 처리
- rule version

## 4. PR requirements into baseline

각 하위 작업 PR에는 최소 다음을 포함합니다.

### What changed

- 어떤 Baseline 구간을 연결했는지

### Contract impact

- API / Schema / Status / ID가 바뀌었는지

### How to verify

- 실행 명령
- 테스트 명령
- Golden Scenario에서 확인할 단계

### Known gaps

- 아직 연결되지 않은 부분
- 임시 adapter/mock 여부

### Ownership

- 이후 어느 담당자가 고도화하기 쉬운지

## 5. Merge rule

Baseline 개발 중:

```text
feature/docs branch
→ PR
→ base: integration/mvp-baseline
→ review / test
→ merge
```

Baseline 완성 후:

```text
integration/mvp-baseline
→ PR to develop
→ 전체 통합 검증
→ merge

개발 안정화 후

develop
→ PR to main
→ release 검증
→ merge
```

`integration/mvp-baseline`에서 바로 `main`으로 건너뛰지 않습니다.

## 6. Merge checklist

- [ ] PR base가 `integration/mvp-baseline`인지 확인
- [ ] unrelated file 변경이 없는지 확인
- [ ] contract 변경 여부 표시
- [ ] migration 필요 여부 표시
- [ ] test/verification 결과 표시
- [ ] 기존 Notice/Document/Profile 흐름 regression 없음
- [ ] Evidence trace 유지
- [ ] UNKNOWN/FAILURE guardrail 유지
- [ ] Golden Path의 어느 단계를 완료했는지 표시

## 7. Conflict resolution order

병렬작업 중 충돌이 생기면 다음 순서로 해결합니다.

1. stable Backend source identity 보존
2. Canonical contract 의미 보존
3. 기존 실제 동작 regression 방지
4. adapter로 연결 가능한지 검토
5. 필요하면 contract 변경을 명시적으로 합의

단순히 최신 commit이라는 이유만으로 한쪽 구현을 덮어쓰지 않습니다.

## 8. Handoff completion definition

담당자가 다음 질문에 답할 수 있으면 Handoff가 완료된 것으로 봅니다.

- 내가 어느 입력을 받는가?
- 어떤 stable ID를 신뢰하는가?
- 어떤 출력을 다음 파트에 주는가?
- 실패/정보부족일 때 어떤 상태를 주는가?
- 근거를 어떻게 추적하는가?
- 로컬에서 어떻게 재현하는가?
- Golden Path의 어느 단계를 책임지는가?

## 9. Final team review

Baseline이 Golden Path를 통과하면 팀 공유 시 다음 세 가지를 중심으로 리뷰합니다.

1. 실제로 전체 흐름이 연결됐는가
2. 담당별 고도화 시 Contract가 충분히 명확한가
3. develop에 올려도 기존 기능을 깨뜨리지 않는가

이 리뷰가 끝난 뒤에만 `integration/mvp-baseline → develop` PR을 진행합니다.

## 10. PR #74 merge 이후 Demo / Golden 갱신 절차

기존 AnalysisRun은 새 validation 정책을 자동 충족하지 않는다. `ai-analysis-v0.2`가 같거나 기존 SUCCEEDED여도 새 grounding/상동 guard 적용 증거가 아니다. 자동 cache 무효화/재분석 migration은 미구현이며 Rule 재판정만으로는 부족하다.

1. merge된 코드/commit을 확인하고 Backend 코드 변경 후 API 이미지를 rebuild한다. 단순 restart로는 코드가 반영되지 않는다.

   ```bash
   docker compose up -d --build api
   ```

2. API 기동을 확인하고 기존 Demo/Golden Case의 company, baseline/current NoticeVersion, 문서 ID와 file/text SHA를 기록한다. 과거 run/원본은 보존한다.
3. baseline/current 각각 qualification-analysis POST로 **full re-analysis**를 실행한다. 목록의 과거 캐시를 다시 선택하는 것으로 대체하지 않는다. 새 run ID, status, diagnostic, Requirement/Evidence와 원문 전체 인용을 확인한다.
4. 새 분석으로 `qualification-rules-v0.2` 판정을 생성한다. 재검증에 사용할 source baseline judgment는 동일 profile snapshot/reference_date/rule이어야 한다. profile이 바뀌면 full re-judgment가 먼저다.
5. 최신 질문 중 ASKABLE만 Policy A로 답변하고 새 source/result ID를 기록한다. 과거 답변을 무조건 재사용하거나 Company Profile에 승격하지 않는다.
6. meaningful 실제 자격변경 원문 쌍에서 Diff/revalidation을 실행하고 변경 전후 Evidence와 영향을 받은 key를 대조한다. FAILED/빈 결과 두 개를 성공으로 계산하지 않는다.
7. 01~07 클릭 E2E와 [G0/G1/G2 기준](05-e2e-golden-path.md)을 재검증한 뒤 팀 reviewer가 Ready 여부를 결정한다. G2 미확보 상태에서는 보류를 유지한다.

구체적인 담당별 P1/P2는 [현재 Handoff](08-team-handoff-current-state.md)를 따른다. 이 문서 업데이트 자체는 DB 재분석이나 Docker rebuild를 실행한 기록이 아니다.
