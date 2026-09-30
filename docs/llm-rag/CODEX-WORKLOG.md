# Codex 작업 로그

## 2026-09-11 — develop 기반 LLM/RAG 기능 통합

- `integration/llm-rag-validation`에서 `feature/llm-rag-pipeline`을 병합하고, 최신 `develop`의 `app.ai.qualification.*` 패키지 구조를 기준으로 충돌을 해소했습니다.
- 자격요건 근거 보존, 구조화 탈락 원문, 위험조항 9종 복수 분류, 공고 요약, 브리핑, 챗봇, 사업계획서 초안, 데모와 평가 도구를 이식했습니다.
- 제품 API에 브리핑 라우터를 등록하고 판정 실행 기준 사업계획서 초안 엔드포인트를 추가했습니다.
- 브리핑 근거에 `source_text`를 추가해 팀 프론트에서 데모와 동일한 원문 펼침과 인용 강조를 구현할 수 있게 했습니다.
- 프론트 소유 파일은 수정하지 않고 `08-frontend-integration-guide.md`에 API 계약과 화면 구현 순서를 정리했습니다.
- 검증: 통합 기능 집중 테스트 87건, 기존 환경 실패군을 제외한 Backend 회귀 193건, Python AST 163개, AI 모듈 import 53개가 통과했습니다.
- Docker 재빌드 후 DB/API healthy, `/health` 정상 응답, Alembic `010_dropped_requirements`, 브리핑·요약·챗봇·사업계획서 OpenAPI 경로 노출을 확인했습니다.
- 전체 테스의 나머지 실패는 외부 DB 접속 차단, Windows 임시 폴더 권한·CP949, 기존 골든셋 해시 불일치로 분리했으며 이번 통합 코드의 실패는 아닙니다.

## 2026-09-10 — 로컬 서버 종료 및 Docker Compose 전환

- 로컬 Backend API(8000)와 AI 데모 서버(8200)를 종료하고 Docker API·DB·notice-poller로 전환했습니다.
- 기존 PostgreSQL 볼륨은 유지하고 Compose 실행 환경에만 로컬 DB 접속값을 적용했습니다.
- 마이그레이션 종료 코드 0, DB/API healthy, `/health` 정상 응답과 OpenAI 환경변수 전달을 확인했습니다.

## 2026-09-10 — 정확도 측정 1차 착수

- 캐시 문서에서 참가자격 관련 원문 후보를 추출하는 `goldenset_span_proposer.py`를 추가했습니다. 자동 정답 라벨링은 하지 않고 사람이 확정할 `REVIEW`/`LIKELY_TRAP` 힌트만 제공합니다.
- 골든 스팬에 canonical 기대 필드와 판정 기대값을 선택적으로 기록할 수 있게 했고, `contained → retrieved → extracted → canonical → judgment` 단계별 깔때기를 지원합니다.
- 실제 모델 측정은 `--with-extraction --runs 3`으로만 명시적으로 실행되며, 세 번의 개별 결과와 평균을 함께 남깁니다.
- 기본 청커는 유지하고 최소 300자 누적·1,800자 상한·120자 겹침·라벨 초기화를 적용한 `hygienic` 실험군을 추가했습니다.
- 1개 공고 A/B 결과, 실험군은 청크 수 328→123, 중앙값 56.5→1,045자, 50자 미만 47.26%→0%, 상한 초과 46→0으로 청킹 건전성은 개선됐습니다. 반면 기존 앵커 검색과 결합하면 precision과 trap rate가 악화돼 자동 승격 게이트가 실패했습니다. 기본값으로 승격하지 않았습니다.
- 현재 캐시 3개 공고에서 사람이 검토할 후보 64건을 생성할 수 있음을 확인했습니다. 다음 단계는 후보를 실제 `POSITIVE`/`TRAP`으로 라벨링하고, 점수 기반 문자 예산 검색을 실험군으로 붙이는 것입니다.

## 2026-09-10 — `risk_types` 복구 및 구조화 탈락 원문 전달

