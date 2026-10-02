# v3.1 구현·재검증 보고서

작성일: 2026-09-14 KST. 최초 산출물인 [현재 상태 감사 보고서](01-current-state-audit.md)와 원본 `audit-evidence/`는 보존했다. 이 문서는 그 이후의 구현과 검사 결과다.

## 1. 결론과 완료 경계

**새 계약 → 읽기 도구 → 복합 조정자 → 생성·의미 검증 → API → 화면의 경로를 구현했다. W0~W6 전체 완료 또는 사용자 테스트 준비 완료로 판정하지 않는다.** 실제 DB, 검수된 Golden Core, 사람의 자유 질문 평가는 아직 실행하지 못했다. 실제 모델 검사에서도 복합 답변의 누락·반복·지연이 남는다.

과거 “47개 검사 통과”와 “W0~W6 완료”는 계속 **UNVERIFIED**다. 아래 신규 검사 수는 과거 주장의 증명이 아니다.

## 2. Git·환경·보존

- 작업 브랜치: `feature/ai-copilot-user-test-hardening`.
- 설계 응답 02를 포함한 동일 브랜치의 최신 변경을 fast-forward-only로 수신했다. 기준 HEAD와 원격 추적 HEAD는 `0c6968400a26f30ce1e1121a9afd752667b4ca97`. 실제 변경은 이 HEAD 위의 미commit 작업이다. 추적 파일만 집계하는 `git diff --stat`에는 신규 파일이 빠지므로 증거의 `source-manifest.json`도 확인해야 한다.
- 기존 stash 두 개(`02a630d4…`, `7481cba9…`)와 등록 worktree 한 개를 그대로 보존했다. 기존 venv, dist, 인덱스, 감사 파일도 삭제하지 않았다. main/develop 수정, 변경 병합 커밋, commit/push, 배포는 하지 않았다.
- 새 검증 환경 `.venv-copilot-v31`: Python 3.12.14, 저장소 개발 의존성 설치, `pip check` 통과. 기존 고장난 venv와 혼합하지 않았다.
- Node 24.14.0, pnpm 11.19.0. CI의 pnpm 10.15.0과 동일 버전 검사는 아니다. lockfile은 변경하지 않았고, 설치된 실행기를 직접 사용했다.
- `.env`의 DB는 공용 Supabase로 식별되어 접속하지 않았다. 사용자에게 별도 DB가 없음을 확인했다. 테스트에서는 DB URL을 loopback port 1로 바꾸고 `Engine.connect`를 차단했다. Windows TestClient 내부 socketpair용 loopback만 허용하고 외부 연결을 차단했다. DB seed를 실행하는 공통 conftest와 자동 플러그인은 비활성화했다.
- 실제 모델 평가 프로세스는 `.env`에서 API 키와 모델명만 사용하고 DB 접속을 별도로 차단했다. 합성 공고·회사 데이터만 보냈다. 자격증명은 보고서·로그에 복사하지 않았다.

## 3. W0~W6별 상태

| 단계 | 코드 상태 | 연결 상태 | 이번 검증 상태와 남은 일 |
|---|---|---|---|
| W0 고정 데이터·trace | PARTIAL | 합성 replay → 동일 coordinator; 실제 모델 runner 연결 | 합성 4턴 재생과 fixture/hash/usage 기록 존재. 실제 공고·회사·분석·판정의 동결 export 및 사람이 검수한 정답집은 없음 |
| W1 네 계약·어댑터 | PRESENT | v3.1 API에서 직접 사용 | 계약, owner/revision/scope, askability, 수동 인용, 저장 상태 불변 경계 PASS. 실제 DB adapter 통합은 BLOCKED |
| W2 대화 조정자 | PRESENT | `/api/v1/copilot/chat`의 `response_version=3.1` 분기 | 실제 ASGI 4턴(인증·도구·모델 대체), 명시 target/순번/오래된 target 거부 PASS. 실제 모델 복합 답변은 PARTIAL. 장기 압축 기억은 미구현이며 최근 12턴·100 target 제한 |
| W3 준비도·범위 RAG | PARTIAL | v3.1 도구가 기존 document_rag의 새 읽기 경계를 소비 | fingerprint/세대 고정/현재 섹션/예외 보완/Point QA 회귀 PASS. 실문서 20개 인덱스 재구축·전체 조건 coverage 평가는 NOT_RUN |
| W4 답변·인용·화면 | PRESENT | 기본 AI 상세 설명 요청 → v3.1 → EnvelopeAnswer | 의미 검증·유효 형제 주장 보존·부분 반환·집계 검사 PASS. 실제 Chrome 화면(모의 API) PASS. 실모델 전체 과업은 PARTIAL |
| W5 변경·가정·제안 | PARTIAL | 기존 변경 조회·제안 생성·확인 실행 API 재사용 | 이전/현재 scope 분리, baseline 변경 재확인, 가정 비저장, stale target 제안 차단 PASS. 실제 SQL lock/rollback/confirm/revalidation 통합은 BLOCKED |
| W6 통합 평가·발표 근거 | PARTIAL | 격리 runner·실제 모델 runner·브라우저 script | 실행 로그와 재현 명령 존재. 검수된 Golden Core/holdout·사용자 평가·실서비스 E2E는 NOT_RUN/BLOCKED. 출시·발표 완료 근거로 사용 불가 |

