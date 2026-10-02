# Decision / ADR 문서 안내

> **상태: Current Guide**

Notion Decision Log는 논의와 팀 결정의 원본 맥락을 보존합니다. 그중 실제 코드·아키텍처에 장기간 영향을 주는 결정은 안정화 후 이 폴더에 ADR(Architecture Decision Record)로 승격합니다.

## Notion과 ADR의 차이

```text
Notion Decision Log
= 무엇을 논의했고 왜 선택했는가

GitHub ADR
= 현재 코드가 어떤 결정을 전제로 구성되어 있는가
```

모든 회의 결정을 ADR로 만들지 않습니다.

## ADR 대상

- Rule과 LLM의 책임 경계
- 핵심 데이터/Version 모델 변경
- API 또는 Contract의 Breaking Decision
- Retrieval / Vector DB / Model 전략 확정
- AI Core / Copilot 모듈 경계 확정
- 인증 / 배포 Architecture 확정
- 중요한 기술을 도입하거나 포기한 결정

## 파일명

```text
ADR-001-short-title.md
ADR-002-short-title.md
```

## 템플릿

```markdown
# ADR-XXX 제목

> 상태: Proposed | Accepted | Superseded
> 날짜: YYYY-MM-DD

## Context
왜 이 결정이 필요한가?

## Options
검토한 선택지는 무엇인가?

## Decision
무엇을 선택했는가?

## Consequences
좋아지는 점, 비용, 제약은 무엇인가?

## Revisit Condition
언제 다시 검토할 것인가?
```

## 현재 ADR 후보 / 상태

- deterministic Rule이 최종 Qualification 판정을 담당하는 구조 — **Accepted architecture candidate**
- Product Integration Baseline 우선 전략 — **Accepted / 이미 develop 반영**
- AI Core와 AI Copilot 역할 분리 — **Accepted ownership decision**
  - 김재현: LLM/RAG Core + Evaluation
  - 이홍규: AI Copilot + Integration
  - 세부 폴더/Contract는 구현·테스트와 함께 Current화
- 위험조항 9종 taxonomy 및 `AI Core 분류 → Backend 저장` 경계 — **Accepted contract candidate**
- 05 평가 대응 — **Pending Frontend Design**, 점수 예측 제외
- Production Web/API 배포 구조 — **TBD**
- 첨부파일 최종 저장소 — **TBD**, 현재 LOCAL

역할·범위가 합의됐더라도 실제 코드 구조가 안정화되지 않았다면 즉시 ADR 파일로 고정하지 않습니다. 구현과 테스트가 따라온 시점에 개별 ADR로 승격합니다.
