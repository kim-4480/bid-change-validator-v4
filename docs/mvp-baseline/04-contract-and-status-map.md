# 04. Contract and Status Map

## 1. Source-of-truth order

Baseline에서 계약 충돌이 생기면 조용히 변환하지 않고 아래 순서로 확인합니다.

1. 실제 Backend source identity / DB data
2. `apps/api/app/ai` Canonical contract
3. 승인된 MVP Baseline contract decision
4. 기존 `docs/contracts/*` 초안
5. 화면 표시용 derived status

기존 문서는 폐기하지 않습니다. 과거 차이는 [Stage 2 이력](07-current-code-contract-gap.md)으로 보존하고 현재 구현은 이 문서로 구분합니다.

## 2. Canonical Requirement types

현재 AI Canonical contract의 닫힌 Requirement Type은 8종입니다.

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

Baseline에서는 우선 이 8종을 공통 판정 언어로 사용합니다.

새 유형이 필요하면 기존 유형에 억지로 끼워 넣지 않고 Contract 변경으로 다룹니다.

## 3. Requirement operators

현재 Canonical contract에서 허용하는 operator:

```text
>=
>
<=
<
=
MATCH
RANGE
```

Requirement는 `raw` 원문과 normalized value를 함께 유지해야 합니다.

## 4. AI analysis status

AI Requirement 분석 실행 자체의 상태입니다.

| Status | Meaning | UI / Backend rule |
| --- | --- | --- |
| `SUCCEEDED` | Canonical 변환까지 정상 완료 | 정상 결과 사용 가능 |
| `PARTIAL` | 일부 결과는 있으나 diagnostic 존재 | 결과 + 경고를 함께 노출/저장 |
| `FAILED` | Canonical 결과를 신뢰할 수 없음 | 성공 판정 흐름으로 전달 금지 |

이 상태는 회사 자격 충족 여부가 아닙니다.

## 5. Judgment status

Requirement와 Company Profile/User Answer를 비교한 판정 상태입니다.

```text
SATISFIED
UNSATISFIED
UNKNOWN
```

| Status | Meaning | Next action |
| --- | --- | --- |
| `SATISFIED` | 현재 근거 기준 조건 충족 | 근거 확인 가능 |
| `UNSATISFIED` | 현재 근거 기준 조건 미충족 | 해결 가능성/조치 안내 |
| `UNKNOWN` | 판정에 필요한 데이터 부족 또는 확인 필요 | Ask-back / review |

## 6. Judgment basis and reason

현재 Canonical contract 기준:

### Basis type

```text
PROFILE
USER_ANSWER
NONE
```

### Reason code

```text
RULE_MATCH
RULE_MISMATCH
INSUFFICIENT_DATA
NEEDS_REVIEW
UNSUPPORTED_REQUIREMENT
```

Baseline에서는 `status`만 저장하지 않고 최소한 `basis_type`과 `reason_code`를 같이 유지합니다.

## 7. Existing draft status gap

기존 `docs/contracts/frontend-backend.md`와 `docs/contracts/backend-llm.md`에는 다음 aggregate status 초안이 존재합니다.

```text
eligible
ineligible
needs_review
insufficient_data
```

세부 check 상태 초안:

```text
passed
failed
unknown
warning
```

반면 현재 Canonical code는 Requirement-level `SATISFIED / UNSATISFIED / UNKNOWN`을 사용합니다.

### 현재 aggregate mapping — qualification-rules-v0.2

- 필수 ANY_OF 그룹: 하나라도 SATISFIED이면 그룹 충족, 그렇지 않고 UNKNOWN이 있으면 보류, 모두 미달이면 그룹 미달.
- 필수 ALL_OF 그룹: 하나라도 UNSATISFIED이면 그룹 미달, 그렇지 않고 UNKNOWN이 있으면 보류, 모두 충족이면 그룹 충족.
- 필수 그룹 중 미달이 있으면 `ineligible`.
- 그 외 미확정 그룹, 필수 그룹 부재, 또는 분석이 `SUCCEEDED`가 아니면 `insufficient_data`.
- 나머지만 `eligible`.

따라서 PARTIAL은 Ask-back 이후에도 자동 eligible로 승격되지 않는다. UNKNOWN은 사용자 질문 가능 여부와 다르다. 기존 초안 `needs_review`와 `warning`을 현재 aggregate 반환값으로 가정하지 않는다.

## 8. Evidence contract

