# MVP Integration Baseline

> 2026-09-08 문서 갱신. 구현 기준: `fix/product-baseline-audit`, PR #74 코드 `87b9a5f`. PR 대상은 `integration/mvp-baseline`; 현재 Draft·미병합. `main`/`develop` 직접 수정 금지.

## 목적과 현재 판단

공통 제품 흐름과 계약을 먼저 연결하고, 이후 각 담당자가 같은 기준선을 유지하며 고도화하는 것이 목적입니다. **Product Baseline Ready는 보류**입니다. CI 성공이나 7개 화면 연결만으로 실제 변경공고까지의 전체 시나리오가 완료되지는 않습니다.

## 구현된 제품 기준선

- 실공고 수집, Notice/Version/문서 저장·추출, 회사 Profile, Preflight Case
- Qualification Analysis/Requirement/Evidence 영속화, deterministic Judgment
- Askability, Policy A USER_ANSWER 부분 재판정, Requirement Diff/affected-only revalidation
- 분석된 현재 공고 대상 Rule Matching; 미분석 공고는 일반 조회와 구분
- Figma 기반 01~07 route, 02~06 같은 Case의 공통 5개 탭
- 기존 Proposal 업로드·추출·원문 기능 유지; Proposal 대응/누락검사 제품 연결은 별도 검증

```text
Company → Notice 조회/분석된 후보 Matching → Case + Version
→ Parsing → LLM/RAG Extraction·Mapping·Evidence
→ deterministic Rule → 판정 → 근거 → Askable만 해결
→ USER_ANSWER 부분 재판정 → 평가 참고 → 변경 Requirement Diff → affected-only
```

[화면별 상태](03-screen-system-map.md)에서 완료 범위와 미완료 기능을 구분합니다. **Evaluation 전용 extraction은 미완료**이며 자격요건을 평가항목으로 해석하거나 예상점수를 만들지 않습니다. Product IA Source of Truth는 [Figma 7개 화면](https://www.figma.com/design/eWoeKC5CCjuWwVzXLvb4ES/?node-id=7-45)입니다.

## 지켜야 할 정책

- LLM/RAG는 원문 이해·추출·매핑·Evidence를 담당하고 최종 판정은 deterministic Rule이 담당합니다.
- `UNKNOWN != ASKABLE`. 복합·법적·예외·불명확·미해결 표 조건을 단순 Yes/No로 바꾸지 않습니다.
- USER_ANSWER Policy A: 현재 Case의 판정 근거, `apply_to_profile=false`, Profile 자동 승격 없음.
- PARTIAL은 전체 참가 가능으로 승격하지 않습니다. 필수 그룹이 확정 미달이면 ineligible, 그 외 insufficient_data를 유지합니다.
- 전체 raw grounding, source-local 조항 검증, 문서/위치/파일 해시/추출문 해시를 유지합니다.
- Rule은 `qualification-rules-v0.2`. 과거 AnalysisRun은 새 validation을 자동 통과한 것으로 간주하지 않습니다.

## 검증과 남은 blocker

| 구분 | PR #74 코드 기준 결과 |
| --- | --- |
| Backend | 102 passed, warning 1; 분리 DB 확인 |
| Frontend | 회귀 3개, 타입, 수정 파일 lint, build 통과 |
| CI | [#58 success](https://github.com/gyuniverse-hq/bid-change-validator/actions/runs/34178537233) |
| 전체 lint | 기존 오류 27개 잔여 |
| G0 | 합성 deterministic 통합 회귀 통과 |
| G1 | 실제 PARTIAL 분석·Evidence·UNKNOWN·unsafe answer 422 확인; 품질 완료 아님 |
| G2 | meaningful Qualification Diff 미확보; 후보 10건 검산 |
| 브라우저 | 01~07 이동·근거·실패/빈 상태 확인; 실제 safe-answer→G2 전체 클릭 E2E 미완료 |

`R26BK01715087`은 같은 RFP에 시간/설명회 안내만 바뀌어 G2에서 탈락했습니다. 상세 [Golden 결과](05-e2e-golden-path.md)와 [audit](11-product-baseline-audit.md)를 확인하세요. 실제 추출 recall/표 문맥, 과거 분석 캐시 정책, 접근성/역사판정 표현 등이 P1로 남아 있습니다. Figma 직접 대조는 도구 사용량 제한으로 미완료입니다.

## PR #74 merge 후 운영 절차

Backend는 build image이므로 코드 변경 후 다음 명령이 필요합니다.

```powershell
docker compose up -d --build api
```

기존 Demo/Golden은 baseline/current **full re-analysis** 후 새 분석 ID로 재판정해야 합니다. Analysis Contract `ai-analysis-v0.2`는 유지되어 과거 결과에 새 검증이 소급 적용되지 않습니다. 캐시 무효화가 이미 구현됐다고 가정하지 마세요. [실행·인계 절차](06-handoff-and-merge.md)를 따릅니다.

## 문서 역할

| 문서 | 역할 |
| --- | --- |
| [01 Scope](01-scope-and-acceptance.md) | 범위·완료 조건과 미충족 gate |
| [02 System Flow](02-system-flow.md) | 실제 연결과 책임 경계 |
| [03 Screen Map](03-screen-system-map.md) | Figma 01~07 구현·검증 범위 |
| [04 Contract](04-contract-and-status-map.md) | 상태·버전·Policy A·grounding 계약 |
| [05 Golden](05-e2e-golden-path.md) | G0/G1/G2, 후보 10건과 재현 기준 |
| [06 Handoff/Merge](06-handoff-and-merge.md) | branch 규칙, rebuild/full re-analysis |
| [07 과거 Gap Audit](07-current-code-contract-gap.md) | Stage 2 당시 기록과 현재 해결 상태 연결 |
| [08 Team Handoff](08-team-handoff-current-state.md) | 담당별 현황·P1/P2 |
| [09 Case Workspace](09-product-case-workspace.md) | 공통 Case·Evidence·평가 화면 정책 |
| [09 Review Checklist](09-team-review-checklist.md) | 실제 제품 동결 검토 항목 |
| [10 Hardening](10-product-baseline-hardening.md) | PR #74 안전성 보강 구현과 한계 |
| [11 Audit](11-product-baseline-audit.md) | 재현 근거·실행 ID·검산 상세 |

기존 `docs/contracts/*`, `docs/parallel-development.md`, Proposal 문서는 보존합니다. 과거 계획을 현재 완료 사실로 읽지 않으며, 새 계약은 실제 코드와 정책을 대조하여 명시적으로 변경합니다.
