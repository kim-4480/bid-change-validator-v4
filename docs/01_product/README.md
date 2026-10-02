# Product 문서 안내

> **상태: Current**  
> 기준: `develop` + Figma 7개 화면 + 2026-09-10 팀 결정

이 문서는 제품 고도화 전에 팀이 같은 사용자 흐름과 현재 범위를 보도록 하는 기준선입니다. 상세 구현은 각 기술 문서에서 관리합니다.

## 제품 목표

원공고를 기준으로 준비한 자격판정과 근거를 확인하고, 변경공고 이후에도 기존 판단이 유효한지 Requirement 단위로 다시 검증합니다.

제품 Vision에는 공고 찾기·자격판정·계약 위험조항 확인·평가 대응·변경 재검증이 포함됩니다. 현재 Release Spine은 **Qualification + Evidence + Ask-back + Contract Risk Clause + Change Revalidation**입니다.

`05 평가 대응`은 Frontend에서 화면/사용자 흐름 구조를 확정한 뒤 Backend/AI Contract를 정합니다. **점수 예측은 MVP 범위에서 제외**합니다.

## 현재 사용자 흐름

```text
회사 Profile
→ 공고 조회/선택
→ Preflight Case / 현재 Version
→ 문서 Parsing
→ Requirement Extraction + Evidence
→ deterministic Judgment
→ Askable UNKNOWN 해결
→ Evidence 원문 확인
→ 계약 위험조항 9종 확인
→ 변경공고 Requirement Diff
→ affected-only Revalidation
```

## 현재 화면 기준

| 순서 | Route | 역할 |
| --- | --- | --- |
| 01 | `/notices` | 공고 찾기 / 분석된 공고 후보 확인 |
| 02 | `/qualification` | 참가자격 분석·판정 결과 |
| 03 | `/ask-back` | 확인 가능한 UNKNOWN에 답변 |
| 04 | `/evidence` | 판정 근거 원문 대조 |
| 05 | `/evaluation` | **Pending Frontend Design** · 화면 구조 확정 후 Backend/AI Contract 결정 · 점수 예측 제외 |
| 06 | `/changes` | 변경공고 Diff / 영향 확인 |
| 07 | `/company` | 회사 Profile 관리 |

Figma는 화면 IA와 UX 방향의 Source of Truth이며, 실제 지원 기능과 상태는 `develop` 코드/API를 우선합니다.

## 계약 위험조항 · MVP Current

위험조항 검토는 MVP에 포함합니다. 현재 taxonomy는 9종입니다.

- `WARRANTY_PERIOD`
- `LATE_PENALTY`
- `LATE_PENALTY_RATE`
- `COPYRIGHT_OWNERSHIP`
- `ACCEPTANCE_CRITERIA`
- `SCOPE_AMBIGUITY`
- `TERMINATION_CONDITION`
- `PAYMENT_TERMS`
- `LIABILITY_SCOPE`

위험조항 `category`는 **AI Core가 분류**하고, Backend는 이를 별도 규칙으로 재분류하지 않고 저장하는 경계를 사용합니다. Frontend는 저장된 category를 사용자용 Label로 표현합니다.

## 초기 기획 ↔ Current 구현 Reconciliation

초기 Notion 문서는 제품 의도와 의사결정 배경으로 보존합니다. 아래 항목은 현재 구현 정책이 발전한 부분이므로 초기 문구를 그대로 재구현하지 않습니다.

| 초기 기획 표현 | Current 기준 |
| --- | --- |
| 자격 7유형 | Qualification Canonical **8유형** (`COMPANY_SIZE` 포함) |
| 🟢/🔵/🟡/🔴 4상태를 판정 상태처럼 사용 | 개별 `SATISFIED/UNSATISFIED/UNKNOWN` + `basis_type` + 전체 `overall_status`로 분리 |
| `confidence: low`이면 Ask-back | **Superseded**. `UNKNOWN != ASKABLE`; grounding/diagnostic/profile completeness/askability를 분리 |
| Ask-back 답변을 자동 Profile 저장 | 현재 MVP Policy A는 기본 `apply_to_profile=false`; `USER_ANSWER` 판정 근거로 사용 |
| RAG = Vector DB 전제 | 현재 Core는 section/keyword Retrieval baseline. Vector/Hybrid/Reranker는 평가 후 선택 후보 |
| 05 Evaluation이 완성된 핵심 흐름 | Route는 존재하지만 최종 UX/Contract는 **Pending Frontend Design** |
| 위험조항 8종 | 현재 MVP taxonomy는 **9종** |

## 기존 Proposal Preflight 기능

통합 전 Backend Prototype에 있던 제안서 업로드·Parsing·누락검사·원문 비교 기능은 폐기 대상으로 보지 않습니다. 다만 `05 평가 대응`의 최종 구조가 아직 미정이므로, Frontend 구조가 나온 뒤 현재 Product Contract에 맞춰 재사용 범위를 결정합니다.

## MVP 데모 / Golden 데이터 방향

- 데모 인증은 **관리자 로그인** 기준으로 진행합니다.
- 자격판정 Evaluation은 특정 회사 1개에 과적합되지 않도록 **합성 회사 Profile 여러 개**를 Golden Set에 사용합니다.
- 실제/합성 여부와 사용한 `company / notice / version / analysis / judgment run` 식별자를 함께 기록합니다.

## 제품 불변조건

- LLM이 최종 참가 가능/불가를 직접 결정하지 않습니다.
- `UNKNOWN`은 곧바로 사용자 질문 가능 상태가 아닙니다.
- `PARTIAL` Analysis를 완전한 성공처럼 표현하지 않습니다.
- 변경 전 결과를 덮어쓰지 않고 Version / Run 단위로 추적합니다.
- 결과에는 추적 가능한 Requirement / Evidence가 연결되어야 합니다.
- 현재 회사 Profile과 과거 Judgment의 `profile_snapshot`을 구분합니다.
- AI Copilot은 기존 Product Judgment를 설명하며 별도 판정기를 만들지 않습니다.
- 위험조항 category는 Core 출력과 Backend 저장 경계를 분리해 이중 분류를 만들지 않습니다.

## 현재 고도화 포인트

- 현재 section/keyword Retrieval과 Requirement Extraction 품질 정량화
- 위험조항 9종의 실제 문서 Extraction/Evidence/API/UI 연결 고도화
- meaningful 변경공고 G2 확보
- 05 평가 대응 Frontend 구조 확정 후 Contract 정의
- 01→02→03→04→06 Human Click Golden Story
- Figma 최신 7 Frame visual QA
- Production Deployment 구조 확정 및 Smoke Test
- AI Copilot을 기존 Product API 위에 추가

## 상세 Current 문서

- [Feature Traceability](../02_architecture/feature-traceability.md)
- [AI Retrieval Current State](../03_ai/retrieval-current-state.md)
- [DB ERD](../04_contracts/db-erd-current.md)
- [Backend API Catalog](../04_contracts/backend-api-catalog.md)
- [Frontend Screen Contract](../05_ui_ux/frontend-screen-contract.md)
- [Requirement/Test/Golden Traceability](../08_qa_reports/requirement-test-traceability.md)

## 변경 체크리스트

제품 흐름 또는 화면 범위를 변경하는 PR에서는 다음을 확인합니다.

- Figma와 실제 Route 영향
- Backend/API/DB/AI Contract 영향
- 초기 기획과 Current 정책 중 무엇을 변경하는지
- 기존 Case / Version / Analysis / Judgment lineage 호환성
- Golden/E2E 시나리오 수정 필요 여부
- 중요한 범위 변경의 Decision Log/ADR 필요 여부
