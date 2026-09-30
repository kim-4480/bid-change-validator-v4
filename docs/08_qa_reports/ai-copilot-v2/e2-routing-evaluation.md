# AI Copilot E2 라우팅 평가

기준 평가셋: `apps/api/eval/copilot_e2_routing.json` 100문항  
범위: **intent routing only** — 답변 정답률, RAG 검색 품질, 사용자 과업 완료율과 구분한다.

## 1. Semantic Router 단독

| Run | 전체 | Document QA | Judgment Explanation | Change Comparison | p50 | p95 | mean |
|---|---:|---:|---:|---:|---:|---:|---:|
| Run 1 | 89/100 (89%) | 56/60 | 25/32 | 8/8 | 2.33s | 3.99s | 2.56s |
| Run 2 | 98/100 (98%) | 60/60 | 32/32 | 6/8 | 2.04s | 3.03s | 2.20s |
| Run 3 | **100/100 (100%)** | **60/60** | **32/32** | **8/8** | **1.98s** | **2.83s** | **2.06s** |

Run 1→2 주요 보정:
- 전체 참가 가능 여부가 포함된 복합 질문은 `QUALIFICATION_SUMMARY` 우선
- 단순 `바뀐/변경된` 표현만으로 `CHANGED_NOTICE`로 보내지 않음
- `원문 기준으로 설명`은 `DOCUMENT_QA`, 근거 위치/조항 자체를 찾을 때만 `REQUIREMENT_EVIDENCE`

Run 2→3 주요 보정:
- 변경된 조건이 **회사 판정에 미친 영향 / 판정 변화**를 묻는 경우는 `CHANGED_NOTICE`
- 현재 조건 의미만 설명하는 변경 표현은 `DOCUMENT_QA`

> **주의:** Run 3의 100%는 frozen 100-question intent 분류셋에 대한 Semantic Router 단독 결과다. 전체 챗봇 정확도나 사용자 과업 완료율이 아니다.

## 2. 최초 Combined 제품 경로 평가

초기 제품 순서:

```text
E1 frontend bounded alias
→ Backend deterministic route_intent
→ deterministic UNKNOWN일 때 E2 semantic fallback
```

최초 combined 결과:
- 전체: **90/100 (90%)**
- Document QA: **52/60 (86.7%)**
- Judgment Explanation: **31/32 (96.9%)**
- Change Comparison: **7/8 (87.5%)**
- route source: Semantic 54 / Deterministic 46
- Semantic fallback rate: 54%
- cached Semantic source latency: p50 1.98s / p95 2.78s / mean 2.06s
- model calls in combined evaluator: **0**

## 3. 최초 Combined 실패 10건 원인

실패 10건은 **Run 3 Semantic Router가 틀린 사례가 아니다.** 동일 질문을 Semantic Router 단독으로는 10/10 모두 맞췄다. 앞단 deterministic router가 keyword substring을 먼저 확정해 semantic fallback까지 도달하지 못했다.

- `D01-3` → `ACTION_REQUEST`: `적용되는지 설명`을 write 관련 `적용`으로 오인
- `D11-2` → `ACTION_REQUEST`: `예외가 어떻게 적용되는지 설명`을 write로 오인
- `D02-3`, `D05-3`, `D13-3`, `D14-3`, `D18-2`, `D20-2` → `REQUIRED_CHECKS`: `확인/왜` 부분 문자열을 사용자 부족정보 확인 요청으로 오인
- `J07` → `REQUIRED_CHECKS`: 전체 참가 가능 여부보다 `부족한 정보` 키워드가 우선
- `CH08` → `REQUIRED_CHECKS`: 변경 영향 비교보다 `확인해줘`가 우선

대표 false positive:
- `중소기업 확인서의 제출 시점 조건을 설명해줘`에서 `확인서` 내부의 `확인`
- `8조와 13조의 AND/OR 표현이 왜 충돌하는지 설명해줘`의 `왜`
- `변경된 조건 때문에 지금 판정이 달라지는지 확인해줘`의 `확인`

## 4. 제품 라우팅 정책 보정

모든 deterministic 결과를 Semantic이 덮어쓰게 하지 않는다. 비용·지연·안전 경계를 유지하면서 **weak deterministic read**만 semantic 재검토 대상으로 둔다.

Semantic ON일 때:
- `UNKNOWN` → E2 semantic
- 자유입력 `REQUIRED_CHECKS` → E2 semantic 재검토
- `적용되는지/어떻게 적용되는지 설명` 같은 읽기형 `ACTION_REQUEST` → E2 semantic 재검토

Semantic이 절대 덮어쓰지 않는 경계:
- explicit UI intent
- `user_input`이 포함된 write payload
- 명확한 실행문 (`재검증해줘`, 실제 적용/반영 실행 등)

Semantic 실패/UNKNOWN/낮은 confidence인 경우:
- 원래 deterministic result로 fallback

관련 구현:
- `apps/api/app/copilot/router.py::semantic_recheck_candidate`
- `apps/api/app/copilot/router.py::resolve_chat_payload`
- `apps/api/tests/test_copilot_semantic_optin.py`

## 5. 최종 Combined v2 결과

동일 Semantic Run 3 결과를 캐시로 재사용하고, 실제 제품 정책 함수 `resolve_chat_payload()`를 사용해 다시 계산했다.

| 지표 | Combined v2 |
|---|---:|
| 전체 | **100/100 (100%)** |
| Document QA | **60/60 (100%)** |
| Judgment Explanation | **32/32 (100%)** |
| Change Comparison | **8/8 (100%)** |
| route source | Semantic 64 / Deterministic 36 |
| semantic fallback | 64/100 (64%) |
| weak deterministic recheck | **10건** |
| cached semantic latency p50 | 1.98s |
| cached semantic latency p95 | 2.84s |
| cached semantic latency mean | 2.07s |
| combined evaluator model calls | **0** |

최종 10개 weak deterministic false positive는 모두 Semantic 재검토로 교정됐다.

## 6. 평가 재현성

Combined evaluator는 모델을 다시 호출하지 않는다.

```text
completed Semantic Run JSON
→ same resolve_chat_payload product policy
→ combined result
```

따라서:
- model calls = 0
- Semantic Run과 Combined Run의 모델 샘플이 동일
- 비용/네트워크 변동 제거
- 제품 코드와 evaluator가 `resolve_chat_payload()` 정책 공유

## 7. E2 종료 해석

E2에서 확정할 수 있는 것은 **고정 100문항의 intent routing**이다.

- E0 자유입력 routing: **1/100 (1%)**
- E1 bounded alias routing: **41/100 (41%)**
- E2 combined routing: **100/100 (100%)**

이 값은 다음을 의미하지 않는다.
- 답변 내용 정답률 100%
- RAG retrieval/grounded answer 정확도 100%
- 사용자 과업 완료율 100%
- 독립 holdout 일반화 성능 100%

특히 I01~I20의 문서 의미 과업은 E2에서 intent를 올바르게 골라도 실제 DOCUMENT_QA 생성 답변 연결이 없으면 업무 완료가 되지 않는다. 따라서 **E3에서 retrieval + grounded answer를 연결한 뒤 task completion을 다시 평가**한다.
