# 프론트엔드 연동 가이드 — LLM/RAG 데모 기능

이 문서는 `apps/api/app/ai/demo`에서 검증한 기능을 제품 프론트에 옮길 때 필요한
API와 화면 변경을 정리한다. 이번 통합에서는 프론트 담당자의 소유 파일인 `apps/web`을
수정하지 않았다.

## 1. 제품 API

| 기능 | 메서드·경로 | 화면에서 쓰는 시점 |
| --- | --- | --- |
| 자격요건 분석 실행 | `POST /api/v1/notices/{notice_id}/versions/{version}/qualification-analysis` | 공고 분석 시작 |
| 분석 결과 조회 | `GET /api/v1/qualification-analyses/{analysis_run_id}` | 요건·탈락 원문 표시 |
| 판정 브리핑 | `GET /api/v1/qualification-judgment-runs/{run_id}/briefing` | 결과 화면 진입 |
| 공고 요약 | `POST /api/v1/notices/{notice_id}/versions/{version}/notice-digest` | 요약만 다시 생성 |
| 브리핑 서술 | `POST /api/v1/qualification-judgment-runs/{run_id}/briefing-narrative` | 표 형태 결과를 문장으로 설명 |
| 챗봇 | `POST /api/v1/qualification-judgment-runs/{run_id}/chat` | 도우미 패널에서 질문 |
| 사업계획서 초안 | `POST /api/v1/qualification-judgment-runs/{run_id}/business-plan-draft` | 사용자 추가 입력 후 초안 생성 |

`briefing`은 기본적으로 공고 요약과 계약조항 검토까지 수행한다. 빠른 판정 결과만
필요하면 `?include_digest=false&include_clause_review=false`를 붙일 수 있다.

## 2. 분석 결과에 추가할 화면

분석 결과의 `dropped_requirements`는 구조화 검증에서 제외된 후보 원문이다. 원문은
자르지 않고 전부 표시한다.

```ts
type DroppedRequirement = {
  raw: string;
  reason_code:
    | 'MISSING_RAW'
    | 'RAW_NOT_FOUND_IN_SOURCE'
    | 'DETAIL_NOT_FOUND_IN_SOURCE'
    | 'SOURCE_VALIDATION_FAILED';
};
```

표시 문구 권장값:

```ts
const DROPPED_REASON_LABELS = {
  MISSING_RAW: '추출 결과에 원문이 없습니다.',
  RAW_NOT_FOUND_IN_SOURCE: '추출된 문장이 공고 원문에서 확인되지 않습니다.',
  DETAIL_NOT_FOUND_IN_SOURCE: '세부 조건이 해당 공고 원문에서 확인되지 않습니다.',
  SOURCE_VALIDATION_FAILED: '공고 원문 대조를 통과하지 못했습니다.',
} as const;
```

- 배열이 비어 있으면 영역을 숨긴다.
- 값이 있으면 `구조화에서 제외된 요건 N건`으로 별도 경고 영역에 표시한다.
- `raw` 전체와 코드에 대응하는 한글 문구를 함께 보여준다.
- `diagnostics.details.notes`를 원문 표시 용도로 파싱하지 않는다.

## 3. 브리핑 화면

`GET .../briefing` 응답에서 다음 영역을 그린다.

### 3.1 공고 요약

- `digest.overview.text`: 공고 개요. 반드시 `AI 요약 · 판정 아님` 표시를 붙인다.
- `digest.sections.sections[]`: 사업 개요·참가자격·과업·제출서류·평가·계약·일정별 요약.
- 각 항목의 `status`가 `OK`가 아니면 빈 카드 대신 `notes`를 표시한다.

### 3.2 참가자격 판정

`judgments[]`의 주요 필드는 다음과 같다.

```ts
type EvidenceQuote = {
  evidence_key: string;
  quote: string;
  location?: string | null;
  document_id?: string | null;
  chunk_id?: string | null;
  source_text?: string | null;
};

type JudgmentBrief = {
  requirement_key: string;
  requirement_type?: string | null;
  requirement_raw: string;
  status: 'SATISFIED' | 'UNSATISFIED' | 'UNKNOWN';
  status_label: string;
  reason_code: string;
  reason: string;
  basis: string;
  requires_evidence: boolean;
  evidence: EvidenceQuote[];
};
```

