# LLM / RAG 통합 보고서

> 작성 2026-09-08 · 김재현, 이홍규
> 대상: `LLM` 브랜치(`64817dc`) → `integration/mvp-baseline`(`b048a10`) 이식

## 한 줄 요약

이식 완료(계약조항 검토 + 예규 221조문 + 임베딩 + 요약 + 확장항목 + API필드 변환 +
DB 없는 첨부 수집), 테스트 108개 통과. 판정기는 Baseline 것을 채택하되 인증 명칭
대조 버그 1건을 이식했습니다.

**가장 급한 것**: 실제 공고에서 자격요건 8개 중 5개가 가드레일에 잘못 걸려 사라지고,
그중에 "대기업·중견기업 참여 제한"이 있어 **지금 대기업이 적격으로 나옵니다.** (→ 3부 2.1)

---

# 1부. 브랜치 비교

두 브랜치에서 같은 계층이 **독립적으로 두 번 구현**됐습니다. 이 문서는 무엇이 겹치고,
무엇이 한쪽에만 있고, 어느 쪽을 남겼는지를 근거와 함께 정리합니다.

### 요약

| | LLM 브랜치 | Integration Baseline | 결론 |
|---|---|---|---|
| 자격요건 판정 | `judgment.py` 849줄 | `judgment.py` 675줄 | **Baseline 채택** (측정 결과 24:19 승) |
| 회사 프로필 모델 | `profile.py` (ProfileView) | `judgment.py` 내 `CompanyProfileSnapshot` | **Baseline 채택** |
| 되묻기 | `followup.py` 605줄 | `askability.py` | **Baseline 채택** (프론트 계약이 이쪽) |
| 변경 재판정 | 없음 | `requirement_diff.py` | Baseline 단독 |
| DB·API 연결 | 없음 | 라우터 5종 + 마이그레이션 006~009 | Baseline 단독 |
| 계약조항 검토 | `clause_review/` 9파일 | 없음 | **LLM 브랜치 이식** |
| 예규 코퍼스 | `data/standards/clauses.json` 221조문 | 없음 | **LLM 브랜치 이식** |
| 임베딩 | `providers/embeddings.py` | 없음 | **LLM 브랜치 이식** |
| 공고 요약 | `summary.py` | 없음 | **LLM 브랜치 이식** |
| 공고별 추가항목 | `extensions.py` | 없음 | **LLM 브랜치 이식** |
| API 필드 → 요건 | `notice_requirements.py` | 없음 | **LLM 브랜치 이식** |
| DB 없는 첨부 수집 | `demo/documents.py` | 없음(DB 경로만 있음) | **LLM 브랜치 이식** |
| 질의응답 도우미 | `assist.py` | 없음 | **보류** (프로필 모델 의존) |

---

### 1. 겹치는 부분 — 판정기

두 구현을 **같은 입력 24개 케이스**로 돌려 비교했습니다. 기준일 2026-09-08 고정,
공통 케이스 매트릭스(명백한 충족/미충족, 정보 없음, 명시적 빈 목록, 표기 차이,
기간 경계, 건수, 지역, 기업규모, 인력, 경험분야).

```
정답   Baseline 23/24  →  (수정 후) 24/24        LLM 브랜치 19/24
위험(모름 → 미충족 확정): 양쪽 다 0건
```

#### Baseline 이 이긴 5건 — 전부 "확정 가능한데 확인 불가로 뺀" 경우

| 케이스 | 기대 | Baseline | LLM 브랜치 |
|---|---|---|---|
| 다른 인증만 보유 (ISO 9001) | 미충족 | 미충족 | 확인 불가 |
| 업종코드 불일치 | 미충족 | 미충족 | 확인 불가 |
| 지역 불일치 (부산 vs 서울) | 미충족 | 미충족 | 확인 불가 |
| 완료일 3년 하루 전 | 미충족 | 미충족 | 확인 불가 |
| 완료일 3년 하루 후 | 충족 | 충족 | 확인 불가 |

**원인**: LLM 브랜치 판정기는 PoC 데이터 모델(실적에 **연도만** 존재, 완전성 정보 없음)을
전제로 설계돼서, 경계 실적을 전부 "확인 불가"로 뺐고 목록 불일치도 확정하지 않았습니다.
이 레포의 프로필은 완료일이 **날짜**로 있고(`completed_at: date`) 완전성 플래그
(`ProfileCompleteness`)가 별도로 있습니다. 그러면 경계는 날짜로 정확히 갈리고,
"목록이 완전한데 일치가 없다"는 미충족으로 확정할 수 있습니다.

