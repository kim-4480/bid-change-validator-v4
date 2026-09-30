# SPEC.md — 공고 적격성 검토 화면

> 작성 2026-09-09 · 담당 김재현 (LLM/RAG)
> 먼저 [PROJECT.md](PROJECT.md)를 읽으십시오. 특히 "절대 변경하면 안 되는 것".
> **현재 구현은 `apps/api/app/ai/demo_web.py` + `demo_web.html` 에 동작하는 형태로 있습니다.**
> 이 문서는 그 구현의 계약을 확정하고, 남은 작업을 지정합니다.

---

## 1. 이번 기능의 요구사항

### 1.1 한 문장

**고객사 프로필을 넣으면, 그 공고의 자격·제한 항목을 항목별로 적/부 판정하고,
공고 내용을 요약해 보여주고, 무엇을 보완해야 하는지 챗봇으로 답한다.**

### 1.2 기능 단위

| # | 기능 | 상태 | 근거 코드 |
| --- | --- | --- | --- |
| F1 | 공고번호로 나라장터에서 공고·첨부를 받아 텍스트로 만든다 | **동작** | `demo_web._lookup_notice`, `demo.documents.G2BDocumentSource` |
| F2 | 공고 산문에서 참가자격 요건을 구조화한다 | **동작** | `analysis_pipeline.analyze_qualification_documents` |
| F3 | 프로필과 요건을 대조해 항목별 적/부를 판정한다 | **동작** | `judgment.judge_requirements` |
| F4 | 판정마다 근거를 요약 + 원문 발췌 2단으로 제시한다 | **동작** | `briefing.build_briefing` + `demo_web._evidence_json` |
| F5 | 계약조건이 계약예규와 어긋나는지 검토한다 | **동작** | `clause_review.detect_standard_diff` / `detect_patterns` |
| F6 | 공고 내용을 요약한다 (개요 + 주제 7종) | **동작** | `notice_digest.build_notice_digest` |
| F7 | 챗봇이 확정된 판정만 보고 답한다 | **동작** | `briefing.answer_question` |
| F8 | 공고가 요구할 때만 프로필 확장항목을 묻는다 | **부분** | `extensions.describe_required` — 화면 표시만, 입력 반영 미구현 |
| F9 | 판정·검토 결과를 DB에 남긴다 | **미구현** | 저장 테이블 없음 |
| F10 | 정정공고 변경분만 재판정한다 | **미구현** | `requirement_diff.py` 존재, 화면 미연결 |

### 1.3 이번 범위에서 제외

- 로그인·권한 (데모는 단일 사용자)
- 프로필 영속화 (화면 새로고침하면 사라짐)
- 제품 화면(`apps/web`) 연결 — 이 데모는 참조 구현이며 프론트 담당 영역을 대체하지 않음

---

## 2. UI 동작

`http://localhost:8200` — 탭 3개.

### 2.1 공고 검토 탭 (주 화면)

```
┌ 검토할 공고 ────────────────────────────────────┐
│ [공고번호 입력]              [불러오기]           │
│ 캐시된 공고 칩 (클릭 시 즉시 로드)                 │
│ ── 로드 후 ──                                    │
│ 공고번호 / 공고명 / 발주기관 / 마감일시             │
│ 업무구분 / 적용 기준 / 첨부 목록                   │
└─────────────────────────────────────────────────┘
┌ 공고문 요약  [AI 서술 · 판정 아님] ──────────────┐
│ 개요 한 단락                                     │
│ ▸ 사업 개요 / 참가자격 / 과업 내용 / 제출 서류 …   │  ← 펼치면 주제별 요약 + 근거 청크 id
└─────────────────────────────────────────────────┘
┌ 좌: 프로필 빌더 ──────┐ ┌ 우: 판정 결과 ─────────┐
│ 기업 기본정보          │ │ 참가자격                │
│  회사명 · 기업규모      │ │  [충족 n][미충족 n][확인불가 n]
│  소재지역 · 지역코드    │ │  항목별 카드            │
│ 업종 · 인증 (칩)       │ │ 확인 필요 계약조항       │
│ 기술인력 (총원/등급별)  │ │ 판정 대상 아닌 확인사항   │
│ 사업실적 (행 추가/삭제) │ │                        │
│ [참가자격 판정]        │ │                        │
└───────────────────────┘ └───────────────────────┘
                                      [?] 도우미 FAB
```

