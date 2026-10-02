# PR #104 리뷰 반영 결과

작성: 2026-09-11 · 브랜치 `feat/llm-rag-core` · 리뷰어 홍규

리뷰 항목별로 무엇을 했고 무엇으로 확인했는지 적었습니다.
확인하지 못한 것은 확인하지 못했다고 적었습니다.

---

## 🔴 수정 필수

### ① 최신 develop 반영 후 재검증 — 완료

`git log HEAD..origin/develop` 가 비어 있습니다. develop 의 모든 커밋을 담고 있고
그 위에 Core 커밋만 얹힌 상태입니다.

테스트는 **222건 전부 통과**입니다(실패 0). 공용 DB 를 쓰는 7건도 포함한
숫자입니다 — 아래 ⑧ 의 migration 을 적용한 뒤 다시 돌렸습니다.

### ② PR 범위를 LLM/RAG Core + Evaluation 으로 정리 — 완료

develop 대비 변경 파일에서 챗봇·Copilot·사업계획서·Demo 코드는 모두 빠졌습니다.
남은 것은 Retrieval/Chunking/Extraction, dropped_requirements, Canonical/Guardrail,
위험조항 9종, Embedding fallback, Golden Set/Evaluation 입니다.

빠진 코드는 지운 것이 아니라 `backup/pr104-full` 브랜치에 그대로 있습니다.
별도 PR 로 올릴 때 그 브랜치에서 가져옵니다.

한 가지만 예외로 남겼습니다. `docs/llm-rag/08-chatbot-design-notes.md` 는
**코드가 아니라 설계 기록**입니다. 챗봇 코드는 전부 제외했지만, 거기 정리해 둔
의도와 실패했던 접근, 판정 결과를 말로 옮길 때 걸렸던 제약은 Copilot 구현에
참고가 될 것 같아 문서만 남겼습니다. 불필요하시면 빼겠습니다.

### ③ 사업계획서 별도 PR 분리 — 완료

`app/ai/narration/business_plan.py`, `tests/test_business_plan.py` 를 이 PR 에서
제외했습니다. 두 파일 모두 `backup/pr104-full` 에 있습니다.

### ④ Demo 를 제품 merge 범위와 분리 — 완료

`app/ai/demo/**` 6개 파일(cli.py · web.py · web.html · documents.py ·
llm_standalone.py · \_\_init\_\_.py)을 제외했습니다. 공고 첨부 캐시는
`.gitignore` 에 `data/demo/` 로 넣어 추적하지 않습니다 — 나라장터에서 다시 받을
수 있는 파일이라 리포에 둘 이유가 없습니다.

이 PR 에 남은 binary 는 두 종류이고, 둘 다 남긴 이유가 있습니다.

| 파일 | 크기 | 남긴 이유 |
|---|---|---|
| `app/ai/clause_review/standards/data/clauses.json` | 604KB | 제품이 런타임에 읽는 리소스입니다. 빠지면 표준 대조가 통째로 동작하지 않습니다. |
| `data/standards/` 예규 원문 5건 (hwp·pdf) | 합계 약 1.3MB | 위 json 의 출처입니다. 없으면 `scripts/build_standard_clauses.py` 를 다시 돌릴 수 없고, 판정 근거가 어느 문장에서 왔는지 감사할 수 없습니다. |

예규 원문까지 빼는 편이 좋다고 보시면 별도 참고 리포로 옮기겠습니다.
다만 그 경우 인덱스 재생성 경로가 리포 밖으로 나간다는 점은 같이 봐주시면
좋겠습니다.

### ⑤ 위험조항 복수 분류 Contract 정합성 — 완료

지적하신 그대로 고쳤습니다. 스칼라는 그 finding 자신의 값으로 두고, 중첩 분류는
배열에만 담습니다.

```python
# app/ai/clause_review/contracts.py
own_category = finding.category_code
own_risk_type = finding.risk_type
classified.append(finding.model_copy(update={
    "risk_type":  own_risk_type,
    "risk_types": _own_first(own_risk_type, risk_types),
    "category":   own_category,
    "categories": _own_first(own_category, categories),
}))

def _own_first[T](own: T, everything: list[T]) -> list[T]:
    """`categories[0] == category` 불변식을 지키면서 전체 집합을 유지한다."""
    rest = [item for item in everything if item != own]
    return [own, *rest]
```

`ClauseFinding` 의 validator 가 `categories[0] == category` 와
`risk_types[0] == risk_type` 을 모델 수준에서 강제하므로, 나중에 누가 스칼라를
대표값으로 덮어쓰면 객체 생성 시점에 터집니다. 검증은
`tests/test_clause_risk_categories.py` 에 있습니다.

직렬화 계약도 데모(`demo/web.py`)에서 `contracts.finding_to_payload()` 로
옮겼습니다. 데모를 떼어낸 뒤에도 저장·API 가 보는 모양이 한곳에 남아 있어야
해서입니다.