즉 LLM 브랜치의 보수성은 **이 레포에 없는 문제를 방어**하고 있었고, 그 대가로 확정
가능한 판정 5건을 되묻기로 넘겼습니다.

Baseline 이 추가로 가진 것: `derive_overall_status`가 **요건 그룹(ANY_OF/ALL_OF)**을
처리합니다. "다음 중 하나 이상" 형태 자격요건에서 LLM 브랜치는 전부 AND로 봅니다.

#### LLM 브랜치가 이긴 1건 — 이식했습니다

`ISO27001` 보유 + 공고가 `ISO/IEC 27001` 표기 → Baseline 이 **미충족으로 확정**.
`_norm()`이 `/`·공백을 지워 `iso27001` vs `isoiec27001`이 되고 부분문자열도 아니라
매칭 실패입니다. **자격 있는 업체를 탈락시키는 방향**이라 그것만 이식했습니다.
(→ `02-integration-requests.md` "이미 수정한 것" 참조)

---

### 2. 한쪽에만 있는 것 — 이식한 모듈

전부 Baseline 에 대응물이 없어 충돌 없이 추가했습니다.

#### 계약조항 검토 `apps/api/app/ai/clause_review/` (9파일, 1,251줄)

공고문의 계약조항을 **예규 원문과 대조**해 업체에 불리한 조항을 찾습니다.

- `lexicon.py` — 어휘 부품 사전. 문장이 아니라 **문장 형식**에 대응합니다.
- `pattern_match.py` — 경로 B: 과업범위 모호(포괄조항). 표준에 대응 수치가 없는 유형.
- `standard_diff.py` — 경로 A: 표준 대조. 하자보수·지체상금·검수기간·해지요건·저작권 귀속.
- `embedding_fallback.py` — 경로 A 2차: 정규식이 놓친 조항을 임베딩 검색 + 원문 인용으로 보강.
- `standards/` — 예규 조문 인덱싱 + 기준값 추출.

**핵심 설계**: 비교 기준값(하자보수 1년, 지체상금 상한 100분의 30 등)이 **코드에 없습니다.**
`standards/values.py`가 예규 원문에서 매번 추출하고, 추출 실패 시 옛 상수로 폴백하지 않고
"확인 불가"로 남깁니다. 예규가 개정되면 인덱스만 다시 만들면 판정 기준이 따라 바뀝니다.

검증: `data/standards/clauses.json` 221조문에서 기준값 6/6 추출 확인.

#### 예규 코퍼스 `data/standards/clauses.json`

용역계약일반조건 75조문 + 정부 입찰·계약 집행기준 145조문 + 국가계약법 시행규칙 1조문.
원본 HWP(실제로는 HWPML)에서 `scripts/build_standard_clauses.py`로 생성합니다.

#### 임베딩 `apps/api/app/ai/providers/embeddings.py`

`Embedder` 프로토콜 + `OpenAIEmbedder` + **문자 2-gram 해싱 폴백**(오프라인, 키 불필요).
`similarity_matrix()`가 사용한 방법(`openai`/`ngram`)을 함께 반환합니다 — 두 점수 분포가
다르기 때문입니다. 신규 의존성 0개(순수 Python cosine).

#### 공고 요약 `apps/api/app/ai/summary.py`
#### 공고별 추가항목 `apps/api/app/ai/extensions.py`
#### API 필드 → 요건 `apps/api/app/ai/notice_requirements.py`
#### DB 없는 첨부 수집 `apps/api/app/demo/documents.py`

첨부를 URL로 직접 받아 캐시하고 `services.document_extraction.extract_document()`
(DB를 쓰지 않는 순수 함수)로 텍스트·블록을 뽑습니다. **HWPML 리더 포함** — 나라장터·법제처가
확장자만 `.hwp`인 XML을 배포하는데 백엔드 추출기가 이를 거부합니다.

---

### 3. 걷어낸 것

| 걷어낸 것 | 이유 |
|---|---|
| `ai/judgment.py` (LLM판) | Baseline 이 24:19 로 우수. 이식 시 판정기 두 벌. |
| `ai/profile.py` | Baseline 은 `judgment.py` 안에 `CompanyProfileSnapshot`을 자체 정의. 프로필 모델 두 벌은 어느 쪽이 정본인지 흐려짐. |
| `ai/followup.py` | Baseline 의 `askability.py`가 대응하고, **프론트 계약(`QualificationQuestion.askable`, `askability_reason_code`)이 그쪽을 가리킴**. |
| `ai/assist.py` | `profile.as_profile_view` 의존. Baseline 프로필 모델로 갈아끼우면 이식 가능 → 보류. |
| `demo/{pipeline,connectors,report,api}.py` | `qualification_analysis.py` 이하 팀 파이프라인이 DB 위에서 같은 일을 함. |
| `scripts/run_eligibility_demo.py` | 위 데모 패키지 의존. |
| `tests/test_judgment.py`, `test_profile_view.py`, `test_followup.py`, `test_prose_features.py`, `test_demo_pipeline.py` | 걷어낸 모듈의 테스트. |
| `test_ai_extensions.py` 중 통합 테스트 4개 | LLM판 `judge_requirement` 시그니처 의존. 탐지·파싱 테스트 7개는 유지. |

