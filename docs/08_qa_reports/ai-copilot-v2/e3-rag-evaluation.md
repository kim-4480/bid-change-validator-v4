# AI Copilot E3 — 근거 기반 Document QA 평가

## 현재 상태

E3 Document QA 연결, retrieval 비교, Grounded Answer prompt refinement와 회귀 검증까지 완료했다.

- 최신 관련 회귀: **251 passed / 1 warning**
- warning: Starlette TestClient의 `anyio.abc.BlockingPortal` deprecation warning으로 이번 Copilot/RAG 변경 실패와 무관한 비차단 경고
- 현재 retrieval 기본값: **Hybrid (BM25 + Dense, RRF)**
- LLM rerank: 품질은 소폭 개선했지만 latency/비용 증가가 커서 **기본 제품 경로에 채택하지 않음**
- Grounded Answer 모델: `gpt-5.6-luna`
- E3 단계 결론: **완료**. 다음은 사용자 관점 Test Case(Stage 11)

## 구현 경계

- Semantic 의미분류 동의와 Document RAG 외부처리 동의를 별도로 유지한다.
- Document RAG 동의가 없으면 공개 문서 retrieval/generation을 실행하지 않는다.
- 현재 notice version의 공개 문서만 검색한다.
- retrieval 0-hit이면 generation을 호출하지 않고 abstain한다.
- Grounded Answer가 검증 가능한 citation을 하나도 사용하지 않으면 생성 문장을 사용자에게 노출하지 않는다.
- 다른 notice version의 index/hit/citation 혼입은 fail-closed한다.
- 회사 참가 가능/불가 질문은 제품의 저장된 판정 경로가 우선하며 Document QA가 독자적으로 판정하지 않는다.
- Grounded Answer는 질문의 핵심 주장에 직접 관련된 SOURCE만 인용하고, 근거가 없으면 citation 없이 abstain한다.
- 일부 근거만 있는 경우 전체 조건을 먼저 단정하지 않고 확인 가능한 부분과 불가능한 부분을 분리한다.
- SOURCE의 코드/자릿수/날짜/금액 표기가 모순되거나 불완전하면 임의로 누락값을 보정·복원하지 않는다.

## 평가셋

고정 입력:

- `apps/api/eval/copilot_e3_document_qa.json`: 기존 `시나리오120`의 DOCUMENT_QA 60건
- `apps/api/eval/copilot_e3_expected_evidence.json`: 해당 질문이 참조하는 golden v0.2 근거 발췌

둘 다 **독립 검토자 승인 전 DRAFT**다. 정답률/법률적 정확도 확정 자료로 표현하지 않는다.

현재 canonical 비교 fixture:

- cases SHA256: `b0aa4e891da01004d32473f41b6e5a26386feab1a1f71b559969f48f89dae585`
- evidence SHA256: `94952b895818d576b7b45b640132d38a752e66114943ee341e3b50b77b48e6f4`
- 총 질문: 60
- 실제 평가: 59
- cross-version scope gap: 1 (`D04-3`)

### 범위 예외

`D04-3`은 현재 001차 근거 `E014`와 이전 000차 근거 `E017`을 동시에 요구한다. 현재 Document RAG는 한 notice version만 검색하므로 이 케이스는 retrieval miss가 아니라 **cross-version scope gap**으로 별도 기록한다.

### 평가 타깃 버전 주의

원래 Copilot 시나리오 표는 초기 근거를 기준으로 작성됐고 이후 golden v0.2에 보완 발췌가 추가됐다. 따라서 strict quote miss에는 실제 retrieval miss뿐 아니라 equivalent support / stale target / wording drift가 섞일 수 있다.

대표 예:

- D03-1: 세 업종 상세는 E079~E081 보완
- D03-2: 기술역량 OR 구조/대안은 E082~E086 보완
- D15-1 / D15-3: 실제 5898 / 5815 / 7607 문구는 E087~E088 보완
- D13 계열 일부: frozen target의 `자원순환시설` 표현과 현재 문서의 `가축분뇨 자원화시설` 표현 차이 존재

## Historical run — provenance 정정 전 Hybrid

초기 expected evidence fixture 일부의 provenance가 golden v0.2와 달랐던 상태에서 Hybrid Recall@4 75%가 한 번 측정됐다.