### ⑥ 계약조항 기준 데이터의 Docker 런타임 경로 — 완료 (컨테이너 실행은 미완)

`data/standards/clauses.json` →
`apps/api/app/ai/clause_review/standards/data/clauses.json` 으로 옮기고, 기본
경로를 패키지 안으로 고정했습니다.

```python
BUNDLED_CLAUSE_INDEX = Path(__file__).with_name("data") / "clauses.json"
```

Dockerfile 이 `COPY app ./app` 를 하고 `.dockerignore` 는
`__pycache__/`, `*.py[cod]`, `.pytest_cache/`, `tests/` 만 제외하므로 이미지에
포함됩니다.

**확인 방법과 한계를 그대로 적습니다.** Docker 데몬이 기동되지 않아
(`npipe:////./pipe/dockerDesktopLinuxEngine` 연결 실패) 실제 컨테이너 실행은 못
했습니다. 대신 Dockerfile 의 COPY 대상과 `.dockerignore` 규칙을 그대로 적용해
리포 **밖** 임시 디렉터리에 이미지 내용물(110개 파일)을 재현하고 거기서
import 했습니다.

```
index path : ...\ctx\app\ai\clause_review\standards\data\clauses.json
exists     : True
clauses    : 423
             70 공사계약일반조건 / 40 물품구매(제조)계약일반조건
             75 용역계약일반조건 / 145 정부 입찰·계약 집행기준
             93 국가계약법 시행규칙
```

경로 의존성이 사라진 것까지는 확인했습니다. 실제 컨테이너 기동 확인은 남아
있으니, CI 에서 이미지가 떠서 `load_clauses()` 가 423건을 읽는지 한 번 봐주시면
확실해집니다.

### ⑦ Related Issue 정리 — 완료

`Related Issue: #XX` 자리표시자를 `Related Issue: 없음` 으로 바꿨습니다. 이 작업에
대응하는 Issue 가 따로 없어서, 연결 대신 '없음' 으로 명시하는 쪽을 택했습니다.
본문 전체는 아래 §PR 본문 에 있습니다.

### ⑧ (리뷰에 없던 항목) 누락된 migration 을 찾아 추가했습니다

🟡 항목을 확인하다 실제 결함을 하나 찾았습니다.

이 PR 은 `analysis_models.py` 에 `dropped_requirements` 컬럼을 추가하는데, 가지
정리 과정에서 그 DDL(`010_add_dropped_requirements`)이 같이 떨어져 나가
**migration 없이 ORM 컬럼만 남아 있었습니다.** 공용 DB 를 쓰는 테스트 7건이
`UndefinedColumn: column "dropped_requirements" ... does not exist` 로 실패해서
드러났습니다. 그대로 merge 됐다면 자격요건 분석이 저장 시점에 깨집니다.

`013_dropped_requirements` 로 다시 넣었습니다. lineage 는 아래 🟡 에 있습니다.

---

## 🟠 범위 확인: SW기술자 등급 / 대기업집단 계열

**"Core 지원 완료 / 제품 입력·저장 연결은 후속" 으로 범위를 끊겠습니다.**

보신 그대로입니다. 단위 테스트는 `extensions` 를 직접 넣어 검증하고 있고, 제품
경로에서는 그 값이 채워지지 않습니다. 확인해 보니 비어 있는 자리가 하나가 아니라
셋이었습니다.

1. **수집** — `ask_back` 이 `required_for()` 로 질문을 만들어야 합니다.
2. **저장** — 답변을 `company_sw_engineer_grades` 행과
   `companies.conglomerate_affiliate` 컬럼에 써야 합니다. 표는 migration 010 으로
   이미 있고 ORM 모델이 없습니다.
3. **적재** — `build_company_profile_snapshot()` 이 그 값을 실어야 합니다.

세 자리 중 둘이 `ask_back` 과 `models.py` — Backend 영역입니다. 이미 파일 수가
많은 PR 에 남의 영역 세로 슬라이스를 얹는 것보다, 경계를 명확히 하고 후속으로
빼는 편이 낫다고 판단했습니다.

대신 **조용히 죽어 있지 않도록** 두 가지를 했습니다.

- `app/ai/extensions.py` 모듈 docstring 에 "제품 연결 현황" 절을 넣어 비어 있는
  세 자리를 이름으로 적었습니다.
- 제품 경로가 이 요건에 답할 수 없다는 사실을 테스트로 고정했습니다.

```python
def test_product_profile_path_cannot_answer_an_extension_yet() -> None:
    company = Company(name="테스트회사", company_size="SMALL")
    snapshot = build_company_profile_snapshot(company, ProfileCompleteness())
    assert snapshot.extensions == {}
    ...
    assert judgment.status == "UNKNOWN"
```

현재 동작은 **항상 UNKNOWN(확인 불가)** 입니다. 모르는 것을 '충족'으로 새어 보내지
않으므로 안전한 상태입니다. 연결이 끝나면 이 테스트가 깨지고, 그게 연결이
끝났다는 신호가 됩니다.

