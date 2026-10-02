# 연결 요청 사항 · 이미 수정한 것

> 작성 2026-09-08 · LLM / RAG (김재현, 이홍규)

LLM/RAG 이식 과정에서 (A) 다른 담당 영역이라 **요청드려야 하는 것**과
(B) 이식이 막혀서 **부득이하게 이미 수정한 것**을 나눠 정리합니다.

---

# A. 요청 사항

## A-1. `document_extraction.py` 에 HWPML 분기 추가 — 백엔드 (전진환)

**증상.** 나라장터·법제처가 **확장자만 `.hwp`이고 실제로는 HWPML(XML)** 인 파일을
배포합니다. `extract_document()`가 이를 `not an OLE2 structured storage file`로 거부합니다.

**확인된 범위.** 계약예규 3개 파일 전부 이 형식이었습니다. 공고 첨부에도 같은 형식이
오면 **텍스트 추출이 실패하고 그 공고는 분석 자체가 불가**합니다.

**우회 중.** `apps/api/app/demo/documents.py` 의 `is_hwpml()` / `extract_hwpml()` 로
임시 처리하고 있습니다. 같은 로직을 `_extract_hwpml()` 로 옮기고 `extract_document()`
분기에 추가하면 됩니다. 판별은 확장자가 아니라 **선두 바이트**로 해야 합니다
(`<?xml` 로 시작 + `HWPML` 포함).

```python
# extract_document() 안, PDF/HWP/HWPX 분기 앞
if signature.lstrip().startswith(b"<?xml") and b"HWPML" in source.read(4096):
    source.seek(0)
    return _extract_hwpml(source)
```

우선순위: **높음.** 지금은 조용히 실패합니다.

---

## A-2. `Judgment` 에 근거 문장 필드 추가 — 백엔드 + 프론트 (전진환, 황수빈)

**증상.** `contracts.Judgment` 에 `reason_code`(예: `INSUFFICIENT_DATA`)만 있고
**사람이 읽을 근거 문장이 없습니다.** 프론트 `QualificationJudgment` 타입도 동일합니다.

**왜 문제인가.** 이 프로젝트의 원칙이 "모든 판정에 원문 근거를 붙인다"인데, 화면에
나갈 근거가 없습니다. 지금 구조로는 프론트가 `reason_code`로 문장을 재구성해야 하고,
그러면 판정 근거가 두 곳에 살게 됩니다.

**요청.** `Judgment` 에 optional 필드 추가:

```python
reason: str = ""                          # "최근 36개월 최대 단건 실적 8.2억원 ≥ 5억원 (자기신고)"
follow_up_question: str | None = None     # UNKNOWN 일 때 되물을 질문
required_extension_key: str | None = None # 공고별 추가항목이 필요한 경우
```

계약문서(`docs/contracts/backend-llm.md`)가 권장하는 **additive-optional** 방식이라
기존 리더는 그대로 동작합니다.

---

## A-3. `docker-compose.yml` 에 `OPENAI_API_KEY` 전달 — 인프라

`api`·`notice-poller` 서비스에 `G2B_SERVICE_KEY`만 전달되고 `OPENAI_API_KEY`가
없습니다. 로컬 CLI는 되지만 **컨테이너 안에는 키가 없어** 요건 추출이 실패합니다.

```yaml
environment:
  G2B_SERVICE_KEY: ${G2B_SERVICE_KEY:-}
  OPENAI_API_KEY: ${OPENAI_API_KEY:-}        # ← 추가
  OPENAI_MODEL_DEFAULT: ${OPENAI_MODEL_DEFAULT:-}
  OPENAI_EMBED_MODEL: ${OPENAI_EMBED_MODEL:-}
```

---

## A-4. `tests/conftest.py` 의 DB 강제 완화 — 백엔드

**증상.** 세션 단위 autouse 픽스처가 실제 PostgreSQL을 요구해서, **순수 로직 테스트도
DB 없이는 못 돌립니다.** 지금은 `--noconftest`로 우회하고 있습니다.

**요청.** 픽스처 본문을 연결 확인으로 감싸고 실패 시 `yield`만 하도록:

