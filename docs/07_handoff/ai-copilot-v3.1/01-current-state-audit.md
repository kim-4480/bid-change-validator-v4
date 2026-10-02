# 현재 상태 감사 보고서

감사일: 2026-09-14 KST / 실행자: Codex  
저장소: `gyuniverse-hq/bid-change-validator`  
작업 위치: `E:/dev/02_TeamProjects/bid-change-validator`  
범위: 상태 조사·기존 검사 재실행·읽기 전용 결함 진단. 제품 구현 변경 없음.

## 1. 결론

- **“47개 격리 검사 통과”: UNVERIFIED — 실행 근거를 확보하지 못함.** 실행 명령, 테스트 목록, SHA, 시각, DB/모델 조건, 원본 로그가 함께 연결된 자료를 찾지 못했다. 실패했다고 단정하지 않는다.
- **“W0~W6 관련 코드 작성/완료”: UNVERIFIED.** 기존 Copilot 자산은 존재하고 코드상 API·프론트 연결도 있다. 새 네 계약, 복합 조정자, Coverage RAG, 주장 의미 검증의 완료 근거는 없다.
- 이번 실제 검사: 기존 Python 테스트 **7 collected / 7 passed / 0 failed / 0 skipped / 0 deselected**, 프론트 독립 스크립트 **2개 종료 코드 0**, TypeScript **종료 코드 0**. 이 수치를 47의 증명이나 실제 모델 품질·서비스 통합 성공으로 사용하지 않는다.
- 기존 테스트가 통과해도 별도 진단에서 **입력 불가 항목의 입력 가능 집계, 수동 항목 인용 소실, 판정과 반대인 산문 수용**이 재현됐다. v3.1 완료 판정은 불가하다.
- 공용 DB 접속·변경, migration, seed, 모델 호출, merge, 배포, main/develop 수정, 기존 파일 삭제를 수행하지 않았다.

## 2. Git 상태와 보존

| 항목 | 확인 결과 |
|---|---|
| 실제 현재 브랜치 | `feature/ai-copilot-user-test-hardening` |
| 로컬 HEAD / 이번 검사 기준 | `49d4d1a4fa350f321c0cbc6bf09b26f70ff5f4e5` |
| 시작 시 원격 추적 ref | `9765ebaf8e4aad213a7d4953ee0482565592c108` |
| 실제 원격 feature HEAD | `ea613b243ee8c52a2538ce521ab3f8bbe267c061` — `git ls-remote` 후 fetch로 확인 |
| 원격 main / 기본 HEAD | `7be094132beef66c1340e3d3af5910fa60f96e81` |
| 원격 develop | `b9153a534a631329ac3082afd20c624f5af6ab22` |
| 로컬 대 원격 feature | `0 ahead / 2 behind` |
| 원격 feature 대 develop | feature `15 ahead / 2 behind` |
| 시작 시 staged / unstaged / untracked | 모두 없음 (`git status --porcelain=v1 --untracked-files=all`) |
| 등록된 worktree | 현재 경로 1개. 별도 등록 worktree 없음 |
| stash 0 | `02a630d4eb4f14275f19d42473356ddc41e82e1a`, `feature/ai-copilot-e1-ux-baseline`, Golden proposal-draft.txt 변경 |
| stash 1 | `7481cba916d94c71755e1d56e70133f9dd1b8725`, `release/pre-copilot-baseline`, requirements-test.txt 변경 |

stash는 파일 목록·통계만 조사했고 apply/pop/drop하지 않았다. fetch만 수행했으며 switch/pull/reset/merge/commit/push하지 않았다. 추적 파일의 staged/unstaged diff는 없다. 새 변경은 이 감사 문서와 `audit-evidence/` 산출물뿐이다. `.env`, 가상환경, 기존 dist, 인덱스를 보존했다. 등록되지 않은 다른 clone·다른 컴퓨터·소멸한 ChatGPT 실행 공간까지 조사했다는 뜻은 아니다.

