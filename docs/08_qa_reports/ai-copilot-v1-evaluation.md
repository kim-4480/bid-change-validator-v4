# AI Copilot v1 — PR C/D 검증 보고

검증일: 2026-09-11. PR A #108 → PR B #109 → PR C #110 → PR D 순서의 stacked 변경이다.
자동 검증과 사람 평가를 구분한다. 자동 merge 및 다중 사용자 공개 승인은 포함하지 않는다.

## PR C 결과

- Commit: 90a0d8c — feat(copilot): share confirmed action lifecycle across views
- PR: https://github.com/gyuniverse-hq/bid-change-validator/pull/110
- 공통 ActionController가 패널, /ask-back, /changes, /qualification의 재검증 제안을 연결한다.
- true/false/null 초안, 서버 proposal, 명시적 확인, 저장 후 재조회를 공유한다.
- 저장 성공 여부 불명(OUTCOME_UNKNOWN)과 저장 성공·조회 실패(DONE_REFRESH_FAILED)를 구분한다.
- 결과 불명은 조회 후에도 자동 성공 처리·자동 재실행하지 않는다.
- qualification의 기존 전체 분석/판정 의미는 유지한다. 공통 작업 실행 잠금 시 '다시 검토'도 비활성화한다.
- 격리 DB 전체 Backend: **500 passed, 1 warning, 23.88s**.
- 기존 5개 golden hash 실패는 checkout CRLF 때문이었다. 아래 3개 파일을 Git HEAD LF 바이트로 복원했다. JSON 내용과 기대 hash 변경은 없고 Git 내용 diff도 없다.
  - profiles/synthetic.json
  - documents/synthetic.blocks.json
  - labels/synthetic.json
  - 공통 경로: samples/golden/qualification-quality-v0.1/
- 실제 confirm, replay 409, stale 및 중복 회귀와 요청 commit 실패 전 flush한 answer/run의 rollback을 검사했다.
- 브라우저에서 명시적 confirm 1회, 자연어 '응'의 confirm 0회, 저장 후 조회 실패/조회 재시도, replay 409를 확인했다.

## PR D 평가셋

파일: apps/api/eval/copilot_v1.json

- 단발 80개: 8개 작업 × 10개. dev 40 / holdout 40.
- 작업: 판정 조회, 확인 항목, 요건 근거, 당시 프로필, 변경 요건, 답변 제안, 재검증 제안, 문서 검색.
- 다회차 20개: 왜/순번/단일 focus, receipt 누락, 판정·분석·case stale, 순번 초과, 모호한 대상, false 입력, 자연어 동의, 부정, 부분 범위, 전체 재검증, 결과 조회 우선순위, 명시적 read, baseline/current stale.
- 모든 API 응답의 action 개수/유형, 의미 있는 answer/presentation, 단일 sources 매핑, citations metadata, reason refs, 외부 처리 없음도 검사한다.
- 공개 문서 10문항은 opt-in 없이 동의 안내까지만 검사한다. 실제 Retrieval/locator/빈 검색/외부 전송 범위는 기존 fake Embedding + FAISS 계약 회귀에서 별도 검증한다.
- 이 JSON은 최초 유효 실행 전에 고정했으며 수정하지 않았다.
- SHA-256 (LF bytes): **9a5677197689a3421ced2f1c217653958568d3cbd50500e34257496f1b8ff99c**

합성 데이터이며 기존 규칙을 아는 구현자가 작성했다. 독립 사용자 데이터나 완전히 보지 않은 blind holdout으로 주장하지 않는다.

| 그룹 | 최초 유효 실행 | 수정 후 재검증 |
|---|---:|---:|
| dev | 40/40 | 40/40 |
| holdout | 39/40 | 40/40 |
| 다회차 | 20/20 | 20/20 |
| 합계 | 99/100 | 100/100 |

최초 실패: holdout-profile-10, '저장된 회사정보' → PROFILE_SNAPSHOT을 기대했으나 ACTION_REQUEST 안내로 분류됐다. 저장/반영/재검증 명사가 있어도 실행 요청이 아닌 프로필 조회는 read로 처리하도록 조정했다. 실제 실행·부정 요청의 우선순위는 유지하고 변형 회귀 4건으로 검증했다.

