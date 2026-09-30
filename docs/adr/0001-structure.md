# ADR 0001: 영역 분리와 파이프라인 중심 구조

- 상태: 제안
- 날짜: 2026-09-30

## 배경

3차 레포에서 확인한 구조 문제:

1. 요건의 경계·유형을 LLM이 정하고 코드는 사후 보정만 한다 (추출 32k자 일괄 입력 → `snap_to_source_span` 등으로 되돌림).
2. 요건 정체성이 raw 문자열이다 (`requirement_diff.semantic_identity`), 줄바꿈·인용 길이에 흔들린다.
3. 요건 표현이 원자 + 한 겹 ALL_OF/ANY_OF라 중첩·예외·사실 참조를 담지 못한다.
4. 열린 어휘(경험분야·인증명)를 문자열 포함으로 비교하고, 불일치를 미달로 처리한다.
5. 파이프라인 사정(PARTIAL)이 전체 적합 판정을 막고, 커버리지는 재지 않는다.
6. PDF 추출 결과가 쪽 단위 평문이라 블록 역할(제목/항목/각주/표/쪽 번호)이 없다.
7. 골든 CI가 canonical을 판정기에 직접 넣어 추출→판정 층을 재지 않는다.
8. 실험과 운영이 같은 DB를 쓴다.

또한 LLM 코드가 ORM을 직접 import하고, `models.py`·`schemas.py`·`main.py`를 모든 영역이 함께 수정해 충돌과 영역 침범이 잦았다.

## 결정

- `engine/`을 독립 Python 패키지로 분리한다. 엔진은 DB·ORM을 모르고 `ports.py`로만 바깥과 연결한다.
- 엔진 내부를 파이프라인 순서로 나눈다: `document`(6) → `clauses`(1) → `labeling`(1) → `requirements`(2·3) → `vocab`(4) → `judgment`(5) / `diff`(2).
- 요건 정체성은 원문 앵커 `(document_id, block_index, char_start, char_end)`로 하고 raw는 파생값으로 둔다.
- `eval/`을 최상위에 두고 전용 DB를 쓴다. e2e(공고→판정)와 k회 안정성 지표를 CI 게이트로 둔다(7·8).
- FE는 LLM 코드를 직접 import하지 않는다. copilot UI는 FE 단독 소유이고, `contracts/`에서 생성한 타입·클라이언트로만 연결한다.
- 모바일은 `apps/web` 반응형 + PWA로 지원한다. 스토어 배포가 필요하면 Capacitor 래퍼를 추가한다.

## 강제 장치

1. CODEOWNERS (레포가 Public이거나 유료 플랜이 되면 브랜치 보호로 필수 승인 전환)
2. CI zone guard: 한 PR이 두 영역 이상을 건드리면 실패 (`cross-zone` 라벨 예외)
3. import 경계: `engine/tests/test_engine_boundary.py` (엔진이 `apps`·`sqlalchemy`·`fastapi` 등을 import하면 실패). TS 쪽 `dependency-cruiser`는 FE 구조 정리 때 추가한다.

## 실행 순서

| 단계 | 내용 |
| --- | --- |
| S0 | e2e 측정 게이트, k회 안정성 지표, eval 전용 DB |
| S1 | 열린 어휘 불일치 → UNKNOWN, 커버리지 도입, PARTIAL 전역 차단 제거 |
| S2 | 문서 모델(블록 역할) |
| S3 | 코드 주도 조항 열거 + 조항 단위 LLM 라벨링 |
| S4 | 앵커 정체성, 앵커 기반 diff |
| S5 | 중첩 논리 + EXEMPT_IF(fact_ref) |
| S6 | 통제 어휘 카탈로그 |

각 단계는 S0 기준선 대비 수치를 PR에 첨부한다.

## 이관 1단계 결과 (2026-09-30)

3차 `develop` 112a8e3의 파일을 커밋 이력 없이 옮겼다. 동작은 바꾸지 않았고, 옮기기 전과 후의 수치가 같다.

| 검증 | 3차 | 4차 |
| --- | --- | --- |
| 백엔드 테스트 | 924 통과 | 924 통과 (engine 284 + eval 46 + api 594) |
| 골든 회귀 | 일치 110 / 보류 28 / 잘못된 확정 0 | 결과 JSON 동일 (실행 시각 제외) |
| copilot v3.1 검증 | 339 통과 | 339 통과 |
| 웹 | test·tsc·build 통과 | 동일 |

### 옮긴 위치

| 3차 | 4차 |
| --- | --- |
| `apps/api/app/ai/{contracts,extensions,evaluation_contracts}.py`, `normalization/`, `providers/`, `clause_review/` | `engine/bidengine/` 같은 이름 |
| `ai/qualification/extraction/{backend_blocks,chunking}.py` | `bidengine/document/` |
| `ai/qualification/extraction/{requirement_extraction,notice_requirements,code_salvage}.py` | `bidengine/labeling/` |
| `ai/qualification/extraction/{analysis_pipeline,analysis_result}.py` | `bidengine/pipeline/` |
| `ai/qualification/canonical/` | `bidengine/requirements/` |
| `ai/qualification/grounding/` | `bidengine/grounding/` |
| `qualification/rules/judgment.py` | `bidengine/judgment/rules.py` |
| `qualification/rules/{askability,clause_safety}.py` | `bidengine/judgment/` |
| `qualification/rules/requirement_diff.py` | `bidengine/diff/` |
| `document_rag/{answer,store,retrieval,readiness,langchain_pipeline}.py` | `bidengine/rag/` |
| `ai/quality_eval/`, `scripts/validate_real_golden_dataset.py` | `eval/bideval/` |
| `samples/golden/` | `eval/golden/` |
| `scripts/{run_golden_regression,run_extraction_recall,check_extraction_determinism}.py` | `eval/runners/` |
| `scripts/*copilot_v31*`, `scripts/ci_copilot_integration.sh` | `eval/runners/copilot/` |
| `scripts/build_standard_clauses.py` | `engine/scripts/` |
| `scripts/collect_code_master*.py` | `db/scripts/` |
| API 없이 도는 테스트 30개 | `engine/tests/`, `eval/tests/` |

### 이번 단계에서 결정과 다르게 남긴 것

- **copilot은 아직 `apps/api/app/copilot/`에 있다.** 모든 모듈이 API 스키마(`*_schemas.py`)와 ORM(`models.py`)에 이어져 있어 엔진으로 옮기면 경계가 깨진다. `ports.py`로 DB 접근을 뒤집은 뒤 옮긴다. 소유는 LLM.
- **`document_rag/service.py`, `services/document_extraction.py`는 API에 남겼다.** 둘 다 SQLAlchemy를 쓴다. 문서 추출은 S2(문서 모델)에서 엔진 `document/`로 다시 쓴다.
- **`qualification/{analysis,judgment,ask_back,matching,revalidation}.py`는 API에 남겼다.** DB를 읽고 쓰는 서비스 계층이고, 엔진을 호출한다.
- **docker-compose는 루트에 남겼다.** 사용법(`docker compose up`)을 바꾸지 않기 위해서다. API 이미지는 루트를 빌드 컨텍스트로 쓰고 엔진을 함께 설치한다.
- **eval 실행기 일부(`run_extraction_recall`, `check_extraction_determinism`)는 여전히 운영 DB를 읽는다.** S0에서 eval 전용 DB로 바꾼다(문제 8).
- **`docs/`는 3차 스냅샷이다.** 문서 안의 경로는 3차 기준이다.