재사용: 기존 판정·profile snapshot·required checks·변경 diff·제안/확인 서비스, 문서 chunk/FAISS/hybrid 검색, 기존 UI action controller.

보완: askable 집계, 서버 scope 재확인, index fingerprint/readiness, target 연결, 새 화면 요청·렌더링.

신규: v3.1 네 계약, 프로세스 메모리 대화 저장소, 복합 계획/조정자, 주장 검증·한 번 복구, 명시적 세대 인덱싱 명령, 합성 replay/실모델 평가 runner.

## 4. 실제 호출 경로와 기본 설정

```text
apps/web/lib/copilot-conversation.ts
  AI 상세 설명 ON → response_version=3.1 + semantic header
  → copilot/router.py: authorize_case_access → chat_v31
  → conversation_state: owner/case/company/revision 확인
  → orchestration: TaskPlan + 기존 읽기 도구 조합
  → tool_adapters: 기존 제품 서비스 / document_rag.readiness
  → answer_validation: 생성 → 기계 검사·의미 검증 → 실패 주장 1회 수정·재검증
  → 현재 기준 재확인 → state commit → AnswerEnvelope
  → EnvelopeAnswer: 저장 상태·문장·인용·후속 target·부분 응답 표시
```

- UI의 AI 상세 설명은 기본 ON이다. 공고문 근거 답변은 별도 토글이며, target 선택이 이를 자동으로 켜지 않는다.
- v3.1은 인증된 사용자가 필요하다. 저장소는 1 worker 프로세스 메모리, 1시간 TTL, 256개 대화 제한이다. 재시작·만료 시 새 대화가 필요하다. 분산·다중 worker 지속 저장 완료로 해석하면 안 된다.
- claim/fact/source/target ID를 분리했다. requirement_key가 없는 MANUAL도 인용과 후속 조회가 가능하다. 모호한 순번·서로 다른 목록은 선택을 요구한다.
- 변경 제안은 기존 도메인 문법과 expected provenance를 사용한다. 채팅은 confirm API를 호출하지 않는다. 실제 저장은 기존 검토 화면의 실행 확인을 거친다.
- 기존 `legacy` API·화면 경로는 비교·호환을 위해 보존했다. 기존 legacy narrator의 D-02/D-03 의미 검증 문제가 전역 수정된 것으로 보고하지 않는다. 새 경로의 경계와 회귀를 별도로 검증했다. 이 브랜치는 배포하지 않았다.

## 5. Q-001 구현과 한계

- 서버 overall status·counts·provenance를 모델의 주장과 분리했다. 원문/확인사항 질문의 검증기에도 저장된 전체 판정을 전달한다.
- 생성된 결론·본문·주의·다음 행동의 사실 주장은 모두 동일한 검증 대상이다. 참조 존재/연결/scope 검사 후 수치·주어·단위·기간·AND/OR·예외·부정을 의미 검증한다.
- 최초 생성·검증은 2회, 실패 주장 수정·재검증을 포함해 품질 계층 최대 4회다. planner 최대 1회와 query embedding 최대 3회는 별도 trace에 남긴다. SDK retry=0, 호출당 입력 UTF-8 byte 기반 보수 상한 16,000, 출력 3,000, 턴 deadline 45초다.
- 성공한 형제 문장은 유지한다. 실패/미검증 산문은 내보내지 않고, 현재 검증된 source의 정확한 인용으로 부분 반환한다. 긴 인용은 원문을 누락하지 않고 나눠 출력한다.
- fact_id 사용만으로 전체 과업 PASS를 주지 않는다. 요청별 coverage, 조회된 fact 누락, 같은 의미 검증 호출의 필수 조건/예외 coverage를 함께 본다. 계획기 fallback·누락·검증 실패는 PARTIAL/FAIL이다.
- 동일 모델이 작성·검증하므로 독립적 정답 보증은 아니다. coverage도 모델 판단이다. 실사용 평가는 별도다. 반복 산문과 긴 응답의 복구 지연이 남아 있으며 Q-003에 기록했다.

## 6. Q-002 구현과 한계