---

## 🟡 권장

### Migration lineage 단순화 — 완료

지적하신 `010_dropped → 013 merge → 014` 가지 구조를 없앴습니다. merge revision
없이, 공용 DB 가 이미 올라와 있는 최신 head 위에 선형으로 얹었습니다.

```
... → 011_contract_clause_findings → 012_late_penalty_rate → 013_dropped_requirements
```

```
heads: ['013_dropped_requirements']
bases: ['001_company_profile']
012 -> head: ['013_dropped_requirements']
```

공용 DB 가 012 면 적용되는 SQL 은 이것이 전부입니다. 추가 전용이고 기존 행은
server_default 로 채워집니다.

```sql
BEGIN;
ALTER TABLE qualification_analysis_runs
  ADD COLUMN dropped_requirements JSONB DEFAULT '[]'::jsonb NOT NULL;
ALTER TABLE qualification_analysis_runs
  ADD CONSTRAINT qualification_analysis_runs_dropped_requirements_array
  CHECK (jsonb_typeof(dropped_requirements) = 'array');
UPDATE alembic_version SET version_num='013_dropped_requirements'
  WHERE version_num = '012_late_penalty_rate';
COMMIT;
```

**공용 DB 에 적용 완료했습니다** (2026-09-11, 재현님 승인 후).

```
적용 전 : 012_late_penalty_rate
적용 후 : 013_dropped_requirements (head)
```

적용 후 전체 테스트 222건 통과(실패 0)를 확인했습니다. 추가 전용이라 이 컬럼을
모르는 다른 브랜치는 영향을 받지 않습니다.

#### 이 PR 에 **넣지 않은** DDL 하나

원래 가지에는 `contract_clause_findings` 에 `risk_types`/`categories` JSONB 를
추가하는 `014` 가 있었습니다. 이번에는 뺐습니다.

그 표는 예린님 영역이고 저장 코드도 그쪽에서 만들고 있어서, 제가 여기에 컬럼을
먼저 넣으면 같은 변경이 두 PR 에 생깁니다. Core 는 payload 모양
(`finding_to_payload` 의 `risk_types`/`categories`)까지만 제공하고, 컬럼 추가는
저장 PR 과 함께 가는 편이 맞다고 봤습니다. 예린님과 맞춰 보겠습니다.

### 압축파일·binary 정리 — 완료

`docs/llm-rag/LLM-RAG-노션.zip` 을 추적에서 뺐습니다(`git rm --cached`,
`.gitignore` 에 `docs/llm-rag/*.zip` 과 `*.7z` 추가). demo binary 는 ④ 에
적었습니다.

---

## Merge 조건 대조

| 조건 | 상태 |
|---|---|
| 최신 develop 반영 | ✅ |
| Core/Copilot 경계에 맞게 Copilot 코드 제외 | ✅ |
| 사업계획서 별도 PR 분리 | ✅ |
| 위험조항 분류 Contract 정합성 수정 | ✅ |
| clauses.json Docker runtime 문제 해결 | ✅ (컨테이너 실행 확인은 CI 에 부탁드립니다) |
| Issue 연결 정리 | ✅ 연결할 Issue 없음으로 명시 |
| 수정 후 전체 CI 재통과 | ✅ 222건 전부 통과 (실패 0) |

---

## PR 본문

```
## 무엇을 하는 PR 인가
LLM/RAG Core + Evaluation 고도화입니다. 판정은 코드가 하고 모델은 서술만 합니다.

- Retrieval / Chunking / Extraction 고도화
- dropped_requirements — 버린 요건 후보와 그 이유를 보존
- Canonical / Guardrail 개선
- 위험 계약조항 9종 탐지·분류 (계약유형별 기준 분기 포함)
- Embedding fallback
- Golden Set / Evaluation (반복 측정 포함)

## 범위에서 뺀 것
챗봇·Copilot·사업계획서·Demo 코드는 제외했습니다. backup/pr104-full 브랜치에
보존돼 있으며 별도 PR 로 올립니다.

## DB 변경
013_dropped_requirements 1건입니다. 선형이고 추가 전용입니다.
공용 DB 에는 이미 적용했습니다 (012 -> 013). 로컬에서는 `alembic upgrade head`
한 번 돌려 주세요.

## 확인
- 테스트 222건 전부 통과 (공용 DB 테스트 포함, 실패 0)
- clauses.json: Docker COPY 규칙을 재현한 리포 밖 컨텍스트에서 423건 로드 확인

## 리뷰 반영
docs/llm-rag/09-pr104-review-response.md 에 항목별로 정리했습니다.

Related Issue: 없음
```

리뷰어가 "실제 Issue 를 연결하거나 없음으로 명확히" 라고 하셨는데, 이 작업에
대응하는 Issue 가 없어 '없음' 으로 명시했습니다.
