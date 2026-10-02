# Feature ↔ Screen ↔ API ↔ DB ↔ AI Traceability

> **상태: Current**  
> 기준: `develop` · 실제 코드/테스트가 최종 Source of Truth

이 문서는 제품 기능 하나를 바꿀 때 어떤 화면·API·저장 데이터·AI/Rule·검증이 함께 영향을 받는지 빠르게 찾기 위한 지도입니다.

## 전체 흐름

```text
사용자 화면
→ Product API / Case Context
→ Persisted Run / Version
→ AI Core 또는 deterministic Rule
→ 결과 저장
→ 화면 표시
→ Test / Golden / Human E2E
```

## 01~07 Traceability

| 기능 | Screen | 주요 API / Service | 주요 Persisted State | AI / Rule | 현재 검증 포인트 |
| --- | --- | --- | --- | --- | --- |
| 01 공고 찾기 | `/notices` | `GET /api/v1/notices`, `GET /api/v1/companies/{company_id}/notice-matches` | `bid_notices`, `bid_notice_versions`, Company Profile | cached qualification matching | 미분석 공고와 분석 완료 공고를 구분하고 추천 근거/상태를 과장하지 않음 |
| 02 참가자격 | `/qualification` | Qualification Analysis + Judgment API | `qualification_analysis_runs`, `qualification_requirements`, `qualification_evidence`, `qualification_judgment_runs`, `qualification_judgments` | Requirement Extraction → deterministic Judgment | `AnalysisStatus`와 `JudgmentStatus`를 분리하고 최신 Analysis와 일치하는 Judgment만 표시 |
| 03 확인 필요 | `/ask-back` | Questions + Answers API | `qualification_answers`, 새 `qualification_judgment_run` | `askability.py` + targeted re-judgment | `UNKNOWN != ASKABLE`; 단순 사용자 사실로 안전하게 해소 가능한 항목만 질문 |
| 04 근거 원문 | `/evidence` | Notice/Proposal document text/source/preview API | `notice_documents`, `proposal_documents`, `qualification_evidence` | Evidence grounding / locator | `requirement_key → evidence_key → document_id → location` 역추적 유지 |
| 05 평가 대응 | `/evaluation` | 현재 전용 Evaluation Product API 없음 | 전용 Evaluation persistence 미확정 | `evaluation_contracts.py`는 criteria contract이며 LLM 품질평가 Harness가 아님 | 현재 화면을 자격요건 분석 결과와 평가기준 전용 추출로 혼동하지 않음 |
| 06 변경 이력 | `/changes` | Notice Version 조회 + Qualification Revalidation API | `bid_notice_versions`, `qualification_revalidation_runs`, 이전/현재 Analysis/Judgment Run | `requirement_diff.py` + affected-only revalidation | 문자열 diff보다 Requirement 영향과 before/after Judgment를 우선 |
| 07 회사 프로필 | `/company` | Company CRUD / completeness / performance / certification | `companies`, `company_*`, completeness | qualification rule의 좌변 | 현재 Profile과 과거 `profile_snapshot`을 구분하고 수정이 과거 판정을 소급 변경하지 않게 함 |

## 핵심 Lineage

```text
BidNotice
  └─ BidNoticeVersion
       ├─ NoticeDocument
       └─ QualificationAnalysisRun
            ├─ QualificationRequirementRecord
            └─ QualificationEvidenceRecord

Company + PreflightCase + AnalysisRun
  └─ QualificationJudgmentRun
       └─ QualificationJudgmentRecord
            ├─ QualificationAnswer → result JudgmentRun
            └─ QualificationRevalidationRun → result JudgmentRun
```

## 화면 공통 Case Context

02~06 화면은 서로 독립된 결과 화면이 아니라 같은 `preflight_case_id`를 공유하는 Workspace입니다.

```text
caseId
→ company_id
→ notice_id
→ baseline/current version
→ latest compatible analysis
→ matching rule-version judgment
→ ask-back / evidence / revalidation
```

Frontend는 `apps/web/lib/case-workspace.ts`에서 이 관계를 맞춥니다. 오래된 Analysis/Judgment를 단순히 최신 생성시각만 보고 섞지 않습니다.

## 변경 시 영향 확인

### Requirement Contract 변경

확인 대상:

- `app/ai/contracts.py`
- Analysis persistence/schema
- Judgment rule
- Frontend qualification/evidence rendering
- Askability / Requirement Diff
- Golden fixture / regression

### Company Profile 변경

확인 대상:

- SQLAlchemy model + Alembic
- Company API
- Profile completeness
- deterministic Judgment
- `/company`, `/qualification`, Matching
- `profile_snapshot` 재현성

### Evidence locator 변경

확인 대상:

- source block/chunk adapter
- `qualification_evidence.location`
- Document source/preview API
- `/evidence` / qualification evidence link
- citation/evidence accuracy test

### Changed Notice 로직 변경

확인 대상:

- Notice Version / relation
- Requirement Diff
- Revalidation lineage
- `/changes`
- G2 Golden scenario

## 문서 갱신 규칙

기능 PR에서 위 연결 중 하나가 바뀌면 해당 파트 문서만 수정하는 것으로 끝내지 않고 이 Traceability의 연결도 함께 확인합니다. 실제 Task 상태는 이 문서에 복제하지 않고 GitHub Issue / Projects에서 관리합니다.