- source AVAILABLE/PARTIAL/UNAVAILABLE/UNVERIFIED와 index READY/MISSING/STALE/CORRUPT/UNVERIFIED/BUILDING을 분리했다. build 예외는 명령 실패로 반환하며 장기 ERROR 작업 상태 저장소는 없다.
- 같은 version의 문서 집합·source/extracted hash·실제 blocks digest·extractor·chunk 설정·model/dimensions/index format을 fingerprint로 비교한다. null hash는 검증 증거가 아니다.
- 현재 DB 추출 metadata와 blocks digest를 확인한다. 매 질문마다 원본 bytes를 다시 다운로드해 hash를 대조하지 않으며 이 차이를 trace에 명시한다.
- READY Point QA는 기존 hybrid 검색을 사용하고 현재 source의 부모 섹션·인접 단락을 확장한다. broad 요청은 현재 확보된 전체 섹션, 특정 실적/공동수급 질문은 최대 2회 로컬 예외 보완 scan을 사용한다. 모든 업무 유형의 완전한 Coverage RAG가 검증된 것은 아니다.
- 새 채팅에서 build/document embedding/save를 실행하지 않는다. source를 읽을 수 있으면 stale index.records 대신 현재 source로 답한다. 오래된 세대는 보존한다.
- 명시적 사전 인덱싱은 `python -m apps.api.app.scripts.prepare_copilot_index --version <UUID> --index-root <별도 경로>`로 dry-run한다. 이 명령도 DB 조회를 하므로 승인된 DB에서만 사용해야 한다. 이번에는 실행하지 않았다.
- 실제 build는 dry-run fingerprint와 `--max-embedding-tokens`를 명시해야 한다. retry 없는 embedding, 불변 generation 생성·검증, active pointer 교체, O_EXCL 중복 build 잠금을 사용한다. process crash가 남긴 lock은 자동 삭제하지 않는다. 운영자가 실행 중인 builder를 확인하고 복구해야 한다. 실서비스 운영 복구 검증은 미실행이다.

## 7. 실행 결과

최종 실행 수치·비용·파일 연결은 같은 폴더의 `implementation-evidence/summary.json`과 아래 실행 증거에 기록한다.

최종 코드 기준의 [검사 요약](implementation-evidence/summary.json), [전체 미commit 코드 diff](implementation-evidence/implementation.patch), [소스 hash 목록](implementation-evidence/source-manifest.json), [Python 원본 로그](implementation-evidence/copilot-v31-final-tests-2.log), [브라우저 캡처](implementation-evidence/browser-final.png)를 함께 제공한다.

최종 실제 모델 실행 `194132Z`의 4턴은 **PARTIAL / PASS / PASS / PARTIAL**, 각각 **41.968 / 8.156 / 7.281 / 35.875초**였다. 기대 fact ID는 모두 포함했으나, 복합 답변의 의미상 범위와 복구 문제 때문에 전체 과업 PASS가 아니다. [원본 모델 trace](implementation-evidence/copilot-v31-live-20260913T194132Z/results.json).

| 검사 | 결과 | 범위 |
|---|---|---|
| 새/기존 Python 회귀 9개 파일 | **330 passed / 0 failed / 0 skipped** | 새 정상 venv, 외부 network/DB 차단. TestClient deprecation warning 1건 |
| 고정 합성 4턴 replay | **PASS** | 모의 판정·문서·모델, coordinator 실제 실행 |
| 실제 ASGI v3.1 4턴 | **PASS** | 실제 route/요청·응답 직렬화, 인증 의존성·권한 함수·제품 읽기·모델은 대체 |
| 실제 모델 의미 판별 7개 | **7/7 기대 일치** | 반대 판정·예외·숫자·OR 오류, 올바른 부정/말바꾸기, 근거 없는 등록증 단정. 합성 근거 |
| 실제 모델 4턴 | **PARTIAL** | 실제 planner/generator/verifier + 합성 읽기 도구. 최종 trace의 각 턴 결과를 확인해야 함 |
| 프론트 기존 독립 검사 2개 | **PASS** | client/view-model 및 target memory |
| TypeScript / 변경 파일 oxlint | **PASS** | 저장소 설치 실행기 직접 실행 |
| web production build | **PASS** | 기존 dist 보존을 위해 현재 소스를 별도 snapshot으로 복사. vinext beta route 분류 안내 존재 |
| 실제 headless Chrome 화면 | **PASS** | 실제 React panel + 모의 API. 2회 chat 요청, 인용, target/conversation/revision 전달, 문서 동의 유지, 새 대화. page error 0 |
| PostgreSQL 16 트랜잭션·Golden Core·사용자 평가 | **BLOCKED / NOT_RUN** | 별도 DB 및 검수 데이터·사용자 관찰 없음 |