Evidence는 최소 다음 identity를 보존합니다.

- `evidence_key`
- `source_type`
- `document_id`
- `notice_version_id` 또는 Case context
- `location`
- `quote`
- `source_sha256`
- `extracted_text_sha256`

전체 raw는 공백 정규화 후 실제 source chunk에 포함되어야 하며 세부 필드도 같은 원문에서 검증한다. reference는 해당 chunk의 조항 라벨/줄 시작을 확인한다. 일부 추출 거절이나 입력 잘림은 diagnostic/PARTIAL로 남긴다. 인용문 일치는 주변 예외·표 문맥의 완전한 이해를 보장하지 않는다.

### Location rule

Backend extracted block이 source of truth입니다.

가능한 locator:

- block range
- PDF page
- section index
- paragraph range
- source line range
- clause label

HWP/HWPX에 존재하지 않는 page 정보를 임의로 생성하지 않습니다.

## 9. Requirement contract

Requirement는 최소 다음을 추적합니다.

- `requirement_key`
- optional group key / ALL_OF / ANY_OF
- `notice_version_id`
- `type`
- `operator`
- `value`
- `unit`
- `period_months`
- `scope`
- `required`
- `raw`
- `confidence`
- `evidence_keys`

## 10. Judgment contract

현재 Canonical object의 핵심 필드:

- `judgment_key`
- `preflight_case_id`
- `notice_version_id`
- `requirement_key`
- `status`
- `basis_type`
- `evidence_held`
- `reason_code`
- `requires_evidence`
- `profile_refs`
- `requirement_evidence_keys`
- `rule_version`

현재 Judgment service가 생성하고 JudgmentRun/Record에 저장합니다.

## 11. 구현된 경계와 남은 validation 과제

Analysis/Requirement/Evidence, Judgment, Answer, Revalidation 저장과 API는 구현되어 있다. 모델은 `analysis_models.py`, `judgment_models.py`, `ask_back_models.py`, `revalidation_models.py`다.

- LLM/RAG는 문서 이해·요건 추출·근거 연결을 담당한다. normalization, 최종 회사 비교, Askability, Diff는 deterministic code다.
- `UNKNOWN != ASKABLE`: 사용자에게 알려진 단일 사실로 안전하게 해결 가능한 조건만 질문한다. 복합 법률·절차·상동 표 참조는 mapping/rule/askability 공통 guard로 보류한다.
- Policy A: `apply_to_profile=false`, `basis_type=USER_ANSWER`; 해당 검토 판정만 갱신한다. Yes만으로 `evidence_held=true`가 되지 않는다. unsafe answer는 422, stale source는 409다.
- 답변은 Case 행 잠금과 최신 source/analysis/rule/company/profile 검증을 거친다.
- Diff는 `UNCHANGED / MODIFIED / ADDED / REMOVED`. 의미 일치를 우선하고 key fallback을 적용하며 raw 변경도 MODIFIED다. UNCHANGED는 유효 source record가 있을 때 승계하고 없으면 재판정한다.
- 재검증은 baseline source analysis, 최신 baseline judgment, 동일 reference_date/rule/profile snapshot을 요구한다.
- AI contract `ai-analysis-v0.2`와 Rule `qualification-rules-v0.2`는 별도다. 기존 AnalysisRun은 동일 contract 또는 SUCCEEDED라는 이유만으로 새 grounding/validation 정책을 충족하지 않는다. 자동 재검증/캐시 무효화는 미구현이다.
- PR #74 merge 이후 기존 Demo/Golden Case는 [운영 절차](06-handoff-and-merge.md)에 따라 **full re-analysis**해야 한다. Rule 재판정만으로 이전 추출 문제를 해결할 수 없다.
- `EvaluationCriterion`/`EvaluationAnalysisResult` foundation은 존재하지만 Evaluation 전용 extraction/API/제품 연결은 미완료다.

## 12. Change rule

계약을 바꿀 때는 다음 원칙을 적용합니다.

- 새 optional field 추가는 비교적 자유롭게 진행합니다.
- stable ID 의미를 변경하지 않습니다.
- 기존 field name/type/meaning 변경은 관련 영역에 공유합니다.
- LLM prompt나 retriever 내부 구현은 contract를 깨지 않는 범위에서 자유롭게 교체할 수 있습니다.
- 실제 구현이 문서와 다르면 실제 상태를 먼저 기록하고 팀 합의로 contract를 갱신합니다.
