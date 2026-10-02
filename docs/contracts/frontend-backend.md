# Frontend ↔ Backend Contract

> Status: DRAFT v0.1
> 목적: 주말 병렬 개발 중 Frontend와 Backend가 서로 기다리지 않고 작업하기 위한 최소 인터페이스 초안입니다. 최종 API 스펙이 아니며 구현 과정에서 변경 가능합니다.

## Responsibility Boundary

### Frontend

- 사용자 입력 수집
- 요청 전송 및 로딩 / 오류 상태 표현
- Backend 응답을 화면에 표시
- 판정 → 근거 → 해결 흐름을 UI로 구성

### Backend

- 요청 검증
- DB 조회 및 저장
- 나라장터 데이터와 사용자 프로필 결합
- 필요 시 LLM / RAG 호출
- Frontend에 안정된 응답 형태 제공

## Suggested API Shape

### Qualification Check

`POST /api/v1/qualification/check`

Request example:

```json
{
  "notice_id": "string",
  "company_id": "string",
  "profile": {
    "business_type": "string",
    "licenses": ["string"],
    "regions": ["string"]
  }
}
```

Response example:

```json
{
  "request_id": "string",
  "status": "eligible",
  "summary": "string",
  "checks": [
    {
      "code": "LICENSE_REQUIRED",
      "status": "passed",
      "label": "string",
      "reason": "string"
    }
  ],
  "evidence": [
    {
      "source_id": "string",
      "page": 12,
      "section": "string",
      "quote": "string"
    }
  ],
  "missing_conditions": []
}
```

## Suggested Status Values

- `eligible`
- `ineligible`
- `needs_review`
- `insufficient_data`

세부 check 상태는 다음 정도로 시작할 수 있습니다.

- `passed`
- `failed`
- `unknown`
- `warning`

## Error Shape

```json
{
  "error": {
    "code": "INVALID_REQUEST",
    "message": "string",
    "details": null
  }
}
```

## Change Rule

- 필드 추가는 비교적 자유롭게 진행합니다.
- 기존 필드 이름 / 의미 / 타입을 바꿀 때는 Frontend와 Backend 양쪽에 공유합니다.
- 아직 확정되지 않은 필드는 코드에서 강하게 의존하지 않습니다.
- 구현이 먼저 진행된 경우 실제 동작을 기준으로 이 문서를 갱신할 수 있습니다.

## Notice document viewer

HWP/HWPX rendering uses rhwp WebAssembly in the frontend. PDF rendering uses an
inline PDF viewer. The backend remains responsible for original-byte storage,
download integrity, and extracted source blocks.

See `docs/contracts/rhwp-viewer.md` for the document metadata, source URL, and
text-location contract.

### Proposal preflight flow

1. `POST /api/v1/preflight-cases` with a notice id and optional baseline/current
   version numbers.
2. Upload HWP/HWPX/PDF through
   `POST /api/v1/preflight-cases/{case_id}/documents` as multipart form data.
3. Reload `GET /api/v1/preflight-cases/{case_id}` and render each returned
   `render_source_url` or `preview_url`.
4. Use `text_url` only for comparison/search and source highlighting.

The backend does not generate the comparison judgment in this flow. A later
contract can attach externally produced findings to the stable case, document,
version, and block identifiers.