### 2.2 판정 카드 — 근거 2단 (이번 기능의 핵심)

```
┌ [미충족] COMPANY_SIZE ──────────────────────────┐
│ 사유   회사 프로필이 요건에 미치지 못합니다        │
│ ─────────────────────────────────────────────  │
│ 근거 — 공고가 요구한 내용                        │  ← 1단: 항상 보임
│ 사업금액 20억 미만의 사업으로서, 「소프트웨어…     │
│                                                 │
│ ▸ 원문 발췌 보기 (p.2 · CHUNK-0002)             │  ← 2단: 접힘
└─────────────────────────────────────────────────┘
```

**펼쳤을 때 규칙**

- 인용문(`quote`)이 아니라 **그 문장이 있던 청크 전체(`source_text`)** 를 보여준다
- 인용 부분에 `<mark>` 하이라이트를 건다
- 위치(`location`, `chunk_id`)를 함께 표기한다
- `source_text`가 없으면 `quote`만 보여준다

계약조항 카드는 발췌가 둘이다 — **공고 원문 발췌**와 **기준 조문 원문**을 각각 접어 둔다.

### 2.3 상태 표시 규칙

| 상태 | 색 | 정렬 |
| --- | --- | --- |
| UNSATISFIED / NEEDS_REVIEW | 빨강 | 맨 위 |
| UNKNOWN / UNDETERMINED | 노랑 | 가운데 |
| SATISFIED / COMPLIANT | 초록 | 아래 |

- 계약조항 목록은 **COMPLIANT를 숨긴다** (집계 숫자로만 표시)
- 참가자격은 **전부 보여준다** — 충족도 근거를 확인할 수 있어야 한다

### 2.4 열화 동작

| 상황 | 화면 |
| --- | --- |
| `OPENAI_API_KEY` 없음 | 헤더 chip "LLM 없음 · 조항검토만 가능". 요약·판정 카드는 이유를 문장으로 표시 |
| 공고번호 없음 | 입력 아래 빨간 문장. 하이픈 없이 넣으라고 안내 |
| 첨부에서 텍스트 못 읽음 | 공고정보는 표시하고 검토는 생략 |
| 요건 0건 | "판정할 요건을 찾지 못했습니다" + 흔한 이유 설명 |
| 해당 계약 종류에 기준 조문 없음 | 그 룰은 **아예 표시하지 않는다** (판정 보류와 구분) |

---

## 3. 데이터 구조

### 3.1 `POST /api/notice` — 공고 로드

**요청**
```json
{ "notice_no": "R26BK01705963", "refresh": false }
```

**응답**
```jsonc
{
  "context_id": "R26BK01705963",
  "notice": {
    "notice_no": "...", "name": "...", "institution": "...",
    "demand_institution": "...", "deadline": "...", "price": "...",
    "business_type": "SERVICE"        // SERVICE|GOODS|CONSTRUCTION|FOREIGN|OTHER
  },
  "documents": [{ "filename": "...", "bytes": 150366, "blocks": 98, "error": null }],
  "chunk_count": 326,
  "char_count": 127146,
  "contract_scope": "SOFTWARE",       // COMMON|SOFTWARE|CM|GOODS|CONSTRUCTION
  "scope_label": "용역계약일반조건 제4장 …",
  "counts": { "NEEDS_REVIEW": 1, "COMPLIANT": 3, "UNDETERMINED": 1 },
  "findings": [ /* 3.3 */ ],
  "requirement_count": 3,
  "extraction_note": "",              // 비어있지 않으면 요건을 못 뽑은 이유
  "summary": "…",                     // null 이면 요약 없음
  "summary_available": true,
  "sections": [{ "topic": "QUALIFICATION", "label": "참가자격",
                 "summary": "…", "chunk_ids": ["CHUNK-0002"] }],
  "requirements": [{ "requirement_key": "...", "type": "COMPANY_SIZE", "raw": "..." }],
  "extensions": [{ "key": "sw_engineer_grade", "label": "...", "why": "...",
                   "ask": "...", "input_hint": "..." }]
}
```

