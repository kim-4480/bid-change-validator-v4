# AI / RAG 문서 안내

> **문서 상태: Current + Proposed 혼재**  
> 기준 브랜치: `develop` · 역할 분리 합의: 2026-09-10

이 폴더는 Product Integration Baseline 이후 AI 영역을 **Core Intelligence**와 **AI Copilot**으로 나누고, 병렬 개발 시 파일 소유권과 Contract 경계를 관리합니다.

## 역할 상태

역할 분리는 합의 완료 상태입니다.

- **김재현 = LLM/RAG Core + Evaluation**
- **이홍규 = AI Copilot + Integration**

다만 역할 합의와 구현 완료는 구분합니다. `app/copilot/**`의 구체 폴더/Contract/API는 실제 구현과 테스트를 거쳐 Current로 승격합니다.

## 현재 AI 구조

```text
나라장터 / 첨부문서
        ↓
Backend Parsing / extracted_blocks
        ↓
app.ai
├─ Semantic Chunking
├─ Eligibility section / keyword candidate selection
├─ Requirement Extraction
├─ Source-grounding validation
├─ Canonical Mapping / Normalization
├─ Evidence
├─ Askability Guardrail
├─ Contract Risk Clause classification
├─ deterministic Judgment
└─ Requirement Diff / Revalidation 기반
        ↓
Backend Product API / DB
        ↓
app.copilot (Role Accepted · 구현 진행 대상)
├─ Intent
├─ Product Context
├─ Tool Adapter
├─ Grounding Guardrail
└─ Narration
        ↓
사용자 대화 UI
```

## 현재 Retrieval 사실

현재 Qualification Core에는 **Vector DB / Dense Retriever / Hybrid Retriever / Reranker가 Production 기능으로 구현되어 있지 않습니다.**

현재 baseline은:

```text
Semantic Chunks
→ 참가자격 section anchor
→ keyword fallback
→ candidate context
→ LLM structured extraction
```

이며 structured extraction 입력은 현재 최대 32,000 characters입니다.

실제 공고 측정에서 Retrieval 자체뿐 아니라 **Evidence/Guardrail에서 Requirement가 탈락하는 원인**이 중요한 품질 이슈로 확인됐으므로, 고도화 순서는 측정 → Drop Diagnostic → Evidence/Guardrail → Retrieval 실험 순으로 둡니다.

상세: [AI Retrieval · Current State / Upgrade Path](retrieval-current-state.md)

## 책임 경계

### 김재현 — LLM/RAG Core · Evaluation · Current Owner

> 공고문에서 자격요건·계약 위험조항과 근거를 얼마나 정확하고 안전하게 구조화할 수 있는가?

주요 영역:

- Semantic Chunking / Retrieval baseline·고도화
- Requirement Extraction
- Canonical Mapping
- Evidence Grounding
- UNKNOWN / Askability Guardrail
- 계약 위험조항 9종 분류와 Evidence
- Retrieval·Extraction Golden Set / Evaluation
- 변경공고 분석 Core / Revalidation 고도화

### 이홍규 — AI Copilot · Integration · Current Owner

> 이미 계산된 Product/Core 결과를 사용자가 자연어로 어떻게 안전하게 탐색하고 이어서 업무할 수 있는가?

역할은 확정됐지만 Copilot 구현/API 자체는 아직 Current 기능으로 간주하지 않습니다.

목표 영역:

- Intent Classification
- Conversation / Product Context
- Tool Orchestration
- Qualification / Evidence / Ask-back / Change API Adapter
- Grounded Response / Citation
- Multi-turn Flow
- Copilot Evaluation / Integration E2E

## 계약 위험조항 · MVP Current

위험조항은 MVP에 포함하며 현재 taxonomy는 9종입니다.

`WARRANTY_PERIOD`, `LATE_PENALTY`, `LATE_PENALTY_RATE`, `COPYRIGHT_OWNERSHIP`, `ACCEPTANCE_CRITERIA`, `SCOPE_AMBIGUITY`, `TERMINATION_CONDITION`, `PAYMENT_TERMS`, `LIABILITY_SCOPE`

경계:

```text
AI Core
→ contract risk category 분류 + 근거
→ Backend는 category를 재분류하지 않고 저장
→ Frontend가 사용자용 Label로 표현
```

