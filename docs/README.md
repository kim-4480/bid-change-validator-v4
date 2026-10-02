# 프로젝트 문서 안내

> **문서 상태: Current**  
> 기준 브랜치: `develop` · Product Integration Baseline은 PR #75로 `develop`에 병합 완료되었습니다.

이 문서는 `docs/`의 탐색 순서와 문서 상태를 안내하는 색인입니다. 과거 Baseline 문서와 현재 운영 문서를 구분해, 계획 문구를 현재 구현 사실처럼 읽지 않도록 합니다.

## 문서 상태

| 상태 | 의미 |
| --- | --- |
| **Current** | 현재 `develop` 코드·제품 운영에 적용되는 기준 |
| **Proposed** | 담당자/팀 합의 또는 코드 검증 전 설계안 |
| **Baseline Snapshot** | 특정 통합 시점의 재현·비교·인수인계 기준 |
| **Historical** | 당시 작업·초기 설계·과거 운영 기록 |
| **Superseded** | 후속 결정이나 최신 문서로 대체됨 |

## Source of Truth

| 대상 | 기준 |
| --- | --- |
| 실제 동작·Schema·상태 | **Code / Test** |
| 현재 기술 구조·실행·Contract | **GitHub `docs/`** |
| 기획 배경·논의·회의 맥락 | **Notion** |
| 현재 작업·담당·진행 상태 | **GitHub Projects / Issue** |
| 중요한 기술 결정 | Notion Decision Log → 안정화 후 ADR |

> Notion 문서를 그대로 복사해 Current 문서로 사용하지 않습니다. 현재 `develop`의 코드와 테스트를 대조해 실제 구현 기준으로 정제한 내용만 GitHub docs의 Current 기준으로 둡니다.

## 먼저 읽을 문서

1. [프로젝트 README](../README.md)
2. [Product 기준선](01_product/README.md)
3. [Architecture 기준선](02_architecture/README.md)
4. [Feature ↔ Screen ↔ API ↔ DB ↔ AI Traceability](02_architecture/feature-traceability.md)
5. [AI / RAG 문서 안내](03_ai/README.md)
6. [AI Retrieval Current State](03_ai/retrieval-current-state.md)
7. [Backend / API 기준선](04_contracts/backend-api.md)
8. [Backend API Catalog](04_contracts/backend-api-catalog.md)
9. [Data / DB 기준선](04_contracts/data-and-db.md)
10. [DB ERD · Current](04_contracts/db-erd-current.md)
11. [Frontend / UI·UX 기준선](05_ui_ux/README.md)
12. [Frontend Screen · Component · API Contract](05_ui_ux/frontend-screen-contract.md)
13. [현재 Ownership / Handoff](07_handoff/current-ownership.md)
14. [Local Run / Operations Runbook](07_handoff/runbook.md)
15. [QA / E2E 기준](08_qa_reports/README.md)
16. [Requirement ↔ Test ↔ Golden/E2E Traceability](08_qa_reports/requirement-test-traceability.md)
17. [Post-Baseline Roadmap](09_roadmap/README.md)
18. [Product Integration Baseline Snapshot](mvp-baseline/README.md)

## 현재 문서 체계

```text
docs/
├─ README.md
├─ 01_product/
│  └─ README.md
├─ 02_architecture/
│  ├─ README.md
│  └─ feature-traceability.md
├─ 03_ai/
│  ├─ README.md
│  ├─ parallel-boundary.md
│  ├─ core-copilot-contract.md
│  └─ retrieval-current-state.md
├─ 04_contracts/
│  ├─ backend-api.md
│  ├─ backend-api-catalog.md
│  ├─ data-and-db.md
│  └─ db-erd-current.md
├─ 05_ui_ux/
│  ├─ README.md
│  └─ frontend-screen-contract.md
├─ 06_decisions/
│  └─ README.md
├─ 07_handoff/
│  ├─ current-ownership.md
│  └─ runbook.md
├─ 08_qa_reports/
│  ├─ README.md
│  └─ requirement-test-traceability.md
├─ 09_roadmap/
│  └─ README.md
├─ mvp-baseline/          # 기존 Snapshot 보존
├─ contracts/             # 초기 계약 문서 보존
└─ parallel-development.md
```

## 문서 역할

- `README.md`: 빠른 탐색과 상태만 제공
- Traceability/Contract/ERD/Catalog: 구현을 바꾸기 전에 영향 범위를 확인하는 Current 문서
- `mvp-baseline/`: 과거 통합 기준선 Snapshot
- Notion: 제품 배경, 회의, 결정, Historical/Planning 원문

## Product Integration Baseline 이후 핵심 작업

- 담당별 기능·품질 병렬 고도화
- LLM/RAG Core와 AI Copilot의 파일/Contract 경계 확정
- 현재 section/keyword Retrieval baseline 정량 평가 후 Hybrid/Reranker 필요성 판단
- 실제 Extraction/Evidence 품질 평가 및 Golden Set 확장
- meaningful 변경공고 G2 확보 및 Revalidation 검증
- 01~07 Human Click E2E 및 UI/접근성 검증
- Production Deployment 구조 확정 및 Smoke Test

## 문서 갱신 규칙

- Contract 또는 Architecture가 바뀌면 관련 코드 PR에서 docs도 함께 수정합니다.
- API 변경 → `backend-api-catalog.md` 확인
- DB/Migration 변경 → `db-erd-current.md` 확인
- Route/Component/상태 변경 → `frontend-screen-contract.md` 확인
- Requirement/Rule/Askability 정책 변경 → `feature-traceability.md`, QA Traceability 확인
- Retrieval/Extraction 변경 → `retrieval-current-state.md`, Golden/Evaluation 갱신
- 논의 중인 설계는 `Proposed`로 표시하고 합의·구현 전 Current라고 쓰지 않습니다.
- 실제 Task 일정/담당/Status를 docs에 중복 관리하지 않고 GitHub Projects/Issue를 사용합니다.
