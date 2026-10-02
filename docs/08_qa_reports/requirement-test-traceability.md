# Requirement ↔ Test ↔ Golden / E2E Traceability

> **상태: Current Mapping + Open Gaps**  
> 기준: `develop`

이 문서는 기획 FR/NFR을 그대로 복제하기보다, 현재 구현된 제품 기능이 어떤 자동테스트·Golden·Human E2E로 검증되는지 연결합니다.

## 검증 단계

```text
Requirement / Product Invariant
→ Unit / Domain Test
→ Service / API Test
→ Golden Regression
→ Human Click E2E
→ Deployment Smoke
```

자동테스트가 있다는 사실과 실제 사용자 흐름이 검증됐다는 사실을 구분합니다.

## Core Qualification

| 요구 성격 | 현재 구현 | 주요 테스트 | 추가 필요 |
| --- | --- | --- | --- |
| 문서 → Requirement Extraction | Current | `test_requirement_extraction.py`, `test_analysis_pipeline.py`, `test_ai_integration.py` | 실제 공고 기준 field-level recall/precision baseline |
| Canonical Mapping / Normalization | Current | `test_canonicalize.py`, `test_normalization.py`, `test_analysis_result.py` | 복합/표/상동기호 실공고 실패셋 확장 |
| deterministic Judgment | Current | `test_qualification_judgment.py` | Golden Profile × Requirement coverage 확장 |
| UNKNOWN / Askability 분리 | Current | `test_askability.py`, Judgment 관련 regression | Ask-back 전용 API/service 테스트를 더 명시적으로 분리 가능 |
| Requirement Diff | Current | `test_requirement_diff.py` | 실제 meaningful changed-notice G2 |
| affected-only Revalidation | Current Product API | G0/E2E regression에 일부 포함 가능 | 전용 Revalidation service/API 테스트 + G2 검증 강화 |

## Data / Backend

| 영역 | 주요 테스트 | 검증 내용 |
| --- | --- | --- |
| Company Profile | `test_companies.py` | Company / performance / certification CRUD 및 validation |
| Master Codes | `test_master_codes.py` | 업종/기관 등 기준정보 |
| Notice Collection | `test_notice_polling.py`, `test_notices.py` | 공고 수집/버전/조회/문서 경계 |
| Qualification Analysis Service | `test_qualification_analysis_service.py` | persisted Analysis Run / API service boundary |
| Product Golden Data | `test_bootstrap_product_data.py`, `test_product_data_inventory.py`, `test_product_golden_candidates.py`, `test_product_golden_inspector.py`, `test_seed_product_golden_demo.py` | Demo/Golden 데이터 준비 및 검사 |

## Product Golden Regression

현재 대표 회귀:

- `test_mvp_golden_e2e.py`
- `test_product_baseline_regression.py`

이 둘은 **Product Integration Baseline이 무너지지 않는지** 확인하는 데 유용하지만, LLM/RAG 품질평가 전체를 대신하지 않습니다.

```text
Product Regression
≠
Extraction Quality Evaluation
≠
Retrieval Quality Evaluation
≠
Human Browser E2E
```

## FR/NFR Reconciliation 예시

초기 Notion 요구사항 ID는 역사와 의도를 보존합니다. 현재 구현 정책과 의미가 달라진 ID는 그대로 재구현하지 않고 Current Contract를 우선합니다.

| 초기 요구 | Current 해석 | 검증 |
| --- | --- | --- |
| NFR: LLM이 최종 판정하지 않음 | 유지 | deterministic Judgment test / 의존성 검토 |
| NFR: `confidence low`면 Ask-back | **Superseded** | `UNKNOWN != ASKABLE`, `test_askability.py` |
| FR: Ask-back 답변을 Profile에 자동 저장 | **Superseded for MVP** | Answer의 `apply_to_profile=false`, USER_ANSWER basis 확인 |
| FR: 판정 4색 상태 | UI 표현으로 해석 | Judgment 3상태 + Basis + Overall status 테스트 |
| FR: 변경 항목 재판정 | 유지 | Requirement Diff + Revalidation + G2 필요 |
| FR: Evidence 원문 연결 | 유지 | extraction/analysis regression + Human evidence navigation 필요 |

## Golden 구분

### G0 — Synthetic deterministic regression

목적:

- Rule/Contract 회귀
- PASS / FAIL / UNKNOWN
- Boundary / askability
- Version/Run 연결

### G1 — Real Notice Reality Check

목적:

- 실제 공고 Parsing/Chunking
- Requirement 누락/오추출
- Evidence grounding
- `PARTIAL` / unsupported failure pattern

필요 지표 예:

- Requirement field-level precision/recall/F1
- Evidence citation/support accuracy
- rejected/unmapped rate
- abstention correctness

### G2 — Meaningful Changed Notice

목적:

```text
실제 v1 Requirement
→ 실제 v2 Requirement
→ meaningful change
→ affected Requirement
→ before Judgment
→ after Judgment
→ before/after Evidence
```

현재 가장 중요한 미완료 검증 축입니다.

## Human Click E2E

최소 Release Story:

```text
01 공고 찾기
→ 02 Case 생성 / Analysis / Judgment
→ 03 ASKABLE UNKNOWN 답변
→ 02 결과 갱신
→ 04 Evidence 원문 확인
→ 06 변경공고 Revalidation 확인
```

05 Evaluation은 전용 Product pipeline 범위가 확정되기 전까지 위 Qualification Golden Story의 Release Blocker로 자동 간주하지 않습니다.

## Copilot QA — Proposed

Copilot 구현 후 별도 평가셋을 만듭니다.

- Intent routing accuracy
- Tool selection accuracy
- Grounded answer correctness
- Citation correctness
- Abstention / cannot-answer correctness
- Multi-turn context consistency
- Ask-back → result judgment explanation
- Changed notice explanation

Copilot의 자연어 답변 품질이 Core의 deterministic Judgment 정답을 대체하지 않습니다.

## Done 기준

기능 PR을 Done으로 보기 전에 최소 다음 질문에 답할 수 있어야 합니다.

1. 어떤 Requirement/Invariant를 구현했는가?
2. 어떤 자동테스트가 이를 보호하는가?
3. 실제 데이터에서 별도 Golden 검증이 필요한가?
4. 화면 기능이면 Human E2E가 필요한가?
5. Contract/Architecture/Current docs가 함께 갱신됐는가?