---

### 4. 이식 후 상태

```
apps/api/app/ai/
├── (Baseline) analysis_pipeline, analysis_result, askability, backend_blocks,
│              canonicalize, chunking, contracts, evaluation_contracts,
│              evidence_adapter, judgment, legacy_slots, requirement_diff,
│              requirement_extraction, normalization/
├── (이식)     clause_review/          계약조항 검토 + 예규 대조
├── (이식)     summary.py              공고 요약·판정 브리핑
├── (이식)     extensions.py           공고별 추가항목
├── (이식)     notice_requirements.py  공고 API 필드 → 요건 + 가격정보
└── (이식)     providers/embeddings.py 임베딩 + 오프라인 폴백

apps/api/app/demo/documents.py         DB 없는 첨부 수집 + HWPML
data/standards/clauses.json            예규 221조문
scripts/build_standard_clauses.py      예규 인덱스 생성
```

테스트 108개 통과 (`--noconftest`, DB 불필요 대상).

---

# 2부. 연결 요청 사항 · 이미 수정한 것

LLM/RAG 이식 과정에서 (A) 다른 담당 영역이라 **요청드려야 하는 것**과
(B) 이식이 막혀서 **부득이하게 이미 수정한 것**을 나눠 정리합니다.

---

## A. 요청 사항

### A-1. `document_extraction.py` 에 HWPML 분기 추가 — 백엔드 (전진환)

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

### A-2. `Judgment` 에 근거 문장 필드 추가 — 백엔드 + 프론트 (전진환, 황수빈)

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

### A-3. `docker-compose.yml` 에 `OPENAI_API_KEY` 전달 — 인프라

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

### A-4. `tests/conftest.py` 의 DB 강제 완화 — 백엔드

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

### A-5. 계약조항 검토 결과를 담을 자리 — 백엔드 + 프론트

이식한 `clause_review/`가 `ClauseFinding`(확인 필요 조항 + 예규 근거)을 만드는데
**저장할 테이블도, 노출할 엔드포인트도, 표시할 화면도 없습니다.**

- 테이블: `qualification_clause_findings` (analysis_run 에 매달림)
- 엔드포인트: `GET /api/v1/qualification-analyses/{runId}/clause-findings`
- 화면: 프론트 `changes` / `evidence` 페이지와 성격이 가까워 보이는데 확인 필요

우선순위: 중간. 기능은 동작하나 사용자에게 도달하지 못합니다.

---

### A-6. 확장항목(`extensions.py`)을 판정기에 연결 — LLM/RAG 내부 + 계약

`extensions.py`는 "공고가 요구할 때만 추가 항목을 받는" 탐지·파싱 계층입니다
(소프트웨어기술자 등급, 상호출자제한기업집단 계열사 여부).

Baseline `judge_requirement()`에 연결하려면 `CompanyProfileSnapshot` 에 `extensions`
필드가 필요합니다. 프로필 모델 변경이라 **DB(정예린) + 프론트 입력 폼(황수빈)** 협의가
필요합니다. 현재는 탐지·파싱만 동작하고 판정에는 미연결입니다.

---

## B. 이미 수정한 것

> 원칙: `apps/api/app/ai/**` 는 LLM/RAG 영역이라 자유롭게 수정했고, 그 외 영역은
> **최소·가산적으로만** 손대고 코드에 사유 주석을 남겼습니다.

### B-1. `ai/judgment.py` — 인증 명칭 대조 수정 (팀 코드)

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

### B-2. `ai/legacy_slots.py` — 업종코드 추출 (팀 코드)

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

### B-3. `ai/normalization/numbers.py` — `extract_values()` 추가 (팀 코드, 가산)

`clause_review`가 조항 텍스트에서 금액·기간·비율을 한꺼번에 뽑아야 해서 추가했습니다.
`normalize_value()`는 "이 문자열 하나가 얼마인가"를 답하지만, 조항 검토는 "이 문장에
어떤 수치들이 들어 있는가"라는 반대 질문이 필요합니다. **기존 함수·동작 무수정.**

### B-4. `ai/providers/openai.py` — `OpenAINarrator` 추가 (팀 코드, 가산)