**실패를 보고 코드를 수정했으므로 수정 후 40/40은 독립 holdout 성능이 아니라 노출된 고정 셋의 재검증이다.** 새 표현에 대한 일반화는 별도 독립 평가가 필요하다. 기대값이나 질문 문자열은 변경하지 않았다.

실행기 최초 시도에서는 Windows asyncio의 loopback self-pipe까지 차단해 100개 모두 실행 환경 오류가 났다. 이를 제품 평가 점수에 포함하지 않았다. 실행기는 DB Engine 연결을 차단하고 외부 네트워크를 차단하며 Windows 내부 통신용 loopback만 허용한다.

## D hardening

- chat.py: 실행 의도가 없는 프로필/회사정보 조회를 Action 안내가 가로채지 않게 했다. 판정/Action/confirm의 Product 계약은 변경하지 않았다.
- panel.tsx: 과거 답변의 근거 버튼은 그 응답의 receipt와 함께 문맥 의존 질의를 보낸다. 기존 문구는 receipt를 보내도 서버의 문맥 비교 경로를 타지 않았다. 오래된 판정은 STALE_CONTEXT로 복구되며 임의 focus를 적용하지 않는다.
- copilot-conversation.ts: 존재하지 않는 ref뿐 아니라 citation 누락·순서·실제 source metadata 불일치와 reasons/answer 불일치도 표시 전에 거부한다. JSON 객체 키 순서는 의미에 영향을 주지 않는다.
- qualification/page.tsx: 요건 상세 이동에 router.push를 사용해 layout 메모리의 초안/실행 상태를 보존한다.
- 회귀 검사: 잘못된 quote/version, 누락 citation, 잘못된 reason ref, 과거 receipt, 상태 잠금과 Drawer를 포함한다.

## 실행 결과와 재현

프로젝트 루트, 기존 Python 의존성이 설치된 환경:

~~~powershell
python -B -m apps.api.app.scripts.evaluate_copilot_v1
~~~

- --noconftest로 DB-seeding fixture를 제외한다. 실제 Chat API + fake Product read + 실제 propose_answer 경계를 사용한다.
- 100 passed / 5 deselected, 1 warning, pytest 3.15s (실행기 총 4.55s).
- deselected 5개는 별도 hardening 테스트이며 전체 Backend 실행에 포함했다.
- 네트워크·DB guard가 있는 이 실행기는 일반 테스트 DB 설정으로 fallback하지 않는다.
- 위 시간은 합성 API 계약 검사 시간이다. 실제 서비스 사용자 지연시간/LLM 성능 수치가 아니다.

전용 테스트 DB guard를 적용한 전체 실행:

~~~powershell
python -m pytest -q -p no:cacheprovider --tb=short --basetemp <fresh-test-temp> apps/api/tests
~~~

**605 passed / 0 failed, 1 warning, 22.76s**.
명령만 공용 DB 설정에서 실행해서는 안 된다. 이번 실행은 Docker의 테스트 목적 label, 전용 volume, loopback binding, DB identity marker 및 모든 Engine 연결의 목적지를 검사한 process-local bootstrap을 먼저 적용했다. 누락/불일치 테스트 URL은 거부했다. Supabase 및 수집기 DB는 사용하지 않았다. 이 bootstrap을 영구 CI guard로 구현했다는 의미는 아니다.

Web (apps/web):

~~~powershell
npx tsc --noEmit
node scripts/check-copilot.mjs
node scripts/check-copilot-actions.mjs
npm run build
~~~

통과. 변경 파일 oxlint 통과. **전체 UI lint는 기존 unrelated baseline debt가 남아 있으며 green으로 보고하지 않는다.** 규칙 억제나 unrelated 파일 수정 없음. Backend warning은 기존 Starlette/anyio deprecation이다. 빌드의 route classification 경고는 기존 vinext 제약이다.

브라우저 검사에는 PLAYWRIGHT_MODULE(설치된 Playwright 경로), COPILOT_TEST_URL(격리 UI의 합성 case URL)이 필요하다.