- 당시 위험조항 저장/API 계약을 `risk_type=코드`로 잘못 적용했습니다. 이 기록은 아래 2026-09-11 필드 의미 정정으로 대체됩니다.
- 추출 검증에서 탈락한 후보를 30자로 잘라 `notes`에 넣던 로직을 제거했습니다. `RequirementAnalysisResult.dropped_requirements`에 `{raw, reason_code}`로 원문 전체를 보존합니다.
- 탈락 사유를 `MISSING_RAW`, `RAW_NOT_FOUND_IN_SOURCE`, `DETAIL_NOT_FOUND_IN_SOURCE`, `SOURCE_VALIDATION_FAILED` 코드로 고정했습니다.
- `qualification_analysis_runs.dropped_requirements` JSONB 컬럼 마이그레이션, ORM 저장·조회, API 스키마, 프론트 타입과 참가자격 화면 표시까지 연결했습니다.
- 직전 패키지 재배치 커밋이 import를 갱신하지 않아 로드되지 않던 `extraction`, `narration`, `demo` 경로와 이를 참조하는 서비스·스크립트·테스트의 import를 전수 재배치했습니다. 데모 파일 이동으로 달라진 저장소 루트와 HTML 경로도 함께 바로잡았습니다.
- 검증: 전체 테스트 211건 수집, DB 의존 테스트를 제외한 백엔드 184건, AI 패키지 45개 전수 import, Python 컴파일, Alembic 단일 head(`010_dropped_requirements`), 단독 API OpenAPI 생성, 프론트 TypeScript `--noEmit` 및 Vinext/Vite 프로덕션 빌드가 통과했습니다.
- 프론트 `oxlint`는 코드 검사 전에 기존 `.oxlintrc.json`의 `options.typeAware` 위치 오류로 중단됐으며, 이번 변경과 무관한 저장소 도구 설정 문제로 남겼습니다.

> Codex가 수행한 LLM/RAG 세부 조정 내역을 시간순으로 기록합니다.
> 설계와 범위의 기준 문서는 `PROJECT.md`와 `SPEC.md`입니다.

## 2026-09-10 — 위험조항 9종 분류의 중첩 전달

- 한 원문 조항에 여러 룰이 동시에 걸릴 때 전체 분류를 전달하는 복수 필드가 없음을 확인했습니다.
- 당시 필드 의미를 반대로 적용했으며, 아래 2026-09-11 정정 작업에서 `risk_type=한글 라벨`, `category=오류 코드`로 바로잡았습니다.
- 중첩 판정은 같은 공고 버전·청크·조항에서 원문 발췌가 동일하거나 서로 포함되는 경우에만 묶습니다. 같은 청크에 있을 뿐 원문 문장이 다른 결과는 합치지 않습니다.
- `/api/review-text`와 `/api/notice` 모두 응답 최상위에 검출된 `risk_types` 목록을 포함하고, 각 finding에는 해당 원문에 겹친 분류 목록을 포함합니다.
- 데모 프론트는 각 finding의 `categories`를 분류 칩으로 모두 표시합니다. 지체상금 한 문장에 상한·요율이 함께 있으면 두 칩이 표시됩니다.
- 검증: 위험조항·사업계획서 관련 집중 테스트 51건과 DB 의존 테스트를 제외한 API 테스트 167건이 통과했습니다.

### 팀 설계 변경 반영

- 이 시점의 저장 계약 정리는 필드 의미를 반대로 이해한 기록입니다. 최종 계약은 아래 2026-09-11 정정을 따릅니다.
- 원인이 하나뿐이어도 복수 배열은 원소 1개이며, 각 배열의 첫 원소가 대응 단수 대표값과 같습니다.
- 대표값은 `NEEDS_REVIEW → UNDETERMINED → COMPLIANT` 순으로 먼저 고르고, 동률이면 팀 확정 9종 순서를 적용합니다. 탐지 순서에 의존하지 않습니다.
- 데모 상세 화면은 `categories` 전부를 표시하고 복수이면 `N종에 걸림`을 함께 보여줍니다.
- `ClauseFinding`의 최초 복수 필드 구현은 방향이 뒤집혀 있었고, 아래 정정 작업에서 바로잡았습니다.
- 원격을 갱신해 확인했으나 현재 브랜치와 `origin/develop` 어디에도 팀원이 언급한 기존 `category` DB 컬럼/위험조항 저장 테이블은 아직 없습니다. 중복 마이그레이션은 만들지 않고 `02-integration-requests.md`에 안전한 JSONB 추가·백필 순서를 남겼습니다.
- 검증: DB 의존 테스트를 제외한 API 테스트 183건이 통과했습니다.

