# 07 — import 경로 마이그레이션 (GPT 인계)

> 작성 2026-09-10 · 김재현 (LLM/RAG)
> **선행 커밋에서 `git mv` 로 파일만 옮겼습니다. import 경로는 아직 안 고쳤습니다.**
> 지금 리포는 **동작하지 않습니다.** 이 문서의 작업이 그걸 되돌립니다.

---

## 0. 지금 상태

```
직전 커밋   순수 이동만 (git mv). 코드 내용은 한 줄도 안 바꿈
현재        import 경로가 옛 위치를 가리켜 ImportError
할 일       import 50줄 · 22개 파일 수정
검증        pytest 183개 통과하면 완료
```

이동과 수정을 두 커밋으로 나눈 이유는 리뷰 때문입니다. 섞으면 "파일이 옮겨진 것"과
"코드가 바뀐 것"을 구분할 수 없어 리뷰가 불가능해집니다.

---

## 1. 무엇이 어디로 갔나

### 1.1 `ai/extraction/` — 공고 산문을 구조화하는 계층 (모델 사용)

```
apps/api/app/ai/requirement_extraction.py  →  ai/extraction/requirement_extraction.py
apps/api/app/ai/legacy_slots.py            →  ai/extraction/legacy_slots.py
apps/api/app/ai/canonicalize.py            →  ai/extraction/canonicalize.py
apps/api/app/ai/analysis_pipeline.py       →  ai/extraction/analysis_pipeline.py
apps/api/app/ai/analysis_result.py         →  ai/extraction/analysis_result.py
apps/api/app/ai/notice_requirements.py     →  ai/extraction/notice_requirements.py
apps/api/app/ai/evidence_adapter.py        →  ai/extraction/evidence_adapter.py
apps/api/app/ai/backend_blocks.py          →  ai/extraction/backend_blocks.py
```

### 1.2 `ai/narration/` — 확정된 판정을 문장으로 옮기는 계층 (판정하지 않음)

```
apps/api/app/ai/briefing.py         →  ai/narration/briefing.py
apps/api/app/ai/notice_digest.py    →  ai/narration/notice_digest.py
apps/api/app/ai/notice_sections.py  →  ai/narration/notice_sections.py
apps/api/app/ai/summary.py          →  ai/narration/summary.py
apps/api/app/ai/business_plan.py    →  ai/narration/business_plan.py
```

### 1.3 `ai/demo/` — 데모 진입점 (파일명도 바뀜)

```
apps/api/app/ai/demo.py          →  ai/demo/cli.py        ← 이름 변경
apps/api/app/ai/demo_web.py      →  ai/demo/web.py        ← 이름 변경
apps/api/app/ai/demo_web.html    →  ai/demo/web.html      ← 이름 변경
apps/api/app/demo/documents.py   →  ai/demo/documents.py
apps/api/app/demo/__init__.py    →  ai/demo/__init__.py
apps/api/app/llm_standalone.py   →  ai/demo/llm_standalone.py
```

`apps/api/app/demo/` 디렉터리는 없어졌습니다.

### 1.4 옮기지 않은 것

`ai/` 최상위에 남은 파일들은 그대로입니다.

```
contracts.py  judgment.py  extensions.py  askability.py
chunking.py   requirement_diff.py  evaluation_contracts.py
clause_review/  normalization/  providers/  goldenset/
```

`qualification_briefing.py` 와 `qualification_briefing_router.py` 는 **일부러 안
옮겼습니다.** SQLAlchemy·Session 에 묶여 있어 `ai/` 안에 들어가면 "ai 는 DB 를
모른다"는 경계가 깨집니다. 나중에 `services/`·`routers/` 로 갈 파일입니다.

---

## 2. 고쳐야 할 import 50줄

**모듈 이름은 그대로고 경로만 한 단계 깊어집니다.** 아래 규칙이 전부입니다.

| 위치 | 옛 형태 | 새 형태 |
| --- | --- | --- |
| `ai/` 최상위 파일 | `from .briefing import X` | `from .narration.briefing import X` |
| `ai/extraction/` 내부끼리 | `from .analysis_result import X` | 그대로 (같은 패키지) |
| `ai/narration/` 내부끼리 | `from .summary import X` | 그대로 (같은 패키지) |
| `ai/extraction/` → 상위 | `from .contracts import X` | `from ..contracts import X` |
| `ai/narration/` → 상위 | `from .contracts import X` | `from ..contracts import X` |
| `ai/demo/` → 형제 패키지 | `from .analysis_pipeline import X` | `from ..extraction.analysis_pipeline import X` |
| `app/` 최상위 | `from .ai.briefing import X` | `from .ai.narration.briefing import X` |
| 테스트 | `from apps.api.app.ai.briefing import X` | `from apps.api.app.ai.narration.briefing import X` |

