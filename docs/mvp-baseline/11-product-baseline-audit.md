# Product Baseline 최종 점검 — 2026-09-08

문서 동기화 기준: PR #74 코드 `87b9a5f`, 2026-09-08, Draft/merge 전. 구현과 아래 테스트 결과는 해당 코드 기준이며 이번 문서 갱신에서 재실행한 결과가 아니다. 현재 화면은 [03](03-screen-system-map.md), 검증 요약은 [05](05-e2e-golden-path.md), 후속 담당 작업은 [08](08-team-handoff-current-state.md)에 연결한다.

## 1. Executive Summary

**이번 변경은 안전성 보강 PR이며, Product Baseline Ready 선언은 보류한다.**
원문 일부만 일치해도 추출을 승인하던 문제, PARTIAL 분석의 Ask-back 후 참가 가능 승격,
복합 원문의 단순 인증 매핑, 업종 부분문자열 비교, 원문 변경을 놓치는 Diff,
화면의 최신 분석/오래된 판정 혼합을 수정했다. LLM 추출과 deterministic Rule 판정의 분리는 유지했다.

Backend 102개, 프런트엔드 데이터 연결 회귀 3개, 타입 검사, 수정 파일 lint, build가 통과했다.
실제 공고의 PARTIAL 분석 → Evidence 확인 → UNKNOWN 판정 → unsafe answer 거절까지 확인했다.
그러나 실제 자격요건이 의미 있게 바뀐 G2를 확보하지 못했고, 실제 공고에서의 추출 완전성도 부족하다.

## 2. 현재 Product Baseline 완성도

| 구간 | 확인 결과 | 완료 판단의 한계 |
|---|---|---|
| 회사 → 공고 → Case → 분석 → Rule | 연결되어 있으며 실제 API 호출 확인 | 실제 공고 추출 품질은 PARTIAL/FAILED |
| UNKNOWN → Ask-back → USER_ANSWER | G0/API 회귀 통과, 실제 unsafe 답변 422 | 실제 G1에는 안전한 답변 대상이 없어 긍정 답변은 G0에서 검증 |
| Evidence | 실제 인용문, 파일·추출문 해시, 문서 이동 확인 | 표 문맥·인접 조건 의미까지 입증하는 것은 아님 |
| 변경 Requirement → affected-only | 합성 G0와 원문 변경/키 재배열 회귀 통과 | meaningful 실제 G2 미확보 |
| 01~07 | 브라우저 클릭 이동·Case 유지·원문·실패/빈 상태 확인 | 성공 답변부터 실제 변경까지의 전체 Human Click E2E는 미완료 |
| 평가 대응 | 전용 추출 미지원 명시, 자격요건을 참고자료로 구분 | EvaluationCriterion 전용 추출은 후속 작업 |

통합 계약과 안전한 보류 동작은 마련되었다. 처음 정의한 “하나의 실제 제품 시나리오가 변경공고까지 통과” 조건은 아직 충족하지 못했다.

## 3. Audit findings

아래 경로는 저장소 기준이다. “수정”은 이 PR 내 조치이며, 전체 제품에 결함이 없다는 뜻이 아니다.

### P0 — 수정한 결함

