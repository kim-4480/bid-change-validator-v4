# Codex 인계 00 — 이전 작업 복구·재검증 기준

작성일: 2026-09-14 (한국 시간)  
대상: `gyuniverse-hq/bid-change-validator` / `feature/ai-copilot-user-test-hardening`  
문서 성격: **인계 상태 정정과 착수 지침. 구현 완료 보고서 또는 테스트 통과 보고서가 아니다.**

## 1. 가장 먼저 적용할 정정

> 이전 ChatGPT 보고의 “47개 격리 검사 통과”와 “W0~W6 관련 코드 작성”은, 이번 인계 조사에서 해당 코드 버전·실행 명령·테스트 목록·원본 로그를 연결해 확인하지 못한 **미검증 주장(UNVERIFIED)** 이다. 완료 사실로 인계하지 않는다.

이는 검사가 실패했다거나 작업물이 반드시 없다는 뜻도 아니다. 근거 부족과 실패를 구분한다. 기존 파일을 무조건 삭제하거나 처음부터 다시 만들지 말고, 로컬·원격 코드와 실행 결과를 조사한 뒤 재사용·보완·신규 구현을 결정한다.

**47은 맞춰야 할 테스트 개수가 아니다.** 기존 검사 47개를 찾지 못하면 그 사실을 기록하고 현재 코드에 필요한 검사를 새로 구성한다. 신규 검사 통과를 과거 47개 실행의 소급 증명으로 사용하지 않는다.

## 2. 이번 인계에서 확인한 범위

### 2.1 문서 추가 전 원격 기준선

| 항목 | 확인값 | 해석 |
|---|---|---|
| feature HEAD | `9765ebaf8e4aad213a7d4953ee0482565592c108` | 이번 인계 문서 추가 직전에 GitHub ref를 다시 읽어 확인 |
| develop HEAD | `b9153a534a631329ac3082afd20c624f5af6ab22` | 비교 API의 base commit |
| 공통 조상 | `81f101934608dd880f6ef1a633558b523c82ee6e` | 비교 기준 |
| 비교 결과 | feature 14 ahead / 2 behind, feature 측 변경 파일 10개 | 아래 목록은 공통 조상 이후 feature 측 변경. 양쪽 변경을 모두 나열한 2-way diff가 아님 |
| 해당 feature HEAD의 Actions 실행 | 조회 결과 `total_count=0` | 그 SHA의 CI green을 확인한 것이 아님. 다른 SHA·로컬 실행의 존재 여부는 별도 |

위 SHA는 **문서 작성 전 스냅샷**이다. 이 문서의 commit으로 브랜치 HEAD가 이동하므로 Codex는 시작 시 다시 fetch하고 실제 HEAD를 기록한다. 고정 SHA로 강제 reset하지 않는다.

### 2.2 원격에서 확인한 기존 변경 파일

```text
apps/api/app/copilot/narration.py
apps/api/app/copilot/product_tools.py
apps/api/app/copilot/router.py
apps/api/tests/test_copilot_narration.py
apps/api/tests/test_copilot_product_tools.py
apps/api/tests/test_copilot_required_checks_narration.py
apps/web/components/copilot/panel.tsx
apps/web/lib/copilot-conversation.ts
apps/web/scripts/check-copilot-target-memory.mjs
apps/web/scripts/check-copilot.mjs
```

이 파일들은 앞서 진행한 Narrator·수동 확인 응답·최신 판정 선택·순번/대상 기억 보완의 자산이다. **파일 존재와 W0~W6 전체 구현 완료는 다르다.** 테스트 파일이 있다는 사실 역시 테스트가 실행됐다는 증거는 아니다.

`router.py`의 확인된 진입 경로는 권한 확인 → 기존 resolve → DOCUMENT_QA 또는 chat → 선택적 narration → 표시 대상 동기화다. 이것을 v3.1의 새 대화 조정자·복합 도구 계획 전체가 연결됐다는 증거로 사용하지 않는다.

### 2.3 작업 공간과 과거 보고의 한계

