# 위험조항 유형 확정 · 팀 공유용

> 그대로 복사해서 붙여넣도록 만든 문서입니다. 아래 두 블록이 전달할 내용 전부입니다.
> 지체상금이 상한·요율 두 값으로 갈리면서 **9개 값**이 되었습니다.

---

## 블록 1 — 확정 목록과 근거 (복사용)

```
[위험조항 유형 확정 + 검출 현황] — LLM/RAG 김재현

■ 확정 9개 값

  1  WARRANTY_PERIOD        하자담보 기간
  2  LATE_PENALTY           지체상금 상한
  3  LATE_PENALTY_RATE      지체상금 요율      ← 새로 나눈 값
  4  COPYRIGHT_OWNERSHIP    저작권(지식재산권) 귀속
  5  ACCEPTANCE_CRITERIA    검사·검수
  6  SCOPE_AMBIGUITY        과업범위 모호 (포괄조항 포함)
  7  TERMINATION_CONDITION  계약해지 요건
  8  PAYMENT_TERMS          대금지급
  9  LIABILITY_SCOPE        손해배상

  수빈님 §4.3 의 8유형을 그대로 쓰되, 지체상금만 상한과 요율로 나눠 9개가 됐습니다.
  ※ 「포괄조항」은 별도 유형이 아니라 6번(과업변경)에 포함됩니다.
    앞서 제가 따로 센 건 착오였고, 그 부분은 목록 수정이 필요 없습니다.

■ 지체상금을 둘로 나눈 이유

  근거 문서가 다르고, 각각 따로 어긋날 수 있습니다.

    LATE_PENALTY       상한  총액이 넘을 수 없는 한도
                             용역계약일반조건 제18조제1항 · 100분의 30
    LATE_PENALTY_RATE  요율  지연 1일당 붙는 비율
                             국가계약법 시행규칙 제75조제3호 · 1천분의 1.25

  용역계약일반조건 제55조는 요율을 직접 정하지 않고 시행규칙 제75조를 가리킵니다.
  그래서 상한은 예규에서, 요율은 법령에서 각각 읽어옵니다.

  공고는 보통 한 문장에 둘 다 씁니다.

    "지체상금은 지연일수 1일당 계약금액의 0.5%로 하며,
     그 총액은 계약금액의 100분의 30을 초과하지 아니한다"

      → 상한 100분의 30 = 적합
         요율 0.5%      = 표준(0.125%)의 4배 → 확인 필요

  전에는 요율을 아예 안 봤습니다. 수빈님이 확인해두신 1천분의 1.25가 근거이고,
  이번에 룰을 붙여서 이런 경우가 잡히게 됐습니다.

■ 검출 현황 : 9 / 9 구현 완료

  값                     근거 조문                          표준값
  ──────────────────────────────────────────────────────────────────────
  1 하자담보 기간         용역계약일반조건 제58조제1항          1년
  2 지체상금 상한         용역계약일반조건 제18조제1항          100분의 30
  3 지체상금 요율         국가계약법 시행규칙 제75조제3호       1천분의 1.25
  4 저작권 귀속           제56조제1항(SW) / 제35조의2제1항(공통)  공동소유
  5 검사·검수            용역계약일반조건 제20조제2항          14일
  6 과업범위 모호         (문장 형태 탐지 — 비교할 기준값 없음)
  7 계약해지 요건         용역계약일반조건 제31조제1항          100분의 40
  8 대금지급             용역계약일반조건 제27조제2항          5일
  9 손해배상             용역계약일반조건 제23조제1항 단서      귀책 없는 손해는 발주기관 부담

  기준값은 코드에 박아두지 않고 계약예규·법령 원문에서 매번 추출합니다.
  개정되면 값이 따라 바뀌고, 개정 사실도 함께 보고됩니다.

■ 알아두실 점 — 계약 종류에 따라 적용 조문이 다릅니다

  용역계약일반조건은 장(章)별로 적용 대상이 갈립니다.
    제2장 일반용역(공통)  → 모든 용역
    제3장 건설사업관리     → CM 용역만
    제4장 소프트웨어용역   → SW 용역만

  하자담보(제58조)와 저작권(제56조)은 제4장이라 SW 공고에만 적용됩니다.
  SW가 아닌 공고에서는 하자담보를 아예 검토하지 않습니다.
  (저작권은 공통 대응 조문 제35조의2가 있어서 그쪽으로 판정합니다)
```

---

## 블록 2 — DB 스키마 제안 (예린님께, 복사용)

