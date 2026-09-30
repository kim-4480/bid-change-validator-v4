# Parallel Development Workspaces

> Status: Weekend parallel-work guideline

메인 통합 저장소가 안정화되기 전, 주말 동안 빠르게 병렬 개발하기 위한 3개 workspace를 운영합니다.

## Workspaces

### Frontend

- Repository: https://github.com/gyuniverse-hq/bid-change-validator-frontend
- Main: 황수빈
- Sub: 이홍규
- Scope: 화면설계 반영, UI / UX, Frontend 구현, Backend API 연동

### Backend / Data

- Repository: https://github.com/gyuniverse-hq/bid-change-validator-backend
- Backend / API: 전진환
- DB / Data: 정예린
- Scope: API, DB, 나라장터 실제 데이터 연결, Backend 비즈니스 로직, LLM / RAG 결과 연동

### LLM / RAG

- Repository: https://github.com/gyuniverse-hq/bid-change-validator-llm-rag
- Owners: 김재현, 이홍규
- Scope: 문서 분석, RAG, 참가 자격 판정, 근거 인용, Guardrail, Evaluation

## Working Principle

주말 병렬 작업에서는 빠른 실험과 구현을 우선합니다.

- 각 workspace의 `main` / `develop`은 현재 별도 보호 규칙을 강제하지 않습니다.
- 기능 브랜치 사용은 권장하지만, 초기 프로토타이핑을 막는 수준의 규칙은 두지 않습니다.
- 영역 간 충돌을 줄이기 위해 API와 LLM 입출력 형식은 공통 계약 문서에서 맞춥니다.
- 계약 문서는 초기에는 `DRAFT v0.1`이며 구현을 강제하는 최종 스펙이 아닙니다.
- 구조가 안정된 뒤 메인 저장소 통합 방식은 다시 결정합니다.

## Integration Boundary

```text
Frontend
   ↓
Backend API
   ↓
┌──────────────┐
│ DB / Data    │
└──────────────┘
   ↓ / ↔
LLM / RAG
   ↓
판정 결과 + Evidence
```

## Shared Contracts

- Frontend ↔ Backend: `docs/contracts/frontend-backend.md`
- Backend ↔ LLM / RAG: `docs/contracts/backend-llm.md`

계약 변경이 필요하면 구현을 멈추기보다 먼저 변경안을 제안하고, 팀 합의 후 문서를 갱신합니다.