## 2026-09-10 — 사업계획서 초안 데모 프론트 연결

- 공고 검토 화면 하단에 `사업계획서 초안` 카드를 추가했습니다.
- 회사 소개, 제안 목표, 수행 방안, 차별점, 투입 조직·인력, 일정, 추가 참고사항을 입력받아 기존 `POST /api/business-plan-draft`로 현재 공고 컨텍스트와 기업 프로필을 함께 전송합니다.
- 공고를 불러오기 전 또는 구조화된 참가자격 요건이 없을 때는 생성 버튼을 비활성화합니다.
- 생성 중·성공·실패 상태와 서버가 반환한 검토 경고문을 화면에 표시하며, 모델 결과는 HTML로 해석하지 않고 텍스트로 렌더링합니다.
- 사용자 추가 입력이 전부 비어 있으면 요청을 보내지 않고 첫 입력란으로 안내합니다.
- 데모 HTML에 요청 필드와 엔드포인트 연결이 유지되는지 확인하는 회귀 테스트를 추가했습니다.
- 검증: `test_business_plan.py` 5건 및 DB 의존 테스트를 제외한 API 테스트 165건이 통과했습니다. 전체 수집은 현재 저장소의 비어 있는 `DATABASE_URL` 때문에 DB 모듈 7곳에서 중단되며 이번 프론트 변경과는 무관합니다.

## 기록 규칙

각 작업에는 다음 내용을 남깁니다.

- 작업 일시와 목적
- 변경한 파일
- 구현 또는 조사 결과
- 실행한 검증과 결과
- 남은 문제나 후속 작업

## 2026-09-09

### 작업 범위 확인

- `README.md`, `PROJECT.md`, `SPEC.md`를 읽고 LLM/RAG 파트의 소유 범위와 금지 사항을 확인했습니다.
- 우선 작업 대상으로 F8 확장항목 입력 반영, SW 기술자 등급 판정 경로 정리, `payment_period` 수치 인식 실패 조사, 공사 공고 지체상금 수치 인식 실패 조사를 확인했습니다.
- 저장소에 이미 존재하는 미커밋 변경은 보존하며, 이후 작업은 요청받은 범위만 최소한으로 수정합니다.
- 코드 변경 및 테스트 실행은 아직 하지 않았습니다.

### F8 확장항목 입력 반영 및 SW 기술자 등급 경로 정리

- 변경 파일:
  - `apps/api/app/ai/judgment.py`
  - `apps/api/app/ai/demo_web.py`
  - `apps/api/app/ai/demo_web.html`
  - `apps/api/tests/test_ai_extensions.py`
- `CompanyProfileSnapshot.extensions`를 추가하고, 데모 화면에서 공고별 확장 질문의 입력란을 동적으로 생성해 `/api/judge`와 `/api/assist`에 전달하도록 연결했습니다.
- 서버에서 확장 답변 문자열을 `parse_answer_for()`로 파싱한 뒤 프로필을 검증하도록 했습니다. 모델은 개입하지 않습니다.
- SW 기술자 등급 요건은 `extensions._sw_grade_judge`가 단독으로 판정하게 했습니다. 기존 화면의 고정 특급/고급/중급 입력은 제거했고, 일반 인력 요건은 기존 `staff` 판정 경로를 유지합니다.
- 기업규모 제한과 상호출자제한기업집단 제한이 한 요건에 함께 있는 경우에도 계열사 확장 답변을 실제 판정에 반영하도록 연결했습니다. 답변이 없으면 작은 기업도 `UNKNOWN`, 계열사이면 `UNSATISFIED`, 비계열사이면 규모 판정 결과를 유지합니다.