```python
try:
    db = SessionLocal()
    db.execute(text("SELECT 1"))
except Exception:
    yield          # DB 없으면 시딩 생략 — 순수 로직 테스트는 그대로 돈다
    return
```

CI는 DB가 있으니 동작이 같고, 로컬에서 AI 계층 테스트가 3초 만에 돕니다.

---

## A-5. 계약조항 검토 결과를 담을 자리 — 백엔드 + 프론트

이식한 `clause_review/`가 `ClauseFinding`(확인 필요 조항 + 예규 근거)을 만드는데
**저장할 테이블도, 노출할 엔드포인트도, 표시할 화면도 없습니다.**

- 테이블: `qualification_clause_findings` (analysis_run 에 매달림)
- 엔드포인트: `GET /api/v1/qualification-analyses/{runId}/clause-findings`
- 화면: 프론트 `changes` / `evidence` 페이지와 성격이 가까워 보이는데 확인 필요

우선순위: 중간. 기능은 동작하나 사용자에게 도달하지 못합니다.

**2026-09-10 갱신 — 저장 페이로드 확정.** 탐지기는 이제 아래 값을 직접 냅니다.

```json
{
  "risk_type": "지체상금 요율 과다",
  "risk_types": ["지체상금 요율 과다", "지체상금 상한 초과"],
  "category": "LATE_PENALTY_RATE",
  "categories": ["LATE_PENALTY_RATE", "LATE_PENALTY"]
}
```

- `risk_type`: 대표 한글 라벨
- `risk_types`: 전체 한글 라벨 배열. 단일 원인도 길이 1
- `category`: 기존 프론트 그룹핑/DB 컬럼에 넣을 대표 오류 코드
- `categories`: 새 JSONB 컬럼에 그대로 넣을 전체 오류 코드 배열. 단일 원인도 길이 1
- 대표 선정: `NEEDS_REVIEW → UNDETERMINED → COMPLIANT`, 동률이면 확정 9종 순서
- 불변식: 두 배열은 비어 있지 않고 `categories[0] == category`,
  `risk_types[0] == risk_type`

현재 통합 브랜치에는 위험조항 테이블과 `category`, `risk_type` 단수 컬럼이 있습니다.
마이그레이션 014가 `categories`, `risk_types` JSONB를 추가하고 기존 단수값으로 백필한
뒤 `NOT NULL`, 배열, 대표값 일치 제약을 적용합니다.

---

## A-6. 확장항목(`extensions.py`)을 판정기에 연결 — LLM/RAG 내부 + 계약

`extensions.py`는 "공고가 요구할 때만 추가 항목을 받는" 탐지·파싱 계층입니다
(소프트웨어기술자 등급, 상호출자제한기업집단 계열사 여부).

Baseline `judge_requirement()`에 연결하려면 `CompanyProfileSnapshot` 에 `extensions`
필드가 필요합니다. 프로필 모델 변경이라 **DB(정예린) + 프론트 입력 폼(황수빈)** 협의가
필요합니다. 현재는 탐지·파싱만 동작하고 판정에는 미연결입니다.

---

# B. 이미 수정한 것

> 원칙: `apps/api/app/ai/**` 는 LLM/RAG 영역이라 자유롭게 수정했고, 그 외 영역은
> **최소·가산적으로만** 손대고 코드에 사유 주석을 남겼습니다.

## B-1. `ai/judgment.py` — 인증 명칭 대조 수정 (팀 코드)

**무엇을.** `_certification_match()` 추가하고 `_judge_certification` 에서 사용.

**왜.** `ISO27001` 보유 업체가 `ISO/IEC 27001` 요구 공고에서 **미충족으로 확정**됐습니다.
`_norm()`이 구분자를 지워 `iso27001` vs `isoiec27001`이 되고 부분문자열도 아니라서입니다.
**자격 있는 업체를 탈락시키는 방향**이라 고쳤습니다.

**규칙.** 숫자가 인증의 정체성입니다. 요건이 명시한 숫자 토큰을 전부 보유해야 하고
단어도 하나 이상 겹쳐야 합니다.