이번 ChatGPT 실행 컨테이너의 `/mnt/data`에서 기존 일반 파일 74개와 ZIP의 후보 항목·텍스트 로그를 조사했다. `.git` 작업 디렉터리는 없었고, 검사한 텍스트·로그 범위에서 47개 검사 주장과 연결되는 실행 자료를 확보하지 못했다. 첨부 검색 결과에서도 그 주장을 입증하는 자료는 확인하지 못했다.

이는 **현재 접근한 컨테이너·자료 범위에 한정된 결과**다. 사용자의 Windows 저장소, 별도 Codex 작업 공간, 다른 컴퓨터, 과거의 소멸한 실행 환경에 파일이 없는지를 확인한 것은 아니다. 찾지 못한 구현물을 복구됐다고 주장하거나, 파일명을 추측해 존재하는 것처럼 인계하지 않는다.

사용자가 앞선 대화에서 제공한 Narrator `4 passed`, 프론트 검사 성공, TypeScript 무오류 출력은 별도의 과거 사용자 제공 실행 기록이다. 이를 47개 검사 또는 v3.1 전체 성공과 합산하지 않는다. 현재 통합 상태는 다시 검증한다.

## 3. 역할과 문서의 우선순위

- **이 ChatGPT 대화:** 제품 목표·설계·완료 기준 정리, 쟁점 판단, 결과 검토, Notion 정리.
- **Codex:** 실제 작업 공간 조사, 설계와 코드의 차이 분석, 구현·테스트·수정, 재현 가능한 결과 보고.
- **사용자:** 제품 범위와 중요한 변경 선택, 타 파트 협의, 필요 시 이 대화와 Codex 사이의 질문·답변 전달.

제품 설계는 아래 문서를 따른다. 이 파일은 그 설계를 대체하지 않고 **진행 상태와 증거 취급 방식**을 바로잡는다.