### 실제 공고의 수치 인식 실패 조사

- 변경 파일:
  - `apps/api/app/ai/normalization/numbers.py`
  - `apps/api/tests/test_clause_review_standard_diff.py`
- `R26BK01705963`의 `payment_period` 원문을 확인했습니다. 문언은 “용역계약일반조건 및 계약서 등에 따라 … 대가를 지급”으로, 지급기한 숫자가 없습니다. 다른 숫자를 끌어오지 않고 `UNDETERMINED`를 유지하는 것이 맞다고 판단해 회귀 테스트를 추가했습니다.
- `R26BK01716363`의 공사 지체상금 원문은 “지체1일당 1/1,000”입니다. 기존 정규화기가 `천분의 1`과 `%`만 지원해 실패한 것이 원인이었습니다.
- 슬래시 비율(`1/1,000`)을 백분율(`0.1%`)로 변환하도록 정규화기를 확장했습니다.
- 실제 캐시 문서를 다시 추출해 공사 지체상금이 `CHUNK-0315`, `0.1%`, `NEEDS_REVIEW`로 판정되는 것을 확인했습니다.

### 검증

- 저장소 내부 `.venv`에 `apps/api/requirements-dev.txt` 의존성을 설치했습니다. `.venv`는 Git 추적 대상이 아닙니다.
- 확장항목·판정·계약조항 관련 테스트: `52 passed`
- 최종 DB 제외 전체 회귀 테스트: `158 passed in 1.02s`
- `pytest` 캐시 쓰기 권한 경고를 피하기 위해 최종 실행에서는 `-p no:cacheprovider`를 사용했습니다.

### 남은 확인

- 실제 브라우저에서 동적 확장 입력란의 시각적 배치와 입력 UX를 수동 확인할 수 있습니다. 서버 판정 경로와 자동 테스트는 통과했습니다.

### 챗봇 온·오프 토글

- 변경 파일: `apps/api/app/ai/demo_web.html`
- 우측 하단의 원형 `?` 버튼을 상태가 명확한 `챗봇 켜기` / `챗봇 끄기` 토글로 변경했습니다.
- 토글 상태를 `aria-expanded`와 `aria-pressed`에 함께 반영했습니다.
- 끄면 패널만 숨기고 기존 대화 기록은 유지하며, 다시 켜면 질문 입력란에 포커스를 둡니다.
- `Escape` 키로도 챗봇을 끌 수 있고, 꺼진 상태에서는 질문 전송 함수를 실행하지 않습니다.

### 데모 화면 수동 검증

- `computer-use` 스킬로 실제 localhost 데모를 브라우저에서 조작했습니다.
- 챗봇 토글을 켰을 때 패널이 나타나고 입력란으로 포커스가 이동하며, 끄면 접근성 트리에서도 패널이 제거되고 대화 상태는 유지되는 것을 확인했습니다.
- 390×844 뷰포트에서 본문 가로폭은 375px로 가로 넘침이 없었고, 열린 챗봇 패널은 약 346px로 화면 안에 들어왔습니다. 확인 후 뷰포트 설정을 원래대로 복원했습니다.
- 기존 8200 서버가 이전 Python 코드를 들고 있어 종료하고 최신 코드로 재시작했습니다. 확인 후 새 서버도 정상 종료했습니다.
- 새 프로세스에서 세 캐시 공고를 UI로 다시 불러오지 못한 최초 원인을 조회 키 문제로 잘못 판단했습니다. 후속 점검 결과 `.env`의 `G2B_SERVICE_KEY`는 정상적으로 존재하고 `Settings`의 URL 디코딩 후에도 유효했습니다. 동일 조회를 샌드박스 밖에서 실행하자 `R26BK01716363`이 `CONSTRUCTION`으로 정상 조회됐으므로 실제 원인은 테스트 서버의 네트워크 샌드박스 제한입니다. 키 설정 문제라는 이전 기록은 이 문장으로 정정합니다.