오류일 때: `{ "error": "NOTICE_NOT_FOUND" | "NO_READABLE_DOCUMENT", "message": "..." }`

### 3.2 `POST /api/judge` — 참가자격 판정

**요청** — `profile`은 `judgment.CompanyProfileSnapshot` 스키마. `company_id`는 서버가 채운다.
```jsonc
{
  "context_id": "R26BK01705963",
  "profile": {
    "region_code": "11", "region_name": "서울특별시",
    "company_size": "MEDIUM",         // MICRO|SMALL|MEDIUM|MID_SIZED|LARGE|NONE
    "industries":   [{ "code": "1468", "name": "소프트웨어개발" }],
    "staff": { "total_count": 24,
               "roles": [{ "role_name": "특급", "headcount": 2 }] },
    "certifications": [{ "ref": "C1", "name": "직접생산확인증명서" }],
    "performances":   [{ "ref": "P1", "name": "통합정보시스템 구축",
                         "amount": 620000000, "completed_at": "2025-11-30" }],
    "completeness": { "staff_roles": true, "performances": true, "certifications": true }
  }
}
```

**응답**
```jsonc
{
  "overall_status": "eligible",
  "overall_label": "적격",
  "counts": { "SATISFIED": 3, "UNSATISFIED": 0, "UNKNOWN": 0 },
  "judgments": [{
    "requirement_key": "...",
    "type": "COMPANY_SIZE",
    "status": "SATISFIED",            // SATISFIED|UNSATISFIED|UNKNOWN
    "status_label": "충족",
    "reason": "회사 프로필이 요건을 충족합니다",   // 코드 생성. 모델 아님
    "basis": "회사 프로필",
    "requires_evidence": false,
    "requirement_raw": "…",           // 근거 1단
    "profile_refs": [{ "kind": "company", "field": "company_size", "value": "MEDIUM" }],
    "evidence": [{                    // 근거 2단
      "quote": "…",                   // 뽑아낸 문장
      "location": "p.2",              // 없을 수 있음
      "chunk_id": "CHUNK-0002",
      "source_text": "…"              // 청크 전체. 펼침에서 사용
    }]
  }],
  "notice_facts": [{ "code": "UNMAPPED_REQUIREMENT", "message": "...",
                     "raw": "...", "evidence": [ /* 동일 */ ] }]
}
```

오류: `{ "error": "CONTEXT_NOT_FOUND" | "NO_REQUIREMENTS" | "INVALID_PROFILE", "message": "..." }`

### 3.3 `finding` (계약조건 검토 결과)

```jsonc
{
  "risk_type": "지체상금 요율 과다",   // 대표 한글 라벨
  "risk_types": [                     // 같은 원문에 걸린 전체 한글 라벨
    "지체상금 요율 과다", "지체상금 상한 초과"
  ],
  "category": "LATE_PENALTY_RATE",    // 대표 오류 코드
  "categories": [                     // 전체 오류 코드 JSONB. 단일 원인도 길이 1
    "LATE_PENALTY_RATE", "LATE_PENALTY"
  ],
  "label": "지체상금 요율 과다",
  "rule_id": "penalty_rate",
  "verdict": "NEEDS_REVIEW",          // NEEDS_REVIEW|COMPLIANT|UNDETERMINED
  "verdict_label": "확인 필요",
  "reason": "공고 값이 표준(…)을 초과",
  "matched_text": "…",                // 걸린 공고 문언
  "clause_label": "6.1", "chunk_id": "CHUNK-0123",
  "excerpt": "…",                     // 공고 원문 발췌
  "notice_value_raw": "0.5%", "notice_value": 0.5,
  "standard": { "clause_ref": "국가계약법 시행규칙 제75조제3호",
                "description": "…", "value_raw": "1천분의 1.25",
                "text_excerpt": "…" },   // 기준 조문 원문
  "drift": null                       // 예규 개정 감지 시 {recorded, extracted}
}
```

