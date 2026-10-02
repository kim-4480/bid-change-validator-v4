# Core → Copilot Contract

> **문서 상태: Proposed**  
> 작성: 2026-09-10 · 기준: 최신 `develop`

## 목적

AI Copilot이 Core 내부 구현에 의존하지 않도록, Copilot이 소비할 안정된 결과 단위를 정의합니다.

```text
Document / Retrieval / Extraction / Rule
                ↓
          Core / Product Contract
                ↓
        Copilot Tool Adapter
                ↓
 Intent / Context / Grounded Narration
```

## 현재 Source of Truth

현재 `develop`에서 다음 Canonical 객체를 사용합니다.

- `QualificationRequirement`
- `Evidence`
- `Judgment`
- `RequirementAnalysisResult`
- `QualificationJudgmentRunRead`

`RequirementAnalysisResult.contract_version`은 현재 `ai-analysis-v0.2`입니다.

## 상태값

```text
AnalysisStatus
SUCCEEDED | PARTIAL | FAILED

JudgmentStatus
SATISFIED | UNSATISFIED | UNKNOWN

BasisType
PROFILE | USER_ANSWER | NONE

OverallQualificationStatus
eligible | ineligible | insufficient_data
```

`OverallQualificationStatus`는 Backend Judgment Run이 Source of Truth입니다. Copilot이 개별 Judgment를 보고 자체 집계하지 않습니다.

## 현재 Product API

Copilot 첫 구현에서 재사용할 수 있는 기존 API는 다음과 같습니다.

```text
POST /api/v1/preflight-cases/{case_id}/qualification-judgments
GET  /api/v1/preflight-cases/{case_id}/qualification-judgment-runs
GET  /api/v1/qualification-judgment-runs/{run_id}

GET  /api/v1/preflight-cases/{case_id}/qualification-questions
POST /api/v1/preflight-cases/{case_id}/qualification-answers

POST /api/v1/preflight-cases/{case_id}/qualification-revalidation
```

Copilot은 가능한 한 Core 내부 함수를 직접 조립하지 않고 승인된 Product Service/API 결과를 Tool Adapter로 감쌉니다.

## Copilot 최소 Context

| 데이터 | 용도 | Source |
| --- | --- | --- |
| `notice_id` | 공고 식별 | Backend |
| `notice_version_id` | 질문 대상 버전 고정 | Backend / Analysis |
| `preflight_case_id` | 회사·공고 검토 Context | Backend |
| `requirements[]` | 조건 설명 | AI Core |
| `judgments[]` | 충족/미달/확인필요 | Rule / Backend |
| `overall_status` | 전체 자격 상태 | Backend Judgment Run |
| `evidence[]` | 원문 Citation | AI Core |
| Ask-back questions | 추가정보 요청 가능 여부 | Askability / Backend |
| Revalidation result | 변경공고 영향 및 재판정 | Backend |
| `diagnostics[]` | PARTIAL·FAILED 등 안전한 보류 | AI Core |

## Copilot Adapter 응답 예시

기존 Pydantic 계약을 바로 변경하기보다 Copilot Tool Layer에서 필요한 결과를 조립하는 방향을 우선합니다.

```json
{
  "notice_id": "NOTICE-001",
  "notice_version_id": "VERSION-002",
  "case_id": "CASE-001",
  "analysis_status": "SUCCEEDED",
  "overall_status": "insufficient_data",
  "requirements": [
    {
      "requirement_key": "REQ-001",
      "type": "PERFORMANCE_AMOUNT",
      "raw": "최근 3년간 1억원 이상의 실적을 보유한 업체",
      "status": "UNSATISFIED",
      "reason_code": "RULE_MISMATCH",
      "evidence_keys": ["EVD-001"]
    }
  ],
  "evidence": [
    {
      "evidence_key": "EVD-001",
      "document_id": "DOC-001",
      "quote": "최근 3년간 1억원 이상의 실적을 보유한 업체",
      "location": {
        "display": "입찰공고 참가자격"
      }
    }
  ],
  "askable_items": [],
  "diagnostics": []
}
```

이 예시는 Copilot Adapter의 목표 shape이며 기존 Core Contract 자체를 이 구조로 즉시 바꾸자는 의미가 아닙니다.

## 의존성 규칙

- Copilot은 `chunking.py`, `requirement_extraction.py`, Retriever 구현을 직접 호출하지 않습니다.
- Copilot은 분석/판정 결과 Contract 또는 승인된 Product Service를 사용합니다.
- Core가 Keyword → Embedding → Hybrid → Reranker로 바뀌어도 외부 Contract는 유지합니다.
- 새 필드는 가능한 한 additive optional 방식으로 확장합니다.
- Breaking Change는 Core·Copilot·Backend 영향 범위를 함께 검토합니다.

## Grounding 규칙

- 참가 가능 여부는 Backend `overall_status`와 Judgment에 없는 내용을 생성하지 않습니다.
- Requirement를 설명할 때 `raw`의 의미를 임의로 바꾸지 않습니다.
- 근거를 요구하는 답변은 `Evidence.quote`와 location을 연결합니다.
- `PARTIAL`, `FAILED`, `UNKNOWN`, `insufficient_data`를 확정적 참가 가능으로 승격하지 않습니다.
- Askability가 허용하지 않은 UNKNOWN을 단순 Yes/No 질문으로 변환하지 않습니다.
- 최신 Analysis/Judgment/Notice Version 관계가 맞지 않으면 답변보다 재조회·재분석 상태를 우선합니다.

## 첫 Vertical Slice

```text
사용자
"이 공고 우리 회사 참여 가능해?"
        ↓
Conversation / Product Context
        ↓
현재 caseId 확인
        ↓
최신 Qualification Judgment 조회
        ↓
overall_status + judgments
        ↓
Requirement + Evidence 연결
        ↓
Grounding Guardrail
        ↓
자연어 답변 + Citation
```

첫 Vertical Slice에서는 공고 검색·Agent 자율 계획·Vector DB 추가보다 **기존 Product Judgment를 정확하게 대화로 설명하는 것**을 우선합니다.

## 확장 순서

1. `이 공고 참여 가능해?`
2. `왜 미달이야?`
3. `얼마 부족해?`
4. Ask-back 가능한 UNKNOWN에 사용자 답변
5. 부분 재판정 결과 설명
6. 변경공고 발생 후 Revalidation 결과 설명
7. 공고 검색·추천·비교 Tool 확장

## 확정 전 체크

- [x] Backend overall status Source 확인
- [x] Judgment API 확인
- [x] Ask-back API 확인
- [x] Revalidation API 확인
- [ ] 변경공고 상세 응답 Schema 검산
- [ ] Core 담당자와 Contract 필수/선택 필드 합의
- [ ] Copilot Adapter Prototype 검증
- [ ] 첫 Integration E2E 완료 후 `Current` 승격