| 문제와 재현 근거 | 영향 | 파일/함수 및 해결 | 검증 |
|---|---|---|---|
| raw 앞 40자만 실제 원문과 같으면 조작된 뒷부분도 승인 | 근거 없는 조건 생성 | `apps/api/app/ai/requirement_extraction.py::_find_source_chunk`: 공백 정규화 후 전체 raw 일치, 세부 원문 검증 유지 | `test_requirement_extraction.py` fabricated suffix 회귀 |
| accepted + rejected 추출을 ok로 처리; PARTIAL의 마지막 UNKNOWN에 Yes 답변 후 eligible | 미추출 조건이 있는데 참가 가능 표시 | `analysis_result.py`, `judgment.py::derive_overall_status`, 초기/대상/Ask-back/Matching/재검증 호출부에 analysis_status 전파 | `test_analysis_pipeline.py`, `test_product_baseline_regression.py`: PARTIAL은 답변 후에도 insufficient_data |
| 복합·법적 raw를 generic 인증으로 매핑하면 PROFILE 비교로 충족 가능 | Ask-back만 막아도 형제 경로에서 오판정 | `askability.py::unsafe_clause_reason`을 `legacy_slots.py`, `judgment.py`에서도 사용. 상동기호/표 참조도 보류 | 복합 인증 PROFILE 회귀 및 실제 `4. 인허가중급1〃` 회귀 |
| INDUSTRY 1426과 11426을 부분문자열로 일치 처리 | 다른 업종 보유 기업을 충족 처리 | `judgment.py`: 업종 코드/명 정규화 후 정확 비교 | `test_qualification_judgment.py` |
| 동일 key/type/canonical이면 raw의 예외 추가도 UNCHANGED | 변경된 조건에 USER_ANSWER 승계 | `requirement_diff.py`: raw를 판정 비교에 포함, 고유 의미 일치 우선 후 key fallback | 원문 예외 추가 MODIFIED, 키 순서 교환 UNCHANGED 회귀 |
| 다른 baseline analysis 또는 바뀐 reference_date로 unchanged 판정 복사 | lineage와 판정 기준 혼합 | `qualification_revalidation.py`: source 분석 일치, 동일 기준일/Rule, 최신 baseline judgment, profile snapshot 검증 | API baseline 불일치/기준일 변경 회귀 및 기존 G0 |
| 최신 analysis + 이전 judgment를 한 화면에서 표시 | 질문·Evidence·판정이 서로 다른 실행 참조 | `apps/web/lib/case-workspace.ts`와 02~06: version/company/analysis 일치, 구 Rule 결과 숨김, 질문은 current judgment | Node 회귀 3개, 실제 브라우저 Case 탭 이동 |
| 평가 화면에서 자격조건을 평가항목처럼 표시 | 평가 의미 오해 | `apps/web/app/evaluation/page.tsx`: 참가자격 참고자료로 명시하고 전용 추출 부재 표시 | 브라우저에서 점수 미예측·추출 미지원 문구 확인 |

### P1 — 수정한 결함

| 문제/영향 | 파일·조치 | 검증 |
|---|---|---|
| 오래된 source로 답변하면 다른 답변 결과를 덮어쓸 수 있음 | `qualification_ask_back.py`: Case 행 잠금, 최신 source/analysis/Rule, 회사/profile snapshot 확인 | 반복된 오래된 source 제출 409, 회사 인증 목록 불변 |
| 다른 Case로 이동 중 늦은 fetch가 화면을 덮음 | `case-workspace.ts`, 02~06: 요청 세대 확인 및 Case별 컴포넌트 상태 분리 | loader regression, 잘못된 UUID가 다른 Case로 fallback하지 않음 |
| 문서 탭 변경 시 이전 문서 원문/근거 잔류 | `evidence/page.tsx`: 문서 ID에 연결한 로드 상태, 취소 처리, document/block 범위 강조 | 실제 HWPX → PDF 문서 이동 및 Evidence deep link |
| notices/Matching에서 다른 회사·차수의 Case 재사용 | `notices/page.tsx`, `cached-notice-matches.tsx`: company/current version 일치 조건 | 코드 경로 확인, 실제 분석 완료 후보 목록 API 200 |
| 숫자 연산자/유효값 없이 Askable | `askability.py`: 지원 연산자·유한 비음수 수치 검증 | operator/value 회귀 |
| 실적 분야 무시·미래 실적 포함·합산 기준 불명확 | `legacy_slots.py`, `judgment.py`: 분야/기간 전달, 미래일 제외, 합계/최대에 따라 결론이 달라지면 UNKNOWN | 분야/미래 실적 회귀 |
| 다른 문서 라벨로 출처 검증; 원문 뒤쪽의 실제 조항번호는 탈락 | `requirement_extraction.py`: 실제 raw가 있는 chunk의 라벨/줄 시작만 검증, LLM 라벨 합성 금지 지시 | 실제 2-1-1 라벨 및 다른 chunk의 9번 라벨 거절 회귀 |
| 존재하지 않는 분석 ID가 판정/재검증에서 서버 오류로 새어 나감 | `qualification_judgment.py::load_judgment_analysis`에서 오류를 기존 서비스 오류로 변환하고 초기/대상/Ask-back/재검증에서 재사용 | 두 POST 경로 모두 `ANALYSIS_RUN_NOT_FOUND` / HTTP 404 회귀 |
| 문서별 참가자격 영역이 누락되거나 입력이 잘려도 완전 분석처럼 보임 | 문서별 anchor와 다른 문서의 보조 키워드, 선택 원문 32,000자 잘림 diagnostic | 문서 경계/부분 추출 회귀 |

