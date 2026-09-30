# PROJECT.md — LLM / RAG 파트

> 작성 2026-09-09 · 담당 김재현 (LLM/RAG)
> **이 문서는 인수인계용입니다.** 코드를 읽기 전에 이것부터 읽으십시오.
> 여기 적힌 "절대 변경하면 안 되는 것"을 어기면 팀의 다른 작업과 충돌합니다.

---

## 1. 제품 목표

나라장터를 이용하는 **고객사가 공고 내용이 중간에 변경되어도 즉시 대처할 수 있게** 하는 것.

입찰 공고는 마감 전에 정정공고로 바뀝니다. 자격요건이 바뀌었는지, 그래서 우리 회사가
여전히 참여 가능한지를 담당자가 매번 첨부파일을 열어 확인하는 것이 현재 방식입니다.
이 제품은 그 확인을 자동화합니다.

### 이 파트(LLM/RAG)가 맡는 것

```
고객사 프로필 입력
      ↓
공고의 자격사항 · 제한사항과 대조  →  항목별 적 / 부 / 확인불가 판정
      ↓
공고 내용 LLM 요약               →  담당자가 훑어볼 수 있는 서술
      ↓
챗봇 질의응답                    →  "무엇을 보완해야 하나"에 답변
```

세 가지 모두 **근거를 원문까지 되짚을 수 있어야** 합니다. 판정만 내놓고 근거를 못 대면
담당자가 쓰지 않습니다.

### 이 파트가 맡지 않는 것

| 영역 | 담당 |
| --- | --- |
| 공고 수집 · 변경 감지 · 첨부 다운로드/추출 | 전진환 (Backend) |
| DB 스키마 · 마이그레이션 | 정예린 (DB) |
| 제품 화면 (`apps/web`) | 황수빈 (Frontend) |

---

## 2. 아키텍처

### 2.1 전체 위치

```
apps/api/app/
├── ai/                    ← 주 작업 영역. 단 일부는 공동 소유(5.1.1)
│   ├── clause_review/     계약조건 검토 (순수 코드, 모델 미사용)
│   ├── normalization/     숫자·기간·금액 정규화
│   ├── providers/         OpenAI 클라이언트 · 임베딩
│   ├── judgment.py        참가자격 판정 (순수 코드)
│   ├── requirement_extraction.py  공고 산문 → 구조화 (모델 사용)
│   ├── legacy_slots.py    추출 슬롯 → canonical 요건 매핑
│   ├── canonicalize.py    요건 + 근거 + 진단 조립
│   ├── analysis_pipeline.py  추출 파이프라인 진입점
│   ├── briefing.py        판정 → 담당자용 브리핑 + 챗봇
│   ├── notice_digest.py   공고 요약 (개요 + 주제별)
│   ├── extensions.py      공고가 요구할 때만 받는 프로필 확장항목
│   ├── demo.py            CLI 데모
│   └── demo_web.py        웹 데모 (별도 FastAPI 앱)
├── routers/ services/ models.py main.py   ← 다른 담당자 영역. 읽기만
└── ...

data/standards/            계약예규 원문 + 파생 인덱스(clauses.json)
data/demo/notice-documents/  공고 첨부 캐시
docs/llm-rag/              이 파트의 문서
```

### 2.2 두 개의 독립된 판정

**서로 다른 질문에 답하므로 코드도 분리되어 있습니다.**

| | 참가자격 판정 | 계약조건 검토 |
| --- | --- | --- |
| 묻는 것 | 우리 회사가 입찰할 수 있나 | 이 계약 조건이 표준에서 벗어났나 |
| 입력 | 공고 + **고객사 프로필** | 공고만 |
| 모델 | 요건 추출에만 사용 | **전혀 사용 안 함** |
| 코드 | `judgment.py` | `clause_review/` |
| 결과 | SATISFIED / UNSATISFIED / UNKNOWN | COMPLIANT / NEEDS_REVIEW / UNDETERMINED |

### 2.3 데이터 흐름