대표 `category`와 이에 대응하는 `risk_type`은 같은 원문 조항에 걸린 결과 중 다음
순서로 정한다.

1. 판정 조치 필요도: `NEEDS_REVIEW` → `UNDETERMINED` → `COMPLIANT`
2. 같은 판정이면 §4.2의 확정 위험유형 9종 순서

따라서 탐지기 실행 순서가 바뀌어도 대표 분류는 변하지 않으며, 정상 판정이 확인 필요
판정보다 먼저 그룹 대표가 되는 일도 없다. `categories[0]`은 항상 `category`와 같다.
같은 방식으로 `risk_types[0]`은 항상 `risk_type`과 같다.

### 3.3.1 구조화 탈락 요건

`RequirementAnalysisResult`는 원문 대조에서 탈락한 모델 후보를 진단 문자열과 분리해
다음 배열로 제공한다.

```json
{
  "dropped_requirements": [
    {
      "raw": "모델이 추출한 요건 원문 전체",
      "reason_code": "RAW_NOT_FOUND_IN_SOURCE"
    }
  ]
}
```

`raw`는 길이를 자르지 않는다. `reason_code`는 `MISSING_RAW`,
`RAW_NOT_FOUND_IN_SOURCE`, `DETAIL_NOT_FOUND_IN_SOURCE`,
`SOURCE_VALIDATION_FAILED` 중 하나이며 표시 문장은 프론트에서 매핑한다.

### 3.4 나머지 엔드포인트

| 메서드 | 경로 | 용도 |
| --- | --- | --- |
| GET | `/api/health` | `llm_available`, `narrator_available`, `cached_notices` |
| GET | `/api/standards` | 계약 종류별 기준값 (원문에서 즉시 추출) |
| POST | `/api/review-text` | 문장 하나 즉석 검토 `{text, scope}` |
| POST | `/api/assist` | 챗봇 `{context_id, question, profile?, history[]}` |
| POST | `/api/business-plan-draft` | 판정 브리핑 + 사용자 입력으로 사업계획서 초안 생성 |

### 3.5 `POST /api/business-plan-draft` — 사업계획서 초안

판정 결과를 바꾸지 않고 `briefing.render_briefing_text()`의 확정 정보와 사용자가 직접
입력한 회사·수행 정보만 `Narrator`에 전달합니다. 출력 목차는 서버 프롬프트에 고정되어
있으며 모든 응답에 검토 필요 경고가 포함됩니다.

**요청**

```json
{
  "context_id": "R26BK01705963",
  "profile": {
    "company_size": "MEDIUM",
    "region_name": "서울특별시",
    "industries": [],
    "staff": {"total_count": 24, "roles": []}
  },
  "inputs": {
    "company_overview": "공공 정보시스템 구축 경험 보유",
    "proposal_goal": "안정적인 통합플랫폼 전환",
    "approach": "단계별 데이터 이관과 검증",
    "differentiators": "",
    "staffing": "PM 1명과 개발팀 투입",
    "schedule": "",
    "additional_notes": "보안 대응을 강조"
  }
}
```

**응답**

```json
{
  "text": "# 1. 사업 이해 및 제안 목표\n…",
  "status": "OK",
  "disclaimer": "AI가 작성한 사업계획서 초안입니다. 제출 전에 담당자가 사실과 표현을 검토하세요.",
  "notice_id": "R26BK01705963",
  "source": {
    "notice_id": "R26BK01705963",
    "judgment_count": 3,
    "flagged_clause_count": 1
  }
}
```