- check-copilot-browser.cjs: 실제 Backend read → 근거 → 기존 evidence 화면, 닫기/열기, 390px modal Drawer와 1440px non-modal panel, confirm 요청 0회. **통과**.
- check-copilot-outcome-browser.cjs: confirm을 API 전송 전에 abort → OUTCOME_UNKNOWN → read-only 재조회 후 잠금 유지 → qualification/changes 이동 및 Drawer 닫기/열기. **통과**, 실제 API write 0회.
- check-copilot-actions-browser.cjs: PR C에서 실제 저장·재조회 실패·복구 및 replay 검증. COPILOT_ALLOW_ISOLATED_WRITE=yes 추가 opt-in이 필요하다. 전용 테스트 API http://127.0.0.1:18000만 허용한다.
- 합성 fixture에서 남은 performance UNKNOWN에는 연결 evidence가 없다. 읽기 브라우저 검사는 순서상의 마지막 항목 대신 실제 근거가 있는 등록 요건을 선택한다. 근거 없는 요건의 결과를 만들어내지 않는다.

## 사람 평가 checklist / fixture

**사람 평가 미수행. 아래는 평가 준비물이며 합격 결과가 아니다.** 개발자 자동 브라우저 조작을 사용자 평가로 세지 않는다.
평가자에게 scenario의 첫 질문/대상만 제공하고, 답변 후 '지금 상태·그 이유 또는 이유를 모르는 이유·다음 행동'을 자신의 말로 설명하게 한다. 목표: 12개 중 최소 11개 이해, 안전 오류 0개.

| ID | 합성 상황/입력 | 확인할 이해·행동 | 실제 사람 결과 |
|---|---|---|---|
| H01 | insufficient_data + '참여 가능해?' | 참가 확정 아님, 확인 대상과 다음 행동 이해 | 미평가 |
| H02 | PARTIAL + '왜?' | 미분석 문서를 임의 추정하지 않음, 범위 한계 이해 | 미평가 |
| H03 | 등록 UNKNOWN + 사용자 답변 가능 | 회사정보 변경 없이 해당 검토 건에 답변하는 의미 이해 | 미평가 |
| H04 | unsupported 요건 | 입력 강제 대신 원문/담당자 확인 선택 | 미평가 |
| H05 | '두 번째 근거' | 자신이 본 두 번째 요건과 같은 원문·위치인지 확인 | 미평가 |
| H06 | stale receipt | 새 요건 자동 선택 없이 재조회/재선택 안내 이해 | 미평가 |
| H07 | false 충족 + false 증빙 | 미선택과 '아니요'가 다름을 인지 | 미평가 |
| H08 | proposal 표시 + '응' | 미저장임을 이해하고 명시적 확인 버튼 사용 | 미평가 |
| H09 | 전체 변경 요건 재검증 | 단일 요건 실행이 아님을 확인 | 미평가 |
| H10 | 저장 응답 timeout | 성공 여부 불명, 자동 재실행 금지 이해 | 미평가 |
| H11 | 저장 성공 후 조회 실패 | 저장 재시도 대신 결과 조회만 실행 | 미평가 |
| H12 | 모바일 panel + 화면 이동 | focus/초안 유지, 근거 이동, 닫기/열기 가능 | 미평가 |

각 평가에 evaluator/date/browser/viewport, 표시된 source/version, 기대·관찰·판단, 오류 재현 절차를 기록한다. 실사용 회사 데이터 대신 합성 데이터를 사용한다. 평가 완료 전 이해율 수치를 발표하지 않는다.

## 남은 Gate / 범위

- C/D 자동 검증 완료. 사람 이해도/접근성의 실제 사용자 평가는 미수행.
- 인증/권한: Copilot 및 같은 데이터를 읽고 쓰는 기존 API를 포함한 별도 공개 gate.
- layout 메모리 수명 내 복구만 지원. 새로고침/탭 종료 후 outcome 복구 미지원. 별도 탭/사용자의 실행은 서버 context/replay 검증에 의존한다.
- 기존 전체 분석 시작 흐름을 새로운 Copilot Action으로 재정의하지 않았다. 서버 전역 작업 lock이나 durable execution ID를 추가하지 않았다.
- 생성형 설명 노출, LLM intent 분류, private 데이터 외부 전송 추가 없음.
- 독립 holdout과 사람 평가 없이 제품 정확도 100%를 주장하지 않는다.
- 기존 원본 작업트리의 미커밋 UI·평가 파일과 exports/ 보존.
- merge는 미승인. 리뷰 순서: #108 → #109 → #110 → PR D.
