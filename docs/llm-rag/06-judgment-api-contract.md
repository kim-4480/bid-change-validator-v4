# 06 — 판정 정보 전달 기술 명세서

> 작성 2026-09-10 · 김재현 (LLM/RAG) · **인수인계용**
> 판정 결과가 **AI 라이브러리 → 서비스 → DB → API → 프론트**로 어떻게 흘러가는지,
> 지금 무엇이 연결되어 있고 무엇이 끊겨 있는지를 확정합니다.
>
> 이 문서는 **실제 코드를 읽고 작성**했습니다. 추정이 아니라 현재 상태입니다.

---

## 0. 한 장 요약

```
                    ┌─────────────────────────────────────────┐
                    │  app/ai/**   판정 엔진 (순수 라이브러리)  │
                    │  DB·네트워크·ORM 의존 없음               │
                    └────────────────┬────────────────────────┘
                                     │ Pydantic 객체를 반환할 뿐
                                     │ 저장도 응답도 하지 않음
                    ┌────────────────▼────────────────────────┐
                    │  app/qualification_*.py   서비스 계층     │
                    │  라이브러리 호출 → ORM 레코드로 변환·저장  │
                    └────────────────┬────────────────────────┘
                                     │
                    ┌────────────────▼────────────────────────┐
                    │  app/qualification_*_router.py           │
                    │  HTTP 노출. main.py 가 include_router    │
                    └────────────────┬────────────────────────┘
                                     │ JSON
                    ┌────────────────▼────────────────────────┐
                    │  apps/web   Next.js 프론트               │
                    └─────────────────────────────────────────┘
```

**핵심 원칙 — 이 경계는 단방향입니다.**
`app/ai`는 자기 아래 계층을 모릅니다. DB에 무엇이 저장되는지, 어떤 URL로
노출되는지 알지 못하고 알 필요도 없습니다. 그래서 판정 로직만 따로 테스트할 수
있고, 데모 앱(`demo_web.py`)이 DB 없이 같은 판정을 돌릴 수 있습니다.

---

## 1. 현재 연결 상태 (2026-09-10 기준)

### 1.1 라우터 등록 현황

`apps/api/app/main.py`가 등록하는 것:

| 라우터 | 등록 | 프론트 사용 |
| --- | :---: | :---: |
| `qualification_analysis_router` | ✅ | ✅ |
| `qualification_judgment_router` | ✅ | ✅ |
| `qualification_ask_back_router` | ✅ | ✅ |
| `qualification_revalidation_router` | ✅ | ✅ |
| `qualification_matching_router` | ✅ | ✅ |
| **`qualification_briefing_router`** | **❌ 미등록** | **❌ 미사용** |

> **`qualification_briefing_router.py` 파일은 존재하지만 `main.py`가 import 하지
> 않습니다.** 공고 요약·브리핑·챗봇 4개 엔드포인트가 코드로만 있고 HTTP로
> 노출되지 않은 상태입니다. 제품 목표의 "요약"과 "챗봇"이 여기 들어 있습니다.

### 1.2 계약조건 검토(9종 위험조항)의 전달 경로

**없습니다.** `app/ai/clause_review/`는 완성되어 동작하지만,

- 저장할 DB 테이블이 없고
- 노출하는 라우터가 없고
- 프론트가 호출하는 곳이 없습니다

현재 이 결과를 볼 수 있는 유일한 경로는 데모 앱(`demo_web.py`)뿐입니다.
스키마 제안은 [05-clause-types-team-share.md](05-clause-types-team-share.md).

---

## 2. 참가자격 판정 — 전체 흐름

### 2.1 두 단계로 나뉩니다

판정은 **한 번의 호출이 아니라 두 번**입니다. 이유는 재사용입니다 — 공고 분석은
회사와 무관하므로 한 번만 하고, 판정은 회사마다 다시 합니다.

```
[1단계] 공고 분석 (회사 무관, 공고 버전당 1회)
  POST /api/v1/notices/{notice_id}/versions/{version_number}/qualification-analysis
     → analysis_pipeline.analyze_qualification_documents()   ★ 모델 사용
     → 요건(QualificationRequirement) + 근거(Evidence) 를 DB에 저장
     → QualificationAnalysisRun 생성

[2단계] 판정 (회사별, 분석 결과를 재사용)
  POST /api/v1/preflight-cases/{case_id}/qualification-judgments
     → judgment.judge_requirements(요건, 프로필)                ★ 모델 미사용
     → QualificationJudgmentRun + JudgmentRecord 저장
```

**1단계에서만 모델을 씁니다.** 2단계는 순수 코드라 같은 입력이면 항상 같은 결과가
나옵니다. 이 분리가 "판정은 코드가 한다"(PROJECT.md 3.1)를 구조로 강제합니다.