```
나라장터 API (G2BClient)
   └→ 공고 조회 · 첨부 다운로드 (G2BDocumentSource, 디스크 캐시)
        └→ 텍스트 추출 (services/document_extraction — Backend 소유, 읽기만)
             └→ chunking.chunk_source_blocks()   조항 단위 청크
                  ├→ clause_review.detect_standard_diff()   계약조건 (코드)
                  │    └ 비교 기준: data/standards/clauses.json 에서 매번 추출
                  ├→ analysis_pipeline.analyze_qualification_documents()  (모델)
                  │    └→ judgment.judge_requirements(요건, 프로필)  (코드)
                  └→ notice_digest.build_notice_digest()   요약 (모델)
                       └→ briefing.build_briefing() → answer_question()  챗봇
```

---

## 3. 디자인 원칙

### 3.1 판정은 코드가 한다. 모델은 서술만 한다

**이 프로젝트에서 가장 중요한 원칙입니다.**

모델이 하는 일은 두 가지뿐입니다.

1. **산문 → 구조화**: "최근 3년 이내 5억원 이상 실적" → `{type: PERFORMANCE_AMOUNT, operator: ">=", value: 500000000, period_months: 36}`
2. **서술**: 확정된 판정을 문장으로 풀어쓰기, 공고 요약, 챗봇 응답

모델이 **하지 않는** 일: 충족 여부 결정, 사유 작성, 값 비교.

이유는 재현성입니다. 같은 프로필과 같은 공고는 항상 같은 판정이 나와야 하고,
"왜 이렇게 판정했나"에 코드 경로로 답할 수 있어야 합니다.

### 3.2 비교 기준은 코드에 쓰지 않는다

하자보수 1년, 지체상금 상한 100분의 30 같은 숫자는 **코드 어디에도 없습니다.**
계약예규 원문에서 실행할 때마다 추출합니다. 코드에는 "원문 어디를 볼지"만 있습니다.

```python
# apps/api/app/ai/clause_review/standards/values.py
"anchor": r"종료를\s*확인한\s*후\s*([^(]{1,12}?)간",   # 위치만
"recorded": 12,                                        # 트립와이어일 뿐, 판정에 미사용
```

예규가 개정되면 값이 따라 바뀌고, 코드에 기록된 값과 다르면 `drift`로 함께 보고됩니다.
**추출에 실패하면 옛 값으로 되돌아가지 않고 판정을 보류합니다.**

### 3.3 판정하지 않는 것과 판정할 수 없는 것을 구분한다

세 상태가 각각 다른 뜻입니다. 하나로 뭉뚱그리면 담당자가 잘못 판단합니다.

| 상태 | 뜻 | 담당자가 할 일 |
| --- | --- | --- |
| SATISFIED / COMPLIANT | 확인했고 문제없음 | 없음 |
| UNSATISFIED / NEEDS_REVIEW | 확인했고 어긋남 | 대응 필요 |
| UNKNOWN / UNDETERMINED | **확인하지 못함** | 정보를 채우면 뒤집힐 수 있음 |
| (결과 없음) | 이 계약 종류에는 **해당 기준 자체가 없음** | 없음 |

### 3.4 근거는 원문까지 되짚을 수 있어야 한다

모든 판정에 근거가 두 겹으로 붙습니다.

1. **요건 문장** — 공고에서 뽑아낸 한 줄 (`requirement.raw`)
2. **원문 발췌** — 그 문장이 실제로 있던 단락 전체 (`chunk.text`) + 위치

화면에서 2번은 접혀 있다가 펼치면 나오고, 1번이 어디서 왔는지 하이라이트됩니다.

### 3.5 기준이 없으면 판정하지 않는다

계약 종류(용역/공사/물품)마다 적용되는 계약예규가 다릅니다. 물품 공고에
용역 기준을 들이대면 **적용된 적 없는 기준으로 위반 판정**을 내게 됩니다.
해당 조문이 없으면 그 룰은 검토 대상에서 아예 빠집니다.

---

## 4. 현재 결정사항

### 4.1 Canonical 요건 유형 — 8종 (팀 확정)

```
PERFORMANCE_AMOUNT   실적 금액
PERFORMANCE_COUNT    실적 건수
INDUSTRY             업종 등록
REGION               소재 지역
STAFF                인력
REGISTRATION_CERTIFICATION  등록·인증
EXPERIENCE_FIELD     수행 분야
COMPANY_SIZE         기업 규모
```

### 4.2 위험조항(계약조건) 유형 — 9종

수빈님 8유형을 그대로 쓰되, 지체상금만 근거 문서가 달라 상한·요율로 나눴습니다.

