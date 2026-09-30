# E2 Semantic Router 단독 평가 — Run 1

평가셋: `apps/api/eval/copilot_e2_routing.json`
Fixture SHA256: `174f9a4ce47d83ba73bd6539eea8a949863e0c2b977096aedb240202962f3fea`

> 이 결과는 **Semantic Router 단독 intent classification 성능**이다. 실제 제품은 E1 frontend alias → backend deterministic router → UNKNOWN일 때만 E2 semantic fallback 순서로 동작하므로, 아래 89%를 제품 전체 라우팅 정확도로 해석하지 않는다.

## 결과

- 전체: **89 / 100 = 89.0%**
- Document QA: **56 / 60 = 93.33%**
- Judgment Explanation: **25 / 32 = 78.12%**
- Change Comparison: **8 / 8 = 100%**
- latency p50: **2325.68 ms**
- latency p95: **3985.72 ms**
- latency mean: **2562.76 ms**

## 실패 11건

### A. 현재 조건 설명을 변경 비교로 오분류
- D01-3: DOCUMENT_QA → CHANGED_NOTICE
- D03-3: DOCUMENT_QA → CHANGED_NOTICE
- D04-3: DOCUMENT_QA → CHANGED_NOTICE

원인: `변경된/바뀐` 표현을 이전/현재 버전 비교 요청으로 과도하게 해석.

### B. 원문 기준 설명을 근거 찾기로 오분류
- D07-3: DOCUMENT_QA → REQUIREMENT_EVIDENCE

원인: `원문 기준으로 설명`과 `근거 위치를 찾아줘`의 task 구분 부족.

### C. 전체 참가 가능 여부보다 확인사항을 우선
- J01, J02, J03, J07, J09, J25: QUALIFICATION_SUMMARY → REQUIRED_CHECKS

원인: 한 문장에 `참가 가능 여부 + 확인/부족/다음 행동`이 같이 있을 때 LIST_MISSING을 primary intent로 선택.

### D. 전체 판정 질문보다 세부 조건 설명을 우선
- J26: QUALIFICATION_SUMMARY → DOCUMENT_QA

원인: `회사 판매 허가와 제품 품목허가 구분`이라는 부가 요청이 전체 참가 가능 여부보다 우선됨.

## 반복 안정성 메모

별도로 전달된 첫 번째 콘솔 출력은 앞부분이 잘려 D06-2부터 CH08까지 84건만 남아 있다. 이 84건과 완전한 Run 1을 비교했을 때 일부 케이스의 intent 결과가 실행 간 달라졌다. 따라서 단발 accuracy 외에 반복 실행 일치율도 후속 평가 대상으로 둔다.

## Run 1 이후 Prompt 수정

- 전체 참가 가능 여부가 포함되면 QUALIFICATION_SUMMARY를 primary intent로 우선
- `바뀐` 단어만으로 CHANGED_NOTICE를 선택하지 않고 실제 이전/현재 비교 요청인지 구분
- `원문 기준 설명`은 DOCUMENT_QA, 근거 위치/조항 자체를 찾는 요청만 REQUIREMENT_EVIDENCE

## 다음 평가

1. 수정 Prompt로 Semantic-only 재실행
2. `evaluate_copilot_e2_combined_routing.py`로 실제 E1 → deterministic → E2 fallback 순서를 재현
3. 두 결과를 분리해 기록