### 남은 P0/P1

- **P0, 제품 동결 조건:** 실제 meaningful G2 미확보. 코드로 만든 변경이나 시간·가격 변경으로 대체하지 않는다. 아래 후보 표를 바탕으로 DB/Data가 수집 범위를 확장해야 한다.
- **P1, LLM/RAG:** 실제 문서의 표 역할·인원 필드, 중복 chunk, 주변 예외 문맥, 긴 문서 선택의 recall 문제. 이번 보수적 차단은 잘못된 성공을 줄이지만 구조화 개수를 늘리는 해결은 아니다. `requirement_extraction.py`, `legacy_slots.py`를 실제 라벨링 세트의 precision/recall과 함께 고도화해야 한다.
- **P1, Frontend:** 전체 lint는 기존 접근성/React Compiler 오류 27개로 실패한다. `components/ui/*`, `components/product/profile-records-manager.tsx`, `hooks/use-mobile.ts`, `app/company/{layout,page}.tsx` 등은 승인 범위 밖이므로 고치지 않았다. 실제 프로필 변경 후 화면의 과거 판정/현재 회사값 표시 방식도 추가 검증해야 한다.

### P2 — 담당자 고도화

- Matching/공고 목록의 공고별 query/fetch 비용: 현재 bounded candidate 범위에서 작동하지만 N+1은 남아 있다. 요청 수·DB 쿼리 수를 측정한 후 batch로 개선한다.
- Evaluation 전용 추출/Contract 연결, USER_ANSWER의 명시적 profile promotion(Policy B), 후보 ranking은 후속 기능이다.
- 02 대형 컴포넌트 전면 분해는 하지 않았다. 중복 workspace fetch만 공통 loader로 줄였다.
- CaseHeader의 역사 차수 원본 링크·요약 표시, Evidence 자동 스크롤, 모바일/키보드 전체 탐색은 추가 검증 대상이다.

## 4. 실제 수정한 내용

- Rule 버전 `qualification-rules-v0.2`. 과거 판정은 DB에 남기고 화면에서 현재 Rule 결과로 재사용하지 않는다.
- 초기/부분/Matching/변경 재검증 모두 동일한 분석 완전성 규칙을 적용한다. PARTIAL이라도 필수 그룹이 확정 미달이면 ineligible, 그렇지 않으면 insufficient_data를 유지한다.
- 원문 전체 인용 검증, 문서별 선택, source-local 조항번호, 추출 누락/잘림 diagnostic을 보강했다.
- Case 기준 행 잠금과 source freshness 검증, source 분석/기준일/profile 보존으로 부분 재판정의 전제를 고정했다.
- current analysis에 연결된 judgment와 questions만 표시한다. 없는 Case/차수는 오류로 남긴다.
- 문서/Evidence 상태 및 다른 Case 선택의 URL을 연결하고, `evidence_held`를 Yes 답변만으로 true로 만들지 않는다.

### 기존 AnalysisRun과 merge 후 재분석

Rule `qualification-rules-v0.2`와 AI contract `ai-analysis-v0.2`는 별도다. 기존 AnalysisRun은 동일 contract/SUCCEEDED라는 이유만으로 강화된 전체 raw grounding·source-local reference·상동 guard를 자동 충족하지 않는다. 자동 validation revision/cache 무효화는 미구현 P1이며 과거 run은 보존한다.