공고 요약·판정 브리핑처럼 모델이 **산문**을 쓰는 경로가 필요해서 추가했습니다.
`OpenAIStructuredExtractor`는 JSON 스키마 고정 출력 전용이라 자유 서술에 쓰면
디코딩 단계만 늘어납니다. **기존 클래스 무수정.**

### B-5. `demo/` 패키지 축소 · `run_eligibility_demo.py` 제거

반쯤 머지된 상태(`DU`)로 남아 있던 파일들이 이 브랜치에 없는 모듈을 import 해서
패키지 전체가 깨져 있었습니다. `documents.py`(DB 없는 첨부 수집)만 남기고 나머지는
제거했습니다 — 팀 파이프라인이 DB 위에서 같은 일을 합니다. 사유는 `__init__.py`
docstring 에 적어뒀습니다.

### B-6. `tests/test_ai_extensions.py` — 통합 테스트 4개 제거

LLM 브랜치 `judge_requirement(profile, today=...)` 시그니처에 묶여 있던 테스트입니다.
Baseline 판정기는 프로필 모델 자체가 달라 그대로 못 씁니다. 탐지·파싱 테스트 7개는
유지했고, 파일에 사유 주석을 남겼습니다. (→ A-6 과 연결)

---

## 손대지 않은 것

`routers/`, `services/`, `models.py`, `main.py`, 마이그레이션, `apps/web/**` 는
**한 줄도 수정하지 않았습니다.** A-1 ~ A-5 가 그 영역에 필요한 변경입니다.

---

# 3부. Extraction · RAG · Rule · Eval 품질 고도화

### 0. 먼저: 어디서 요건을 잃고 있는가

실제 공고 `R26BK01705963`(주택도시보증공사, 법무정보 통합플랫폼)의 첨부 3개를
받아 파이프라인에 계측을 넣었습니다.

```
공고문 참가자격 8개 항목
  → LLM이 슬롯 8개 추출            추출 손실 0
  → 가드레일에서 5개 탈락           ← 손실의 대부분
  → 유형 매핑에서 1개 탈락
  → 최종 canonical 요건 2개
```

**탈락 사유 (실제 로그):**

```
근거조항 '제12조, 제14조'가 실제 조항 라벨과 불일치
근거조항 '제27조, 제76조'가 실제 조항 라벨과 불일치
```

`근거조항`이 **"이 문서의 조항 번호"인지 "인용된 법령 조문"인지 모호**합니다. 한국
공고문은 자격요건을 거의 전부 「국가계약법 시행령」제12조 식으로 법령을 인용해 씁니다.
모델이 법령 조문을 넣으면 검증기가 문서 라벨에서 못 찾고 환각으로 폐기합니다.
**진짜 환각 방지 장치인 `raw` 원문 대조는 5개 모두 통과했습니다.**

**심각도:** 탈락한 5개 안에 **"대기업 및 중견기업 참여 제한"**이 있습니다.
COMPANY_SIZE 유형이고 판정기가 정확히 다루는 요건인데, 요건이 되질 못해서
**지금 대기업이 이 공고에 적격으로 나옵니다.** 그리고 이 손실은 `status="ok"` 에
`notes` 문자열로만 남아 사실상 조용히 사라집니다.

> **이 문서에서 가장 중요한 교훈**: 이 결론에 도달하기 전, 저희는 "검색이 73%를
> 버리고 있다"는 **틀린 진단**을 확신을 갖고 냈습니다. `참가자격`이 포함된 청크를
> 정답으로 삼은 잘못된 근사 때문이었습니다. 실제로는 12만 자 제안요청서에 자격요건이
> **0개**였고(전부 목차 줄과 벌칙 조항), 검색은 4,580자 공고문의 해당 섹션을
> **정확히 찾았습니다.** 라벨과 지표가 없으면 몇 시간을 잘못된 방향에 씁니다.
> **그래서 Eval 이 1순위입니다.**

---

### 1. Eval — 측정 먼저 (최우선)

측정 없이 개선을 주장할 수 없습니다. 그리고 위 사례가 보여주듯, **단일 end-to-end
지표로는 손실 위치를 못 찾습니다.** 필요한 건 **단계별 깔때기**입니다.

#### 1.1 라벨 단위: 청크 ID가 아니라 문자열 스팬

`_build_global_chunks`가 `CHUNK-%04d`를 위치 기반으로 다시 매깁니다. 청킹을 손대는
순간 모든 청크 ID가 바뀌므로 **청크 ID를 라벨링하면 첫 개선에서 골든셋이 무효화됩니다.**

