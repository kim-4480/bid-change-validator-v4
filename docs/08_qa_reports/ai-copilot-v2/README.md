# AI Copilot v2 개선·평가 기록

이 폴더는 AI Copilot 2차 개선의 **재현 가능한 평가 원본(Source of Truth)** 을 보관합니다.

- Notion `챗봇 2차 개선 정리`: 진행판, 의사결정, 팀 공유용 요약
- 이 GitHub 폴더: 수치·실험 조건·실패 원인·전후 비교의 원본
- 채팅에서 생성되는 다운로드 파일: 전달 편의를 위한 임시 사본

## 기준선

- Repository: `gyuniverse-hq/bid-change-validator`
- E0 기준 commit: `993e5cf446e46c740503ec0840a5996d1f82dfe1`
- 개선 작업 branch: `feature/ai-copilot-e1-ux-baseline`
- Golden Set: `golden_fixtures_v02`, 공고 20건 / 현재 회사 상태 32 / 이전차수 입력 8 / 변경 비교 8
- PR 운영: 중간 PR 없음. 개선·평가·최종 회귀 완료 후 한 번만 `develop` 대상 PR 생성

## 진행 순서

0. 기준선·평가 설계 고정 ✅
1. E0 실행 준비 확인 ✅
2. E0 판정 엔진 Actual ✅
3. E0 Copilot 기준선 측정 ✅
4. E0 실패 유형 분석 ✅
5. E1 UX·응답구조 개선 ✅
6. E1 동일 평가 재측정 ✅
7. E2 자연어 이해·대화 문맥 개선 ✅
8. E2 동일 평가 재측정 ✅
9. E3 근거 기반 RAG 설명 연결 ✅
10. E3·RAG·Prompt 성능 비교 ✅
11. 사용자 관점 Test Case ◀ 현재
12. 최종 회귀·잠금 평가
13. README·발표·데모 정리

## 문서 인덱스

- [`e0-rule-engine-baseline.md`](./e0-rule-engine-baseline.md): 회사 Fixture 40개 / canonical 138행 판정 엔진 기준선
- [`e0-routing-baseline.md`](./e0-routing-baseline.md): 자유입력 100개 라우팅·작업 도달성 기준선
- [`e0-conversation-safety.md`](./e0-conversation-safety.md): I01~I20 대화·안전 시나리오와 E0 실패 유형
- [`e1-routing-remeasurement.md`](./e1-routing-remeasurement.md): E1 제한적 alias 적용 후 동일 100문항 재측정
- [`e1-evaluation-summary.md`](./e1-evaluation-summary.md): E0→E1 동일셋 전후 비교와 I01~I20 재분류
- [`e2-routing-evaluation.md`](./e2-routing-evaluation.md): Semantic Router + 실제 resolver 정책 기반 E2 측정
- [`e3-rag-evaluation.md`](./e3-rag-evaluation.md): Dense/Hybrid/Rerank, Grounded Answer v1~v4, 최종 E3 의사결정
- [`stage11-user-test-plan.md`](./stage11-user-test-plan.md): 사용자 관점 Core 6 + Safety 2 테스트와 관찰 기록 템플릿
- [`stage11-moderator-runbook.md`](./stage11-moderator-runbook.md): P00 환경 검증, Demo seed, 사전 판정 준비, P01~ 실행 절차

## 주요 결과 스냅샷

### Rule Engine Actual

- canonical rows: 138
- draft target exact match: **104/138 = 75.4%**
- safe abstention: **34/138 = 24.6%**
- dangerous determinate error: **0**
- overall state match: **36/40 = 90.0%**

이 수치는 독립 holdout 정확도가 아니라 draft target 대비 고정 판정 엔진 결과다.

### E0 → E1

- 자유입력 intent 일치: **1/100 → 41/100**
- 판정 설명: `0/32 → 32/32`
- 변경 비교: `0/8 → 8/8`
- 대화·안전 완전 성공: **5/20 → 9/20**
- 치명적 안전 위반 후보: **0 유지**

### E2 Semantic Routing

- Semantic-only Run1: `89/100`
- Run2: `98/100`
- Run3: `100/100`
- 실제 제품 resolver 순서 combined v2: **100/100**
- DOCUMENT_QA `60/60`, JUDGMENT_EXPLANATION `32/32`, CHANGE_COMPARISON `8/8`

**주의:** 100/100은 고정 100문항 intent routing 결과다. 답변 정답률, RAG 품질, 사용자 업무 완료율이 아니다.

### E3 Retrieval

- Dense Recall@4: **29.17%**
- Hybrid Recall@4: **50.00%**
- Hybrid + LLM Rerank Recall@4: **55.56%**

제품 기본 retrieval은 **Hybrid**로 잠갔다. Rerank는 품질 향상 대비 추가 모델 호출과 약 2.8초 p50 latency가 커 기본 제품 경로에 채택하지 않았다.

### E3 Grounded Answer v4

- evaluable cases: 59 / scope gap 1
- generation success: **59/59**
- generation failure: **0**
- citation version integrity: **100%**
- citation present: **57/59**
- strict expected-evidence citation recall: **45.83%**
- total latency p50: **2925.77ms**
- total latency p95: **5449.73ms**

45.83%는 답변 정답률이 아니라 frozen expected excerpt와 실제 citation source의 strict matcher 결과다.

Grounded Answer 안전 계약:

- 질문 핵심을 직접 뒷받침하는 SOURCE만 citation
- 근거가 없으면 abstain / 억지 citation 금지
- 일부 근거만 있으면 전체 결론 금지
- 문서 충돌은 차이를 표시하고 임의 우선순위 금지
- 회사 실제 참가 가능/불가를 LLM이 독자 판정하지 않음
- SOURCE의 깨진 코드·자릿수·날짜·금액을 임의 복원하지 않음

최신 관련 회귀: **251 passed / 1 non-blocking deprecation warning**.

## 현재 단계 — Stage 11

현재는 자동 평가 점수를 더 올리는 단계가 아니라 실제 사용성을 검증한다.

먼저 [`stage11-moderator-runbook.md`](./stage11-moderator-runbook.md)로 **P00 Moderator Dry-run**을 수행해 Demo Case/저장 판정/UI를 검증한다. P00은 사용자 완료율에 포함하지 않는다.

이후 [`stage11-user-test-plan.md`](./stage11-user-test-plan.md)의 Core 6개와 Safety 2개를 사용해 다음을 기록한다.

- 과업 PASS / PARTIAL / FAIL
- CRITICAL safety issue
- 완료시간
- 힌트 수
- 잘못된 경로 이동
- 사용자가 이해한 결론
- 신뢰도
- 반복 blocker

최소 3명 × Core 6개를 실행하고, CRITICAL 0건과 반복 blocker triage를 확인한 뒤 Stage 12로 이동한다.

## 수치 해석 원칙

서로 다른 수치를 하나의 `정확도`로 합치지 않는다.

- Fixture 정합성
- Rule engine draft-target exact match
- Intent routing
- Retrieval strict Recall@K
- Grounded citation structural metrics
- 사용자 task completion

각각 평가 대상과 분모가 다르므로 발표에서도 별도 지표로 설명한다.
