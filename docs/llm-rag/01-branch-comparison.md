# LLM 전용 브랜치 ↔ Integration Baseline 비교

> 작성 2026-09-08 · LLM / RAG (김재현, 이홍규)
> 대상: `LLM` 브랜치(`64817dc`) vs `integration/mvp-baseline`(`b048a10`)

두 브랜치에서 같은 계층이 **독립적으로 두 번 구현**됐습니다. 이 문서는 무엇이 겹치고,
무엇이 한쪽에만 있고, 어느 쪽을 남겼는지를 근거와 함께 정리합니다.

## 요약

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

## 1. 겹치는 부분 — 판정기

두 구현을 **같은 입력 24개 케이스**로 돌려 비교했습니다. 기준일 2026-09-08 고정,
공통 케이스 매트릭스(명백한 충족/미충족, 정보 없음, 명시적 빈 목록, 표기 차이,
기간 경계, 건수, 지역, 기업규모, 인력, 경험분야).

```
정답   Baseline 23/24  →  (수정 후) 24/24        LLM 브랜치 19/24
위험(모름 → 미충족 확정): 양쪽 다 0건
```

### Baseline 이 이긴 5건 — 전부 "확정 가능한데 확인 불가로 뺀" 경우

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

### LLM 브랜치가 이긴 1건 — 이식했습니다

`ISO27001` 보유 + 공고가 `ISO/IEC 27001` 표기 → Baseline 이 **미충족으로 확정**.
`_norm()`이 `/`·공백을 지워 `iso27001` vs `isoiec27001`이 되고 부분문자열도 아니라
매칭 실패입니다. **자격 있는 업체를 탈락시키는 방향**이라 그것만 이식했습니다.
(→ `02-integration-requests.md` "이미 수정한 것" 참조)

---

## 2. 한쪽에만 있는 것 — 이식한 모듈

전부 Baseline 에 대응물이 없어 충돌 없이 추가했습니다.

### 계약조항 검토 `apps/api/app/ai/clause_review/` (9파일, 1,251줄)

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

### 예규 코퍼스 `data/standards/clauses.json`

용역계약일반조건 75조문 + 정부 입찰·계약 집행기준 145조문 + 국가계약법 시행규칙 1조문.
원본 HWP(실제로는 HWPML)에서 `scripts/build_standard_clauses.py`로 생성합니다.

### 임베딩 `apps/api/app/ai/providers/embeddings.py`

`Embedder` 프로토콜 + `OpenAIEmbedder` + **문자 2-gram 해싱 폴백**(오프라인, 키 불필요).
`similarity_matrix()`가 사용한 방법(`openai`/`ngram`)을 함께 반환합니다 — 두 점수 분포가
다르기 때문입니다. 신규 의존성 0개(순수 Python cosine).

### 공고 요약 `apps/api/app/ai/summary.py`
### 공고별 추가항목 `apps/api/app/ai/extensions.py`
### API 필드 → 요건 `apps/api/app/ai/notice_requirements.py`
### DB 없는 첨부 수집 `apps/api/app/demo/documents.py`

첨부를 URL로 직접 받아 캐시하고 `services.document_extraction.extract_document()`
(DB를 쓰지 않는 순수 함수)로 텍스트·블록을 뽑습니다. **HWPML 리더 포함** — 나라장터·법제처가
확장자만 `.hwp`인 XML을 배포하는데 백엔드 추출기가 이를 거부합니다.

---

## 3. 걷어낸 것

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

## 4. 이식 후 상태

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
