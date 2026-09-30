# QA / E2E 문서 안내

> **상태: Current + Proposed**  
> 기준: `develop` + 2026-09-10 팀 결정

이 문서는 기능 구현이 실제 제품 흐름에서 안전하게 동작하는지 검증하기 위한 공통 기준입니다. 실제 Requirement/Test 연결은 [Requirement ↔ Test ↔ Golden / E2E Traceability](requirement-test-traceability.md)를 함께 봅니다.

## 검증 레이어

```text
Unit / Domain
→ Service / API
→ Integration
→ Golden Regression
→ Human Click E2E
→ Deployment Smoke
```

자동테스트 통과와 실제 사용자 E2E 완료를 같은 의미로 사용하지 않습니다.

## E2E Spine

```text
Company Profile
→ Notice 선택
→ Analysis
→ Judgment
→ UNKNOWN 확인
→ Ask-back
→ 부분 재판정
→ Evidence 원문 확인
→ Contract Risk Clause
→ Changed Notice
→ Revalidation
```

`05 평가 대응`은 Frontend 구조안 확정 전까지 별도 E2E Spine에 강제로 포함하지 않습니다.

## Golden 기준

- **G0**: Synthetic deterministic regression
  - 특정 회사 1개에 과적합되지 않도록 **합성 회사 Profile 여러 개**를 사용
- **G1**: 실제 공고 Extraction / Evidence reality check
- **G2**: 실제 meaningful Qualification 변경공고 시나리오

과거 Product Baseline 상세 결과는 `docs/mvp-baseline/`을 Snapshot으로 참고합니다.

## 현재 테스트와 요구사항 연결

상세: [requirement-test-traceability.md](requirement-test-traceability.md)

주요 현재 테스트 축:

- Requirement Extraction / Analysis
- Canonical Mapping / Normalization
- deterministic Judgment
- Askability
- Requirement Diff
- Contract risk clause extraction / classification
- Company / Notice / Master Data
- Product Golden regression

Ask-back/Revalidation은 Product 기능/API가 존재하지만 **전용 테스트 축을 더 명시적으로 분리하고 G2에서 검증할 여지**가 있습니다.

## 파트별 Evaluation

### AI Core
- Requirement precision / recall / F1
- Retrieval Recall@K / MRR
- Evidence grounding/citation correctness
- Unsupported / abstention correctness
- Guardrail / dropped requirement diagnostic
- 위험조항 9종 category/Evidence correctness

### AI Copilot — 구현 대상
- Intent accuracy
- Tool selection accuracy
- Grounded answer correctness
- Citation correctness
- Multi-turn context consistency

### Frontend
- Route / Case Context 유지
- Loading / Error / Empty / Partial
- Evidence 이동
- 접근성
- Human Click E2E
- 05 평가 대응은 Frontend 구조안 확정 후 별도 검증 항목 정의

### Backend / DB
- API Contract
- Error Code
- transaction/data integrity
- stale Run 방지
- Migration regression
- Supabase 공유 DB Alembic lineage

## MVP Demo 인증 / 데이터

- 데모는 **관리자 로그인** 기준으로 진행합니다.
- Golden Set의 회사 Profile은 **복수 합성 Profile**을 사용합니다.
- 실제/합성 여부와 Dataset/Version을 기록합니다.
- 사용한 notice/company/version/analysis/judgment run 식별자를 데모 문서에 남깁니다.

## CI 현재 기준

`.github/workflows/`의 실제 Workflow 파일을 Source of Truth로 둡니다. CI 통과만으로 G1/G2/Human E2E를 완료 처리하지 않습니다.

## 완료 조건

기능을 Done으로 판단하기 전에 최소한 다음을 확인합니다.

- 정상 경로 테스트
- 실패/불완전 데이터 경로
- 관련 Contract regression
- 실제 Golden 검증 필요 여부
- 화면이면 Human E2E 필요 여부
- 기존 기능 영향
- 필요한 docs 갱신

## Known Gaps

- 실제 meaningful G2 확보 필요
- 복수 합성 Profile Golden Set 최종 확정/버전 관리
- 01~07 전체 Human Click E2E 완료 필요
- AI Core 정량 Evaluation baseline 필요
- Copilot Golden Set 신규 설계 필요
- 05 평가 대응 Frontend 구조 확정 후 검증 범위 정의
- Production Smoke Test
- 접근성/전체 lint debt 정리 필요
