# 05. E2E Golden Path

## 0. 현재 결과 — 2026-09-08 / PR #74

| 구분 | 현재 상태 | 증명하지 못한 것 |
| --- | --- | --- |
| G0 | 합성 DB/Canonical 회귀 통과: 4억→6억 MODIFIED, USER_ANSWER 승계 | 실제 LLM extraction / Evidence grounding |
| G1 | R26BK01687395: PARTIAL 2요건/2근거, UNKNOWN 2, insufficient_data, unsafe Yes 2건 422 | safe-answer 성공과 추출 품질 완료; 다른 공고 R26BK01689803은 FAILED/0 |
| G2 | 실제 후보 10건 검산, meaningful Qualification Diff 미확보 | 실제 affected-only 및 전체 Human Click E2E |

7개 화면 navigation smoke와 G0 성공만으로 Product Baseline Ready를 선언하지 않는다. G1 저장 분석은 최종 상동 guard 이전 실행이며 최종 Rule/Ask-back 차단을 확인한 것이다. PR #74 merge 후 기존 Demo/Golden의 baseline/current를 모두 [full re-analysis](06-handoff-and-merge.md)해야 한다.

### 실제 후보 10건 검산 요약

| 공고 | 원문/차수 비교 결과 | G2 판단 |
| --- | --- | --- |
| R26BK01715087 | v1→2 설명회 미개최 안내·시작시간 13→14시, v2→3 14→14:30, v3/v4 동일; RFP 동일 | 의미 있는 자격변경 없음으로 탈락 |
| R26BK01715236 | v1→2 취소, 현재 문서 0 | 현재 자격원문 없음 |
| R26BK01715042 | v1→2 취소, 현재 문서 0 | 동일 |
| R26BK01715257 | v1→2 취소, 현재 문서 0 | 동일 |
| R26BK01715375 | 예정가격 범위 ±2%→±3% | 자격조건 변경 아님 |
| R26BK01715394 | v1→2 취소, 현재 문서 0 | 비교 불가 |
| R26BK01715477 | 낙찰하한율 88→90%, 시간 11→12시, 중복 PDF 감소 | 자격조건 변경 아님 |
| R26BK01715691 | 양 차수 문서 0 | 확인 불가 |
| R26BK01715492 | v1→2 취소, 현재 문서 0 | 확인 불가 |
| R26BK01716110 | 기존 5종 추출 해시 동일, 미추출 보험 XLSX 추가, 특수조건 source_field 이동 | 자격변경 미입증, XLSX 확인 필요 |

R26BK01715087 v1/v4 분석은 source-local 참조 개선 전에 모두 FAILED/0이었다. 빈 분석의 Diff를 성공으로 세지 않는다. 문서 재배치는 삭제로 간주하지 않았다. 실행 ID/해시 검증 범위는 [audit](11-product-baseline-audit.md)에 보존한다.

아래 단계와 체크박스는 **실제 제품 acceptance 재검증 절차**이며 현재 모두 통과했다는 기록이 아니다.

## 1. Purpose

Golden Path는 “각 파트가 따로 동작한다”가 아니라 **실제 사용자 흐름이 전 구간을 통과한다**는 것을 증명하는 Baseline 시나리오입니다.

초기에는 하나의 재현 가능한 공고/기업 Profile 시나리오로 시작하고, 이후 Golden Set을 여러 유형으로 확장합니다.

## 2. Golden Scenario data principle

Golden Scenario에는 다음 데이터가 고정되어야 합니다.

- Notice
- Notice Version V1
- Notice documents + source hashes
- Company Profile
- Canonical Requirement fixture 또는 재현 가능한 분석 결과
- Requirement-level expected Judgment
- UNKNOWN을 해소하는 User Answer
- 변경공고 Version V2
- V1 ↔ V2 Requirement change expectation

실제 공고를 사용할 수 있으면 실제 공고를 우선하되, 테스트 안정성을 위해 원본 snapshot/fixture를 함께 보존합니다.

## 3. Golden Path — Version 1

### Step 1. Notice ingest / select

사용자가 Baseline 대상 공고를 조회합니다.

Expected:

- `notice_id`가 존재한다.
- 현재 `notice_version_id`가 식별된다.
- 분석 대상 document가 존재한다.

### Step 2. Source readiness

공고 원문/첨부파일의 텍스트 추출 상태를 확인합니다.

Expected:

- `document_id`
- original file hash
- extracted text hash
- extracted blocks

가 추적 가능합니다.

### Step 3. Company Profile

Golden Company Profile을 생성 또는 선택합니다.

최소 한 개 이상의 Canonical Requirement가 Profile 값으로 바로 판정되고, 최소 한 개는 UNKNOWN이 되도록 시나리오를 구성하는 것을 권장합니다.

예:

```text
업종       → 값 존재
지역       → 값 존재
인력       → 값 존재
인증/특정 확인값 → 일부 부족
```

합성 G0 fixture는 `apps/api/tests/test_mvp_golden_e2e.py`에 고정되어 있습니다. 실제 G1/G2에는 조건을 인위적으로 만들지 않습니다.

### Step 4. Requirement Analysis

공고 Version의 Backend extracted blocks를 Qualification Analysis에 전달합니다.

Expected:

```text
AnalysisStatus = SUCCEEDED 또는 의도된 PARTIAL
requirements[]
evidence[]
```