1. [챗봇 3차 개선 정리](https://app.notion.com/p/3dae94b44d07805b8d19cc5b9c28c4e6)
2. [기본 설계 v3.1](https://app.notion.com/p/3dae94b44d0781e1ba5bedf81822f619)
3. [구현·평가 계획 v3.1](https://app.notion.com/p/3dae94b44d07814bac73cb2e9a93abcc)

설계가 말하는 목표, 코드가 구현한 동작, 실행에서 관찰한 결과를 별도 기록한다. 기존 코드가 설계와 다르다고 설계를 조용히 축소하지 않는다. 설계 자체에 모순·필수 결정 누락이 있으면 질문으로 정리한다. Notion 접근이 안 되면 필요한 설계 원문을 요청하고, 문서 제목만으로 세부 계약을 추측하지 않는다.

**이번 단계는 복구·검증 인계부터 정리하는 단계다.** 이 문서가 생성됐다고 W0가 완료되거나 W1~W6 구현이 시작·완료된 것은 아니다.

## 4. Codex 첫 작업 — 변경 전에 현재 상태부터 확정

### A. 로컬과 원격을 구분해서 조사

기존 프로젝트 루트는 사용자가 제공한 `E:\dev\02_TeamProjects\bid-change-validator`다. 현재 컴퓨터에서도 이 경로가 맞는지 먼저 확인한다. 터미널에서 아래 명령은 Git 상태 조회용으로 사용할 수 있다.

```powershell
Get-Location
git rev-parse --show-toplevel
git branch --show-current
git status --short
git rev-parse HEAD
git diff --stat
git diff --cached --stat
git ls-files --others --exclude-standard
git stash list
git worktree list

# fetch는 원격 추적 ref를 갱신하지만 작업 파일을 병합하지 않는다.
git fetch origin
git rev-parse origin/feature/ai-copilot-user-test-hardening
git rev-parse origin/develop
git rev-list --left-right --count HEAD...origin/feature/ai-copilot-user-test-hardening
git rev-list --left-right --count origin/develop...origin/feature/ai-copilot-user-test-hardening
```

브랜치가 다르거나 미commit 변경이 있으면 즉시 switch/pull/reset하지 않는다. 작업 소유자와 변경 내용을 확인하고 안전한 보존 방법을 정한다. stash는 존재 확인부터 하며 자동 pop하지 않는다. 파일 목록에서 비밀 파일을 발견해도 내용 전체를 보고서에 복사하지 않는다.

### B. 실제 파일·호출 경로를 대조

`ConversationState`, `TaskPlan`, `EvidenceBundle`, `AnswerEnvelope`, 조정자, 생성·검증, 평가 runner에 해당하는 코드·문서를 찾는다. 설계에서 제시한 파일명은 후보이므로 이름이 다르다는 이유만으로 미구현이라고 판단하지 않는다.

코드를 찾으면 경로·심볼·commit 또는 파일 hash를 기록하고 다음을 구분한다.

- 자료형/함수만 정의되어 있는가?
- 실제 `/copilot/chat` 또는 새로 합의한 엔드포인트에서 호출되는가?
- 프론트가 그 요청을 전송하고 새 응답을 렌더링하는가?
- 기본 설정에서 실행되는가, 실험 플래그 뒤에 있는가?
- 의존성·환경변수·저장소·테스트가 함께 연결되어 있는가?

테스트용 가짜 도구로만 실행되는 구현을 실제 서비스 연결 완료로 보고하지 않는다. 다른 작업 공간에서 발견한 파일은 즉시 덮어쓰지 말고 diff와 의존성을 검토한다.

### C. 과거 검사 근거를 조사

47개 검사와 연결되는 명령, 선택한 테스트 목록, 코드 SHA/작업 diff, 실행시각, 원본 로그, 종료 코드, fixture/DB/모델 조건을 찾는다. 다른 시점의 테스트 결과나 기존 700개 회귀 결과를 대신 사용하지 않는다.

찾지 못하면 `UNVERIFIED — 실행 근거를 확보하지 못함`으로 종료하고 다음 단계로 진행할 수 있다. 과거 자료 수색을 무한 반복하거나 숫자 47을 맞추는 테스트를 만들지 않는다.

## 5. 재검증 순서와 실행 조건

**이 인계 문서 작성 과정에서는 제품 테스트를 실행하지 않았다.** 아래는 Codex가 수행할 절차다.

### 5.1 실행 전 환경 확인

Python/Node/pnpm 버전, 실제 의존성·lockfile, 실행 위치를 기록한다. 테스트 파일과 `conftest.py`의 fixture 및 import 부수효과를 먼저 확인한다. `--collect-only`도 import와 fixture 로딩을 유발할 수 있으므로 환경 확인의 대체 수단으로 쓰지 않는다.

DB 접속은 비밀번호를 출력하지 않고 host/port/database와 실제 접속 대상을 대조한다. 공용 Supabase와 격리 테스트 DB를 혼동하지 않는다. DB를 변경하는 테스트·seed·migration은 격리 환경에서만 실행하며 공용 DB는 임의 초기화·migration하지 않는다. 부족한 실행 조건은 `BLOCKED`로 기록하고 가능한 독립 검사는 계속 진행한다.

### 5.2 검사 계층

| 계층 | 확인할 것 | 이것만으로 주장할 수 없는 것 |
|---|---|---|
| 코드/계약 검사 | import, 타입, schema, mock/fake tool 계약 | 실제 DB 연결·LLM 답변 품질 |
| 격리 통합 검사 | 실제 Backend, 인증, DB, 상태·버전·기존 API 연결 | 실서비스 데이터 정답·사용성 |
| Frontend 검사 | 타입·lint·build, 실제 컴포넌트와 응답 연결 | 실제 LLM 품질 |
| 고정 데이터 + 실제 모델 | 고정 공고/회사/분석/판정과 모델의 대화 결과 | 모든 공고로의 일반화 |
| Golden Core 및 사용자 검증 | 검수된 기대 조건, 과업 완료, 자유 질문 | 수행하지 않은 다른 조합의 성공 |

현재 존재하는 검사 진입점 예시는 다음과 같다. **그대로 실행하라는 무조건 지시가 아니며, 위 환경 확인 후 각각의 의존성과 범위를 확인해서 선택한다.**

```powershell
# 프로젝트 루트에서, 격리 여부 확인 후
python -m pytest apps/api/tests/test_copilot_narration.py -q
python -m pytest apps/api/tests/test_copilot_required_checks_narration.py -q
python -m pytest apps/api/tests/test_copilot_product_tools.py -q

# 프론트 패키지 위치에서
Set-Location apps/web
node scripts/check-copilot.mjs
node scripts/check-copilot-target-memory.mjs
pnpm exec tsc --noEmit
pnpm build
```

새 W0~W6 검사는 실제 구현된 계약에 맞게 추가한다. 기존 테스트를 삭제하거나 기대값을 실제 오류에 맞춰 약화시켜 PASS를 만들지 않는다. 계약이 합의되어 바뀐 경우에만 변경 이유와 대응 테스트를 기록한다.

## 6. 상태 보고 형식

코드 상태와 검증 상태는 별개다.

- 코드: `PRESENT`, `PARTIAL`, `NOT_FOUND_IN_SCOPE`, `NOT_INSPECTED`.
- 검증: `UNVERIFIED`, `NOT_RUN`, `BLOCKED`, `PASS`, `PARTIAL`, `FAIL`, `CRITICAL`.
- `UNVERIFIED`: 과거 실행/완료 주장은 있으나 연결된 근거가 부족함.
- `NOT_RUN`: 이번 검사에서 아직 실행하지 않음.
- `BLOCKED`: 필요한 환경·권한·자료가 없어 해당 검사를 진행하지 못함.
- `PASS`: 명시한 범위·버전·조건에서 실제 완료 기준을 충족함.

W0~W6의 시작 상태는 전부 **새 설계 기준의 완료 근거 미확인**이다. 기존 재사용 코드가 일부 있더라도 W 전체를 완료로 올리지 않는다.

| 작업 | 조사할 대상 | 최초 보고에서 필요한 내용 |
|---|---|---|
| W0 | 고정 평가 데이터·실행 추적 | 실제 manifest/runner/log 존재와 재현 여부 |
| W1 | 네 계약·기존 도구 어댑터 | 심볼·scope 검증·실제 호출 위치 |
| W2 | 대화 조정자 | 복합 도구 조합·대화 이력·최대 재시도·연결 여부 |
| W3 | 인덱스 준비도·범위형 RAG | 원문/추출/인덱스 일치·섹션/예외 검색·Point QA 회귀 |
| W4 | 통합 답변·주장 근거·화면 | 수동 항목 인용·상태 표시·수치/예외 의미·실제 렌더링 |
| W5 | 변경·가정·제안 | 버전 분리·비저장 가정·확인 후 실행 경계 |
| W6 | 통합 평가·발표 근거 | 실제 실행된 평가와 미실행 항목·로그·실사용 검증 |

각 실행에는 최소한 다음을 남긴다.

```text
작업/검사 ID:
실행자 및 시각(시간대):
브랜치 / HEAD / 미commit diff 또는 파일 hash:
실행 위치 / 명령 / 도구 버전:
DB·fixture·manifest 식별(비밀값 제외):
실제 모델 또는 mock 구분 / 모델·설정:
선택·수집·통과·실패·skip·deselect 수:
종료 코드 / 원본 로그·JUnit·trace 위치:
관찰 결과 / 주장할 수 있는 범위 / 미검증 범위:
문제 / 원인 가설 / 개선안 / 적용 변경 / 재검사:
```

로그 파일이 있다는 것만으로 통과 처리하지 않는다. 명령이 실제로 실행·종료됐는지, 테스트 수가 무엇을 의미하는지 확인한다. 기능 요약·assistant의 완료 문구는 실행 로그를 대체하지 못한다.

## 7. 문제 발생 시 보고와 설계 질의

구현 중 지역적·복구 가능한 문제는 **현상 → 근거 → 원인 가설 → 개선안 → 영향 범위 → 적용 → 재검증** 순서로 기록하고 기존 사용자 승인 범위 안에서 진행한다.

다음은 임의 변경하지 않고 설계 질의로 올린다: 사용자 목표/완료 기준 축소, 판정·실행 권한 경계 변경, 타 파트 공용 API의 호환성 파괴, 공용 DB 변경, 기존 작업 삭제, 데이터/모델 비용 범위의 중요한 변경. 막히지 않은 작업은 병행할 수 있다.

질의는 `Q-001`처럼 식별하고 아래 형식으로 작성한다.

```text
관련 W 단계와 설계 절:
확인한 코드·로그·실제 동작:
설계와 충돌하거나 부족한 결정:
대안 A/B의 장단점:
권장안과 영향 범위:
답변 전 진행 가능한 작업:
사용자/이 설계 대화에서 필요한 결정:
```

이 ChatGPT 대화와 Codex의 자동 통신 연결은 확인되지 않았다. 직접 질의 채널이 없는 경우 사용자에게 위 내용을 전달해 이 대화에서 검토받는다. 연결 없이 “ChatGPT와 협의 완료”라고 쓰지 않는다. 승인된 결정은 문서에 남겨 다음 실행에도 이어지게 한다.

## 8. 최초 인계 작업의 완료 기준

첫 산출물은 **현재 상태 감사 보고서(audit report)** 다. 아래 내용을 근거와 함께 작성한 뒤 W0~W6의 재사용·보완·신규 작업 계획을 확정한다.

1. 로컬/원격 HEAD, 미commit·stash·worktree 상태와 보존 조치.
2. 실제 발견한 구현물·테스트·로그의 위치와 증거 수준.
3. “47개 검사 통과”의 확인 또는 미검증 결론.
4. W0~W6별 코드 상태, 실행 연결 상태, 검증 상태와 남은 일.
5. 실행한 검사·결과·실패·차단·미실행을 구분한 목록.
6. 개선안, 바로 진행할 구현 묶음, 설계 질의.

이 조사가 끝난 뒤에도 실제 테스트를 실행하지 못한 항목은 PASS로 바꾸지 않는다. main/develop 직접 수정, branch 삭제, force push, 공용 DB 변경, PR merge 또는 배포를 이 문서만으로 승인한 것으로 해석하지 않는다.

## 9. Codex에 전달할 시작 지시

> 이 문서를 먼저 읽고 현재 작업 브랜치의 이전 구현물을 조사해 주세요. “47개 검사 통과”와 W0~W6 코드 작성은 미검증 주장입니다. 로컬·원격 코드와 원본 실행 자료로 확인한 뒤 재사용할 것과 새로 구현할 것을 구분하세요. 먼저 상태 감사 보고서를 작성하고, 구현은 기본 설계 v3.1과 최신 사용자 지시에 따라 이어가세요. 설계상 중요한 문제가 있으면 근거·대안·권장안을 정리해 사용자에게 이 설계 대화로 전달하도록 요청하세요. 실제 통신·실행·검증 없이 완료를 주장하지 마세요.

## 10. 확인 근거

- [문서 작성 전 코드 기준](https://github.com/gyuniverse-hq/bid-change-validator/tree/9765ebaf8e4aad213a7d4953ee0482565592c108)
- [고정 SHA 간 feature 측 변경 비교](https://github.com/gyuniverse-hq/bid-change-validator/compare/b9153a534a631329ac3082afd20c624f5af6ab22...9765ebaf8e4aad213a7d4953ee0482565592c108)
- [확인한 router 진입 경로](https://github.com/gyuniverse-hq/bid-change-validator/blob/9765ebaf8e4aad213a7d4953ee0482565592c108/apps/api/app/copilot/router.py)
- [해당 SHA의 Actions 조회](https://api.github.com/repos/gyuniverse-hq/bid-change-validator/actions/runs?head_sha=9765ebaf8e4aad213a7d4953ee0482565592c108&per_page=100)

과거 47개 검사 주장과 사용자 실행 기록은 이 프로젝트 대화에서 인계된 내용이며, 이번 조사에서 새로 실행한 테스트 결과가 아니다. 이 문서의 재검증 절차와 보고 형식은 이번 인계를 위해 정한 운영 기준이다.