PR #74 merge 이후 기존 Demo/Golden Case의 baseline/current 모두 **full re-analysis**하고 새 분석으로 판정/재검증해야 한다. Rule 재판정만으로 과거 추출을 정정할 수 없다. Backend 코드 변경 후 `docker compose up -d --build api`가 필요하다. 실행 순서와 기록할 identity는 [06 운영 절차](06-handoff-and-merge.md)를 따른다.

## 5. 수정하지 않은 내용과 이유

DB schema/migration, API endpoint 명세, main/develop, 핵심 7개 IA를 변경하지 않았다.
회사 프로필 자동 승격, 예상 심사점수, 외부 배포/자동 merge도 수행하지 않았다.
루트의 기존 untracked `package.json`, `pnpm-lock.yaml`은 이 PR에 포함하지 않는다.
추가 UI 컴포넌트 수정은 사용자에게 승인받은 파일 범위 밖이다. HTTP 분석 조회 오류는 승인된 공통 서비스에서 처리하여 router 파일을 수정할 필요가 없었다.
Figma `7:45` 직접 대조는 Figma 도구의 사용량 제한 때문에 완료하지 못했다. 7개 route/5개 탭은 저장소와 실제 화면으로 확인했다.

## 6. 테스트 결과

| 검사 | 결과 | 보장 범위 |
|---|---|---|
| 전체 Backend | **102 passed**, Starlette/AnyIO deprecation warning 1 | Rule, 분석, API/DB, G0, 새 회귀 |
| Frontend Node regression | **3 passed** | current/source identity, stale result 배제, 잘못된 Case/차수 |
| `pnpm exec tsc --noEmit --incremental false` | 통과 | 정적 타입 |
| 수정 파일 대상 `pnpm exec oxlint ...` | 통과 | 이번 프런트엔드 변경 |
| `pnpm build` | 통과 | vinext 5단계; route 정적 분류 Unknown 경고 유지 |
| `pnpm lint` 전체 | 실패, 기존 오류 27개 | 전역 lint green으로 보고하지 않음 |
| `git diff --check` | 통과 | 공백 오류 |
| Docker API rebuild | 성공 | source bind가 아닌 새 이미지 적용 |
| 브라우저 | 01~07 navigation smoke 통과 | 실공고 E2E 전체 완료와 구분 |

PR #74 [CI #58](https://github.com/gyuniverse-hq/bid-change-validator/actions/runs/34178537233)도 성공했다. CI는 fresh PostgreSQL/migration/Backend pytest와 Frontend install/non-blocking 전체 lint/build를 실행한다. Node 3개·tsc·수정 파일 lint는 별도 로컬 검사다.

최종 Backend 전체 실행은 `codex_baseline_audit_20260908` DB를 별도로 사용했다.
`DATABASE_URL` 설정 후 `get_settings.cache_clear()`를 호출하고, import된 engine의 DB명을 assert하여 대상이 맞는지 확인했다.
기존 G0의 seed/cleanup을 재사용했으며 실제 수집 공고를 합성 fixture로 덮어쓰지 않았다.

재현 명령(저장소 루트, PowerShell; 테스트 DB는 기존 migration으로 초기화 필요):

```powershell
@'
import os, sys
from sqlalchemy.engine import make_url
from apps.api.app.config import get_settings
os.environ['DATABASE_URL'] = make_url(get_settings().sqlalchemy_database_url).set(database='codex_baseline_audit_20260908').render_as_string(hide_password=False)
get_settings.cache_clear()
from apps.api.app.database import engine
assert engine.url.database == 'codex_baseline_audit_20260908'
import pytest
sys.exit(pytest.main(['-p', 'no:cacheprovider', '-q', 'apps/api/tests']))
'@ | .\.venv\Scripts\python.exe -B -X utf8 -
node --test apps/web/tests/case-workspace.test.cjs
```

## 7. Golden Scenario 결과

### G0 — 통과

기존 `test_mvp_golden_e2e.py`의 PROFILE → UNKNOWN → USER_ANSWER → 실적 4억→6억 변경 → affected-only 흐름을 유지했다.
새 API 회귀는 PARTIAL 승격 방지, unsafe answer, stale answer, profile 비반영, baseline/기준일 불일치를 검증한다.
G0는 합성 Canonical/DB 회귀이며 실제 LLM 및 Evidence grounding을 증명하지 않는다.