```json
{
  "notice_no": "R26BK01705963",
  "document_sha256": "...",
  "document_role": "NOTICE | RFP | FORM | DUPLICATE",
  "span_kind": "POSITIVE | TRAP",
  "quote": "「소프트웨어진흥법」제48조 ... 대기업 및 중견기업",
  "note": "COMPANY_SIZE 요건"
}
```

- 매칭은 기존 코드에 이미 두 번 있는 방식을 재사용: `_squash(quote)[:N] in _squash(chunk_text)`.
  청커를 바꿔도 라벨은 그대로 유효합니다.
- `span_kind=TRAP` — 자격요건 어휘를 쓰지만 요건이 아닌 것(목차 줄, 벌칙 조항
  "정보 누출 시 참가자격 제한", 평가배점표). **정밀도를 의미 있게 만들고, 저희가
  실제로 저지른 실수를 지표 자체가 거부하게 만듭니다.**
- `document_role` — 문서별로 라벨. 이 공고의 제안요청서는 POSITIVE 스팬 **0개**로
  라벨링됩니다. 자격요건이 없는 문서에서 끌어오는 검색기는 측정 가능하게 틀린 것입니다.

#### 1.2 지표 세 갈래

**청킹 건전성** (LLM 불필요, 결정적)

| 지표 | 현재값 | 목표 |
|---|---|---|
| 청크 수 / 중앙값 크기 | 328 / **56자** | 중앙값 ≥ 250자 |
| 50자 미만 비율 | **47%** | < 10% |
| `max_chars`(1800) 초과 | **46개** (최대 2,838자) | 0 |
| `span_containment` | 미측정 | 회귀 없음 |

**검색** (결정적)

| 지표 | 현재값 |
|---|---|
| `recall@k` / `precision@k` | 미측정 |
| `trap_rate` (목차·벌칙 조항을 집는 비율) | 약 0.25 |
| `budget_utilisation` (32,000자 예산 중 실제 사용) | **0.14** (4,504자) |
| `heading_only_rate` (40자 미만 청크 비율) | 약 0.25 |

**단계별 깔때기** (헤드라인 산출물)

POSITIVE 스팬 1개당 한 행, 불리언 4열:

| 스팬 | 청크에 담김 | 검색됨 | 추출됨 | canonical 됨 |
|---|---|---|---|---|

이 공고는 **9 / 9 / 약8 / 2** 로 읽힙니다. 한 화면으로 논증이 끝나고, 저희가 어제
저지른 실수를 잡아낼 수 있는 유일한 산출물입니다.

#### 1.3 라벨을 싸게 만드는 법

`apps/api/app/scripts/product_golden_inspector.py` 의 `find_snippets()` +
`KEYWORDS["qualification"]` 를 **제안기**로 재사용합니다(캐시 바이트에 붙이는 얇은 어댑터
필요). 사람이 POSITIVE/TRAP 만 판정합니다. 이 공고는 637자 청크에서 8줄 복사 + TRAP 5개,
**10분 이내**.

목표: **8~10개 공고, POSITIVE 60~90 스팬, TRAP 40 스팬.** 하루 오후.
공고 선정은 `product_golden_candidates.candidate_score` 재사용. 분량보다 **형식 다양성**
(HWPX/HWP/PDF/DOCX)이 중요합니다 — 포맷별 블록 단위 비대칭이 청크 크기 분포의 원인입니다.

#### 1.4 신호와 잡음

- **청킹·검색 지표는 완전히 결정적**입니다. LLM도 샘플링도 없으므로 **반복 실행 불필요**.
  대신 라벨이 충분해야 합니다. 75 스팬이면 1 스팬 = 1.3%p 이므로
  **약 7%p (5 스팬) 미만은 개선으로 보고하지 않습니다.** 공고별 분해도 항상 같이 출력합니다.
- **깔때기의 `추출됨` 열만 확률적**입니다. 모델·온도 고정 후 `n=3`, 평균과 전체 범위를
  같이 보고하고, 효과가 범위보다 작으면 그렇게 말하고 멈춥니다.

#### 1.5 파일

```
apps/api/app/ai/goldenset/       fixtures.py · spans.py · scoring.py · funnel.py
samples/golden/retrieval-v0.1/   spans.json · README.md
apps/api/app/scripts/            retrieval_report.py · goldenset_span_proposer.py
```

**이름 주의**: `evaluation*` 금지. `ai/evaluation_contracts.py` 가 이미 그 단어를
**제안서 평가기준(정량/정성 배점)** 의미로 쓰고 있습니다. `goldenset` / `retrieval_report` 사용.

---

### 2. Rule — 손실이 실제로 나는 곳 (2순위, 가장 큰 숫자)

#### 2.1 `근거조항` 의미 충돌 해소 — 최우선

가드레일이 **5/8을 잘못 버립니다.** 옵션:

1. 필드를 분리: `문서조항` (이 문서의 라벨) vs `인용법령` (「...」제N조)
2. 법령 형태의 참조는 **치명적 실패로 취급하지 않음** — 슬롯은 통과시키고 참조만 버리거나 표시
3. 「...」 인용 패턴을 별도 종류로 검증

`raw` 원문 대조는 유지합니다 — **그게 실제 환각 방지 장치이고 5개 모두 통과했습니다.**

**기대 효과:** 이 공고에서 canonical 요건 **2 → 6~7개**.

#### 2.2 탈락을 구조화된 진단으로

지금은 `notes` 문자열 하나이고 `status="ok"` 입니다. **62% 손실이 조용히 사라집니다.**
슬롯별 사유 코드를 가진 severity 있는 진단으로 바꾸고 `status`에 반영해야 합니다.

#### 2.3 `기타요건` 폐기 중단

`legacy_slots.py` 의 `기타요건` 은 요건 0개 + 진단 1개를 만듭니다. 그런데
`SYSTEM_PROMPT` 규칙 12가 부정문·공동수급·법령상 예외를 **적극적으로 그쪽으로 보냅니다.**

최소 변경: canonical enum 은 그대로 두되 **버리지 않습니다.** 근거를 가진 **판정하지 않는
기록**으로 남겨 사용자에게 인용과 함께 보여줍니다. "부정당업체로 지정되지 않은 자"에
대해 "판정하지 않음"은 **정답**입니다 — 사라지는 것이 오답입니다.

이건 `물품분류로 입찰참가 제한하지 않음` 같은 문장과 같은 문제입니다. 지금은
"제한 없음을 확인했다"와 "확인하지 않았다"가 구분되지 않습니다.

#### 2.4 판정기 자체

24개 케이스에서 **24/24**. 인증 명칭 대조 수정 반영 완료(`02-integration-requests.md` B-1).
추가 개선보다 **위 2.1~2.3 이 우선**입니다 — 판정기에 요건이 도달하지 못하는 게 문제입니다.

---

### 3. Extraction (3순위)

#### 3.1 재시도 루프가 무의미

`max_retry=1` 이 **동일한 프롬프트를 다시 보냅니다.** 거절 사유를 되먹이지 않는 순수
리샘플링이고, **전 슬롯이 탈락했을 때만** 발동합니다. 2.1 을 고치면 발동 빈도 자체가
떨어지므로 그 뒤에 재평가합니다.

#### 3.2 프롬프트 규칙 12 재검토

부정문·법령 예외를 `기타요건`으로 보내는 규칙이 2.3 과 정면으로 충돌합니다.
2.3 을 먼저 고치고 나서 이 규칙을 손대야 순서가 맞습니다.

---

### 4. RAG (4순위 — 근거가 생긴 뒤에)

#### 4.1 지금 위치를 정직하게

**계측된 이 공고에서 검색은 병목이 아니었습니다.** 637자 참가자격 섹션을 정확히
찾아왔습니다. 그러나 **명백한 결함 2개**가 있고 둘 다 저렴합니다.

#### 4.2 청킹 위생 — 결정적, 가장 싼 실질 개선

`apps/api/app/ai/chunking.py`:

- **(a) 최소 크기 누적.** 누적 텍스트가 `min_chars`(약 300) 미만이면 헤딩에서 flush 하지
  않습니다. **중앙값 56자의 직접 원인**입니다 — HWPX는 문단당 블록 1개이고 거의 모든
  줄이 헤딩 패턴에 걸려 매 문단이 flush 됩니다. 번호 목록이 N개의 한 줄 청크가 됩니다.
- **(b) 초과 프래그먼트 분할.** 캡을 append **후에** 검사하고 `max_chars` 보다 큰 단일
  프래그먼트는 **절대 분할되지 않습니다** — 46개 초과, 최대 2,838자. 줄 경계에서 자르되
  한 줄(약 120자) 겹침을 줍니다. **겹침이 값을 하는 유일한 자리입니다** — 전역 슬라이딩
  윈도우는 넣지 않습니다.
- **(c) `flush()` 에서 `current_label` 리셋.** 지금은 리셋하지 않아 연속 청크가 이전
  라벨을 물려받습니다(관측: 본문이 페이지 번호 `- 3 -` 인 청크가 `clause_label="8"`).
  `근거조항` 검증 경로에 영향을 주므로 지표가 아니라 **정확성** 이유로 고칩니다.

#### 4.3 목차·벌칙 조항 판별