브라우저 검사와 ASGI 검사는 각각 대체 의존성을 썼다. 이를 브라우저→실제 DB→실제 모델을 한 번에 통과한 E2E로 합산하지 않는다. `agent-browser` 실행기가 없어 번들 Playwright와 설치된 Chrome으로 화면을 검사했다.

초기 실모델 시도는 sandbox에서 APIConnectionError였다. 이후 승인된 network 실행에서 실제 usage를 확보했다. 초기 실패·중간 회귀 실패도 별도 로그로 보존하며 최신 PASS 로그로 덮어쓰지 않았다.

## 8. 비용과 재현

사용자가 허용한 모델 평가 한도는 **$10**이다. 각 dialogue 실행에 추가로 $0.50, 판별 실행에 $0.10 이하의 보수 한도를 걸었다. 실제 사용 모델은 `gpt-5.6-luna`다. 확인한 공식 단가는 input $0.20/M, output $1.20/M이며 reasoning token은 completion usage에 포함된다. [공식 모델 가격](https://developers.openai.com/api/docs/models/gpt-5.6-luna).

`summary.json`은 모든 보존된 시도의 usage 기반 비용과 usage가 없는 시도의 호출별 최대 비용을 합산한다. 실제 청구액은 아니다. 연결 실패에도 최대 비용을 계상하므로 보수 추정이다. **현재 검증을 위해 $10보다 많은 예산은 필요하지 않다.** 다음 병목은 격리 DB·검수 데이터와 답변 품질/지연이다.

이번 보존된 8개 실행의 합산 보수 비용 추정은 **$0.169586(약 $0.17)**이다. 모델 호출·reasoning usage·오류·경과 시간은 각 trace에 남겨 두었다. 원본 청구 내역을 조회한 금액은 아니다.

```powershell
# 저장소 루트, DB와 외부 모델을 차단한 회귀
.venv-copilot-v31/Scripts/python.exe scripts/verify_copilot_v31.py

# 별도 승인된 모델 예산 내에서만 실행. 합성 데이터, DB 차단
.venv-copilot-v31/Scripts/python.exe scripts/eval_copilot_v31_live.py --max-usd 0.50
.venv-copilot-v31/Scripts/python.exe scripts/eval_copilot_v31_live.py --max-usd 0.10 --verifier-only

# apps/web에서 실행
node scripts/check-copilot.mjs
node scripts/check-copilot-target-memory.mjs
node node_modules/typescript/bin/tsc --noEmit --incremental false
node node_modules/oxlint/bin/oxlint components/copilot/envelope-answer.tsx components/copilot/panel.tsx lib/copilot-api.ts lib/copilot-conversation.ts lib/copilot-v31.ts
```

## 9. Q-003 — 설계 대화에 전달할 쟁점

**제목:** 복합 답변의 실사용 완료 기준과 45초 안에서의 복구 우선순위.

**근거:** 실제 `gpt-5.6-luna` + 고정 합성 4턴에서 단일 예외/원문 질문은 답할 수 있었지만, 복합/후속 체크리스트 답변에 반복과 부분 반환이 발생했다. `193335Z` 및 `193821Z` 실행은 마지막 턴 45초에서 재검증이 시간 초과했다. 원문 source 하나를 인용해도 질문에 필요한 모든 조건을 설명한 것이 아니므로, coverage 검사로 PARTIAL을 유지했다. 합성 fixture에는 실제 회사 실적·일정·제출서류 전체가 없어 데이터 부족과 계획 범위 확장을 구분할 필요도 있다.

**대안 A:** deadline/토큰/복구 횟수를 늘린다. 느린 답변·비용은 늘고 실제 근거 부족은 해결되지 않는다.

**대안 B:** 현재 안전 상한을 유지하고, 사람이 검수한 실제 고정 공고·회사 bundle에서 필수 답변 범위를 먼저 고정한다. 계획의 불필요한 확장과 반복을 줄이고, 하위 요청별 누락과 지연을 함께 평가한다. 근거 부족과 검증 실패를 구분하여 부분 답변을 유지한다.

**권장안:** B. 검증을 끄거나 safe partial을 PASS로 바꾸지 않는다. 운영 예산 확대 전에 격리 PostgreSQL 16 및 실제 고정 데이터·기대 조건을 확보하고 Core/사용자 평가를 수행한다. 초기 p50 8초/p95 20초 목표는 아직 달성·입증되지 않았다. 4턴 표본으로 운영 백분위 성능을 주장하지 않는다.

**현재 처리:** 상한은 변경하지 않았다. 신규 의미 coverage·상태 문맥·target 경계를 구현했으며 남은 품질 문제를 완료로 올리지 않았다. 이 질의는 사용자가 설계 대화에 전달할 수 있는 문서이며 자동 전달하지 않았다.
