# Current Ownership / Handoff

> **상태: Current Ownership + Contract 세부 조정 중**  
> 기준: `develop` 이후 병렬 고도화 단계 · 2026-09-10 역할 합의 반영

이 문서는 각 담당자가 어디를 주로 수정하고, 다른 파트와 어떤 Contract에서 만나는지 정리합니다. 역할은 소유권을 명확히 하기 위한 기준이며 Review나 의견 제시를 제한하지 않습니다.

## 현재 담당 기준

| 영역 | 주 담당 | 주요 경계 |
| --- | --- | --- |
| Frontend / UI·UX | 황수빈 | `apps/web/**`, Figma ↔ Product API |
| Backend / API | 전진환 | `apps/api/app/**` Product Service/API |
| DB / Data | 정예린 | Schema, Migration, Supabase 공유 DB, data integrity |
| LLM/RAG Core + Evaluation | 김재현 | `apps/api/app/ai/**`, Core quality, 위험조항 9종 |
| AI Copilot + Integration | 이홍규 | 신규 `apps/api/app/copilot/**`, Product API orchestration, docs/integration |

> **AI Core / Copilot 역할 분리는 합의 완료**입니다. 다만 `app/copilot/**`의 실제 세부 폴더와 Core → Copilot Contract는 구현·테스트를 거치며 Current로 고정합니다.

## Handoff 원칙

- 담당자의 내부 구현보다 **Contract와 테스트 가능한 결과**를 넘깁니다.
- 다른 파트가 내부 파일을 직접 참조해야 한다면 먼저 공개 Contract/API 추가를 검토합니다.
- 작업 완료는 구현만이 아니라 Test/문서 갱신까지 포함합니다.
- 현재 Required approval은 0명이지만, 영향이 큰 변경은 필요 시 Review를 요청합니다.
- Breaking Change는 관련 담당자에게 먼저 영향 범위를 공유합니다.

## 주요 파트 간 Handoff

```text
DB/Data
  ↓ Schema / persisted state
Backend
  ↓ Product API / current context
Frontend

Backend extracted_blocks
  ↓
AI Core
  ↓ Requirement / Evidence / Risk Clause category
Backend Judgment / Revalidation / persistence
  ↓
Copilot / Frontend
```

### 위험조항 Contract

```text
김재현 AI Core
→ 위험조항 9종 category + 근거
→ Backend는 category를 재분류하지 않고 저장
→ Frontend는 사용자용 Label로 표현
```

## 05 평가 대응

`/evaluation`의 최종 UX/Contract는 **Pending Frontend Design**입니다.

- 점수 예측은 MVP 제외
- Frontend 구조안 수신 전 Backend/AI 세부 Contract 확정 금지
- 통합 전 Backend Prototype의 Proposal 업로드·Parsing·누락검사 기능은 Reference로 보존하고 재사용 범위를 추후 결정

## Branch 기준

모든 신규 작업은 최신 `develop`에서 Branch를 분기합니다.

예시:

```text
develop
├─ feat/... frontend
├─ feat/... backend
├─ feat/... data
├─ feature/llm-core-hardening
└─ feature/ai-copilot
```

PR #77처럼 `main`을 직접 base로 둔 예외 작업은 재작업 요청 상태이며, 일반 기능 통합 기준은 `develop`입니다.

## Handoff 체크리스트

PR 전 다음을 남깁니다.

- 무엇을 변경했는가
- 공개 Contract/API가 바뀌었는가
- 다른 담당자가 이어서 해야 할 일
- 실행/테스트 방법
- Known limitation
- Migration / env 변경
- 문서 갱신 위치

## 현재 공통 다음 단계

- Frontend: Figma visual QA / Human Click E2E / 05 평가 대응 구조안
- Backend: API 경계·오류·도메인 모듈 고도화 / Migration lineage reconciliation
- DB: Supabase 공유 DB 기준 Migration 정합성 / provenance / Golden data
- AI Core: 실제 데이터 Extraction/Retrieval/Evidence Evaluation + 위험조항 9종
- Copilot: Product API 기반 첫 ELIGIBILITY Vertical Slice
- Integration: 배포 구조는 TBD로 유지하며 Current 문서와 코드의 차이를 계속 검산
