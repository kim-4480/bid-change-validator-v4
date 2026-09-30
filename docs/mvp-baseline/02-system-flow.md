# 02. System Flow

## 1. Current integration spine

현재 저장소에서 확인되는 기본 축은 다음과 같습니다.

```text
apps/web
   ↓ HTTP
apps/api
   ├─ companies
   ├─ master-codes
   ├─ notices
   └─ preflight-cases
        ↓
PostgreSQL + document storage
        ↓
notice/document extracted blocks
```

공고 수집과 문서 추출, Company Profile, Preflight Case 및 Analysis/Requirement/Evidence/Judgment/Answer/Revalidation 저장과 API가 구현되어 있습니다. 구현 기준은 PR #74 코드 `87b9a5f`입니다.

AI 영역에는 Backend state를 직접 수정하지 않는 Qualification 분석 파이프라인이 존재합니다.

```text
Backend extracted blocks
        ↓
canonical source blocks
        ↓
semantic chunks
        ↓
structured extraction
        ↓
deterministic normalization
        ↓
Canonical Requirement + Evidence
        ↓
RequirementAnalysisResult
```

## 2. 구현된 Product Flow와 검증 범위

아래 API/서비스 흐름은 구현되어 있습니다. G0 통과와 G1 보류 경로 확인을 실제 meaningful G2 완료로 해석하지 않습니다. [검증 결과](05-e2e-golden-path.md)를 참조합니다.

```text
[1] 나라장터 Notice Sync / Poller
        ↓
[2] Notice
        ↓
[3] Notice Version
        ↓
[4] Notice Documents
        ↓
[5] Extracted Source Blocks
        ↓
[6] Qualification Analysis
        ↓
[7] Canonical Requirements + Evidence
        ↓
[8] Company Profile
        ↓
[9] Judgment Engine
        ↓
    SATISFIED
    UNSATISFIED
    UNKNOWN
        ↓
[10] UNKNOWN → Askability → ASKABLE만 Ask-back
        ↓
[11] User Answer 저장 (Policy A / apply_to_profile=false)
        ↓
[12] 영향 Requirement 부분 재판정
        ↓
[13] Frontend 결과 표시
```

변경공고가 들어오면 동일한 제품 흐름에 Version 축이 추가됩니다.

```text
Notice Version N
        ↓
Canonical Requirements N
        ↓
기존 Judgment

        + 변경공고

Notice Version N+1
        ↓
Canonical Requirements N+1
        ↓
Requirement Diff
        ↓
Affected Requirement Keys
        ↓
Revalidation
        ↓
변경 전/후 판정 + 새 Evidence
```

## 3. Responsibility boundaries

### Frontend — `apps/web`

책임:

- 공고 탐색/선택
- Company Profile 입력 및 선택
- 참가자격 판정 화면
- 근거 원문 이동
- Ask-back 입력
- 변경 전/후 결과 표현

Frontend는 Canonical 판정 로직을 자체 복제하지 않습니다.

### Backend — `apps/api`

책임:

- API request validation
- 원본 Backend ID의 source of truth
- DB 조회/저장
- Notice/Version/Document 관리
- Company Profile 관리
- AI 분석 호출
- Judgment orchestration
- Ask-back / Answer state 관리
- Change/Revalidation orchestration
- Frontend용 안정된 응답 제공

### DB / Storage

책임:

- Notice / Version
- Document metadata / hash / storage location
- Extracted blocks
- Company Profile
- Preflight Case
- 구현된 Requirement / Evidence / Judgment / Answer / Revalidation state

저장 모델은 `analysis_models.py`, `judgment_models.py`, `ask_back_models.py`, `revalidation_models.py`에 연결되어 있습니다.

### LLM / RAG — `apps/api/app/ai` + related modules

책임:

- Backend extracted block을 입력으로 받음
- Semantic chunking
- Structured requirement extraction
- Deterministic normalization과 결합
- Canonical Requirement 생성
- Evidence provenance 보존
- 분석 diagnostic 반환

AI가 Backend DB PK나 원본 문서 ID를 임의 생성해 source of truth를 대체하지 않습니다.

### Judgment / Rule layer

현재 구현 책임:

- Canonical Requirement와 Company Profile 비교
- `SATISFIED / UNSATISFIED / UNKNOWN` 생성
- `reason_code`, basis, profile reference 기록
- UNKNOWN이 사용자 입력으로 해소 가능한지 식별

`apps/api/app/ai/judgment.py`의 `qualification-rules-v0.2`가 초기/부분/Matching/변경 재검증의 공통 판정 기준입니다.

## 4. Identifier chain

핵심 식별자는 다음 순서로 추적 가능해야 합니다.

```text
notice_id
└─ notice_version_id
   ├─ document_id
   │  └─ extracted block locator
   │     └─ evidence_key
   └─ requirement_key
      └─ judgment_key
         ├─ preflight_case_id
         ├─ company/profile refs
         └─ optional user answer
```

### Identifier rules

- `notice_id`: 공고 identity
- `notice_version_id`: 분석과 판정의 공고 버전 고정점
- `document_id`: Backend가 관리하는 원본/첨부문서 identity
- `evidence_key`: Requirement와 원문 근거 연결 key
- `requirement_key`: 해당 Version의 Canonical Requirement identity
- `judgment_key`: 특정 Case/Version/Requirement 판정 identity

## 5. Evidence flow

```text
원본 파일
→ file_sha256
→ extracted text
→ extracted_text_sha256
→ source blocks
→ semantic chunks
→ Evidence location
→ UI 원문 근거
```

원본 파일 hash와 추출 텍스트 hash는 서로 다른 identity이며 합쳐서 취급하지 않습니다.

## 6. Failure flow

### AI analysis failure

```text
SUCCEEDED → 정상 canonical result
PARTIAL   → 일부 결과 + diagnostic
FAILED    → canonical requirement/evidence를 성공 결과처럼 사용 금지
```

### Judgment information gap

```text
Requirement는 유효
+ Profile 정보 부족
→ UNKNOWN
→ Ask-back 또는 확인 필요
```

AI 분석 실패와 사용자 Profile 정보 부족은 서로 다른 상태이므로 같은 상태값으로 합치지 않습니다.

## 7. 현재 화면/운영 연결

01 조회와 분석된 공고 Matching → 02 검토 시작 한 번으로 Analysis와 Judgment 순차 호출 → 03 안전한 답변 → 04 원문 → 05 평가 참고 → 06 변경 검토 → 07 회사정보 관리가 연결됩니다. 02~06은 같은 Case와 current analysis/judgment를 사용하고 baseline judgment는 변경 비교의 source로 구분합니다.

Evaluation 전용 extraction은 미완료입니다. 기존 Proposal 업로드·추출·문서 검증 경로는 유지하며 Qualification 흐름과의 제품 연결 범위는 별도로 확인합니다.

PARTIAL은 필수 그룹의 확정 미달을 제외하면 insufficient_data를 유지하고, FAILED는 성공 판정 입력으로 쓰지 않습니다. Evidence는 전체 raw·source-local 조항을 검증하지만 과거 AnalysisRun에 검증이 소급 적용되지는 않습니다.

Backend 코드 변경 후 `docker compose up -d --build api`가 필요합니다. PR #74 merge 후 기존 Demo/Golden full re-analysis 절차는 [06](06-handoff-and-merge.md)에 있습니다. 실제 G2와 전체 성공 클릭 흐름은 미완료입니다.
