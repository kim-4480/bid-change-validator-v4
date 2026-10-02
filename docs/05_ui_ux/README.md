# Frontend / UI·UX Baseline

> **상태: Current**  
> 기준: `develop` + Figma

이 문서는 Frontend 고도화 시 화면 흐름, API 연결, 실패/빈 상태를 일관되게 유지하기 위한 기준선입니다. 상세 연결은 [Frontend Screen · Component · API Contract](frontend-screen-contract.md)를 함께 봅니다.

## 현재 Route

- `/notices`
- `/qualification`
- `/ask-back`
- `/evidence`
- `/evaluation`
- `/changes`
- `/company`

02~06은 같은 `caseId`를 공유하는 Workspace입니다.

## Source of Truth

- 화면 IA / 디자인 방향: Figma
- 실제 지원 기능 / 상태: `develop` 코드와 Backend API
- 화면 공통 Context/상태 표현: `case-workspace.ts`, `status-copy.ts`
- Figma와 구현이 다르면 이유를 문서 또는 Decision Log에 남깁니다.

## 구현 원칙

- `SATISFIED / UNSATISFIED / UNKNOWN`과 전체 `eligible / ineligible / insufficient_data`를 혼동하지 않습니다.
- `PARTIAL` Analysis와 `UNKNOWN` Judgment를 같은 상태로 합치지 않습니다.
- 최신 Analysis/Judgment와 연결된 데이터만 표시합니다.
- Loading / Error / Empty / Partial 상태를 명시적으로 처리합니다.
- Evidence는 실제 원문으로 이동할 수 있어야 하며 HWP/HWPX에 가짜 page를 만들지 않습니다.
- Evaluation 화면은 자격요건과 별도 평가기준을 혼동하지 않습니다.

## 상세 문서

- [Frontend Screen · Component · API Contract](frontend-screen-contract.md)
- [Feature Traceability](../02_architecture/feature-traceability.md)
- [Backend API Catalog](../04_contracts/backend-api-catalog.md)
- [Requirement/Test/Golden Traceability](../08_qa_reports/requirement-test-traceability.md)

## AI Copilot 확장 지점

Copilot은 기존 화면을 대체하기보다 Product Workspace를 연결하는 보조 인터페이스로 검토합니다.

예시:
- 현재 선택한 공고/Case Context를 사용
- 판정 이유 설명
- Evidence 이동
- Ask-back 유도
- 변경사항 설명

현재 Copilot UI는 **Proposed**입니다.

## Known Gaps

- 01~07 전체 Human Click E2E 완료 필요
- Figma 최신 7 Frame 직접 visual QA
- Error/Empty 상태 통일
- 접근성/반응형 품질
- Copilot Panel의 위치·모바일 대응 미확정

## 변경 체크리스트

- Figma와 차이 여부
- API Contract 영향
- Case/Version Context 유지 여부
- Loading/Error/Empty/PARTIAL 상태
- Evidence deep link
- 기존 Product Component 재사용 여부
- 접근성 및 키보드 사용성
- `frontend-screen-contract.md` 갱신 필요 여부
- E2E 시나리오 갱신 여부