`status`: `OK | EMPTY_INPUT | NARRATOR_UNAVAILABLE | FAILED`. 입력에 없는 사실은 모델이
채우지 않고 `[담당자 확인 필요: ...]`로 표시하도록 강제합니다.

### 3.6 서버 상태

`_contexts: dict[notice_no, ctx]` — **메모리 캐시일 뿐 저장소가 아닙니다.**
프로세스가 죽으면 사라집니다. DB에 남기는 것은 F9(미구현).

---

## 4. 완료 조건

### 4.1 이미 충족된 것 (회귀 방지 대상)

- [x] 공고번호 하나로 조회 → 첨부 다운로드 → 추출 → 청킹까지 자동
- [x] 계약 종류를 업무구분에서 판별하고, 종류별로 다른 예규 조문을 적용
- [x] 비교 기준값이 코드에 없고 원문에서 매번 추출됨 (`--standards`로 확인 가능)
- [x] 판정마다 요건 문장 + 원문 청크가 붙어 나옴
- [x] `OPENAI_API_KEY` 없이도 계약조건 검토는 동작
- [x] 테스트 152개 통과

### 4.2 이번에 끝내야 하는 것

- [ ] **F8 확장항목 입력 반영** — `describe_required()`가 돌려준 질문을 화면에서 입력받아
      판정에 반영. 현재는 안내만 표시하고 값이 판정에 들어가지 않음
- [ ] **SW기술자 등급 판정 경로 확정** — 지금은 `staff.roles`에 `특급/고급/중급`으로 넣어
      `_judge_staff`가 처리. `extensions._sw_grade_judge`와 이중 경로인지 정리 필요
- [ ] **`payment_period` UNDETERMINED 원인 규명** — 실제 공고에서 "관련 조항은 있으나
      수치 정규화 실패"가 반복됨. 문언을 확인해 anchor를 넓힐지, 보류가 맞는지 결정
- [ ] **공사 공고 지체상금 UNDETERMINED 원인 규명** — 같은 청크(제19조)에 조항은 있으나
      수치를 못 읽음. 표 형태이거나 계약서로 위임했을 가능성

### 4.3 다음 단계 (이번 범위 아님)

- [ ] F9 결과 저장 — 스키마 제안은 [05-clause-types-team-share.md](05-clause-types-team-share.md)
- [ ] F10 정정공고 변경분 재판정 — `requirement_diff.py` 연결
- [ ] 측정 하네스 — 골든셋으로 미검출/오탐을 셀 수 있게. **임베딩을 켤지 판단하는 전제**

---

## 5. 테스트 방법

### 5.1 자동 테스트

```bash
python -m pytest apps/api/tests/ --noconftest -q \
  --ignore=apps/api/tests/test_companies.py --ignore=apps/api/tests/test_notices.py \
  --ignore=apps/api/tests/test_master_codes.py --ignore=apps/api/tests/test_mvp_golden_e2e.py \
  --ignore=apps/api/tests/test_notice_polling.py --ignore=apps/api/tests/test_bootstrap_product_data.py \
  --ignore=apps/api/tests/test_product_data_inventory.py \
  --ignore=apps/api/tests/test_product_golden_candidates.py \
  --ignore=apps/api/tests/test_product_golden_inspector.py \
  --ignore=apps/api/tests/test_seed_product_golden_demo.py
```

**152 passed** 가 기준선입니다. 줄어들면 회귀입니다.

관련 테스트 파일:

