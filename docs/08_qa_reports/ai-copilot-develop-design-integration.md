# AI Copilot v1 — 릴리스 기준선·프론트 설계 통합 검증

검증일: 2026-09-12 KST. 구현·자동 검증·브랜치 게시와 실제 사용자 검수·merge 승인은 구분한다.

## 1. 고정 기준

- 제품 기준: develop `40de1a37224080c0b1a9b45a65691d1c0f419a7d` (#107/#112/#114).
- main 릴리스 `02033a3edb6e43493b3acf0b7b806fa44c201273` (#116)와 제품 파일 트리가 동일하다.
- 기존 Copilot A–D: `4bc66322d82d54db99eff7e3fc43c331da4fa304`.
- 통합 코드 커밋: `a761e32d341fb4f66d142f1f817e5243a8da344a`.
- 실제 통합 검증 파일 트리: `0ddf21f054cf385352d8610dd0253b41ebcec39c`. 이 보고서 갱신은 검증 후 문서 변경이다.
- 작업 브랜치: `feature/ai-copilot-v1` 하나. main/develop 직접 수정·자동 merge·원본 Windows 작업트리/exports 수정 없음.
- 디자인 출처: 황수빈의 Notion 「챗봇 화면 설계」 (`3d7e94b44d078039b3f1fffa76d7046b`) 및 첨부한 7개 상태 Figma CSS.
- Figma MCP 호출 한도로 원본 캔버스 직접 비교는 미수행. 마스코트는 제공 CSS의 원형 몸통·눈을 재현했으며 원본 exported asset이라고 주장하지 않는다.

## 2. 제품 기능 보존

공통 조상·develop·Copilot의 3-way 파일 비교를 기준으로 통합했다. #107 건너뛰기/다시 보기와 변경이력 한국어 문구, #112 NOTICE_FACT/dropped_requirements 구분, #114 빈 원문 안내와 실제 Evidence가 있을 때만 원문 버튼을 보이는 동작을 보존했다.

Core 판정·app/ai·DB migration·Golden fixture 원본은 develop과 동일하다. 기존 master seed fixture는 opt-in을 유지한다. Copilot DB 테스트에서 필요한 seed를 명시적으로 요청한다. 최신 migration 017의 상태/unknown_reason 제약을 위반하던 합성 fixture는 유효한 상태·사유 조합으로 수정했으며 DB 제약을 완화하지 않았다.

## 3. 통합 경계 보완

- 인증: 기존 HttpOnly 세션 쿠키를 설정된 API origin에만 공유한다. 새 token 저장소·tenant/auth 정책을 만들지 않았다. 실제 cross-site 쿠키/CORS·로그인 UX·사용자/case 권한은 별도 공개 gate다.
- 인증 거절: Backend가 명확히 반환하는 401 AUTHENTICATION_REQUIRED/INVALID_SESSION은 AUTH_REQUIRED로 구분한다. 출처가 불명확한 401·네트워크 단절·5xx는 OUTCOME_UNKNOWN을 유지하고 자동 write 재시도하지 않는다.
- 실행: 전체 검토와 Copilot은 탭 내 실행 잠금을 공유한다. 분산 lock을 구현했다는 뜻은 아니다.
- 조회 실패: workspace 재조회 실패 시 이전 데이터를 최신처럼 취급하지 않고 오류를 표시·신규 동작을 잠근다. ask-back/changes/qualification에서 완료 ActionCard는 조회 성공 여부와 독립적으로 유지한다.
- 재검증 결과: case·기준/현재 analysis·결과 judgment가 일치하는 경우만 현재 결과로 표시한다.
- 과거 근거: 근거 링크의 analysisRunId와 현재 분석이 다르면 재사용된 evidence_key로 자동 이동하지 않고 이전 분석 기준임을 안내한다.
- 설명 범위: 판정에 사용된 동일 analysis에서 NOTICE_FACT·제외 요건·파이프라인 진단을 가져온다. 실제 resolve된 Evidence만 사용하고 없는 키·링크·원문을 만들지 않는다. diagnostic details를 설명에 그대로 복사하지 않는다.
- 판정 밖 항목: 저장된 overall_status를 바꾸지 않는다. 추가 확인사항을 기존 자격요건 순번 또는 답변 반영 대상으로 만들지 않는다. 응답 전체의 source mapping은 일관되게 유지한다.

## 4. 프론트 설계 대응표

| 설계 | 구현 |
|---|---|
| 400×720 참고 프레임, radius 24/20, padding 20, gap 14 | 반응형 공통 패널 CSS |
| 헤더 20px / 빈 상태 64px 중립 마스코트 | 원형 몸통·흰 눈, 고정 표정 |
| Gothic A1 / 공통 색상 | 기존 폰트 변수와 product 토큰 재사용 |
| 상태·버전 배지 | 동일한 최근 Backend 조회 결과 기준, 정적 판정 배지 없음 |
| 빈 상태 / 판정 없음 / 로딩 / 확인필요 답변 / 변경공고 / 근거 부족 / 오류 | 공통 renderer의 구분된 표시 상태 |
| EvidenceChip | 검증된 원문 위치·04 이동, 과거 분석 오연결 차단 |
| 03 입력·06 변경 상세 | 패널은 요약, 기존 상세 화면의 공통 controller로 명시 확인·실행 |
| 좁은 화면 Drawer | 1024px 미만 native modal dialog, Case 메모리 공유 |
| 오류 재조회 | 실패한 read 질문·intent·문맥 재시도, confirm 재전송 없음 |

의도적 차이: localStorage/서버 대화 저장 대신 layout 메모리, analysis != SUCCEEDED 일괄 차단 대신 실제 판정/분석 상태 확인, 모든 citation 부재를 오류로 처리하지 않고 근거가 필요한 응답에만 근거부족 표시.

## 5. 실제 자동 검증 결과

실행: https://github.com/gyuniverse-hq/bid-change-validator/actions/runs/34646280556

| 검사 | 실제 결과 |
|---|---|
| 전용 PostgreSQL migration | 001~020 적용 성공 |
| 전체 Backend | 659 passed / 0 failed, Starlette 경고 1건, 12.09초 |
| 기존 고정 평가 | 100 passed / 5 deselected, 2.41초 |
| TypeScript | 통과 |
| client / actions / integration 검사 | 3개 스크립트 통과 |
| 변경 파일 lint | 26개 파일, 오류 0·경고 0 |
| 프로덕션 build | 통과 |
| Chromium UI | 7개 표시 상태·390px Drawer·원문/상세 이동·명시 confirm·조회 실패 복구 통과 |
| 브라우저 요청 계수 | 합성 confirm 1건 / read 10건 / pageErrors 0건 |
| 전체 repository lint | 기존 미변경 영역의 27개 오류 남음. 전체 lint green으로 보고하지 않음 |

평가 JSON SHA-256(LF): `9a5677197689a3421ced2f1c217653958568d3cbd50500e34257496f1b8ff99c`.
이 평가셋은 이전 개발 때 노출됐다. dev 40/holdout 이름의 40/다회차 20의 이번 통과는 고정 회귀이며 독립 holdout 정확도가 아니다. 실행 묶음은 중복 가능하므로 659와 100을 고유 테스트 수로 합산하지 않는다.

브라우저는 실제 앱을 Chromium으로 렌더링하되 API 응답은 합성 fixture로 interception했다. 원문 칩·세부 화면 이동, 새로고침 실패에도 성공 카드 유지, 역사적 분석 오연결 차단, 평가 화면에서는 패널을 숨기는 것을 검사했다. 실제 DB의 confirm/replay/rollback은 별도의 Backend suite에서 검증했다. 실제 배포·실사용 데이터의 브라우저 E2E 통과로 대체해 주장하지 않는다.

스크린샷은 01-empty, 02-no-judgment, 03-loading, 04-answer, 05-changed, 06-no-evidence, 07-error, 08-mobile 총 8개다. 자동 캡처 후 이미지로 확인했으며 디자이너 또는 실제 사용자 합격 판정은 아니다.

### 검증과 게시 상태의 구분

위 run의 제품 검증 step은 success다. 이후 게시 step만 GitHub Actions bot의 workflows 권한 부족으로 거절되어 run 전체 결론은 failure다. 이를 전체 CI green이라고 보고하지 않는다. 생성된 commit/tree의 동일성을 확인한 뒤 이미 승인된 사용자 GitHub 연결의 non-force ref 갱신으로 정확히 같은 통합 커밋을 게시했다. bot 권한을 확대하거나 main/develop 보호를 해제하지 않았다.

최종 파일 트리에는 임시 source transport가 없으며, 최종 workflow는 contents:read만 사용하는 일반 검증이다. 이후 PR/branch workflow 결과는 해당 최신 실행에서 별도로 확인한다.

## 6. 재현과 격리 범위

`.github/workflows/copilot-integration.yml`이 `scripts/ci_copilot_integration.sh`를 실행한다. 이 스크립트는 GITHUB_ACTIONS=true와 명시적인 loopback copilot_ci DB를 먼저 검사하고, 전용 PostgreSQL service에서 migration·Backend·평가·web·browser를 실행한다. OpenAI/G2B API key를 사용하지 않는다. Supabase·수집기 DB는 사용하지 않았다.

이 CI 진입점의 guard를 모든 로컬 pytest에 자동 적용한 것은 아니다. 일반 pytest 명령을 공용 DB 설정에서 실행해서는 안 된다. 원시 로그·JUnit·스크린샷·browser-result.json은 CI artifact에 남긴다.

## 7. 남은 gate

- 사용자/case 소유권·접근권한과 실제 분리 배포의 쿠키/CORS·로그인 UX.
- Figma 원본 자산·픽셀 비교와 디자이너 시각 검수, 사람 이해도 평가.
- 실제 수집 공고/회사 데이터를 사용하는 배포 환경 Golden Path.
- layout 메모리 수명 밖의 대화·OUTCOME_UNKNOWN 복구. read만 성공했다고 결과 불명 잠금을 풀지 않는다.
- 기존 27개 lint debt, 실제 추출 품질·등록/프로필 연결·빈 첨부 등의 기존 제품 후속 사항.

일반 message/profile/user_input 외부 LLM 전송 및 생성형 설명은 활성화하지 않았다. 이번 자동 검증 통과는 다중 사용자 공개 승인이나 자동 merge 승인이 아니다.
