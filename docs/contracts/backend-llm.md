# Backend ↔ LLM / RAG Contract

> Status: DRAFT v0.1
> 목적: Backend와 LLM / RAG가 독립적으로 구현·실험하면서도 최소한의 입출력 경계를 공유하기 위한 초안입니다. 최종 모델 API 스펙이 아닙니다.

## Responsibility Boundary

### Backend

- 나라장터 공고 / 변경공고 원문 및 메타데이터 제공
- 사용자 / 기업 프로필 제공
- LLM / RAG 호출 및 timeout / retry / 오류 처리
- 결과 저장 및 Frontend 전달

### LLM / RAG

- 문서 chunking / retrieval / reranking 등 검색 로직
- 자격조건 해석 및 판정
- 판정 근거 구성
- 부족 정보 식별
- Guardrail 및 Evaluation

## Suggested Input

```json
{
  "request_id": "string",
  "notice": {
    "notice_id": "string",
    "title": "string",
    "version": "string",
    "published_at": "2026-09-05T00:00:00+09:00",
    "content": "string"
  },
  "company_profile": {
    "company_id": "string",
    "business_type": "string",
    "licenses": ["string"],
    "regions": ["string"]
  },
  "task": "qualification_check"
}
```

## Suggested Output

```json
{
  "request_id": "string",
  "decision": "eligible",
  "summary": "string",
  "checks": [
    {
      "code": "LICENSE_REQUIRED",
      "status": "passed",
      "reason": "string"
    }
  ],
  "evidence": [
    {
      "source_id": "string",
      "page": 12,
      "section": "string",
      "quote": "string",
      "retrieval_score": 0.92
    }
  ],
  "missing_conditions": [],
  "warnings": [],
  "model_meta": {
    "provider": "string",
    "model": "string",
    "prompt_version": "string"
  }
}
```

## Suggested Decision Values

- `eligible`
- `ineligible`
- `needs_review`
- `insufficient_data`

## Evidence Rule

- 판정에 영향을 준 근거는 가능한 한 `evidence`에 포함합니다.
- 근거가 부족한 경우 억지로 확정 판정을 내리기보다 `needs_review` 또는 `insufficient_data`를 사용할 수 있습니다.
- `quote`는 화면에 그대로 노출될 수 있으므로 원문 근거와 연결 가능한 형태를 권장합니다.

## Change Rule

- 내부 prompt / retriever / vector DB 구조는 자유롭게 변경할 수 있습니다.
- Backend가 의존하는 출력 필드의 이름 / 타입 / 의미를 변경할 때는 공유합니다.
- 새 실험 필드는 optional로 추가하는 것을 권장합니다.
- 실제 구현이 초안보다 먼저 안정되면 코드 동작을 기준으로 계약 문서를 갱신합니다.