### 참가자격 검색 골든셋 측정 하네스

- 추가 파일:
  - `apps/api/app/ai/goldenset/__init__.py`
  - `apps/api/app/ai/goldenset/fixtures.py`
  - `apps/api/app/ai/goldenset/spans.py`
  - `apps/api/app/ai/goldenset/scoring.py`
  - `apps/api/app/scripts/retrieval_report.py`
  - `apps/api/tests/test_goldenset_scoring.py`
  - `samples/golden/retrieval-v0.1/spans.json`
  - `samples/golden/retrieval-v0.1/README.md`
- 청크 ID가 아니라 공백을 제거한 원문 문자열 스팬으로 POSITIVE/TRAP 라벨을 매칭하도록 했습니다. 문서 ID도 함께 검사해 중복 PDF/HWPX가 서로의 정답으로 계산되지 않습니다.
- 청크 수, 중앙값 크기, 50자 미만 비율, 최대 크기 초과, 스팬 포함률, recall, precision, trap rate, 문자 예산 사용률, heading-only 비율과 스팬별 깔때기를 한 명령으로 JSON 출력합니다.
- 현재 깔때기의 `extracted`와 `canonical`은 결정적 검색 기준선에서는 `null`로 명시합니다. 이후 고정 모델 3회 결과를 입력받는 연결이 필요합니다.
- 첫 라벨은 캐시에 확실히 존재하는 `R26BK01705963`의 POSITIVE 4개와 TRAP 2개입니다. 일반화 목표인 8~10공고/60~90 POSITIVE/40 TRAP에는 아직 못 미치므로 README에 제한을 명시했습니다.
- 기준선 재현 결과: 328청크, 중앙값 56.5자, 50자 미만 47.26%, 1,800자 초과 46개, 최대 2,838자, 검색 4청크, recall 1.0, precision 0.25, trap rate 0.5, 예산 사용률 13.69%, heading-only 25%.
- 실행 명령: `python -m apps.api.app.scripts.retrieval_report --goldenset samples/golden/retrieval-v0.1 --retriever default --json`
- 최종 DB 제외 전체 회귀 테스트: `160 passed in 1.27s`.

## 2026-09-10

### 위험조항 목록 및 실제 구조화 샘플 팀 공유

- 당시 `RiskType`과 `RISK_TYPE_BY_RULE`로 불리던 9종 코드 목록을 확인했습니다. 최종 정정 후 명칭은 `CategoryCode`와 `CATEGORY_BY_RULE`입니다.
- 기존 8종에서 지체상금 상한(`LATE_PENALTY`)과 일별 요율(`LATE_PENALTY_RATE`)을 서로 다른 근거로 판정하기 위해 분리한 것이 9종이 된 이유입니다.
- 내부 검사 `warranty_bond_rate`는 개별 한글 `risk_type`을 유지하고 `category=WARRANTY_PERIOD`로 그룹핑합니다.
- 캐시된 실제 공사 공고 `R26BK01716363`의 `LATE_PENALTY_RATE` 구조화 결과를 재생성했습니다. 공고 `1/1,000` → `0.1%`, 시행규칙 기준 `1천분의 0.5` → `0.05%`, 판정 `NEEDS_REVIEW`를 확인했습니다.
- 팀 전달 문서: `docs/llm-rag/06-risk-types-and-structured-sample.md`

### 사업계획서 초안 생성 프로토타입

- 추가 파일:
  - `apps/api/app/ai/business_plan.py`
  - `apps/api/tests/test_business_plan.py`
- 변경 파일:
  - `apps/api/app/ai/demo_web.py`
  - `docs/llm-rag/SPEC.md`