### G1 — 실제 경로/보류 동작 확인, 품질 완료 아님

- 공고: `R26BK01687395`, 가덕도신공항 여객터미널 및 부대건물 설계단계 건설사업관리용역.
- Case: `8b09a545-060a-4e4c-b7f5-f29bf6eeeb1c`.
- 실제 Analysis: `33607976-4c9f-4229-bfdb-8a1997354cbc`, PARTIAL, Requirement 2 / Evidence 2.
- 최종 규칙 Judgment: `32630bb4-3a1c-4a3e-9b9a-c21f3c56c572`, UNKNOWN 2, `insufficient_data`.
- `REQ-002-EVD`, `REQ-011-EVD`의 전체 인용문이 추출 원문에 존재하고 file SHA/text SHA가 DB 문서와 일치했다.
- Askable 0 / Not-askable 2. 두 항목 모두 강제 Yes 제출 시 HTTP 422 `REQUIREMENT_NOT_ASKABLE`.
- 실공고에서 발견한 `〃` 표 참조는 마지막 공통 guard에 반영했다. 위 분석은 그 guard 추가 전에 저장된 실행이며, **기존 저장 요건도 최종 Rule/Ask-back에서 차단됨**을 확인했다. 새 Mapping은 같은 raw를 UNMAPPED로 남긴다.
- 다른 실공고 `R26BK01689803` 분석은 FAILED/0건. 복합 지역·업종 대안·법률 조건을 강제 판정하지 않았다.
- `/companies/{id}/notice-matches` 200; 분석된 현재 공고 5개가 반환되는 것을 확인했다. 미분석 공고는 별도 조회 목록에 남는다.

브라우저에서 공고 찾기 → 검토 → 확인 필요 → 근거 → 평가 → 변경 → 회사 프로필을 클릭했다.
같은 Case의 5개 탭 URL, 실제 HWPX/PDF 원문 전환, Evidence deep link, PARTIAL/FAILED, 분석 필요, 최초 차수, 없는 UUID 오류를 확인했다.
실제 safe Yes 답변은 이번 G1에서 실행하지 않았다. 안전한 항목이 없는데 질문을 만들지 않았다.

### G2 — 미완료

전체 로컬 다차수 후보 10건의 각 차수 문서 수·해시·추출 텍스트 차이를 확인했다.
source_field 이동은 파일명/해시로 다시 대조하여 파일 재배치를 조건 삭제로 오인하지 않았다.

| 공고 | 차수 | 관찰 | Golden 판단 |
|---|---|---|---|
| R26BK01715087 | 1→2→3→4 | 설명회 미개최 안내 추가, 제출 시작 13:00→14:00→14:30, v3/v4 추출문 동일; RFP 동일 | meaningful 자격변경 없음 |
| R26BK01715236 | 1→2 | 취소공고, 현재 문서 0 | 비교 가능한 현재 자격원문 없음 |
| R26BK01715042 | 1→2 | 취소공고, 현재 문서 0 | 동일 |
| R26BK01715257 | 1→2 | 취소공고, 현재 문서 0 | 동일 |
| R26BK01715375 | 1→2 | 예정가격 범위 ±2%→±3% | 자격조건 변경 아님 |
| R26BK01715394 | 1→2 | 취소공고, 현재 문서 0 | 비교 가능한 현재 자격원문 없음 |
| R26BK01715477 | 1→2 | 낙찰하한율 88%→90%, 시간 11:00→12:00, 중복 PDF 1종 감소 | 자격조건 변경 아님 |
| R26BK01715691 | 1→2 | 양 차수 문서 0 | 확인 불가 |
| R26BK01715492 | 1→2 | 취소공고, 현재 문서 0 | 확인 불가 |
| R26BK01716110 | 1→2 | 기존 5종 추출 해시 모두 동일, 보험대상 XLSX 추가(텍스트 미추출), 특수조건 source_field 이동 | 자격변경 입증 못함; XLSX 내용 별도 확인 필요 |

