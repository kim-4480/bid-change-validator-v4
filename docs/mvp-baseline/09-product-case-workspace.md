# 09. Product Case Workspace — Figma 02~06 Baseline

> 기준: Figma 02 참가자격 검토 / 03 확인 필요에 답하기 / 04 근거 원문 대조 / 05 평가 대응 / 06 변경 이력

기준: PR #74 코드 `87b9a5f`. Figma 01~07이 Product IA Source of Truth이며 이 문서는 그중 02~06 공유 workspace의 구현 계약이다. 01 공고 찾기와 07 회사 프로필까지 route 연결/navigation smoke는 완료했고, 실제 변경공고까지 전체 E2E는 미완료다.

## 1. 목표

하나의 `PreflightCase`를 중심으로 다음 데이터를 공유하는 Product Workspace가 구현되어 있다.

```text
caseId
→ Notice + NoticeVersion
→ Company Profile
→ Qualification Analysis + Canonical Requirement + Evidence
→ Qualification Judgment
→ Ask-back USER_ANSWER
→ Changed-notice Requirement Diff / Revalidation
```

화면별로 서로 다른 case를 다시 선택하지 않고 동일한 `caseId`를 유지하는 것이 기준이다.

## 2. Figma 화면과 실제 기능

| 화면 | Route | Product Baseline 기능 |
| --- | --- | --- |
| 02 참가자격 검토 | `/qualification?caseId=...` | Requirement + 회사값 + Judgment + Evidence |
| 03 확인 필요에 답하기 | `/ask-back?caseId=...` | 질문 가능한 UNKNOWN만 답변, 부분 재판정 |
| 04 근거 원문 대조 | `/evidence?caseId=...` | 첨부문서 extracted text/blocks + Evidence + Judgment 대조 |
| 05 평가 대응 | `/evaluation?caseId=...` | 자격요건 기반 회사 참고자료 + 원문 근거; Evaluation 전용 추출 미완료 |
| 06 변경 이력 | `/changes?caseId=...` | NoticeVersion 비교 + Canonical Diff + affected-only Revalidation |

## 3. Ask-back 정책 — Product Baseline A

현재 Baseline은 **A 방식**을 사용한다.

```text
사용자 답변
→ QualificationAnswer 저장
→ basis_type=USER_ANSWER
→ 해당 Requirement만 부분 재판정
→ Company Profile 자체는 변경하지 않음
```

UI 문구:

> 이 답은 이번 검토의 판정 근거로 저장됩니다.

Backend 요청은 계속 `apply_to_profile=false`를 사용한다. UNKNOWN 전체가 아니라 ASKABLE만 답변하며 unsafe 422 / stale 409를 처리한다. 최신 analysis/source/rule/profile을 검증하고 Yes만으로 evidence_held를 true로 바꾸지 않는다.

### 왜 A를 사용하는가

사용자가 `예/아니오` 또는 간단한 정규화 값만 답한 경우, 그 답을 곧바로 회사의 영구 Master Profile fact로 승격하기에는 provenance와 구조화 정보가 부족할 수 있다.

예:

- `정보통신공사업 등록 보유`는 Certification 후보가 될 수 있음
- `최근 AI 사업 경험 3건`은 각 실적의 사업명/발주기관/금액/기간이 없어 Performance row로 안전하게 승격할 수 없음

따라서 현재는 검토 건의 판정 근거로만 보존한다.

## 4. 후속 고도화 B — USER_ANSWER → Company Profile Promotion

후속 고도화 후보:

```text
USER_ANSWER
→ 답변 타입/Requirement 타입 확인
→ Profile promotion 가능 여부 판정
→ 추가 필수값 요청
→ provenance 포함 Company fact 생성/수정
→ 다른 공고 판정에서도 재사용
```

필요 설계:

1. Requirement type별 promotion mapping
2. Certification / Performance / Staff / Industry 등 엔터티별 필수 필드
3. USER_ANSWER provenance와 사용자가 직접 입력한 Profile fact 구분
4. 검증/verified 상태 정책
5. 기존 판정에 대한 재평가 정책

이 기능은 Product Baseline 완료 후 별도 고도화 항목으로 관리한다.

## 5. 04 Evidence 원칙

- Backend `extracted_blocks` / extracted text가 원문 표시의 Source of Truth
- Canonical Evidence의 `document_id`, `quote`, `location`을 판정과 연결
- 원문을 화면에서 임의 요약하거나 고쳐 쓰지 않음
- raw 전체와 세부 필드가 실제 source chunk에 있는지 검증하고 reference도 source-local로 검증함
- document ID별 텍스트/근거 상태를 유지하며 부분 추출 거절·잘림은 PARTIAL diagnostic으로 보존함
- HWP/HWPX의 브라우저 미리보기 한계가 있는 경우 source endpoint 또는 extracted text를 사용

## 6. 05 평가 대응 정책

Figma 원칙대로 **점수를 예측하지 않는다.**

Backend `apps/api/app/ai/evaluation_contracts.py`에 `EvaluationCriterion` / `EvaluationAnalysisResult` foundation은 존재한다. **Evaluation 전용 extraction과 API/제품 연결은 아직 미완료**다. 현재 화면은 평가항목으로 오인하지 않도록 다음을 자격요건 참고자료로만 표시한다.

```text
공고 참가자격에서 구조화된 실적/인력/인증 관련 조건
+
회사 프로필 실제 값
+
원문 Evidence
→ 값 있음 / 확인 필요
```

후속 고도화:

- 기존 Evaluation contract에 전용 extraction 연결
- 배점표 row canonicalization
- 배점 원문 위치/버전 추적
- 제안서/제출서류 대응 근거 연결

점수 예측은 별도 정책 결정 전까지 Non-goal이다.

## 7. 06 변경 이력 원칙

두 층을 분리한다.

### NoticeVersion 원본 필드 변화

```text
bid_closed_at
estimated_price
allocated_budget
contract_method
documents
...
```

나라장터 수집값끼리 비교한다.

### 자격 판정 영향

```text
Canonical Requirement Diff
UNCHANGED / MODIFIED / ADDED / REMOVED
→ MODIFIED / ADDED affected-only revalidation
```

판정 영향은 UI가 임의 추정하지 않고 Backend Revalidation 결과를 Source of Truth로 사용한다. UNCHANGED는 유효 source record가 있을 때만 승계한다. source analysis와 최신 baseline judgment, reference_date/rule/profile snapshot을 검증한다.

## 8. 후속 E2E

```text
01 공고 찾기
→ 07 회사 프로필
→ 02 참가자격 분석/판정
→ 03 ASKABLE UNKNOWN 답변(USER_ANSWER)
→ 04 Evidence 대조
→ 05 평가 대응 확인
→ 06 변경공고 affected-only 재검증
```

이 흐름을 Golden Product Scenario와 사람이 직접 클릭하는 Product E2E의 기준으로 사용한다.

## 9. 결과 identity와 재분석

02~06은 현재 Case/version/company/analysis/Rule과 일치하는 결과를 표시한다. Rule은 `qualification-rules-v0.2`다. 필수 그룹 미달이면 ineligible, 그 외 UNKNOWN/분석 PARTIAL은 insufficient_data로 보류한다. 없는 Case/차수는 오류이며 다른 Case로 fallback하지 않는다.

기존 AnalysisRun은 새 validation을 자동 충족하지 않는다. PR #74 merge 후 기존 Demo/Golden은 [full re-analysis 절차](06-handoff-and-merge.md)를 따른다. Backend 코드 변경 후 `docker compose up -d --build api`가 필요하다. 기존 Proposal/문서 검증 기능은 유지되며 workspace의 미완료 Evaluation/Proposal RAG 통합과 구분한다.