```
WARRANTY_PERIOD        하자담보 기간
LATE_PENALTY           지체상금 상한
LATE_PENALTY_RATE      지체상금 요율
COPYRIGHT_OWNERSHIP    저작권(지식재산권) 귀속
ACCEPTANCE_CRITERIA    검사·검수
SCOPE_AMBIGUITY        과업범위 모호 (포괄조항 포함)
TERMINATION_CONDITION  계약해지 요건
PAYMENT_TERMS          대금지급
LIABILITY_SCOPE        손해배상
```

`rule_id → category` 매핑은 `clause_review/contracts.py`의 `CATEGORY_BY_RULE`에 있습니다.
DB에 넣을 때는 **PostgreSQL enum이 아니라 CHECK 제약**입니다 — 이 프로젝트는 enum 타입을
하나도 쓰지 않습니다.

### 4.3 계약 종류 — 5종

```
COMMON        용역계약일반조건 제2장 (모든 용역)
SOFTWARE      용역계약일반조건 제4장 (소프트웨어용역)
CM            용역계약일반조건 제3장 (건설사업관리용역)
GOODS         물품구매(제조)계약일반조건
CONSTRUCTION  공사계약일반조건
```

`SOFTWARE`·`CM`은 용역계약일반조건 **안의 장**이라 `COMMON`을 물려받습니다.
`GOODS`·`CONSTRUCTION`은 **별개 예규라 아무것도 물려받지 않습니다**
(`standards/values.py`의 `SCOPE_FALLBACK`).

계약 종류는 **나라장터 업무구분에서 먼저 읽고**, 용역 안에서 SW/CM을 가릴 때만
본문 키워드로 추론합니다 (`clause_review.scope_for_notice`).

### 4.4 표준 조문 인덱스

`data/standards/`에 예규 원문 5건(.hwp/.pdf)이 있고, 여기서
`scripts/build_standard_clauses.py`가 `clauses.json`(423조문)을 만듭니다.

```
공사계약일반조건             70
물품구매(제조)계약일반조건    40
용역계약일반조건             75
정부 입찰·계약 집행기준     145
국가계약법 시행규칙          93
```

**예규가 개정되면 원문을 교체하고 스크립트를 다시 돌리는 것이 전부입니다.**
코드 수정은 필요 없습니다(문언이 바뀌어 anchor가 안 맞으면 그때만).

### 4.5 아직 하지 않기로 한 것

| 항목 | 상태 | 이유 |
| --- | --- | --- |
| 임베딩 검색(리트리버) | **꺼둠** | `make_embedding_fallback`은 있으나 호출부 없음. 미검출 사례가 관측되지 않았고, 지금 병목은 재현율이 아니라 정밀도. 유사도가 판정에 섞이면 근거 설명이 흐려짐 |
| pgvector · 벡터 DB | 미도입 | 검색 범위가 공고 하나 안(약 330청크)이라 전수 코사인이 마이크로초. ANN이 풀 문제가 없음 |
| 청크 저장소 | 미구현 | [04-chunk-store-draft.md](04-chunk-store-draft.md). 청킹을 고칠 때 같이 와야 함 |
| 조항검토 결과 저장 | **테이블 없음** | 검출해도 결과가 남지 않음. 스키마 제안은 [05](05-clause-types-team-share.md) |

> 지금 `similarity_matrix`는 쓰고 있으나 **오프라인 n-gram 벡터**이고, 판정이 아니라
> 후보 청크 정렬용입니다. 실패해도 그냥 넘어갑니다.

---

## 5. 절대 변경하면 안 되는 것

### 5.1 다른 담당자 소유 파일 — 읽기만

```
apps/api/app/routers/         Backend
apps/api/app/services/        Backend
apps/api/app/models.py        DB
apps/api/app/main.py          Backend
apps/api/alembic/versions/    DB
apps/web/                     Frontend
```

**import 해서 쓰는 것은 됩니다. 고치는 것은 안 됩니다.**
부득이하게 고쳐야 하면 (a) 코드에 이유를 주석으로 남기고 (b) 담당자에게 명시적으로 알립니다.

### 5.1.1 `app/ai/` 는 이 파트 전용이 아닙니다 — 중요