### 2.1 파일별 목록

아래가 전부입니다. 줄 번호는 이동 직후 기준이라 수정하면서 밀릴 수 있습니다.

```
apps/api/app/ai/clause_review/embedding_fallback.py
    35  from ..requirement_extraction import StructuredExtractor
        → from ..extraction.requirement_extraction import StructuredExtractor

apps/api/app/ai/demo/documents.py
    38  from ..ai.notice_requirements import extract_notice_facts
        → from ..extraction.notice_requirements import extract_notice_facts
        ※ 이 파일은 app/demo/ 에서 왔으므로 `..ai.` 접두사가 이제 틀립니다.
          ai/demo/ 안에 있으니 `..extraction.` 이 맞습니다.

apps/api/app/ai/demo/web.py
    30  from .analysis_pipeline import (        → from ..extraction.analysis_pipeline import (
    35  from .briefing import ...               → from ..narration.briefing import ...
    36  from .business_plan import ...          → from ..narration.business_plan import ...
    49  from .notice_digest import ...          → from ..narration.notice_digest import ...
    ※ web.py 안의 다른 상대 import (`.chunking`, `.clause_review`, `.judgment`,
      `.extensions`, `.clause_review.standards`) 도 전부 `..` 로 한 단계 올려야 합니다.
    ※ PAGE_PATH 가 `demo_web.html` 을 가리키면 `web.html` 로 바꿔야 합니다.
    ※ REPO_ROOT = parents[4] 가 parents[5] 로 바뀝니다 (경로가 한 단계 깊어짐).

apps/api/app/ai/demo/cli.py
    ※ 위 web.py 와 같은 이유로 상대 import 전부 `..` 로. REPO_ROOT 깊이도 확인.

apps/api/app/ai/demo/llm_standalone.py
    ※ app/ 에서 왔으므로 `from .config`, `from .errors`,
      `from .qualification_briefing_router` 가 전부 `...` 로 바뀝니다.

apps/api/app/ai/extraction/analysis_pipeline.py
    24  from .analysis_result import ...      → 그대로 (같은 패키지)
    25  from .backend_blocks import ...       → 그대로
    26  from .canonicalize import ...         → 그대로
    29  from .requirement_extraction import ... → 그대로
    ※ 이 파일이 `.contracts` `.chunking` 등 ai 최상위를 참조하면 `..` 로.

apps/api/app/ai/extraction/canonicalize.py
    8   from .evidence_adapter import ...     → 그대로
    9   from .legacy_slots import ...         → 그대로

apps/api/app/ai/narration/briefing.py
    25  from .analysis_result import ...      → from ..extraction.analysis_result import ...
    29  from .notice_digest import ...        → 그대로 (같은 패키지)
    30  from .summary import ...              → 그대로

apps/api/app/ai/narration/business_plan.py
    14  from .briefing import ...             → 그대로
    15  from .summary import ...              → 그대로

apps/api/app/ai/narration/notice_digest.py
    24  from .notice_sections import (        → 그대로
    29  from .summary import ...              → 그대로

apps/api/app/ai/__init__.py
     9  from .analysis_pipeline import (      → from .extraction.analysis_pipeline import (
    14  from .analysis_result import ...      → from .extraction.analysis_result import ...

apps/api/app/analysis_schemas.py
     9  from .ai.analysis_result import ...   → from .ai.extraction.analysis_result import ...

apps/api/app/qualification_analysis.py
    11  from .ai.analysis_pipeline import (   → from .ai.extraction.analysis_pipeline import (
    17  from .ai.analysis_result import ...    → from .ai.extraction.analysis_result import ...

apps/api/app/qualification_briefing.py
    23  from .ai.briefing import (            → from .ai.narration.briefing import (
    32  from .ai.notice_digest import ...     → from .ai.narration.notice_digest import ...
    34  from .ai.summary import ...           → from .ai.narration.summary import ...
   110  from .ai.analysis_result import ...   → from .ai.extraction.analysis_result import ...
   168  from .ai.backend_blocks import ...    → from .ai.extraction.backend_blocks import ...

apps/api/app/qualification_briefing_router.py
    26  from .ai.briefing import ...          → from .ai.narration.briefing import ...
    27  from .ai.notice_digest import ...     → from .ai.narration.notice_digest import ...
    28  from .ai.summary import ...           → from .ai.narration.summary import ...

apps/api/app/scripts/retrieval_report.py
     8  from ..ai.requirement_extraction import ...
        → from ..ai.extraction.requirement_extraction import ...

apps/api/tests/  (전부 절대경로 `apps.api.app.ai.X` → `apps.api.app.ai.<패키지>.X`)
    test_ai_integration.py          backend_blocks · legacy_slots      → .extraction.
    test_analysis_pipeline.py       analysis_pipeline · legacy_slots   → .extraction.
    test_analysis_result.py         analysis_result                    → .extraction.
    test_canonicalize.py            canonicalize · legacy_slots ×3     → .extraction.
    test_requirement_extraction.py  backend_blocks · requirement_extraction ×2 → .extraction.
    test_briefing.py                analysis_result → .extraction. / briefing → .narration.
    test_business_plan.py           briefing · business_plan           → .narration.
    test_notice_sections.py         notice_sections                    → .narration.
```