`select_eligibility_chunks` 가 **본문이 10자 `"1. 입찰 참가자격"` 인 목차 줄**을 앵커로
집었습니다. 다음 청크(`"2. 입찰 및 낙찰방식"`, 역시 목차)가 top-level 이라 자식 탐색이
즉시 종료됩니다.

- 목차 신호: 전체 텍스트가 40자 미만 헤딩 한 줄 **이면서** ±5 이내 이웃 3개 이상이
  같은 형태. 모델도, 제목 목록도, 공고별 튜닝도 불필요합니다.
- 벌칙 신호: 자격요건 어휘가 `누출`·`제한된다`·`처벌`·`제재`·`취소` 와 **같은 문장**에
  있으면 조건이 아니라 벌칙. 제안요청서의 거짓 히트 15개가 정확히 이 형태였습니다.

**주의: 4.2(a) 가 이걸 상당 부분 해소합니다** — 최소 크기 누적을 넣으면 목차 7줄이 한
청크로 합쳐져 눈에 띄게 목차가 됩니다. **4.2 를 먼저 측정하고 4.3 을 판단하십시오.**

#### 4.4 점수 기반 예산 채우기 — RAG 기계가 실제로 붙는 자리

32,000자 예산 중 **4,504자(14%)** 만 보냅니다. 원인은 랭킹이 아니라 제어 흐름입니다 —
앵커 분기가 조기 반환해서 목차성 앵커 4개가 **16청크 폴백을 통째로 억제**합니다.

3단 캐스케이드를 교체: 전 청크 점수화 → 앵커 규칙은 **강한 사전 확률**(단락이 아니라)
→ 점수 순으로 문자 예산까지 채움.

- 스코어러: **문자 2-gram BM25**, 순수 Python 약 60줄. 한국어 복합어는 공백 토큰화가
  안 되고, 이식한 코드가 이미 이 코퍼스에서 문자 2-gram을 작동 단위로 확립했습니다.
  `rank-bm25` 의존성은 넣지 않습니다 — 40줄 아끼고 한국어에 틀린 토큰화 모델을 삽니다.
- 쿼리는 `retrieval/query.py` 에 **데이터로** 두어 하네스가 A/B 할 수 있게 합니다.

**정직한 예상: 이 공고에서 `budget_utilisation` 은 크게 오르고 `recall@k` 는 변하지
않습니다.** 대상 청크가 이미 검색됐기 때문입니다. 그것도 정당한 결과이고, 그래서
8~10개 공고 세트가 먼저 필요합니다.

#### 4.5 문서 선택 · 중복 제거

공고문이 **HWPX(12청크)와 PDF(3청크)로 두 번** 들어옵니다. `G2BDocumentSource` 는
페이로드 sha256으로 걸러서 같은 문서의 두 렌더링을 못 봅니다.

`cosine(ngram_vectors([a, b]))` 로 탐지(이식한 `providers/embeddings.py` 에 이미 있음)해
저품질 사본을 버립니다. 나아가 파일명/첫 페이지로 `공고문 / 제안요청서 / 과업지시서 /
별지·서식` 을 분류해 공고문 청크에 가중치를 줍니다 — **자격요건은 공고문에 살고,
12만 자 제안요청서는 코퍼스의 96%를 차지하는 방해물입니다.**

#### 4.6 예규 조문 대조 — 진짜 RAG 사례

이식한 `clause_review/` 는 공고 조항을 **예규 221조문과 대조**합니다. 고정 코퍼스,
인용 가능한 근거, 명확한 정답 — **검색 지표(recall@k)를 내기 가장 좋은 재료**이고
프로젝트 이름(bid **change** validator)과도 맞습니다.

실제 공고에서 4건 탐지 확인:

```
[5.1] 하자보수 기간 과다     표준 인수 확인 후 1년 (용역계약일반조건 제58조제1항)
[7.1] 저작권 단독 귀속        표준 공동소유·지분 균등 (제56조제1항)
[4.1] 검수 기간 과다          표준 통지받은 날부터 14일 (제20조제2항)
[3.5] 과업범위 모호(포괄조항)
```

지금은 정규식 + 임베딩 보조입니다. 청킹 전략·하이브리드·리랭킹을 실험할 여지가 크고,
**자격요건과 달리 산문이 유일한 출처**입니다(API에 절대 안 나옵니다).

#### 4.7 밀집 임베딩 · 하이브리드 — 발동 조건부 보류

**조건:** 8개 이상 라벨 공고에서 4.2~4.5 이후 깔때기의 검색 단계 손실
(`청크에 담김`=참, `검색됨`=거짓)이 **POSITIVE 스팬의 15% 초과**일 때만.
**오늘 그 근거는 0입니다.**

