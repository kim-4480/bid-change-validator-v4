# Backend / API Baseline

> **상태: Current**  
> 기준: `develop`

이 문서는 현재 Backend/API의 책임과 주요 진입점을 정리합니다. 실제 Endpoint 목록과 주요 경계는 [Backend API Catalog](backend-api-catalog.md)를 함께 봅니다. 정확한 Request/Response 스키마는 코드와 Swagger가 최종 Source of Truth입니다.

## Backend 책임

- 회사 Profile 저장/조회
- 나라장터 Notice / Version / Document 저장 및 조회
- Preflight Case 관리
- Qualification Analysis 실행/조회
- Qualification Judgment 실행/조회
- Ask-back 질문/답변 및 부분 재판정
- 변경공고 Revalidation
- Profile → Notice Matching
- 공통 오류 응답 및 상태 관리

## Router 등록 기준

`apps/api/app/main.py`에서 다음 Router가 등록됩니다.

- Companies
- Master Codes
- Notices
- Preflight Cases
- Qualification Analysis
- Qualification Judgment
- Qualification Ask-back
- Qualification Revalidation
- Qualification Matching

## 공통 API 원칙

- API prefix는 `/api/v1`을 사용합니다.
- 공통 오류는 `ApiError` 형식으로 `{ error: { code, message, details } }`를 반환합니다.
- 요청 Validation 오류는 `422 INVALID_REQUEST` 형식으로 정규화합니다.
- 현재 Case / Company / Notice Version과 맞지 않는 오래된 Run을 그대로 재사용하지 않습니다.
- Analysis/Judgment/Answer/Revalidation의 Run lineage를 보존합니다.

## Qualification 관련 주요 흐름

```text
Preflight Case
  ↓
Qualification Analysis
  ↓
Qualification Judgment
  ↓
UNKNOWN
  ↓
Askability
  ↓
Answer + Partial Re-judgment
  ↓
Changed Notice
  ↓
Qualification Revalidation
```

상세 Endpoint: [backend-api-catalog.md](backend-api-catalog.md)

## Copilot 연계 원칙

AI Copilot은 이 Product API를 우선 소비합니다. 다음 기능을 별도 구현하지 않습니다.

- 자격판정 재구현
- Ask-back 재구현
- 변경공고 재판정 재구현
- DB 직접 조회를 통한 비공식 판정

Copilot은 API 결과를 조합·설명하는 Orchestration Layer 역할을 가집니다. 현재 Copilot API 자체는 **Proposed / 미구현**입니다.

## Known Gaps / 고도화 후보

- API 도메인 파일이 `apps/api/app/` 최상위에 증가하고 있어 패키지 분리 여부 검토 가능
- Evaluation 전용 API 범위 미확정
- Copilot용 Tool Adapter/API 추가 필요
- 운영 환경 인증/권한 정책은 별도 확정 필요

## 변경 체크리스트

- Response Schema 변경 여부
- 기존 Frontend 호환성
- Migration 필요 여부
- stale Run / Version 검증 유지 여부
- Error Code 변경 여부
- AI/Core Contract 영향
- [Backend API Catalog](backend-api-catalog.md) 갱신 필요 여부
- Swagger와 docs 동기화 여부