### 2.2 서비스 계층이 하는 일

`apps/api/app/qualification_judgment.py`

```python
run_qualification_judgment(db, case_id=..., analysis_run_id=..., reference_date=...)
  │
  ├─ 1. case → company, analysis_run 조회
  ├─ 2. build_company_profile_snapshot(company, completeness)
  │        ORM Company  →  app.ai.judgment.CompanyProfileSnapshot
  │        ★ 여기가 DB 모델과 AI 계약의 유일한 변환 지점
  ├─ 3. judge_requirements(analysis.requirements, profile, ...)
  │        ★ app.ai 호출. 순수 함수. DB 모름
  ├─ 4. QualificationJudgmentRun 레코드 생성 (overall_status, profile_snapshot 등)
  └─ 5. judgment 하나당 QualificationJudgmentRecord 생성
```

**주의할 점.** `profile_snapshot`은 판정 당시의 회사 프로필을 **통째로 JSON으로
박제**합니다. 회사 정보가 나중에 바뀌어도 그때 왜 그렇게 판정했는지 재현할 수
있어야 하기 때문입니다. 이 필드를 지우면 감사 추적이 끊깁니다.

---

## 3. 엔드포인트 명세

모든 경로의 prefix는 `/api/v1`입니다.

### 3.1 공고 분석 (요건 추출)

| 메서드 | 경로 | 응답 |
| --- | --- | --- |
| POST | `/notices/{notice_id}/versions/{version_number}/qualification-analysis` | `QualificationAnalysisRunRead` |
| GET | `/notices/{notice_id}/versions/{version_number}/qualification-analyses` | `list[QualificationAnalysisRunSummary]` |
| GET | `/qualification-analyses/{run_id}` | `QualificationAnalysisRunRead` |

POST는 **모델을 호출하므로 느리고 비용이 듭니다.** 같은 공고 버전에 대해
반복 호출하지 마십시오. 이미 분석된 것이 있으면 GET으로 재사용합니다.

### 3.2 참가자격 판정

| 메서드 | 경로 | 응답 |
| --- | --- | --- |
| POST | `/preflight-cases/{case_id}/qualification-judgments` | `QualificationJudgmentRunRead` |
| GET | `/preflight-cases/{case_id}/qualification-judgment-runs` | `list[QualificationJudgmentRunSummary]` |
| GET | `/qualification-judgment-runs/{run_id}` | `QualificationJudgmentRunRead` |
| GET | `/companies/{company_id}/qualification-profile-completeness` | `QualificationProfileCompletenessRead` |
| PATCH | `/companies/{company_id}/qualification-profile-completeness` | `QualificationProfileCompletenessRead` |

### 3.3 되묻기 (부족한 프로필 정보 채우기)

| 메서드 | 경로 | 응답 |
| --- | --- | --- |
| GET | `/preflight-cases/{case_id}/qualification-questions` | `list[QualificationQuestionRead]` |
| POST | `/preflight-cases/{case_id}/qualification-answers` | `QualificationAnswerRead` |

`UNKNOWN` 판정이 나온 요건에 대해 "이걸 알려주면 판정할 수 있습니다"를 질문으로
돌려줍니다. 답을 받으면 재판정(3.4)으로 뒤집힐 수 있습니다.

### 3.4 재검증 · 매칭

| 메서드 | 경로 | 응답 |
| --- | --- | --- |
| POST | `/preflight-cases/{case_id}/qualification-revalidation` | `QualificationRevalidationRead` |
| GET | `/companies/{company_id}/notice-matches` | `NoticeMatchSearchResponse` |

### 3.5 요약 · 브리핑 · 챗봇 — **미등록**

`qualification_briefing_router.py`에 구현되어 있으나 `main.py`에 등록되지 않아
현재 호출할 수 없습니다.

| 메서드 | 경로 | 응답 |
| --- | --- | --- |
| POST | `/notices/{notice_id}/versions/{version_number}/notice-digest` | `NoticeDigest` |
| GET | `/qualification-judgment-runs/{run_id}/briefing` | `NoticeBriefing` |
| POST | `/qualification-judgment-runs/{run_id}/briefing-narrative` | `NoticeSummary` |
| POST | `/qualification-judgment-runs/{run_id}/chat` | `ChatAnswer` |

**등록 방법** — `main.py`에 두 줄 추가하면 됩니다. 다만 **`main.py`는 Backend
소유**이므로 직접 고치지 말고 담당자에게 요청하십시오.

```python
from .qualification_briefing_router import router as qualification_briefing_router
app.include_router(qualification_briefing_router)
```

---

## 4. 판정 결과 데이터 구조