| | 결과 |
|---|---|
| `ISO/IEC 27001` ↔ `ISO27001` | 충족 (숫자 27001 일치, 단어 ISO 공유) |
| `ISO/IEC 27001` ↔ `ISO 9001` | 미충족 (숫자 다름) |
| `ISO/IEC 27001` ↔ `KS 27001` | 미충족 (인증기관 다름) |

회귀 테스트 3개 추가 (`test_qualification_judgment.py`). 기존 테스트 전부 통과.

## B-2. `ai/legacy_slots.py` — 업종코드 추출 (팀 코드)

**무엇을.** `_INDUSTRY_CODE_RE` 추가. `등록요건`·`업종요건` 슬롯의 원문에 `업종코드: 1468`
형태가 있으면 그 **코드**를 `INDUSTRY` 요건 값으로 씁니다.

**왜.** 실제 공고 `소프트웨어사업(컴퓨터관련서비스사업, 업종코드: 1468)` 에서 회사가
1468을 보유하는데 **확인 불가**가 나왔습니다. 명칭으로만 대조해서
`소프트웨어사업` vs `소프트웨어사업자` 한 글자 차이로 실패한 것입니다.

문장에 코드가 박혀 있으면 **코드가 대조 가능한 형태**입니다. 이름은 같은 조건을 다르게
쓴 것뿐이라 별도 요건으로 내보내지 않습니다 — 하나의 조건을 두 번 판정하면 더 흐린
매처가 결과를 정해버립니다.

**부수 발견.** LLM이 같은 문장을 실행마다 `업종요건`으로도 `등록요건`으로도 분류합니다.
두 분기 모두 코드에 도달하게 했습니다 — 판정이 공고가 아니라 분류 라벨에 따라 바뀌면
신뢰할 수 없습니다. 회귀 테스트 3개 추가 (`test_canonicalize.py`).

**효과.** 실제 공고에서 `확인 필요` → **`적격`** 으로 정정 (근거: "등록 업종코드 '1468' 보유").

## B-3. `ai/normalization/numbers.py` — `extract_values()` 추가 (팀 코드, 가산)

`clause_review`가 조항 텍스트에서 금액·기간·비율을 한꺼번에 뽑아야 해서 추가했습니다.
`normalize_value()`는 "이 문자열 하나가 얼마인가"를 답하지만, 조항 검토는 "이 문장에
어떤 수치들이 들어 있는가"라는 반대 질문이 필요합니다. **기존 함수·동작 무수정.**

## B-4. `ai/providers/openai.py` — `OpenAINarrator` 추가 (팀 코드, 가산)

공고 요약·판정 브리핑처럼 모델이 **산문**을 쓰는 경로가 필요해서 추가했습니다.
`OpenAIStructuredExtractor`는 JSON 스키마 고정 출력 전용이라 자유 서술에 쓰면
디코딩 단계만 늘어납니다. **기존 클래스 무수정.**

## B-5. `demo/` 패키지 축소 · `run_eligibility_demo.py` 제거

반쯤 머지된 상태(`DU`)로 남아 있던 파일들이 이 브랜치에 없는 모듈을 import 해서
패키지 전체가 깨져 있었습니다. `documents.py`(DB 없는 첨부 수집)만 남기고 나머지는
제거했습니다 — 팀 파이프라인이 DB 위에서 같은 일을 합니다. 사유는 `__init__.py`
docstring 에 적어뒀습니다.

## B-6. `tests/test_ai_extensions.py` — 통합 테스트 4개 제거

LLM 브랜치 `judge_requirement(profile, today=...)` 시그니처에 묶여 있던 테스트입니다.
Baseline 판정기는 프로필 모델 자체가 달라 그대로 못 씁니다. 탐지·파싱 테스트 7개는
유지했고, 파일에 사유 주석을 남겼습니다. (→ A-6 과 연결)

---

# 손대지 않은 것

`routers/`, `services/`, `models.py`, `main.py`, 마이그레이션, `apps/web/**` 는
**한 줄도 수정하지 않았습니다.** A-1 ~ A-5 가 그 영역에 필요한 변경입니다.