2장에서 `app/ai/`를 "이 파트의 영역"이라고 썼지만, **실제 커밋 이력은 다릅니다.**
최근 3주간 다른 담당자들이 같은 파일을 고쳐 왔습니다. 이 사실을 모르고 작업하면
pull 할 때마다 충돌합니다.

**경쟁 파일 — 작업 전 반드시 `git pull`, 작업 후 즉시 PR**

```
apps/api/app/ai/requirement_extraction.py    ← 가장 경쟁이 심함
apps/api/app/ai/legacy_slots.py
apps/api/app/ai/analysis_pipeline.py
apps/api/app/ai/analysis_result.py
apps/api/app/ai/contracts.py
apps/api/app/ai/judgment.py
apps/api/app/ai/requirement_diff.py
apps/api/app/ai/evidence_adapter.py
apps/api/app/ai/chunking.py
apps/api/app/ai/backend_blocks.py
apps/api/app/ai/__init__.py

apps/api/tests/test_ai_integration.py
apps/api/tests/test_requirement_extraction.py
apps/api/tests/test_analysis_pipeline.py
apps/api/tests/test_qualification_judgment.py
apps/api/tests/test_canonicalize.py
apps/api/tests/test_askability.py
apps/api/tests/test_analysis_result.py
apps/api/tests/test_requirement_diff.py
apps/api/tests/test_product_baseline_regression.py
```

**단독 파일 — 충돌 이력 없음**

```
apps/api/app/ai/clause_review/**       계약조건 검토 전체
apps/api/app/ai/goldenset/**
apps/api/app/ai/briefing.py            notice_digest.py  notice_sections.py
apps/api/app/ai/summary.py             notice_requirements.py
apps/api/app/ai/extensions.py          business_plan.py
apps/api/app/ai/demo.py                demo_web.py
apps/api/app/ai/providers/embeddings.py
docs/llm-rag/**                        data/standards/**   scripts/**
```

> 새 기능은 가능하면 **단독 파일 쪽에 새 모듈로** 두십시오. 경쟁 파일을 크게
> 고쳐야 한다면 그 작업만 따로 떼어 먼저 올리는 편이 낫습니다. 오래 들고 있을수록
> 남의 커밋이 쌓여 충돌이 커집니다.

### 5.1.2 충돌을 미리 보는 법

pull 하기 **전에** 내 변경과 남의 변경이 겹치는지 확인합니다.

```bash
git fetch origin
git diff --name-only HEAD origin/develop | grep -Ff <(git diff --name-only)
```

아무것도 안 나오면 안전합니다. 파일이 나오면 그 파일만 조심하면 됩니다.

**작업 규칙 세 가지**

1. **작게 자주 커밋한다.** 미커밋 변경은 pull 할 때 전부 충돌 후보가 됩니다.
   커밋해두면 git이 3-way merge로 대부분 자동 해결합니다.
2. **매일 시작할 때 `git pull --rebase origin develop`.** 내 커밋이 남의 커밋 위로
   올라가 히스토리가 깔끔하고, 충돌이 나도 커밋 단위로 해결하면 됩니다.
3. **브랜치를 옮기기 전에 커밋한다.** GitHub Desktop은 브랜치 전환 시 변경사항을
   자동으로 stash 했다가 다른 브랜치에 푸는데, 이때 충돌이 나면 stash가 사라진
   것처럼 보입니다(실제로는 `git fsck --unreachable`로 복구 가능).

### 5.1.3 `data/standards/clauses.json` 은 생성 파일입니다

두 사람이 각자 빌드해서 커밋하면 **파일 전체가 충돌하고 병합이 불가능합니다.**
둘 중 하나로 규칙을 정해 두십시오.

- 예규 원문만 커밋하고 `clauses.json`은 `.gitignore` → 각자 빌드
- 또는 **한 사람만 빌드해서 커밋** → 나머지는 절대 재빌드 후 커밋하지 않음

충돌이 났다면 병합하지 말고 **다시 빌드하는 것이 정답**입니다.

```bash
git checkout --ours data/standards/clauses.json   # 아무 쪽이나
python scripts/build_standard_clauses.py          # 원문에서 다시 생성
```

### 5.2 판정 로직을 브라우저에 옮기지 말 것

`demo_web.html`은 순수 클라이언트입니다. 판정을 프론트에서 다시 계산하면 두 곳에
같은 로직이 생기고 반드시 어긋납니다. 화면은 서버가 준 결과를 그리기만 합니다.