```
[조항검토 결과 저장 스키마 제안] — LLM/RAG 김재현

현재 검출은 동작하는데 결과를 남길 테이블이 없어서, 응답으로만 나가고 사라집니다.
라이브 DB 확인 결과 clause / risk 관련 테이블이 아직 없습니다.

■ 먼저 한 가지 — enum 이 아니라 CHECK 로 부탁드립니다

  이 프로젝트는 PostgreSQL enum 타입을 하나도 쓰지 않고 있습니다.
  company_size 같은 닫힌 목록도 전부 CHECK 제약입니다.

    companies_size_valid
      CHECK (company_size IN ('MICRO','SMALL','MEDIUM','MID_SIZED','LARGE','NONE'))

  위험조항 유형도 같은 방식이 관례에 맞을 것 같습니다.

■ 테이블 2개

  -- 한 공고 버전에 대한 조항검토 1회
  clause_review_runs
    id                 uuid        pk default gen_random_uuid()
    notice_version_id  uuid        not null  fk -> bid_notice_versions(id) on delete cascade
    contract_scope     text        not null  -- 어느 장 기준으로 봤는지
    rule_version       text        not null  -- 룰셋 버전
    standards_version  text                  -- 예규 코퍼스 버전
    created_at         timestamptz not null default now()
    CHECK (contract_scope IN ('COMMON','SOFTWARE','CM'))
    index on (notice_version_id, created_at)

  -- 값별 검출 결과 1건
  clause_review_findings
    id                   uuid        pk default gen_random_uuid()
    run_id               uuid        not null  fk -> clause_review_runs(id) on delete cascade
    risk_type            text        not null  -- 대표 한글 라벨
    risk_types           jsonb       not null  -- 전체 한글 라벨. 단일 원인도 배열
    category             text        not null  -- 대표 오류 코드 (기존 그룹핑 컬럼)
    categories           jsonb       not null  -- 전체 오류 코드. 단일 원인도 배열
    rule_id              text        not null  -- 내부 룰 식별자
    detection_method     text        not null
    matched_via          text        not null default 'REGEX'
    verdict              text        not null
    reason               text        not null  -- 사람이 읽을 사유 (코드가 생성)
    matched_text         text                  -- 걸린 공고 문언
    chunk_id             text                  -- 원문 위치
    clause_label         text                  -- 공고상 조항 번호
    excerpt              text                  -- 근거 발췌
    notice_value         numeric               -- 공고에서 읽은 수치
    notice_value_raw     text
    notice_value_unit    text
    standard_source      text                  -- 예: 용역계약일반조건
    standard_clause_ref  text                  -- 예: 용역계약일반조건 제58조제1항
    standard_value       numeric
    standard_value_raw   text                  -- 예: 1년
    standard_excerpt     text                  -- 기준 조문 원문 발췌
    details              jsonb       not null default '{}'::jsonb
    created_at           timestamptz not null default now()

    CHECK (category IN (
      'WARRANTY_PERIOD','LATE_PENALTY','LATE_PENALTY_RATE','COPYRIGHT_OWNERSHIP',
      'ACCEPTANCE_CRITERIA','SCOPE_AMBIGUITY','TERMINATION_CONDITION',
      'PAYMENT_TERMS','LIABILITY_SCOPE'))
    CHECK (jsonb_typeof(risk_types) = 'array' AND jsonb_array_length(risk_types) >= 1
           AND risk_types ->> 0 = risk_type)
    CHECK (jsonb_typeof(categories) = 'array' AND jsonb_array_length(categories) >= 1
           AND categories ->> 0 = category)
    CHECK (detection_method IN ('STANDARD_DIFF','PATTERN_MATCH'))
    CHECK (matched_via IN ('REGEX','EMBEDDING_LLM','STANDARD_UNRESOLVED'))
    CHECK (verdict IN ('NEEDS_REVIEW','COMPLIANT','UNDETERMINED'))
    UNIQUE (run_id, rule_id)
    index on (run_id, verdict)

■ rule_id → category 매핑 (제가 넘겨드릴 값)

    warranty_period        →  WARRANTY_PERIOD
    penalty_cap            →  LATE_PENALTY
    penalty_rate           →  LATE_PENALTY_RATE
    ip_ownership           →  COPYRIGHT_OWNERSHIP
    inspection_period      →  ACCEPTANCE_CRITERIA
    open_ended_scope       →  SCOPE_AMBIGUITY
    termination_threshold  →  TERMINATION_CONDITION
    payment_period         →  PAYMENT_TERMS
    liability_scope        →  LIABILITY_SCOPE
    warranty_bond_rate     →  WARRANTY_PERIOD

■ 설계 의도 세 가지

  (1) category와 risk_type을 분리한 이유
      category는 9종 오류 코드로 그룹핑하고, risk_type은 사람이 읽는 개별 탐지 라벨을
      보존합니다. 「하자보수보증금율」은 risk_type 라벨을 그대로 두고 상위 그룹인
      WARRANTY_PERIOD category로 분류합니다.

  (2) standard_* 를 jsonb 가 아니라 컬럼으로 편 이유
      "어느 조문 기준으로 판정했는지"를 조회·집계할 수 있어야 합니다.
      감사 때 "이 판정의 근거 조문" 질문이 바로 나옵니다.
      지체상금 상한과 요율은 근거 문서가 아예 달라서 특히 그렇습니다.

  (3) COMPLIANT 도 저장하는 이유
      "위험 없음"과 "검토 안 함"은 다릅니다.
      전자는 확인한 결과이고 후자는 공백이라, 담당자에게 다르게 보여야 합니다.

■ 부탁드릴 것

  - 위 스키마로 괜찮은지, 컬럼 이름 관례에 어긋나는 게 있는지
  - UNIQUE (run_id, rule_id) 로 룰당 1건이 맞는지
    (지금은 한 룰에서 가장 심각한 1건만 내보내고 있습니다)
```

---

## 이 문서를 만든 근거

- 유형 확정 경위와 대조표 — [Notion 페이지](https://app.notion.com/p/3d6a017a650d81ecafdbe54b309cbca8?pvs=204)
- 검출 룰 구현 — `apps/api/app/ai/clause_review/`
- 결과 계약 — `apps/api/app/ai/clause_review/contracts.py` (`ClauseFinding`)
- 라이브 DB 확인 (2026-09-09) — clause/risk 테이블 없음, enum 타입 전체 0개