## 05 평가 대응 · Pending Frontend Design

`/evaluation`의 최종 화면/사용자 흐름은 Frontend 구조안을 먼저 기준으로 잡습니다. 그 전에는 AI/Backend가 Evaluation Product Contract를 임의 확정하지 않습니다.

- **점수 예측은 MVP 제외**
- 평가기준 추출/근거 활용 범위는 Frontend 구조 확정 후 결정
- 통합 전 Backend Prototype의 제안서 업로드·Parsing·누락검사 기능은 Reference로 보존하고 재사용 범위를 이후 결정

## 절대 원칙

1. **판정은 LLM/Copilot이 새로 만들지 않습니다.**
   - 개별 상태: `SATISFIED | UNSATISFIED | UNKNOWN`
   - 전체 상태: `eligible | ineligible | insufficient_data`
   - 전체 상태의 Source of Truth는 Backend Judgment Run입니다.

2. **근거가 없는 확정 답변을 만들지 않습니다.**
   - `PARTIAL`, `FAILED`, `UNKNOWN`을 확정 결과로 임의 승격하지 않습니다.

3. **`UNKNOWN != ASKABLE`입니다.**
   - 질문 가능 여부는 `askability.py`의 정책으로 별도 판정합니다.

4. **Copilot → Core / Product API 의존만 허용합니다.**
   - Core는 Copilot을 알지 않습니다.
   - Copilot이 자체 Qualification Retriever/Rule을 만들어 이중 판정 구조를 만들지 않습니다.

5. **기존 Core 파일을 대규모 재배치하지 않습니다.**
   - 현재 Backend와 테스트의 import 경로를 보존합니다.
   - 신규 Retrieval/Evaluation 영역과 `app/copilot/**`부터 분리합니다.

## 문서

- [AI Core ↔ Copilot 병렬 개발 기준](parallel-boundary.md) — **Ownership Accepted / 상세 구현 경계 Current화 중**
- [Core → Copilot Contract](core-copilot-contract.md) — **Proposed Contract**
- [AI Retrieval · Current State / Upgrade Path](retrieval-current-state.md) — **Current Baseline + Proposed Experiments**
- [Requirement ↔ Test ↔ Golden/E2E](../08_qa_reports/requirement-test-traceability.md)

## 현재 `develop` Core 주요 파일

```text
apps/api/app/ai/
├─ analysis_pipeline.py
├─ analysis_result.py
├─ askability.py
├─ backend_blocks.py
├─ canonicalize.py
├─ chunking.py
├─ contracts.py
├─ evaluation_contracts.py
├─ evidence_adapter.py
├─ judgment.py
├─ legacy_slots.py
├─ normalization/
├─ providers/
├─ requirement_diff.py
└─ requirement_extraction.py
```

`evaluation_contracts.py`는 **입찰 평가기준(Evaluation Criterion)의 source-grounded 구조 계약**이며, AI 품질평가 Harness 자체를 의미하지 않습니다.

## 기존 `LLM` 브랜치 처리 원칙

`LLM` 브랜치는 최신 `develop` 대비 크게 뒤처져 있으므로 통째로 Merge하지 않습니다.

- 이미 `develop`에 존재: 최신 `develop` 유지
- Core 가치가 남은 모듈: 함수/테스트 단위 선별 이식
- `clause_review/**`, embedding provider: Core 실험 후보
- `assist.py`, `summary.py`: Copilot 요구사항 참고 후보
- 과거 followup/profile/judgment PoC: 현재 Product API/DB 구현 우선
- Demo/CLI 전용 코드: 제품 직접 Merge보다 Test/Historical 자료로 활용

## 다음 개발 순서

1. 재현 현재 작업물과 최신 `develop` Diff 최종 검산
2. Core/Copilot 공개 Contract 필수 필드 검산
3. Core: 측정 Harness → Drop Diagnostic → Evidence/Guardrail 품질 개선
4. Core: 위험조항 9종 + Golden/Evaluation 고도화
5. Copilot: `질문 → Product Tool → Judgment/Evidence → Grounded Answer` 첫 Vertical Slice
6. Ask-back → Revalidation → Change 질의 순으로 Copilot 확장
7. 05 평가 대응은 Frontend 구조안 수신 후 별도 연결