- 새 엔드포인트 `POST /api/business-plan-draft`를 추가했습니다. 요청은 `context_id`, 기존 회사 프로필, 사업계획서용 사용자 추가 입력을 받습니다.
- 기존 `build_briefing()`과 `render_briefing_text()`를 그대로 사용해 판정·사유·공고 근거·계약조항·공고 요약을 모델의 사실 컨텍스트로 조립합니다.
- 모델이 양식을 즉흥 생성하지 않도록 사업 이해, 추진 전략, 조직·인력, 일정·산출물, 품질·위험, 제출 전 확인사항의 6개 Markdown 목차를 고정했습니다.
- 입력에 없는 실적·인력·인증·금액·일정은 생성하지 않고 `[담당자 확인 필요: ...]`로 남기도록 프롬프트 경계를 설정했습니다.
- 모든 응답에 `AI가 작성한 사업계획서 초안입니다. 제출 전에 담당자가 사실과 표현을 검토하세요.` 경고를 별도 `disclaimer` 필드로 반환합니다.
- 빈 추가 입력은 `EMPTY_INPUT`, 모델 미사용 환경은 `NARRATOR_UNAVAILABLE`, 호출 실패나 빈 응답은 `FAILED`로 열화합니다.
- 관련 단위·브리핑·확장항목 테스트: `29 passed in 0.88s`.
- 최종 DB 제외 전체 회귀 테스트: `164 passed in 2.99s`.
- 후속 수정: `.assist { display:flex }`가 브라우저의 기본 `[hidden]` 스타일을 덮어쓰던 문제를 발견해 `.assist[hidden] { display:none }`을 추가했습니다. 이제 토글을 끄면 챗봇 패널 전체가 실제로 사라집니다.

## 2026-09-11

### develop 변경사항 동기화

- `origin/develop`의 DB 연결 안정화 및 마이그레이션 010~012 변경을 `integration/llm-rag-validation`에 병합했습니다.
- 양쪽 브랜치가 `009_qualification_revalidation`에서 각각 갈라져 별도 마이그레이션 헤드를 만들고 있었으므로, 이미 적용된 revision ID를 변경하지 않고 `013_merge_develop_llm` 병합 마이그레이션으로 두 계보를 안전하게 합쳤습니다.
- `.claude/`는 사용자 로컬 파일로 판단해 추적하거나 수정하지 않았습니다.
- Alembic 단일 헤드(`013_merge_develop_llm`)와 전체 오프라인 upgrade SQL 생성을 확인했습니다.
- LLM/RAG 핵심 회귀 테스트는 `59 passed`입니다. API 전체 테스트는 기존 환경 의존 문제(외부 DB 접근, Windows 임시 폴더 권한·CP949, 골든셋 해시 불일치)만 재현됐습니다.

### develop 반영 전 프론트 연동 점검

- 제품 프론트 빌드와 기존 Case 상태 단위 테스트 3건은 통과했습니다.
- 백엔드 OpenAPI에서 `dropped_requirements`, 브리핑, 공고 요약, 챗봇, 사업계획서 초안 엔드포인트 및 `risk_type/risk_types/category/categories` 응답 스키마가 노출되는 것을 확인했습니다.
- 제품 프론트 `apps/web`에는 새 응답 타입과 호출·표시 로직이 아직 연결되지 않아, 기존 화면은 빌드되지만 신규 LLM/RAG 기능은 제품 화면에서 보이지 않습니다.
- 프론트 lint는 이번 변경과 무관한 기존 접근성·React compiler·타입 규칙 오류가 남아 있어 통과하지 않습니다.
- `develop`의 011 DB 마이그레이션에 있는 `category=코드`, `risk_type=표시문구`가 올바른 계약입니다. 런타임과 문서를 반대로 구현·기록한 오류를 확인했으며 복수 JSONB 컬럼만 후속 추가가 필요합니다.

### 위험조항 필드 의미 최종 정정

