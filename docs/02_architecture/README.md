# Architecture 문서 안내

> **상태: Current**  
> 기준: `develop`

이 문서는 전체 제품 구조의 현재 연결과 책임 경계를 설명합니다. 상세 기능 영향은 [Feature ↔ Screen ↔ API ↔ DB ↔ AI Traceability](feature-traceability.md)를 함께 봅니다.

## System Overview

```text
Frontend (apps/web)
        ↓ HTTP
FastAPI (apps/api/app)
        ↓
Product Services
├─ Notice / Document
├─ Company Profile
├─ Preflight Case
├─ Qualification Analysis
├─ Qualification Judgment
├─ Ask-back
├─ Revalidation
└─ Matching
        ↓
PostgreSQL + Document Storage
        ↕
AI Core (app/ai)
```

## 주요 경계

### Frontend
- `apps/web/app/**`의 7개 주요 Route가 제품 IA를 구성합니다.
- 02~06은 같은 `caseId`를 공유하는 Workspace입니다.
- Backend API를 소비하고 Product 상태를 표시합니다.

### Backend / Product Service
- FastAPI `main.py`에서 Companies, Master Codes, Notices, Preflight Case, Qualification Analysis/Judgment/Ask-back/Revalidation/Matching Router를 등록합니다.
- DB 저장·조회, 현재 Case/Version, 상태 전이를 소유합니다.

### AI Core
- 비정형 공고문에서 Requirement/Evidence를 생성하고 deterministic Rule 판정에 필요한 구조를 제공합니다.
- DB PK, HTTP 상태, 현재 공고 Version의 Source of Truth를 소유하지 않습니다.
- 현재 Retrieval baseline은 section/keyword candidate selection이며 Vector/Hybrid는 아직 실험 후보입니다.

### Data
- PostgreSQL을 운영 데이터 저장소로 사용합니다.
- 원본 문서는 Local Volume 또는 설정에 따라 S3-compatible storage로 확장 가능한 인터페이스를 사용합니다.
- Version/Run lineage는 과거 판정 재현과 변경 재검증의 핵심입니다.

## Dependency Direction

```text
UI
 ↓
API / Product Service
 ↓
Domain / AI Core
 ↓
Data / External Provider
```

하위 레이어가 상위 UI 흐름에 의존하지 않도록 유지합니다.

## 상세 Current 문서

- [Feature Traceability](feature-traceability.md)
- [Backend API Catalog](../04_contracts/backend-api-catalog.md)
- [DB ERD · Current](../04_contracts/db-erd-current.md)
- [Frontend Screen Contract](../05_ui_ux/frontend-screen-contract.md)
- [AI Retrieval Current State](../03_ai/retrieval-current-state.md)
- [Requirement/Test/Golden Traceability](../08_qa_reports/requirement-test-traceability.md)

## 현재 주요 실행 구성

`docker-compose.yml` 기준:

- `db`: PostgreSQL 16
- `migrate`: Alembic migration 실행
- `api`: FastAPI
- `notice-poller`: 나라장터 변경공고 수집 Worker
- `master-data-import`: 업종/품목/기관 기준정보 적재 도구
- volumes: `postgres_data`, `notice_documents_data`

## Known Gaps

- `infra/`는 현재 실질 구현이 없는 상태이며 배포 구조가 확정되면 별도 문서로 승격합니다.
- API 도메인 모듈이 `apps/api/app/` 최상위에 증가하고 있어, 기능 확장 시 패키지 재구조화 여부를 검토할 수 있습니다.
- AI Copilot은 Proposed 상태이며 기존 Product API 위에 별도 Orchestration Layer로 추가하는 방향을 검토합니다.
- meaningful changed-notice G2와 전체 Human Click E2E는 아직 완료 기준이 닫히지 않았습니다.

## 변경 체크리스트

Architecture 변경 PR은 다음을 확인합니다.

- Source of Truth가 어느 레이어인지
- 새로운 의존 방향이 역전되지 않는지
- API/DB Contract 변경 여부
- Migration 필요 여부
- Frontend Route 영향
- Test / Golden / E2E 영향
- `feature-traceability.md` 갱신 필요 여부
- ADR 작성이 필요한 결정인지