1순위 후보의 실제 v1/v4 분석도 실행했다:
`8bc9a4c4-3e5f-41ff-9f42-c87a7336fa3f` / `b381b971-b70b-43f6-8d4f-45f9d05870b6`, 모두 FAILED/0건.
두 실행은 source-local 조항번호 개선 전 결과다. 원문 비교에서 이미 meaningful 자격변경이 확인되지 않아 성공 Golden으로 쓰지 않는다.
빈 분석 두 개의 diff를 “변경 없음 검증 성공”으로 계산하지 않았다. 실제 affected-only 완료도 주장하지 않는다.

## 8. 남은 리스크

정규식 guard는 언어의 모든 복합 조건을 판별하지 못한다. 짧은 raw만 추출하면 주변 조건을 잃을 수 있으므로 실제 라벨링과 문맥 연결 검증이 필요하다.
raw 변경은 보수적으로 MODIFIED가 되어 문구만 달라진 항목까지 재검증할 수 있다. 현재는 잘못된 USER_ANSWER 승계를 피하는 쪽을 택했다.
단일 32,000자 입력 상한과 문서별 selector는 완전한 문서 recall을 보장하지 않는다.
행 잠금과 stale 검사는 순차 회귀로 확인했으며 동시 부하 테스트를 수행한 것은 아니다.
계정/권한, 외부 운영 배포, 모든 브라우저/모바일, Figma 픽셀 일치는 이번 결과로 보장하지 않는다.

## 9. 팀원별 Handoff

| 담당 | 다음 작업 | 유지할 계약 |
|---|---|---|
| Frontend | 기존 접근성 lint, profile 갱신/역사판정 표현, 모바일/키보드 E2E | 7개 IA, 02~06 같은 Case·current analysis/judgment |
| Backend | AnalysisRun validation revision/cache 정책, 실제 동시성 검증, Matching query 측정 | PARTIAL 전파, source lineage, USER_ANSWER Policy A |
| DB/Data | 실제 지역/업종/실적 조건 변경 원문 쌍 확보; 보험 XLSX 확인 | NoticeVersion 보존, 문서 해시·출처 |
| LLM/RAG | 표/라벨/인접 예외의 실제 라벨링 회귀 및 recall 개선 | LLM은 추출·매핑, 불확실하면 UNMAPPED/PARTIAL |
| Integration | PR #74 merge 후 기존 Demo/Golden full re-analysis, G1 safe-answer + 실제 G2 전체 클릭 E2E 후 동결 재평가 | build/tests 외 제품 완료 조건 별도 확인 |

연결된 ChatGPT 작업 **integration mvp baseline 진행중**에 진행 상황과 G2 한계를 공유했고, 확인되지 않은 G2를 완료 처리하지 않는 방향을 교차 확인했다.

## 10. Branch / commit / PR

- 기준: `integration/mvp-baseline`, `b048a10e3ab9093af9c4570a1ef82cc35918439e` (push 전 원격 재확인).
- 작업: `fix/product-baseline-audit`.
- Backend: `c0bec5f` — conservative decisions / revalidation lineage.
- Frontend: `4df4424` — current analysis/judgment workspace binding.
- 최초 audit 보고서: `a2942c6`.
- PR: [#74](https://github.com/gyuniverse-hq/bid-change-validator/pull/74), 대상 `integration/mvp-baseline`, Draft, 자동 merge하지 않는다.
- 후속 오류 처리 커밋: `87b9a5f` — 승인된 서비스 파일만 사용해 missing analysis 오류를 HTTP 404로 통일하고 회귀 2개를 추가했다.

## 11. Merge 가능 여부와 원래 목적 평가

**보강 변경을 검토할 수는 있지만, Product Baseline 동결/Ready 목적의 merge 승인은 보류한다.**
변경 범위의 검사 결과는 통과했고 API/schema를 재설계하지 않았다. 원문 안전성·판정·화면 identity가 개선되어 각 담당자가 공통 계약을 지키며 고도화할 토대는 강화됐다.
다만 실제 G2, 실제 safe-answer 포함 전체 클릭 흐름, 추출 품질과 남은 P1을 확인하기 전에는 처음 정의한 Integration Baseline 목적을 완전히 충족했다고 평가할 수 없다.