### 5.3 `app.ai`는 DB·네트워크에 의존하지 않는 라이브러리로 유지

`app.ai`의 어떤 모듈도 모듈 최상단에서 `sqlalchemy`, `app.models`, `app.services`,
`app.config`를 import 하지 않습니다. 데모(`demo.py`, `demo_web.py`)만 예외적으로
**함수 안에서** import 합니다.

### 5.4 비교 기준값을 코드에 쓰지 말 것

3.2 참조. `values.py`의 `recorded`는 트립와이어이고 판정에 쓰이지 않습니다.
값이 필요하면 `resolve_all(clauses, contract_scope=...)`로 원문에서 읽으십시오.

### 5.5 판정 사유를 모델에게 맡기지 말 것

`briefing.REASON_LABELS`가 `reason_code`를 사람이 읽을 문장으로 바꿉니다.
모델에게 사유를 쓰게 하면 판정과 설명이 어긋납니다.

---

## 6. 기술 스택

| 계층 | 사용 |
| --- | --- |
| 언어 | Python 3.14 |
| 웹 | FastAPI · uvicorn · Pydantic v2 |
| DB | PostgreSQL 17 (Supabase) · SQLAlchemy · Alembic — **이 파트는 직접 쓰지 않음** |
| 모델 | OpenAI (`OPENAI_MODEL_DEFAULT`) · Structured Output(JSON schema) |
| 문서 추출 | pypdf · olefile · 자체 HWPML 리더 |
| 외부 API | 나라장터 BidPublicInfoService |
| 테스트 | pytest (현재 **152개 통과**) |

### 환경변수 (`.env`)

```
OPENAI_API_KEY          요건 추출·요약·챗봇에 필요. 없으면 계약조건 검토만 동작
OPENAI_MODEL_DEFAULT
G2B_SERVICE_KEY         나라장터 조회. URL 인코딩된 상태로 두면 config가 디코딩함
DATABASE_URL            전체 URL 형식이어야 함 (호스트명만 넣으면 앱이 뜨지 않음)
```

> 모델 프로바이더는 `os.environ`을 읽고 `Settings`는 `.env`를 읽되 export하지 않습니다.
> 그래서 데모 진입점에서 `load_dotenv()`를 호출합니다. 라이브러리에서는 하지 않습니다.

### 테스트 실행

DB가 필요한 테스트는 `conftest.py`가 실제 Postgres에 붙으려 하므로 분리해서 돌립니다.

```bash
python -m pytest apps/api/tests/ --noconftest -q \
  --ignore=apps/api/tests/test_companies.py \
  --ignore=apps/api/tests/test_notices.py \
  --ignore=apps/api/tests/test_master_codes.py \
  --ignore=apps/api/tests/test_mvp_golden_e2e.py \
  --ignore=apps/api/tests/test_notice_polling.py \
  --ignore=apps/api/tests/test_bootstrap_product_data.py \
  --ignore=apps/api/tests/test_product_data_inventory.py \
  --ignore=apps/api/tests/test_product_golden_candidates.py \
  --ignore=apps/api/tests/test_product_golden_inspector.py \
  --ignore=apps/api/tests/test_seed_product_golden_demo.py
```

---

## 7. 데모 실행 준비

> 클론 직후 상태에서 화면이 뜨기까지 필요한 것 전부입니다.
> **DB는 필요 없습니다.** `DATABASE_URL`이 깨져 있어도 데모는 돌아갑니다.

### 7.1 준비물 체크리스트

| # | 항목 | 필수 | 없으면 |
| --- | --- | :---: | --- |
| 1 | Python 3.14 + `requirements.txt` 설치 | ✅ | 실행 불가 |
| 2 | `.env`에 `OPENAI_API_KEY` | ⚠️ | **계약조건 검토만 동작.** 요약·요건추출·챗봇 전부 꺼짐 |
| 3 | `.env`에 `G2B_SERVICE_KEY` | ⚠️ | 새 공고를 못 받음. 캐시된 공고 3건만 열람 |
| 4 | `data/standards/` 예규 원문 5건 | ⚠️ | `clauses.json`이 있으면 실행은 됨. **재빌드는 불가** |
| 5 | `data/standards/clauses.json` | ✅ | **계약조건 검토 전체 실패** |
| 6 | `data/demo/notice-documents/` 캐시 | ❌ | 없어도 됨. 나라장터에서 새로 받으면 채워짐 |