### 4.1 `QualificationJudgmentRunRead` — 프론트가 받는 최상위 객체

`apps/api/app/judgment_schemas.py`

```jsonc
{
  "id": "uuid",
  "preflight_case_id": "uuid",
  "analysis_run_id": "uuid",        // 어느 공고 분석을 썼는지
  "company_id": "uuid",
  "notice_version_id": "uuid",      // 공고 "버전" 단위. 정정공고는 다른 버전
  "overall_status": "eligible",     // eligible | ineligible | indeterminate
  "rule_version": "...",            // 판정 규칙 버전. 재현에 필요
  "reference_date": "2026-09-10",   // 기간 요건 계산 기준일
  "analysis_status": "OK",
  "profile_completeness": { ... },  // 어떤 프로필 항목이 확정되었는지
  "profile_snapshot": { ... },      // 판정 당시 프로필 전문 (박제)
  "judgments": [ /* 4.2 */ ],
  "created_at": "2026-09-10T..."
}
```

### 4.2 `Judgment` — 요건 하나에 대한 판정

`apps/api/app/ai/contracts.py`

```jsonc
{
  "judgment_key": "...",
  "preflight_case_id": "...",
  "notice_version_id": "...",
  "requirement_key": "...",        // ★ 어느 요건에 대한 판정인지 (4.3과 연결)
  "status": "SATISFIED",           // SATISFIED | UNSATISFIED | UNKNOWN
  "basis_type": "PROFILE",         // PROFILE | USER_ANSWER | NONE
  "evidence_held": false,          // 증빙 서류를 실제로 보유 확인했는가
  "reason_code": "RULE_MATCH",     // ★ 4.4 참조
  "requires_evidence": false,      // 제출 전 증빙이 필요한 유형인가
  "profile_refs": [                // 프로필의 어느 값을 근거로 삼았는가
    { "kind": "company", "field": "company_size", "value": "MEDIUM" }
  ],
  "requirement_evidence_keys": ["..."],   // ★ 공고 원문 근거 (4.3과 연결)
  "rule_version": "..."
}
```

**`Judgment`에는 사람이 읽을 문장이 없습니다.** 의도된 설계입니다 —
`reason_code`만 담고, 문장은 표시 계층에서 만듭니다(4.4).

### 4.3 근거를 원문까지 되짚는 법

판정 → 요건 → 근거는 **키로 연결**되어 있습니다. 프론트는 이 사슬을 따라가야
"왜 이 판정인가"를 원문까지 보여줄 수 있습니다.

```
Judgment.requirement_key
    └→ QualificationRequirement.requirement_key
          ├─ .raw                 공고에서 뽑아낸 요건 문장   ← 근거 1단
          └─ .evidence_keys[]
                └→ Evidence.evidence_key
                      ├─ .quote               인용문        ← 근거 2단
                      ├─ .location            위치 (page/block/clause_label/display)
                      ├─ .chunk_id            원문 청크 식별자
                      └─ .document_id         어느 첨부인지
```

`Judgment.requirement_evidence_keys`는 위 사슬을 미리 펼쳐둔 지름길입니다.

**`Evidence.location`이 왜 이렇게 복잡한가.** HWP/HWPX에는 PDF 같은 "페이지"가
없습니다. 그래서 Backend의 `extracted_blocks` 인덱스(`block_start`/`block_end`)를
진짜 기준으로 삼고, `page`는 있으면 채우는 부가 정보입니다. 화면 표시는
`display` 필드를 쓰십시오 — 사람이 읽을 수 있게 조립된 문자열입니다.

### 4.4 `reason_code` → 표시 문장

| `reason_code` | 뜻 |
| --- | --- |
| `RULE_MATCH` | 프로필이 요건을 충족 |
| `RULE_MISMATCH` | 프로필이 요건에 미달 |
| `INSUFFICIENT_DATA` | 프로필 정보가 없어 판정 불가 |
| `NEEDS_REVIEW` | 사람 확인 필요 |
| `UNSUPPORTED_REQUIREMENT` | 코드가 지원하지 않는 요건 형태 |

**문장 매핑은 `app/ai/briefing.py`의 `REASON_LABELS`에 있습니다.**
프론트에서 문장을 새로 만들지 마십시오. 두 곳에 문구가 생기면 화면과 API 응답이
서로 다른 말을 하게 됩니다. 문장이 필요하면 브리핑 엔드포인트(3.5)를 쓰거나,
`REASON_LABELS`를 단일 출처로 삼아 내려보내는 필드를 추가하십시오.

### 4.5 상태값 해석 — 세 가지를 구분해야 합니다