이 결과는 **현재 canonical retrieval 성능으로 사용하지 않는다.** provenance 정정 후 canonical evidence SHA가 변경됐으므로 현재 50% 계열 결과와 직접 증감 비교하지 않는다.

## Canonical Retrieval 비교 — 동일 fixture

공통 조건:

- `k=4`, `fetch_k=12`
- 동일 cases/evidence SHA
- Supabase session pooler가 포화되어 canonical 실행은 transaction pooler fallback 사용

### Dense

- strict evidence hit: 21/72
- **Evidence Recall@4 = 29.17%**
- **Case Any-hit@4 = 32.20%**
- **Case All-hit@4 = 27.12%**
- latency p50 **144.50ms**, p95 **210.98ms**, mean **176.04ms**

### Hybrid — 채택

- strict evidence hit: 36/72
- **Evidence Recall@4 = 50.00%**
- **Case Any-hit@4 = 52.54%**
- **Case All-hit@4 = 49.15%**
- latency p50 **170.58ms**, p95 **230.54ms**, mean **214.36ms**

Dense만 all-hit이고 Hybrid가 실패한 케이스는 0건, Hybrid만 추가 all-hit인 케이스는 13건이었다. Dense 대비 Hybrid는 Recall +20.83%p, All-hit +22.03%p이며 latency 증가는 p50 약 26ms 수준이므로 **Hybrid를 기본 retrieval로 잠근다.**

### Hybrid + LLM Rerank — 기본 경로 미채택

- rerank model: `gpt-5.6-luna`
- model calls: **59**
- strict evidence hit: 40/72
- **Evidence Recall@4 = 55.56%**
- **Case Any-hit@4 = 57.63%**
- **Case All-hit@4 = 57.63%**
- latency p50 **2849.73ms**, p95 **4556.06ms**, mean **3015.20ms**

Hybrid 대비 Recall +5.56%p, Any-hit +5.09%p, All-hit +8.48%p 개선됐지만 p50은 약 170.58ms → 2849.73ms로 증가하고 매 질문마다 추가 유료 LLM call이 필요하다. 따라서 **기본 제품 경로는 Hybrid 유지**로 결정한다. LLM rerank는 추후 hard-query/selective rerank 후보로만 남긴다.

## Grounded Answer 최종 평가 — v4

실행 범위는 **Hybrid retrieval + Grounded Answer 구조/citation grounding**이다. 이 결과는 semantic answer correctness 확정치가 아니다.

### 구조 지표

- model calls: **59**
- generation success: **59/59**
- generation failure: **0**
- source lookup failure: **0**
- citation present: **57/59 (96.61%)**
- zero-citation generated answers: **2**
- citation notice-version integrity: **59/59 (100%)**
- eligibility-language review flags: **6** — 자동 안전 위반 판정이 아니라 보수적 검토 후보

### strict frozen-evidence citation 지표

- expected evidence: 72
- strict expected evidence cited: **33/72**
- **Expected Evidence Citation Recall = 45.83%**
- **Case Any Expected Evidence Cited = 47.46%**
- **Case All Expected Evidence Cited = 44.07%**

이 수치는 답변 정답률이 아니다. frozen quote matcher가 실제 답변 citation에 포함된 source quote가 기대 발췌와 문자열 기준으로 맞는지 보는 구조 지표다. 동일 의미의 다른 source, 긴 chunk, punctuation/spacing 차이, target drift 때문에 의미상 지원되는 답변도 strict miss가 될 수 있다.

### latency

- retrieval p50 **178.50ms**, p95 **289.22ms**, mean **240.16ms**
- generation p50 **2774.59ms**, p95 **5288.05ms**, mean **2971.85ms**
- total p50 **2925.77ms**, p95 **5449.73ms**, mean **3212.01ms**

첫 요청 D01-1은 retrieval/total latency가 큰 outlier로 관측됐지만 원인은 별도 계측 없이 확정하지 않는다.

## Prompt refinement 결과

Grounded Answer v1부터 v4까지 같은 59개 evaluable case를 반복 측정하며 안전/표현 회귀를 확인했다.

### v1 문제

- 59/59 답변에 citation이 존재했지만, `D07-1`처럼 질문에 직접 답하는 근거가 Top-4에 없는데도 관련 없는 source를 인용하는 문제가 있었다.
- 따라서 citation presence 100%를 grounding quality 100%로 해석할 수 없었다.

### v2 조치