- 정렬은 `UNSATISFIED → UNKNOWN → SATISFIED` 순서를 권장한다.
- 카드에는 상태, `requirement_raw`, `reason`, `basis`를 기본 표시한다.
- `원문 발췌 보기`를 펼치면 `source_text ?? quote`를 보여준다.
- `source_text` 안에서 `quote`와 일치하는 부분을 강조하고 `location`, `chunk_id`도 표시한다.
- `notice_facts[]`는 확인했지만 회사 프로필과 대조할 수 없는 공고 사실이다. 오류나
  미충족으로 합치지 말고 별도 `판정 대상이 아닌 확인사항` 영역에 표시한다.

### 3.3 위험 계약조항 9종

```ts
type ClauseFinding = {
  risk_type: string;              // 대표 한글 라벨
  risk_types: string[];           // 전체 한글 라벨, 단일 원인도 길이 1
  category: string;               // 대표 오류 코드
  categories: string[];           // 전체 오류 코드, 단일 원인도 길이 1
  label: string;
  verdict: 'NEEDS_REVIEW' | 'COMPLIANT' | 'UNDETERMINED';
  reason: string;
  matched_text?: string | null;
  excerpt?: string | null;
  clause_label?: string | null;
  chunk_id?: string | null;
  standard?: {
    clause_ref?: string | null;
    description?: string | null;
    value_raw?: string | null;
    text_excerpt?: string | null;
  } | null;
};
```

- 기존 그룹핑은 `category`로 유지한다.
- 상세 카드에서는 `categories`를 전부 칩으로 표시한다.
- `categories.length > 1`이면 `N종에 걸림`을 표시한다.
- `categories[0] === category`, `risk_types[0] === risk_type`가 서버 불변식이다.
- `NEEDS_REVIEW`를 먼저, `UNDETERMINED`를 다음에 표시한다. `COMPLIANT`는 목록에서
  숨기고 집계 숫자로만 보여줘도 된다.
- 상세 펼침에는 공고 원문 `excerpt`/`matched_text`와 기준 조문
  `standard.text_excerpt`를 서로 다른 영역으로 표시한다.

위험유형 코드는 `WARRANTY_PERIOD`, `LATE_PENALTY`, `LATE_PENALTY_RATE`,
`COPYRIGHT_OWNERSHIP`, `ACCEPTANCE_CRITERIA`, `SCOPE_AMBIGUITY`,
`TERMINATION_CONDITION`, `PAYMENT_TERMS`, `LIABILITY_SCOPE`의 9종이다.

## 4. 챗봇

요청:

```ts
POST /api/v1/qualification-judgment-runs/{runId}/chat
{
  question: string;
  history: Array<{ question: string; answer: string }>;
}
```

응답은 `{ text, status }`이며 `status`는 `OK | EMPTY_QUESTION |
NARRATOR_UNAVAILABLE | FAILED`다.

- FAB 또는 명시적 토글로 패널을 켜고 끈다.
- 끈 상태에서는 헤더만 접는 것이 아니라 챗봇 패널 전체를 DOM에서 숨기거나
  `hidden` 처리한다.
- 패널을 닫아도 같은 `runId`의 대화 기록은 유지하고, 공고/판정 실행이 바뀌면 초기화한다.
- 서버는 확정된 브리핑만 컨텍스트로 사용하므로 프론트에서 별도의 판정 문구를 프롬프트에
  합성하지 않는다.

## 5. 사업계획서 초안

요청:

```ts
POST /api/v1/qualification-judgment-runs/{runId}/business-plan-draft
{
  inputs: {
    company_overview: string;
    proposal_goal: string;
    approach: string;
    differentiators: string;
    staffing: string;
    schedule: string;
    additional_notes: string;
  }
}
```

응답은 `{ text, status, disclaimer, notice_id, source }`다. `status`는 `OK |
EMPTY_INPUT | NARRATOR_UNAVAILABLE | FAILED`이며, `disclaimer`는 초안 아래에 항상
표시한다. 생성 결과는 Markdown으로 렌더링하되 자동 저장·제출하지 않는다.

## 6. 구현 순서

1. API 타입에 `dropped_requirements`, 브리핑·위험조항·챗봇·초안 응답을 추가한다.
2. 기존 결과 화면에서 분석 결과 조회 후 탈락 원문 영역을 붙인다.
3. 판정 완료 후 `run_id`로 브리핑을 조회해 요약·근거·위험조항을 그린다.
4. 근거 원문 펼침과 인용 강조를 붙인다.
5. 챗봇 전체 패널 토글과 이력 전송을 붙인다.
6. 사업계획서 입력 폼과 Markdown 결과·검토 경고를 붙인다.
7. OpenAI 미설정·호출 실패 상태에서도 기존 판정 화면이 깨지지 않는지 확인한다.