### 7.2 설치

```bash
pip install -r apps/api/requirements.txt
pip install -r apps/api/requirements-dev.txt    # 테스트까지 돌릴 경우
```

> **`python-dotenv`는 requirements.txt에 직접 없습니다.** `pydantic-settings`와
> `uvicorn[standard]`가 끌어오는 전이 의존성이라 지금은 설치됩니다. 데모가
> `.env`를 읽는 데 이 패키지를 쓰므로, 나중에 둘 중 하나가 빠지면 **키가 있어도
> "LLM 없음"으로 조용히 내려앉습니다.** 그때는 `pip install python-dotenv`.

### 7.3 `.env` 작성

리포지토리 루트에 둡니다.

```
OPENAI_API_KEY=sk-...
OPENAI_MODEL_DEFAULT=...
G2B_SERVICE_KEY=...        # 나라장터 공공데이터포털 인증키(URL 인코딩된 값 그대로)
```

`G2B_SERVICE_KEY`는 [공공데이터포털](https://www.data.go.kr)에서 **나라장터
입찰공고정보서비스(BidPublicInfoService)** 활용신청 후 발급받습니다. 승인까지
시간이 걸리므로 미리 신청해 두십시오. 인코딩/디코딩 키 중 **인코딩된 값**을 그대로
넣으면 `config`가 디코딩합니다.

### 7.4 표준 조문 인덱스 — 가장 자주 막히는 곳

계약조건 검토는 `data/standards/clauses.json`(423조문) 없이는 **전부 실패**합니다.

**이미 있으면** 아무것도 안 해도 됩니다. 확인:

```bash
python -m apps.api.app.ai.demo --standards
```

계약 종류 5종의 기준값 표가 나오면 정상입니다.

**없거나 다시 만들어야 하면** 예규 원문 5건이 `data/standards/`에 있어야 합니다.

```
(계약예규) 공사계약일반조건 …(제147호)(20260430).hwp
(계약예규) 물품구매(제조)계약일반조건 …(제170호)(20260825).hwp
(계약예규) 용역계약일반조건 …(제149호)(20260430).hwp
(계약예규)정부 입찰ㆍ계약 집행기준 …(제172호)(20260825).pdf
국가를 당사자로 하는 계약에 관한 법률 시행규칙 …(제00001호)(20260102).hwp
```

[법제처 국가법령정보센터](https://www.law.go.kr)에서 행정규칙으로 검색해 받습니다.
파일명은 바뀌어도 됩니다 — `standards/index.py`의 `_SOURCE_NAMES`가 **파일명에
포함된 키워드**로 출처를 판별합니다(`공사계약일반조건`, `물품구매`, `집행기준`,
`법률 시행규칙` 등). 다만 그 키워드는 남아 있어야 합니다.

```bash
python scripts/build_standard_clauses.py
```

9개 기준값이 전부 `[ok]`로 나오면 성공입니다. 하나라도 `[FAIL]`이면 그 룰은
판정하지 않고 "확인 불가"로 보고됩니다 — 조용히 틀린 값을 쓰지는 않습니다.

### 7.5 실행

```bash
uvicorn apps.api.app.ai.demo_web:app --port 8200
```

브라우저에서 **http://localhost:8200**

첫 화면 우측 상단 칩으로 상태를 확인하십시오.

| 표시 | 뜻 |
| --- | --- |
| 연결됨 · 요건 추출 가능 | 전부 정상 |
| LLM 없음 · 조항검토만 가능 | `OPENAI_API_KEY` 미설정 또는 `python-dotenv` 없음 |

### 7.6 화면에서 확인할 것

캐시된 공고가 있으면 공고번호 칩이 떠 있어 클릭만 하면 됩니다.

| 공고번호 | 종류 | 확인 포인트 |
| --- | --- | --- |
| `R26BK01705963` | 소프트웨어 용역 | 요건 판정 + 요약 7섹션 |
| `R26BK01716363` | 공사 | 근거 조문이 **공사계약일반조건**인지 |
| `R26BK01715895` | 물품 | 검출이 적은 것이 정상(규격서 위주) |

1. 판정 카드의 **`▸ 원문 발췌 보기`** — 인용문보다 긴 원문 단락이 나오고 인용
   부분에 하이라이트가 걸립니다
2. **기준값 탭** — 표의 모든 숫자가 방금 예규 원문에서 읽어온 값입니다
3. 공사 공고의 근거가 용역계약일반조건으로 나오면 **회귀입니다**

### 7.7 CLI로도 됩니다

브라우저 없이 확인할 때 씁니다.

```bash
python -m apps.api.app.ai.demo --standards          # 기준값 표 (키 불필요)
python -m apps.api.app.ai.demo --list               # 캐시된 공고 목록
python -m apps.api.app.ai.demo --fetch <공고번호>    # 나라장터에서 받아 검토
python -m apps.api.app.ai.demo --text "지체상금은 …" # 문장 하나 즉석 검토
```

### 7.8 자주 막히는 것

| 증상 | 원인 · 해결 |
| --- | --- |
| `표준 조문 인덱스가 없습니다` | 7.4 참조. `build_standard_clauses.py` 실행 |
| 칩이 계속 "LLM 없음" | `.env` 위치가 리포지토리 루트인지 확인. `python-dotenv` 설치 여부 확인 |
| 공고번호를 못 찾음 | 하이픈 없이 입력. `G2B_SERVICE_KEY` 확인 |
| 첨부에서 텍스트를 못 읽음 | 첨부가 이미지 PDF인 경우. OCR은 지원하지 않음 |
| 포트 충돌 | `--port 8201` 등으로 변경 |
| 한글이 깨짐 (Windows) | `PYTHONIOENCODING=utf-8` 설정. CLI만 해당, 브라우저는 무관 |

---

## 8. 고도화 방향 (검토 중)

> 2026-09-09 팀 논의. 네 가지 제안을 원칙(3장)에 비추어 검토한 결과입니다.
> **"지금 가능"은 이 파트 코드로 착수할 수 있다는 뜻이지, 완성된다는 뜻이 아닙니다.**

### 8.1 로컬 모델 병행 (비용 지속가능성)

API 호출 비용 없이 팀 보유 자원(RunPod/Colab)으로 구동 가능한 로컬 모델
(Qwen 저파라미터 · Gemma 등)을 추가하고, API 모델과 성능을 비교해 최종 채택.
발표 때는 두 경로를 모두 시연.

**지금 가능 — 코드 인터페이스는 이미 맞춰져 있습니다.**
`OpenAIStructuredExtractor`/`OpenAINarrator`는 `(system_prompt, user_body,
json_schema) -> dict` 형태의 **호출 가능한 어댑터**일 뿐이라, 같은 계약을
지키는 `LocalStructuredExtractor`를 하나 더 만들어 vLLM/llama.cpp 같은
OpenAI-호환 엔드포인트(`base_url`만 다른)에 꽂으면 됩니다. 파이프라인
(`analysis_pipeline.py`, `briefing.py`)은 어댑터를 몰라도 되므로 코드 변경이
없습니다. 스키마 강제 출력을 지원하지 않는 서버라도 `extract_legacy_slots`에
이미 있는 재시도(`max_retry`)가 실패를 흡수합니다.

**지금은 안 됨 — 이 파트 소관 밖입니다.** 실제 GPU 서버 구동, 모델 서빙 안정화,
실측 성능 비교는 인프라·운영 작업입니다. 코드 훅만 준비해두고 인프라가
올라오면 바로 붙이는 순서를 권합니다.

### 8.2 실무 어투·용어 파인튜닝

**원칙과 잘 맞습니다.** 이 프로젝트는 "판정은 코드, 서술은 모델"이 원칙이라
(3.1), 파인튜닝 대상은 `Narrator` 하나뿐입니다. `judgment.py`·`clause_review`는
전혀 건드리지 않으므로 **서술 품질만 바뀌고 판정 정확성에는 영향이 없습니다.**

**지금은 안 됨.** "실무자가 어색하다고 느끼는 표현" 학습 데이터가 없고,
파인튜닝 인프라도 없습니다.

**지금 가능한 인터림.** 파인튜닝 전에 시스템 프롬프트에 실무 어투 few-shot
예시를 넣는 것으로 상당 부분을 얻을 수 있습니다. 비용이 0이라 먼저 시도해볼
가치가 있고, 정식 파인튜닝은 8.1의 로컬 모델이 준비된 뒤 묶어서 진행하는 편이
API 모델보다 반복 실험이 쌉니다.

### 8.3 신규 LLM 기능 — 두 제안의 난이도가 다릅니다

**① 강점/취약점 기반 공고 추천 — 지금은 설계만 가능합니다.**

지금 판정은 "이 공고 vs 이 프로필" 1:1입니다. 이 기능은 "여러 공고 vs 이
프로필" N:1 매칭이라 **이 파트가 접근 가능한 공고 코퍼스 자체가 없습니다**
(수집·폴링은 Backend 소관). "강점"을 무엇으로 정의할지도 미정입니다 —
SATISFIED/UNSATISFIED 비율만으로는 강점이 되지 않고, 별도의 도메인 정의가
필요합니다.

**여기서 처음으로 임베딩·벡터 검색이 실제로 필요해집니다.** 4.5에서 "공고 간
검색이 필요해지면"이라고 적어둔 조건이 이것입니다 — 공고 하나 안에서
조항을 찾는 지금까지의 검색과 달리, 이번엔 **공고 여러 건을 가로질러** 찾아야
합니다.

착수하더라도 3.1 원칙은 여기도 그대로 적용됩니다 — **추천 점수는 코드가
계산하고, 모델은 그 점수를 설명만 합니다.** 추천 사유를 모델이 지어내면
지금까지 쌓은 신뢰(근거 원문 발췌)가 이 기능에서만 무너집니다.

**② 사업계획서 초안 작성 — 지금 프로토타입 가능합니다.**

기존 인프라 재사용도가 높습니다. `briefing.py`가 이미 "판정 + 근거 +
공고 원문"을 한 컨텍스트로 조립해두고 있어서, 새 엔드포인트에서 그 컨텍스트와
사용자 추가 입력을 `Narrator`에 넘기기만 하면 됩니다.

다만 짚어야 할 것이 하나 있습니다. **이 기능은 이 프로젝트에서 처음으로
모델이 "서술"이 아니라 "생성"을 하는 영역입니다.** 3.1은 모델이 확정된
판정을 문장으로 풀어쓰는 것까지만 허용했는데, 초안 작성은 없던 문서를
새로 씁니다. 그래서:

- 사업계획서의 "정해진 틀"을 실무자에게 확인해 템플릿으로 고정해야 합니다
  (모델이 양식까지 즉흥으로 만들면 매번 다른 문서가 나옵니다)
- 화면에 **"초안입니다 — 검토 후 사용하세요"** 를 판정 카드와 다른 방식으로
  표시해야 합니다. 지금까지의 UI는 "코드가 확정한 결과"만 보여줬는데, 이
  결과물은 그렇지 않다는 것을 사용자가 혼동하면 안 됩니다

### 8.4 권장 순서

```
1. 사업계획서 초안 프로토타입     기존 인프라 재사용, 코드만으로 시작 가능
2. 로컬 모델 프로바이더 어댑터    코드는 지금 가능, 실측은 인프라 대기
3. 어투 개선 (프롬프트 인터림)   비용 0, 정식 파인튜닝은 2번 이후
4. 강점/취약점 추천             코퍼스·스코어링 설계부터 — 가장 나중
```

---

## 9. 더 읽을 것

| 문서 | 내용 |
| --- | --- |
| [SPEC.md](SPEC.md) | 이번 기능의 요구사항·완료조건·테스트 |
| [01-branch-comparison.md](01-branch-comparison.md) | 이식 경위, 판정기 선택 근거 |
| [02-integration-requests.md](02-integration-requests.md) | 팀에 요청한 것 / 부득이하게 수정한 것 |
| [03-quality-roadmap.md](03-quality-roadmap.md) | Extraction·RAG·Rule·Eval 개선 우선순위 |
| [04-chunk-store-draft.md](04-chunk-store-draft.md) | 청크 저장소 설계 초안 (미구현) |
| [05-clause-types-team-share.md](05-clause-types-team-share.md) | 위험조항 9종 + DB 스키마 제안 |
| [06-judgment-api-contract.md](06-judgment-api-contract.md) | **판정 정보가 프론트·백엔드로 전달되는 경로와 계약** |