- 질문의 핵심 주장을 직접 뒷받침하는 SOURCE만 인용
- 근거가 없으면 `검색된 근거만으로 확인할 수 없습니다.` + citation 없음
- 부분 근거는 확인 가능/불가를 분리
- 문서 충돌은 한쪽을 임의 우선하지 않음

결과적으로 D07-1이 **clean abstention + zero citation**으로 전환됐다.

### v3 조치

부분 근거로 전체 결론을 먼저 내리는 문제를 막았다.

- `D11-1`: 직원 3명만으로 전체 인력조건 충족을 확정하지 않고 최소 3명 + PM 참여율 30% 조건을 분리
- `D19-1`: 디자인업종 두 종류는 근거 부족으로 미확정, 직접생산 두 품목만 AND로 설명

### v4 조치 — 최종

SOURCE 자체가 불완전하거나 모순된 식별자를 임의 복원하지 않도록 규칙을 추가했다.

- `D19-3`: 문서에는 간판 세부품명번호를 `10자리`라고 설명하지만 실제 값은 `551290401` 9자리로 기재됨
- 최종 답변은 SOURCE의 9자리 표기를 그대로 설명하고 **빠진 숫자를 추정·복원하지 않음**

최종적으로 다음 핵심 회귀가 동시에 유지됨을 확인했다.

- D07-1: no-support → abstain / no citation
- D11-1: 단일 사실로 전체 조건 충족 단정 금지
- D19-1: 일부 근거만 있을 때 항목별 답변
- D19-3: malformed identifier 임의 보정 금지
- generation 59/59
- citation version integrity 100%

## zero-citation 케이스 해석

v4의 zero-citation 생성 답변은 2건이다.

- `D07-1`: 실적 금액/기간 직접 근거가 retrieval Top-4에 없음 → 정상 abstention
- `D14-3`: `4110390601`이 회사 업종코드인지 판단할 직접 근거가 Top-4에 없음 → 정상 abstention

제품 helper는 모델 답변이 citation 0개이면 생성문을 그대로 사용자에게 노출하지 않고 deterministic abstention으로 fail-closed하므로 이 동작은 의도된 안전 경계다.

## eligibility-language flag 수동 검토

v4 flag: `D10-3`, `D15-1`, `D15-2`, `D15-3`, `D16-1`, `D17-1`.

자동 flag는 `가능/불가/충족` 같은 표현을 보수적으로 잡는 review candidate이며 자동 위반이 아니다. 수동 검토에서는 **실제 회사 상태를 LLM이 독자적으로 판정한 명확한 사례를 확인하지 못했다.** 대부분 공고 문언을 설명하거나, 실제 회사 판정은 추가 확인이 필요하다고 제한한다.

이 검토도 독립 정답자 승인이나 법률적 검증은 아니므로 최종 사용자 테스트에서 표현 이해도와 과신 여부를 다시 관찰한다.

## Strict metric 해석 주의

자동 점수는 Unicode/공백 정규화 후 frozen excerpt 포함 여부를 보는 strict metric이다. 답변 정확도·의미상 동등 support·사용자 task completion과 분리한다.

최종 평가는 세 층으로 기록한다.

1. **Strict retrieval Recall@K**: Dense/Hybrid/Rerank 자동 비교
2. **Grounded citation structural metrics**: citation 존재/버전무결성/expected-evidence matcher
3. **Semantic/user review**: 실제 답변 의미, 과잉 결론, abstention 적절성, 사용자 과업 완료 여부

자동 fuzzy judge를 추가해 점수를 높이는 방식은 사용하지 않는다.

## Stage 10 결론

**E3·RAG·Prompt 성능 비교를 완료한다.**

- 제품 retrieval: **Hybrid 고정**
- LLM rerank: 기본 경로 **미채택**
- Grounded Answer: citation fail-closed / partial evidence / conflict / malformed identifier 안전 규칙 반영
- latest regression: **251 passed / 1 warning**
- v4 structural execution: **59/59 generated, 0 failed, citation version integrity 100%**
- strict expected-evidence citation recall **45.83%**는 답변 정답률이 아니며 retrieval miss와 target/matcher 한계를 함께 포함

다음 단계는 **Stage 11 사용자 관점 Test Case**다. 실제 사용자가 설명 없이 공고 검토 과업을 수행하면서 완료율, 소요시간, 막힘 지점, 잘못된 신뢰/오해가 발생하는 답변을 관찰한다.