각 Requirement의 `notice_version_id`가 분석 대상 Version과 일치해야 합니다.

### Step 5. Evidence validation

각 Golden Requirement가 원문 Evidence로 되돌아갈 수 있는지 확인합니다.

Expected:

```text
requirement_key
→ evidence_key
→ document_id
→ source block/location
→ quote/original source
```

### Step 6. Initial Judgment

Company Profile과 Requirement를 비교합니다.

Expected example:

```text
R-001 → SATISFIED
R-002 → SATISFIED
R-003 → UNKNOWN
```

UNKNOWN은 실패가 아니라 정보 부족 상태입니다.

### Step 7. Ask-back

UNKNOWN인 Requirement가 사용자 답변으로 해소 가능한 경우 질문을 만듭니다.

Expected:

- 질문이 `preflight_case_id`와 해당 Requirement/Judgment에 연결된다.
- 질문의 이유가 표시된다.
- 관련 없는 Requirement에는 질문을 만들지 않는다.

### Step 8. User Answer

사용자가 확인값을 입력합니다.

Expected:

- ASKABLE만 허용하며 `apply_to_profile=false`로 Answer가 저장된다.
- `basis_type=USER_ANSWER`로 추적할 수 있다.
- Answer가 어떤 Requirement를 해소하는지 알 수 있다.

### Step 9. Partial re-judgment

Answer의 영향을 받는 Requirement를 다시 판정합니다.

Expected:

```text
R-001 → 기존 결과 유지
R-002 → 기존 결과 유지
R-003 → UNKNOWN → SATISFIED 또는 UNSATISFIED
```

불필요하게 공고 Requirement Extraction 전체를 다시 수행하지 않는 경로를 우선합니다.

### Step 10. Frontend result

사용자가 화면에서 다음을 확인합니다.

- 판정 결과
- 원문 근거
- 사용된 Company Profile/User Answer basis
- 해결 완료 상태

## 4. Golden Path — Changed Notice Version 2

### Step 11. Changed notice ingest

같은 Notice의 변경공고를 수집합니다.

Expected:

- V1을 덮어쓰지 않는다.
- V2가 새 Version identity를 가진다.
- V1과 V2를 모두 조회할 수 있다.

### Step 12. Analyze Version 2

V2 문서 기준으로 Canonical Requirement를 생성합니다.

Expected:

- V2 Requirement Evidence가 V2 document/source를 가리킨다.
- V1 Evidence를 현재 근거로 재사용하지 않는다.

### Step 13. Requirement Diff

V1과 V2 Requirement를 비교합니다.

실제 원문에서 의미 있는 MODIFIED/ADDED와 UNCHANGED를 확인해야 합니다. 반환 상태는 다음과 같습니다.

```text
ADDED
REMOVED
MODIFIED
UNCHANGED
```

가격·시간 변경만으로 Qualification Diff를 통과 처리하지 않습니다.

### Step 14. Revalidation

영향 Requirement를 다시 판정합니다.

Expected:

- 변경되지 않은 Requirement는 영향 없음으로 구분 가능하다.
- 변경된 Requirement는 새 Version 기준으로 판정된다.
- 이전/현재 판정과 Evidence를 비교할 수 있다.

### Step 15. Frontend change result

사용자는 다음 흐름으로 변경 영향을 봅니다.

```text
무엇이 바뀌었나
→ 내 판정에 영향이 있나
→ 이전에는 어땠나
→ 지금은 어떤가
→ 근거는 어디인가
→ 내가 무엇을 해야 하나
```

## 5. Golden assertions

Baseline E2E의 핵심 assertion:

- [ ] Notice V1/V2 identity가 보존된다.
- [ ] Requirement가 정확한 Version에 묶인다.
- [ ] Evidence가 원문 source를 역추적할 수 있다.
- [ ] Company Profile basis가 추적된다.
- [ ] 정보 부족은 UNKNOWN이다.
- [ ] Ask-back Answer 후 영향 항목만 재판정 가능하다.
- [ ] 변경공고 후 영향 Requirement를 식별할 수 있다.
- [ ] V2 판정은 V2 Evidence를 사용한다.
- [ ] Frontend에서 판정 → 근거 → 해결 흐름이 끊기지 않는다.

## 6. Test layers

### Contract tests

- Pydantic/Schema validation
- Requirement/Evidence internal links
- Status enum
- stable ID rule

### Service tests

- Company Profile CRUD
- Notice/Version retrieval
- AI analysis adapter
- Judgment rules
- Answer/re-judgment
- Diff/revalidation

### Integration tests

- DB persistence
- Backend ↔ AI
- Backend ↔ Frontend response contract

### E2E

Golden Scenario 전체 흐름을 최종 Baseline acceptance로 사용합니다.

## 7. Expansion after baseline

Baseline 1개가 통과한 뒤 Golden Set을 다음 축으로 늘립니다.

- Requirement Type 8종 coverage
- SATISFIED / UNSATISFIED / UNKNOWN 분포
- AND / OR requirement group
- 서로 다른 공고 업무 유형
- 변경 없음 / 조건 강화 / 조건 완화 / 조건 추가 / 조건 삭제
- Evidence 위치 형식: PDF page / HWP block/paragraph
- Analysis `PARTIAL` / `FAILED` guardrail case