| `overall_status` | 뜻 | 화면 처리 |
| --- | --- | --- |
| `eligible` | 모든 필수 요건 충족 | 진행 가능 |
| `ineligible` | 하나 이상 미달 | 어느 요건인지 보여줄 것 |
| `indeterminate` | **판정하지 못한 요건이 있음** | 되묻기(3.3)로 유도 |

`indeterminate`를 `ineligible`처럼 빨갛게 표시하면 안 됩니다. **"자격이 없다"와
"확인하지 못했다"는 다릅니다.** 후자는 정보를 채우면 뒤집힙니다.

---

## 5. 데모 앱과의 관계

`apps/api/app/ai/demo_web.py`는 **별도 FastAPI 앱**입니다. `main.py`와 무관하고
포트도 다릅니다(8200).

| | 제품 경로 | 데모 앱 |
| --- | --- | --- |
| 진입 | `main.py` | `demo_web.py` |
| DB | 사용 | **미사용** (메모리 캐시) |
| 공고 출처 | Backend 수집 → DB | 나라장터 직접 조회 |
| 판정 엔진 | `app.ai` | **동일** |
| 계약조건 검토 | 노출 없음 | 노출 |
| 요약·챗봇 | 미등록 | 동작 |

**판정 엔진이 같다는 점이 중요합니다.** 데모에서 확인한 판정은 제품 경로에서도
같은 결과가 나옵니다. 데모는 "DB 없이 같은 엔진을 돌려보는 창"이지, 별도 구현이
아닙니다.

데모를 제품에 이식할 계획이라면 옮길 것은 **화면과 엔드포인트 조립 방식**이지
판정 로직이 아닙니다.

---

## 6. 인수인계 — 연결하려면 무엇이 필요한가

우선순위 순입니다.

### 6.1 브리핑 라우터 등록 (가장 작고 효과가 큼)

`main.py` 두 줄. 제품 목표의 **"LLM 요약"과 "챗봇"이 이것 하나로 열립니다.**
파일은 이미 있고 테스트도 있습니다.

- 담당: Backend (`main.py` 소유)
- 선행조건: 없음

### 6.2 계약조건 검토 결과 저장·노출

9종 위험조항이 현재 제품 경로에 전혀 없습니다.

1. DB 테이블 2개 — 제안은 [05](05-clause-types-team-share.md) (담당: DB)
2. 서비스 계층 — `clause_review` 호출 → 레코드 변환 (담당: LLM/RAG)
3. 라우터 — 노출 (담당: LLM/RAG, 등록은 Backend)
4. 화면 (담당: Frontend)

### 6.3 프론트가 근거 사슬을 따라가도록

현재 프론트는 `qualification-judgment-runs/{run_id}`를 읽고 있지만, 4.3의
사슬(Judgment → Requirement → Evidence)을 끝까지 따라가 **원문 발췌를 보여주는
화면이 있는지 확인이 필요합니다.**

판정만 보여주고 근거를 못 보여주면 담당자가 결과를 신뢰하지 않습니다. 데모 앱의
"▸ 원문 발췌 보기"가 참조 구현입니다.

---

## 7. 주의사항

**7.1 `main.py`·`routers/`·`models.py`는 다른 담당자 소유입니다.**
읽고 호출하는 것은 되지만 고치지 마십시오. 수정이 필요하면 요청하고, 부득이하게
고쳤다면 코드에 이유를 주석으로 남기고 담당자에게 알리십시오.

**7.2 `app/ai`에 DB를 끌어들이지 마십시오.**
`app/ai`의 어떤 모듈도 최상단에서 `sqlalchemy`·`app.models`·`app.services`를
import 하지 않습니다. 이 경계가 깨지면 판정 로직만 따로 테스트할 수 없게 되고,
데모 앱도 못 돌아갑니다.

**7.3 판정 문구를 프론트에서 만들지 마십시오.** 4.4 참조.

**7.4 공고는 "버전" 단위입니다.**
정정공고는 새 `notice_version_id`입니다. 판정도 버전에 묶입니다. 공고 단위로
캐시하면 정정된 내용으로 판정하지 못합니다 — 이 제품이 존재하는 이유가 바로
그 정정공고입니다.

---

## 8. 참고

| 문서 | 내용 |
| --- | --- |
| [PROJECT.md](PROJECT.md) | 제품 목표 · 아키텍처 · 원칙 · 절대 변경 금지 |
| [SPEC.md](SPEC.md) | 데모 화면의 요구사항 · 완료조건 · 테스트 |
| [05-clause-types-team-share.md](05-clause-types-team-share.md) | 위험조항 9종 · DB 스키마 제안 |
| [02-integration-requests.md](02-integration-requests.md) | 팀에 요청한 것 / 부득이하게 수정한 것 |