발동 시: `OpenAIEmbedder`(신규 의존성 불필요) + 공고당 약 330청크 brute-force cosine +
BM25 랭킹과 RRF 융합. 오프라인 `ngram` 경로는 기본값으로 유지해 키 없이도 돕니다.

#### 4.8 리랭킹 — 4.7 뒤, 같은 조건

cross-encoder 는 제외(torch·모델 가중치 없음). 가능한 형태는 LLM 리랭커 —
후보 약 20개를 구조화 호출 1회로 점수화. **4.7이 발동하고도 잔여 손실이 남은 뒤에만.**

---

### 5. 하지 말아야 할 것

| | 이유 |
|---|---|
| `참가자격` 포함 청크를 정답으로 삼기 | 저희가 이미 이 실수로 몇 시간을 썼습니다. TRAP 스팬을 라벨 스키마에 넣어 지표가 목차 히트를 보상하지 못하게 합니다. |
| 청크 ID 라벨링 | 위치 기반이고 `_build_global_chunks` 가 다시 매깁니다. 4.2 첫날에 골든셋이 무효화됩니다. |
| pgvector · faiss · chroma · 청크 테이블 | 공고당 약 330청크. 4,096차원 brute-force cosine 은 마이크로초. 영속화는 마이그레이션 + `models.py`(남의 파일)를 요구하는데 그런 문제가 없습니다. |
| numpy · rank-bm25 · sentence-transformers · tiktoken | 각각 읽을 수 있는 순수 Python 40~80줄을 대체합니다. sentence-transformers 는 발동 조건도 충족 못한 이득에 수 GB 설치. |
| LLM 기반 의미 청커 | `min_chars` 누적기가 공짜로 고치는 문제에 공고당 약 330회 호출. |
| `routers/` · `services/` · `models.py` · `main.py` · `apps/web/` 수정 | `target_chunk_ids` 와 `diagnostics` 는 **이미 저장되고 이미 API로 반환됩니다.** 그게 필요한 배관의 전부입니다. |
| `apps/api/app/demo/` 부활 | `documents.py` 만 남기고 정리했습니다. 나머지는 팀 파이프라인과 중복입니다. |
| 재시도 루프 손보기 | 2.1 을 고치면 발동 빈도가 떨어집니다. 그 뒤에 재평가. |
| `evaluation*` 이름 사용 | `evaluation_contracts.py` 가 제안서 평가기준 의미로 선점. |

---

### 6. 실행 순서와 검증

```
1. Eval 하네스 + 라벨 8~10공고        ← 여기부터. 없으면 나머지 주장이 검증 불가
2. Rule: 근거조항 충돌 해소 (2.1)     ← 가장 큰 숫자 (2 → 6~7)
3. Rule: 탈락 진단 구조화 (2.2)
4. Rule: 기타요건 폐기 중단 (2.3)
5. RAG: 청킹 위생 (4.2)
6. RAG: 예산 채우기 (4.4) · 문서 선택 (4.5)
7. RAG: 예규 대조 고도화 (4.6)
8. (조건부) 밀집·하이브리드 (4.7) → 리랭킹 (4.8)
```

**기준선 (아무것도 건드리기 전).** 이 실행이 이후 모든 주장의 근거가 됩니다.

```bash
python -m apps.api.app.scripts.retrieval_report \
    --goldenset samples/golden/retrieval-v0.1 --retriever default --json
```

`R26BK01705963` 예상값: `chunks=328`, `median_chars=56`, `pct_under_50=0.47`,
`over_max=46`, `retrieved=4`, `budget_utilisation=0.14`, `trap_rate≈0.25`,
깔때기 `9 / 9 / 약8 / 2`.
**재현되지 않으면 검색기가 아니라 하네스가 틀린 것이니 멈추십시오.**

**각 단계 후.** 같은 명령 + `--retriever <name>`, 그리고 회귀 게이트:

```bash
python -m pytest -q --noconftest apps/api/tests/test_requirement_extraction.py \
    apps/api/tests/test_analysis_pipeline.py apps/api/tests/test_canonicalize.py \
    apps/api/tests/test_qualification_judgment.py
```

기본 검색기는 동작이 바이트 단위로 같아야 하므로 이 테스트들은 수정 없이 통과해야 합니다.

**전체 성공 기준은 recall 숫자가 아닙니다.** 깔때기 리포트가 존재하고, 한 명령으로 돌고,
8개 이상 공고를 문서 단위 라벨과 함께 덮고, **손실 위치를 정확히 짚는 것**입니다.
오늘의 단일 공고에서 그것은 "손실은 검색이 아니라 canonical 매핑에 있다"고 말할 것이고,
**그걸 몇 시간이 아니라 10초 만에 숫자로 말할 수 있는 것**이 산출물입니다.