---

## 3. 주의할 것

**3-1. `ai/__init__.py` 가 재수출하는 이름은 바꾸지 마십시오.**
`from apps.api.app.ai import analyze_qualification_documents` 같은 외부 호출부가
있습니다. 내부 경로만 고치고 `__all__` 의 이름은 그대로 두면 호출부가 안 깨집니다.

**3-2. 함수 안 import 도 있습니다.**
`qualification_briefing.py:110`, `:168` 처럼 함수 본문 안에 있는 것들입니다.
파일 상단만 보면 놓칩니다.

**3-3. 데모의 경로 상수를 확인하십시오.**
`web.py` 와 `cli.py` 가 `REPO_ROOT = Path(__file__).resolve().parents[4]` 로
리포 루트를 찾습니다. 디렉터리가 한 단계 깊어졌으므로 `parents[5]` 여야 합니다.
`PAGE_PATH` 도 `demo_web.html` → `web.html` 입니다.

**3-4. 경계 규칙은 그대로입니다.**
`ai/` 의 어떤 모듈도 최상단에서 `sqlalchemy`·`app.models`·`app.services`·`app.config`
를 import 하지 않습니다. `ai/demo/llm_standalone.py` 는 예외적으로 `config`·`errors`
를 씁니다 — 데모 진입점이라 허용하되, `ai/__init__.py` 가 `demo` 를 자동으로
import 하지 않도록 두십시오. 그래야 `import ai` 가 여전히 깨끗합니다.

**3-5. 코드 동작은 바꾸지 마십시오.**
이 작업은 import 경로 수정만입니다. 리팩터링·이름 변경·로직 개선을 섞지 마십시오.

---

## 4. 검증

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
  --ignore=apps/api/tests/test_seed_product_golden_demo.py \
  --ignore=apps/api/tests/test_product_baseline_regression.py
```

**183 passed** 가 기준선입니다. 이동 직전 커밋에서 183개였습니다.

추가로 데모가 뜨는지도 확인하십시오.

```bash
python -m apps.api.app.ai.demo.cli --standards      # 기준값 표가 나오면 정상
uvicorn apps.api.app.ai.demo.web:app --port 8200    # http://localhost:8200
```

`--standards` 는 API 키가 없어도 동작합니다.

---

## 5. 커밋

```
fix(ai): 폴더 재배치에 맞춰 import 경로 수정

직전 커밋에서 git mv 로 옮긴 파일들의 import 를 새 경로로 맞춤.
코드 동작은 바뀌지 않았고 테스트 183개 그대로 통과.
```

---

## 6. 더 읽을 것

| 문서 | 내용 |
| --- | --- |
| [PROJECT.md](PROJECT.md) | 아키텍처 · 디자인 원칙 · 절대 변경 금지 (특히 5.1.1 공동 소유 파일) |
| [SPEC.md](SPEC.md) | 기능 요구사항 · 완료 조건 |
| [06-judgment-api-contract.md](06-judgment-api-contract.md) | 판정 정보가 프론트·백엔드로 가는 경로 |