| 파일 | 무엇을 지키는가 |
| --- | --- |
| `test_clause_review_standard_diff.py` | 계약 종류별 조문 선택, 지체상금 상한/요율 분리, 값이 엉뚱한 룰로 새지 않음 |
| `test_clause_review_corpus.py` | 실제 `clauses.json`에서 9개 기준값이 전부 읽힘, 예규 개정 감지 |
| `test_clause_review_patterns.py` | 포괄조항 탐지 |
| `test_qualification_judgment.py` | 요건 유형별 판정. **기업규모 "참여 제한" 반전 포함** |
| `test_requirement_extraction.py` | 근거조항 가드레일 (법령 인용을 문서 조항으로 오인하지 않음) |
| `test_briefing.py` | 판정 사유를 코드가 만든다, 챗봇이 판정을 새로 내리지 않는다 |
| `test_canonicalize.py` | 매핑 실패해도 근거는 남는다 |

### 5.2 수동 확인 — 기준값이 코드에 없다는 것

```bash
python -m apps.api.app.ai.demo --standards
```

계약 종류 5종 × 룰 9종이 나옵니다. **`ok` 행의 값은 전부 방금 원문에서 읽은 것**이고,
`— (이 계약 종류에는 해당 조문 없음)`은 정상 결과입니다.

예규 원문을 바꿔 확인하는 것이 가장 확실합니다.

```bash
# data/standards/ 의 예규에서 "1년간" → "2년간" 으로 바꾸고
python scripts/build_standard_clauses.py
# → warranty_period 가 24개월로 바뀌고 drift 경고가 뜬다
```

### 5.3 수동 확인 — 화면

```bash
uvicorn apps.api.app.ai.demo_web:app --port 8200
```

| 시나리오 | 공고번호 | 기대 |
| --- | --- | --- |
| 소프트웨어 용역 | `R26BK01705963` | scope=SOFTWARE, 요건 3건, 판정 적격(기본 프로필), 요약·주제 7종 |
| 공사 | `R26BK01716363` | scope=CONSTRUCTION, 근거 조문이 **공사계약일반조건**으로 표시 |
| 물품 | `R26BK01715895` | scope=GOODS, 검출 적음(규격서 위주) — 정상 |

**반드시 확인할 것**

1. 판정 카드의 `▸ 원문 발췌 보기`를 펼치면 **인용보다 긴 원문**이 나오고 하이라이트가 걸리는가
2. 공사 공고에서 근거 조문이 용역계약일반조건이 아닌가 (용역이 뜨면 4.3의 회귀)
3. `기업규모` 요건이 "대기업·중견기업 참여 제한"일 때 **중소기업이 충족**으로 나오는가

### 5.4 API 단독 확인

Windows 셸에서 한글 본문을 `curl -d`로 직접 넘기면 인코딩이 깨집니다. 파일로 보내십시오.

```bash
python -c "import json;open('b.json','w',encoding='utf-8').write(json.dumps({'notice_no':'R26BK01705963'},ensure_ascii=False))"
curl -s -X POST http://127.0.0.1:8200/api/notice \
     -H "Content-Type: application/json" --data-binary @b.json
```

---

## 6. 알려진 한계

이미 파악했고 **숨기지 않기로 한** 것들입니다. 화면·응답에 그대로 드러납니다.

| 한계 | 현재 동작 |
| --- | --- |
| 예규 원문의 예외 단서를 읽지 못함 ("별도 법률에서 따로 정하는 경우 제외") | 단서를 무시하고 표준값과 비교 |
| CM 전용 손해배상 조문(용역 제41조) 미반영 | 공통 제23조로 폴백 |
| 시행규칙 제75조의 제4·5호(군용 음식료품, 운송·보관) 미사용 | 용역/공사/물품 3개 호만 사용 |
| 공사 하자담보 기간에 고정값 없음 (시행령·시행규칙 공종별 표에 위임) | 검토 대상에서 제외 |
| 물품에 손해배상·계약해지 기준 조문 없음 | 검토 대상에서 제외 |
| 청크 id가 위치 기반이라 청킹을 고치면 어긋남 | [04-chunk-store-draft.md](04-chunk-store-draft.md) 참조 |