- 팀 기준을 `risk_type=대표 한글 라벨`, `risk_types=전체 한글 라벨`, `category=대표 오류 코드`, `categories=전체 오류 코드 JSONB`로 고정했습니다.
- 탐지기 생성 모델, 겹침 분류, 브리핑 응답, 데모 API와 화면, 테스트 및 연동 문서를 같은 의미로 수정했습니다.
- `CATEGORY_BY_RULE`, `CATEGORY_LABELS`, `CategoryCode`로 내부 명칭도 변경해 코드값을 `risk_type`으로 오인하지 않도록 했습니다.
- 마이그레이션 014에서 복수 JSONB 컬럼을 기존 단수값으로 백필하고 배열·비어 있지 않음·대표값 일치·9종 코드 제약을 추가했습니다.
- 위험조항·브리핑·분석 통합 회귀 테스트 `128 passed`와 Alembic 단일 헤드/오프라인 upgrade SQL 생성을 확인했습니다.
- 실제 데모 `POST /api/review-text` 응답에서도 `risk_type`은 한글 라벨, `category`는 오류 코드이고 각 복수 배열의 첫 원소가 대표값과 일치하는 것을 확인했습니다.
- 대표값의 `[0]`은 탐지 입력 순서가 아니라 판정 우선순위와 9종 코드 우선순위로 정렬한 결과의 첫 원소입니다. 동일 판정 결과를 역순으로 입력해도 고정 코드 순서가 유지되는 회귀 테스트를 추가했습니다.

### PR #104 품질평가 상태 회귀 수정

- `UNMAPPED_REQUIREMENT`는 판정 실패가 아니라 별도 표시할 공고 사실(`NOTICE_FACT`, `INFO`)이라는 현재 계약을 재확인했습니다.
- 운영 코드를 `PARTIAL`로 되돌리면 `test_notice_fact_diagnostic_does_not_degrade_analysis_status`와 제품 의미가 깨지므로, 오래된 품질평가 테스트 기대값을 `SUCCEEDED`로 수정했습니다.
- 품질평가 테스트에는 코드뿐 아니라 `kind=NOTICE_FACT`, `severity=INFO`까지 검증하도록 보강했습니다.
## 2026-09-11 — 실제 공고 라벨 검토 시안 1건 작성

- `qualification-real-v0.1`의 C01(`R26BK01705963`)을 대상으로, 기존 승인 데이터와
  섞이지 않는 `samples/golden/qualification-label-drafts-v0.1/` 초안 영역을 추가했다.
- 입찰 참가자격 원문 8건을 원문 block/paragraph 위치와 함께 정리하고, 그중
  canonical 8종 변환 후보 4건과 `UNMAPPED_REQUIREMENT` 후보 4건을 구분했다.
- 계약 위험조항 후보 5건에 `category/categories`, `risk_type/risk_types`, 예상 판정,
  확신도와 사람 검토 쟁점을 기록했다.
- 특히 지급기한 수치 없이 “대가를 지급함”만 있는 문장이 `PAYMENT_TERMS`로 탐지된
  사례를 낮은 확신도의 잠재 오탐으로 표시했다.
- 모든 항목은 `DRAFT`, `evaluation_eligible=false`, `review_decision=PENDING`으로 두어
  사람 승인 전에는 평가 정답으로 사용할 수 없게 했다.
## 2026-09-14 — PR #133 리뷰 반영

- 지역 꾸밈말에서 범용 `구` prefix 제거를 중단하고, 확인된 `구 광주광역시`만 명시적
  alias로 처리했다. `구미시`, `구리시`, `구례군` 원형 보존 테스트를 추가했다.
- frozen fixture 검증에 `summary.json.fixture_sha256`과 실제
  `fixture_bundle.json` SHA-256 교차검증을 추가하고 stale summary 회귀 테스트를
  추가했다.
- `golden-regression` workflow의 paths 필터를 제거해 `develop`·`main` 대상 모든
  PR에서 실행되게 했다. required status check 지정은 GitHub ruleset 관리 항목임을
  README에 명시했다.
- 게이트 설명과 출력의 `정답 일치`를 `초안 기대값 일치`로 정정하고, 보류 자체에는
  상한이 없지만 기준 일치 하락은 차단한다는 실제 정책을 문서화했다.
- 관련 테스트 `70 passed`; frozen 골든 회귀는 `초안 기대값 일치 110 / 보류 28 /
  잘못된 확정 0`으로 통과했다.