최신 원격의 두 커밋:

1. `9765eba`: `router.py`에 `_sync_visible_targets()` 추가. Narrator 이후 실제 표시한 requirement 순서로 reply context를 갱신한다.
2. `ea613b2`: 요청한 `00-recovery-and-verification.md` 추가.

지정 문서는 로컬에 없었으므로 fetch 후 `git show FETCH_HEAD:docs/07_handoff/ai-copilot-v3.1/00-recovery-and-verification.md`로 읽었다. 원격 router 수정은 diff로 확인했지만 실행하지 않았다. **이번 PASS는 로컬 SHA 기준**이다. 두 SHA 간 변경이 router와 문서뿐이라는 점에서 조사한 나머지 파일은 동일하다.

근거: [Git 상태](audit-evidence/git-state.log), [원격 router 차이](audit-evidence/remote-router-diff.patch), [소스 SHA256 목록](audit-evidence/source-hashes.json).

## 3. 설계와 과거 실행 자료

다음 원문을 Notion connector로 읽어 대조했다. Notion에는 쓰지 않았다.

- [챗봇 3차 개선 정리](https://app.notion.com/p/3dae94b44d07805b8d19cc5b9c28c4e6): 최신 정정과 과거 사용자 관찰 구분.
- [기본 설계 v3.1](https://app.notion.com/p/3dae94b44d0781e1ba5bedf81822f619): §7 네 계약, §8 서버 대화 상태, §9 인덱스 준비도, §10 주장 검증, §11 실행 경계.
- [구현·평가 계획 v3.1](https://app.notion.com/p/3dae94b44d07814bac73cb2e9a93abcc): §4 고정 재현 묶음, §7 12개 회귀 시나리오, §8 W0~W6.

탐색 범위는 현재 소스·문서·scripts·data, fetch된 트리, 로컬 branch/ref의 관련 commit 로그, stash 목록, worktree 목록이다. `ConversationState`, `TaskPlan`, `EvidenceBundle`, `AnswerEnvelope` 및 관련 책임을 검색하고 기존 context/chat/contracts/source_map을 읽어 이름만 다른 구현인지도 확인했다. 현재 소스/원격 트리에서 해당 새 계약 전체를 찾지 못했다. AGENTS.md는 저장소 파일 목록 및 조사한 상위 경로에서 발견하지 못했다.

발견한 이전 자산:

- `apps/api/eval/copilot_v1.json`, `copilot_e2_routing.json`, `copilot_e3_document_qa.json`, `copilot_e3_expected_evidence.json`.
- `apps/api/app/scripts/evaluate_copilot_v1.py`, E2/E3 평가 runner들. v1 runner는 기존 fake fixture, E2/E3에는 fixture hash 기록 코드가 있다. **runner 존재만 확인했으며 이번에 평가 전체를 실행하지 않았다.**
- `docs/08_qa_reports/ai-copilot-v1-evaluation.md`, `ai-copilot-develop-design-integration.md`, `ai-copilot-stage5-6-retrieval.md/.json`, `ai-copilot-stage6-2-to10.md`. 과거 500 passed나 47 chunks 등은 이번 주장과 별개다.
- ignored `data/document-rag/*/manifest.json` **20개**와 인덱스 파일 존재를 목록화했다. 이는 검색 인덱스이며 v3.1 고정 평가 manifest라는 증거가 아니다. 현재 DB 원본/추출 hash와 대조하지 않았다. [인덱스 목록](audit-evidence/index-inventory.json).
- 기존 `apps/web/dist`와 `.wrangler` 상태가 존재한다. 수정 시각만으로 빌드 성공이나 배포 버전을 확정하지 않았다.

한계: `.pytest_cache`의 확장 탐색은 접근 거부로 내용을 확보하지 못했다. GitHub Actions API 조회는 `gh` 미인증으로 실패했다. 따라서 최신 SHA의 CI 실행 수나 green 여부를 이번에 확인했다고 쓰지 않는다. 로컬 `.github/workflows/copilot-integration.yml`은 push 대상을 `feature/ai-copilot-v1`, PR 대상을 develop으로 설정한다. 현재 feature의 push만으로 해당 workflow가 실행된다고 볼 수 없다.

**과거 47개 검사의 연결된 원본 실행 기록은 확보하지 못했으므로 UNVERIFIED를 유지한다.** 사용자 제공 Narrator 4개 성공 기록·이전 보고서·이번 7개 성공을 합산하거나 소급 증거로 사용하지 않는다.

## 4. 실제 호출 연결

코드상 연결은 다음과 같다. HTTP 요청·실서비스 프로세스를 실행 관찰한 결과는 아니다.

```text
app-shell.tsx → CopilotProvider / CopilotPanel
  → ConversationStore.ask → /api/v1/copilot/chat
  → main.py의 protected_api_router → copilot.router.copilot_chat
  → authorize_case_access → resolve_chat_payload
  → DOCUMENT_QA이면 answer_grounded_document_question
  → 그 외 chat → 기존 product_tools/actions의 읽기·제안
  → semantic_processing이면 apply_product_narration
  → [원격에만 있음] _sync_visible_targets
  → CopilotChatResponse → panel의 presentation / sources / actions 렌더링
```

- `ConversationContext`에는 마지막 intent, visible requirement keys, receipt가 있지만 대화 메시지 이력·수동 fact 대상·서버 대화 저장소가 없다. 프론트에 표시된 turn 목록과 모델이 받는 이력은 다르다.
- `chat()`의 2회 시도는 읽기 충돌 재시도다. 복합 TaskPlan 실행이나 검색 보완 2회가 아니다.
- API semantic header 기본값은 false, 화면의 `semanticProcessing` 초기값은 true다. `copilot-conversation.ts`가 header를 전송한다. Narrator는 선택 경로이고 DOCUMENT_QA는 별도 분기다.
- `document_qa.py`는 opt-in 확인 후 index load/build와 `retrieve(method="hybrid", k=4, fetch_k=12)`를 호출한다. 전체 조건 coverage 검사·부모 섹션/예외를 보완하는 새 조정은 찾지 못했다.
- `copilot-api.ts` 및 action store는 `/api/v1/copilot/actions/confirm`을 연결한다. 서버는 접근 권한, dirty session, case lock, 최신 provenance를 확인하고 기존 `answer_and_rejudge` / `run_qualification_revalidation`을 호출한다. 이 트랜잭션의 실제 DB 검증은 미실행이다.

## 5. W0~W6 상태 및 재사용·보완·신규 대상

아래 PARTIAL은 기존 자산을 포함한 코드 상태다. 새 설계 전체의 완료 상태는 전부 UNVERIFIED이며 이번 검사는 일부만 검증했다.

| 단계 | 코드 상태·발견 자산 | 서비스 연결 상태 | 이번 검증 상태 | 다음 작업 |
|---|---|---|---|---|
| W0 | PARTIAL: 기존 eval JSON, Golden fixture/seed, v1/E2/E3 runner와 과거 보고서 PRESENT. v3.1의 코드·회사·분석·판정·문서·모델·trace를 묶은 고정 재생 bundle NOT_FOUND_IN_SCOPE | 독립 평가 entrypoint 존재. 새 trace의 chat 연결 없음 | PARTIAL: 이번 SHA/로그 확보. 고정 bundle 재생 NOT_RUN | 기존 자산 재사용. 별도 고정 manifest·실행 trace 신규 작성; 실데이터와 평가 기준 구분 |
| W1 | PARTIAL: ProductProvenance, ConversationContext, CopilotChatResponse, product_tools 존재. 새 네 계약 NOT_FOUND_IN_SCOPE | legacy API에 연결. 새 TaskPlan/EvidenceBundle/AnswerEnvelope 연결 없음 | 어댑터 DB 검사 BLOCKED; 일부 Narrator/client 계약 PASS. W1 전체 UNVERIFIED | 기존 scope·도구 재사용; 서버 소유 상태·다종 target·askability·facts/claims 계약 신규 구현 |
| W2 | PARTIAL: chat/resolve_intent/semantic router 존재. 복합 조정자 NOT_FOUND_IN_SCOPE | 단일 intent 분기만 확인; 전체 이력·복합 도구 계획 없음 | 복합 질문+후속 3턴 NOT_RUN | legacy 보존; W1 기반 계획 검증·읽기 실행·예산·부분 실패 처리 신규 구현 |
| W3 | PARTIAL: version FAISS manifest, hybrid retrieval, grounded QA 존재 | DOCUMENT_QA와 연결. 기존 index load 시 현재 문서 집합/hash 재대조 없음 | manifest 20개 목록 확인; 현재 원본 일치·실제 검색 품질 UNVERIFIED / DB·모델 평가 BLOCKED | Point QA 재사용. 준비도 대조·section/exception coverage 보완; 담당 경계는 Q-002 |
| W4 | PARTIAL: Presentation/SourceMap/Narrator/panel 존재; 새 claims/서버 status card 계약 없음 | 실제 legacy response → panel 연결 확인 | 기존 7개 PASS와 client/타입 PASS. 별도 진단에서 v3.1 요구 위반 3건 재현 | source mapping/UI 재사용. askability 집계 수정, 수동 fact 인용·문장 의미 검사·응답별 target 신규/보완 |
| W5 | PARTIAL: ChangedNoticeResult, propose_answer, confirm_action과 확인 UI 존재. 비저장 가정 상태/도구 NOT_FOUND_IN_SCOPE | 변경 비교·확인 후 실행 코드 연결. 가정 검토 연결 없음 | DB 트랜잭션·취소·권한·stale 통합 BLOCKED, 가정 시나리오 NOT_RUN | 기존 Confirm API 보존; 버전별 facts 및 비저장 가정 도구 연결·검증 |
| W6 | PARTIAL: 기존 평가 runner, CI workflow, QA 보고서 존재. v3.1 개발/보류/사용자 평가 완료 근거 없음 | CI 실행 파일 존재; 현재 원격 실행 상태 확인 불가 | 일부 독립 검사 PASS; 전체 회귀·실제 모델·3명 사용자 평가 NOT_RUN/BLOCKED | 기존 회귀 재사용; 능력별 시나리오와 검수 정답, 모델/실사용 결과·발표 증거 신규 확보 |

64개 시나리오, 40/24 split, 3회 반복 등은 설계 목표이며 현재 작성/검증된 수로 보고하지 않는다.

## 6. 실행 환경과 안전 조건

원래 `.venv/Scripts/python.exe`는 `pyvenv.cfg`에 기록된 Python 실행기를 시작하지 못했다. 패키지나 가상환경을 재설치·덮어쓰기하지 않았다.

- 실제 검사 실행기: `C:/Users/HGLEE/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`, **Python 3.12.14**.
- 패키지: 기존 `.venv/Lib/site-packages`를 사용. pytest 9.1.1, SQLAlchemy 2.0.52, FastAPI 0.141.1, OpenAI 3.8.0, pydantic-settings 2.15.0, psycopg 3.3.5 확인. requirements.txt/dev.txt와 해당 항목 일치. 전체 의존성 재설치·pip check는 하지 않았다.
- Node **v24.14.0**, pnpm **11.19.0**, 설치된 TypeScript **5.9.3**. package.json 및 pnpm lockfile 확인/hash 보존. CI의 Node 22/pnpm 10.15.0과 동일 환경은 아니다.
- `Settings()`를 읽어 확인한 유효 DB와 migration 대상: **aws-0-ap-northeast-2.pooler.supabase.com : 6543 / postgres**. 비밀번호·사용자·키는 출력하지 않았다. 실제 DB 서버 식별 쿼리/접속은 수행하지 않았으므로 접속 대상의 실측 증명은 없다.
- `conftest.py`의 seed fixture는 master code insert/delete/commit을 수행한다. `test_copilot_product_tools.py`는 `_seed_golden_case`, commit, rejudge, cleanup을 수행한다. 따라서 공용 DB 대상으로 실행하지 않았다. 사용할 수 있는 격리 PostgreSQL과 Docker 실행기를 이번 조사에서 확보하지 못했다.
- Python 독립 검사에서는 env DB를 loopback port 1의 `audit_never_connect`로 강제하고, `Engine.connect` 및 socket connect/connect_ex/create_connection을 차단했다. `--noconftest`, pytest 자동 plugin 비활성화, cache/bytecode 비활성화 적용. DB 연결을 필요로 하면 성공하지 못한다.
- 선택한 두 Python 테스트는 Synthetic SimpleNamespace/Pydantic fixture와 주입한 fake extractor만 사용한다. DB·실제 모델·FAISS 통합 검사가 아니다.
- 프론트 검사 두 개는 기존 mock과 메모리 transport/fetch stub을 사용하며 실제 서버를 호출하지 않는다. TypeScript는 `--incremental false`로 기존 tsbuildinfo를 덮어쓰지 않았다.

## 7. 실제 실행 결과와 재현

검사 시작 2026-09-14 03:23 KST, 각 프로세스 종료 코드는 [실행 메타데이터](audit-evidence/execution-metadata.txt)에 보존했다. 아래 모든 실행의 제품 SHA는 로컬 `49d4d1a...`이며 제품 diff 없음. 감사 실행기만 신규 작성했다. 프론트 스크립트는 pytest 항목 수로 환산하지 않는다.

| ID | 검사 / 명령 | 결과 | 원본 근거 / 주장 범위 |
|---|---|---|---|
| A-01 | 루트에서 번들 Python으로 `audit-evidence/run-isolated-narration.py` 실행 | PASS, 7 collected/7 passed, 0 failed/skip/deselect, exit 0, pytest 0.41s | [narration.log](audit-evidence/narration.log), [JUnit](audit-evidence/narration.xml): 두 기존 테스트 파일 전체. fake extractor 동작만 |
| A-02 | apps/web에서 `node scripts/check-copilot.mjs` | PASS, exit 0 | [client.log](audit-evidence/client.log): 11 response mocks + 1 error fixture와 conversation/client 계약. 화면 실렌더 검증 아님 |
| A-03 | apps/web에서 `node scripts/check-copilot-target-memory.mjs` | PASS, exit 0 | [target-memory.log](audit-evidence/target-memory.log): 비대상 turn 이후 requirement 기억. 수동 fact와 혼재된 목록 전체를 검증한 것 아님 |
| A-04 | apps/web에서 `node node_modules/typescript/bin/tsc --noEmit --incremental false` | PASS, exit 0 | [typecheck.log](audit-evidence/typecheck.log): 출력 없음. 종료 코드 별도 기록. 빌드/브라우저 검증 아님 |
| D-01~03 | 같은 Python runner에 `--probe` | 진단 실행 exit 0; 요구 위반 3건 관찰 | [gap-probes.log](audit-evidence/gap-probes.log). 진단 성공을 제품 PASS로 계산하지 않음 |

재현 명령(PowerShell, 저장소 루트):

```powershell
$auditPython = 'C:/Users/HGLEE/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
$env:PYTHONUTF8 = '1'
& $auditPython docs/07_handoff/ai-copilot-v3.1/audit-evidence/run-isolated-narration.py
& $auditPython docs/07_handoff/ai-copilot-v3.1/audit-evidence/run-isolated-narration.py --probe
Set-Location apps/web
node scripts/check-copilot.mjs
node scripts/check-copilot-target-memory.mjs
node node_modules/typescript/bin/tsc --noEmit --incremental false
```

실행하지 않은 것:

- **BLOCKED:** product_tools 포함 DB 통합·전체 backend 회귀 — 격리 DB 미확보. 공용 DB에는 실행 금지.
- **BLOCKED:** 현재 원본/추출/인덱스 일치 확인과 고정 실제 모델 평가 — 검증된 데이터 묶음·모델 실행 조건 미확보.
- **BLOCKED:** 최신 원격 CI 조회 — gh 인증 없음. Git remote 읽기 성공과 GitHub API 인증은 별개다.
- **NOT_RUN:** build/lint/브라우저 E2E. 기존 dist와 실행 상태를 보존했으며 이번 독립 검사 범위에는 포함하지 않았다. 빌드 환경이 정상이라는 주장 없음.
- **NOT_RUN:** 원격 router 동기화 코드 실행, W0~W6 신규 통합 평가, Golden Core 전체 재검수, 사용자 3명 평가.

## 8. 재현한 결함과 남은 설계 차이

### D-01 — 입력 가능 집계 오류

`narration.py::_compact_required_checks_fallback`은 `answerable_count = len(checks.questions)`를 사용한다. 기존 fixture의 질문을 `askable=false`로 바꾸고 provider 실패를 주입하자 “추가로 답변해 판정을 갱신할 회사정보는 1건”을 출력했다. 기본 설계 §3.5/평가 시나리오 9에 부합하지 않는다. 입력 가능/불가능/수동 확인을 분리하는 보완 대상이다. 제품 코드 수정은 하지 않았다.

### D-02 — 수동 항목 인용 소실

`narration.py::_recompose`는 requirement key가 있는 point에만 원래 source를 연결한다. 원문 evidence 1개가 있는 기존 수동 확인 fixture와 null-key point를 주입하자 `output_source_count=0`, `reason_refs=[[]]`가 나왔다. UI의 일반 상세 링크는 개별 주장 인용을 대체하지 못한다. fact_id/source_ids 계약이 필요하다.

### D-03 — 저장 상태와 반대인 산문 수용

저장 summary와 생성 enum은 `ineligible`로 유지하고 생성 conclusion만 “참가 가능합니다.”로 주입했다. 그대로 presentation conclusion에 수용됐다. 이는 **검증기 경계의 재현된 결함**이지 실제 모델이 해당 문장을 생성했다거나 실서비스에서 사고가 발생했다는 기록이 아니다. 기존 `test_narrator_cannot_flip_product_status`는 enum 변경을 검사하므로 이 결함을 막지 못한다.

### D-04 — 인덱스 최신성의 정적 확인 공백

`document_rag/service.py::load_or_build_version_index`는 파일 존재 시 즉시 load를 시도한다. `VersionFaissIndex.load`는 schema, version 혼입, record 수를 검사하지만 현재 DB의 원본/추출 hash·문서 집합과 요청 embedding model을 비교하지 않는다. **현재 20개 인덱스가 실제 stale이라고 판정한 것은 아니다.** 준비도 점검을 구현할 경계가 확인된 것이다.

## 9. 설계 대화 전달용 질의

### Q-001 — 산문 검증 실패 시 반환 정책과 평가 기준

- **관련 W / 설계 절:** W1·W4·W6, 기본 설계 §7.4/§10, 평가 계획 §7 시나리오 8~9.
- **확인 코드·로그·동작:** D-02/D-03. `narration.py::_recompose`/`apply_product_narration`, [진단 로그](audit-evidence/gap-probes.log). 상태 enum은 맞아도 반대 산문이 수용되고, 수동 항목의 원문이 입력에 있어도 출력 인용이 비어진다.
- **부족한 결정:** 설계는 주장 의미 검증을 요구하지만 검증 모델 장애·판정 불확실 시 어떤 주장까지 표시할지, 재생성 횟수와 추가 호출 비용 상한은 확정되지 않았다. source ID 존재 검사만으로 완료 처리하면 현재 결함이 남는다.
- **대안 A:** 추가 의미 검증 호출을 기본 적용하고 실패 주장만 1회 재작성. 자유로운 설명을 유지하지만 지연/비용과 검증 모델의 오판이 증가한다.
- **대안 B:** 서버 상태 카드·직접 인용을 우선 보장하고 검증되지 않은 생성 주장만 제외/유보한다. 장애 시 결과가 예측 가능하지만 설명이 덜 풍부할 수 있다.
- **권장안·영향:** B를 실패 시 기본 반환 정책으로 두고 A는 설정된 예산 내 보완으로 사용. fact/source 연결과 숫자·부정·상태 검사를 분리하고 의미 검증 실패를 trace에 기록. 저장 상태나 실행 권한은 바꾸지 않는다.
- **답변 전 가능:** 기존 경로 보존, 네 계약 정의, enum/산문 반전·null-key 인용·askable=false의 회귀 기대조건 작성. 실제 모델 없이 검사 가능.
- **필요한 결정:** 검증 실패 시 위 부분 반환 정책, 의미 검증/재작성 호출 상한과 품질 게이트를 설계 대화에서 확정해 전달해 달라. 아직 협의·승인 완료로 기록하지 않는다.

### Q-002 — stale 인덱스의 처리 주체와 요청 중 재구축

- **관련 W / 설계 절:** W3·W0, 기본 설계 §9.1, 평가 계획 §9 LLM/RAG 담당 경계.
- **확인 코드·동작:** D-04. 현재 load 경로에 live fingerprint 대조가 없다. 목록화한 20개 manifest의 최신성은 UNVERIFIED다.
- **부족한 결정:** 불일치를 발견했을 때 chat 요청이 외부 임베딩 비용과 인덱스 쓰기를 수반하는 재구축을 수행할지, 별도 담당 작업으로 넘길지 결정이 필요하다.
- **대안 A:** 요청 중 재구축. 즉시 회복 가능하지만 비용·지연·동시 재구축 제어가 필요하다.
- **대안 B:** 준비도 결과를 반환하고 검증된 원문 직접 읽기/부분 답변으로 계속 처리, 재구축은 담당 서비스로 분리. 응답은 예측 가능하지만 복구 관리가 필요하다.
- **권장안·영향:** B로 책임을 분리하고 Copilot은 readiness 계약을 소비. 기존 `document_rag`를 복제하지 않는다. LLM/RAG·Backend 담당과 invalidation/재구축 소유권을 합의한다.
- **답변 전 가능:** fingerprint 비교 계약·합성 불일치 fixture 설계, 현재 index metadata 재사용 조사. 공용 인덱스 재작성 없음.
- **필요한 결정:** 준비도 실패 시 fallback과 재구축 주체/예산 확정. 자동으로 타 담당자에게 메시지를 보내지는 않았다.

## 10. 후속 구현 순서 제안

1. 이 감사 결과를 기준선으로 보존하고 원격 router 보완의 통합 여부를 정한 뒤 실제 구현 SHA를 다시 고정한다. 기존 로컬 HEAD를 임의로 이동하지 않았다.
2. **W0→W1:** 기존 Golden/E2/E3 자산을 재사용해 불변 평가 bundle·실행 trace를 만들고 네 계약을 정의한다. 먼저 fake-tool scope/askability/대상 소유권을 검증한다.
3. **W2/W4 대표 흐름:** 복합 질문 한 개와 후속 3턴을 기존 API 어댑터로 연결. D-01~03을 제품 회귀 검사로 고정하고 수동 fact 대상과 문장 인용을 함께 처리한다.
4. **W3:** Q-002의 책임 경계를 확정하고 원문/추출/index 일치 및 coverage를 구현. Point QA 회귀 유지.
5. **W5/W6:** 격리 PostgreSQL을 확보한 뒤 인증·stale·Confirm 트랜잭션·가정 검토를 검사하고, 조건을 고정한 실제 모델·Golden Core·사용자 평가를 수행한다.

첫 산출물은 이 감사 보고서다. 위 후속 구현은 아직 수행하지 않았으며, 실패를 숨기기 위한 기대값 변경이나 47개 맞추기용 테스트를 만들지 않았다.
