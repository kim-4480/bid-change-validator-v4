# Data / DB Baseline

> **상태: Current**  
> 기준: `develop`

이 문서는 현재 데이터 저장 구조와 DB 변경 시 확인해야 할 기준을 정리합니다. 실제 핵심 관계는 [DB ERD · Current develop](db-erd-current.md)를 함께 봅니다. 컬럼/제약조건의 최종 Source of Truth는 SQLAlchemy Model과 Alembic Migration입니다.

## 현재 저장 대상

- Company Profile
- Bid Notice / Notice Version
- Notice Document / 추출 상태
- Preflight Case / Proposal Document
- Qualification Analysis Run
- Requirement / Evidence
- Qualification Judgment Run / Records
- Qualification Answer
- Qualification Revalidation
- Master Codes

## 핵심 Lineage

```text
BidNoticeVersion
→ QualificationAnalysisRun
→ Requirement / Evidence
→ PreflightCase + Company
→ QualificationJudgmentRun
→ Judgment Records
→ Answer 또는 Revalidation
→ 새 JudgmentRun
```

상세: [db-erd-current.md](db-erd-current.md)

## Migration 흐름

```text
001 Company Profile
002 Bid Notices
003 Notice Document Storage
004 Document Text Extraction
005 Preflight Cases
006 Qualification Analysis
007 Qualification Judgment
008 Qualification Answers
009 Qualification Revalidation
```

## 저장 원칙

- 공고의 변경 상태는 overwrite보다 Version 단위 보존을 우선합니다.
- Analysis / Judgment / Revalidation은 Run 이력을 남겨 과거 결과와 현재 결과를 구분합니다.
- Company Profile은 현재 값과 판정 시점 `profile_snapshot`을 구분합니다.
- 원본 파일과 extracted text는 Hash/identity를 추적합니다.
- Requirement와 Evidence는 `requirement_key`, `evidence_key` 기반 연결을 유지합니다.
- Ask-back 답변이 곧바로 Company Profile에 영구 저장된다고 가정하지 않습니다. 현재 MVP Policy A에서는 `apply_to_profile=false`가 기본입니다.

## 물리 저장

`docker-compose.yml` 기준:

- PostgreSQL → `postgres_data`
- Notice/Proposal 원본 문서 → Local document storage (`notice_documents_data` volume)
- `DOCUMENT_STORAGE_BACKEND=S3` 설정 시 S3-compatible storage 확장 가능

## DB 구조 변경 시 원칙

- 기존 데이터 마이그레이션 경로를 명확히 합니다.
- Schema 변경은 Alembic migration으로 추적합니다.
- 현재 API Response 및 Frontend Contract 영향을 확인합니다.
- AI Contract와 DB Model을 동일 개념으로 착각하지 않습니다. AI는 Backend-owned PK를 생성하지 않습니다.
- Version/Run lineage를 끊는 overwrite 설계를 피합니다.

## Known Gaps / 고도화 후보

- Evaluation Criterion 저장 여부/Schema 미확정
- Proposal Retrieval 결과 persistence 필요 여부 미확정
- Copilot Session/Message 저장 필요 여부 미확정
- Profile provenance / evidence status 정책 추가 검토 가능
- Production DB backup/restore/observability 정책 미확정
- `db/schema/`, `db/migrations/`, Alembic의 역할 중복 여부 정리 필요

## 변경 체크리스트

- Migration 생성 여부
- downgrade 전략 필요 여부
- 기존 데이터 호환성
- FK / unique / index 영향
- API Schema 영향
- AI Requirement/Evidence/Judgment 계약 영향
- [DB ERD](db-erd-current.md) 갱신 필요 여부
- Golden/E2E fixture 갱신 필요 여부
