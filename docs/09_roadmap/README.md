# Post-Baseline Roadmap

> **상태: Proposed**  
> Product Integration Baseline 이후 고도화 방향을 기록합니다. 실제 일정·담당·진행 상태는 GitHub Projects/Issue를 Source of Truth로 둡니다.

## 목적

이 문서는 Task 목록을 대신하지 않습니다. 현재 구조에서 어떤 방향으로 발전할 수 있는지와 기술 의존 관계를 보존합니다.

## 현재 고도화 Track

### Frontend / UI·UX
- Figma visual QA
- Loading/Error/Empty/Partial 상태 통일
- 01~07 Human Click E2E
- 접근성 및 responsive quality
- Copilot UI integration

### Backend / API
- 도메인별 모듈 구조 정리 검토
- API Error/Contract 안정화
- Evaluation/Copilot 연계 API 필요성 검토
- 인증/권한 및 배포 환경 정책

### DB / Data
- 실제 ERD 최신화
- Profile provenance / data quality
- Evaluation Criterion 저장 전략
- Copilot session/history 저장 필요성 검토
- 실제 변경공고 Golden 데이터 확장

### LLM/RAG Core
- Golden Set/Evaluation baseline
- Retrieval 품질 측정
- Requirement Extraction 개선
- Evidence grounding
- Hybrid Retrieval/Reranking 실험
- 변경공고 의미 변화 품질 고도화

### AI Copilot
- ELIGIBILITY 첫 Vertical Slice
- Intent / Tool Orchestration
- Grounded narration + Citation
- Multi-turn Product Context
- Ask-back / Revalidation 연결
- Change / Search 기능 확장

### Infra / Operations
- 실제 배포 Target 확정
- CI gate 개선
- 환경변수/Secret 관리
- logging / observability
- backup / restore / 운영 Runbook

## 단계 예시

```text
Current Baseline
→ 파트별 품질 측정
→ 병렬 고도화
→ Contract 통합 검증
→ Golden/E2E
→ Demo Ready
→ Final README / 발표 산출물
```

## Roadmap 작성 원칙

- 가능성과 확정 계획을 구분합니다.
- 실험 후보를 바로 최종 Architecture처럼 기록하지 않습니다.
- 선택이 확정되면 Decision Log/ADR로 이동합니다.
- 실제 일정/Owner/Status는 Issue/Project에서 관리합니다.
- 완료된 항목은 최종 문서에 결과와 근거를 남기고 단순 체크리스트로 끝내지 않습니다.
