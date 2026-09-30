# AI Copilot two-job integration result

## 기준과 브랜치

- 기준 브랜치: `origin/develop`
- 기준 커밋: `81b352f3cdc3cf609a91d29994699ad23473bdb7`
- 작업 브랜치: `feature/copilot-two-job-integration`
- PR #136의 추출·판정 규칙과 PR #145의 회사 프로필 편집을 기준으로 선택 통합했다.
- 보존 브랜치 `codex/ai-copilot-evaluation-ready`는 병합하지 않았고, 공유 판정·출처 복구 WIP도 복사하지 않았다.

## 제품 계약

서버가 아래 두 Job과 여섯 질문의 순서, 조회 범위, 완료 기준을 소유한다.

1. 변경 공고 대응
   1. 무엇이 바뀌었나요?
   2. 우리 회사에 어떤 영향이 있나요?
   3. 무엇을 확인해야 하나요?
2. 입찰 참여 준비
   1. 필요한 서류·기한·방법은?
   2. 준비 순서는?
   3. 아직 확인하지 못한 것은?

UI는 `GET /api/v1/copilot/jobs` 결과만 렌더링한다. 자유 입력, 독립 조건 메뉴, 추가 답변 메뉴, 쓰기 확장은 안내형 패널에서 제거했다. 안내형 요청은 자유 텍스트 planner를 거치지 않고 서버 계획을 사용한다.

## 경계

- 변경 비교는 현재 case의 기준 차수와 현재 차수만 사용한다.
- 회사 영향은 동일 회사 snapshot, 규칙 버전, 기준일로 연결된 저장 재검증이 있을 때만 설명한다.
- 편집된 현재 회사 프로필과 저장 판정 snapshot이 다르면 과거 판정을 현재 회사 설명으로 사용하지 않는다.
- 구조화 변경과 원문 추출 차이를 분리하며, 추출 추가·삭제를 법적 변경으로 단정하지 않는다.
- 안내형 답변의 모든 게시 주장은 서버 fact/source 연결을 정규화한 뒤 의미 검증을 통과해야 한다.
- 검증 실패 시 원문 전체를 본문에 덤프하지 않고 검증된 주장과 제한만 표시한다.
- 서류, 확인사항, 준비 순서는 서버가 필수 문서군·분류·행동·강제 순서를 기계적으로 확인해 모델의 범위 확장을 보정한다.
- LangChain은 현재 문서 retriever, prompt/message 조립, structured runnable에 사용한다. 자격증명, 재시도, 저장, 판정 경로는 소유하지 않는다.

## 검증

자동화:

- Copilot v3.1, guided jobs, chat contract: `279 passed`
- 변경 프런트 파일 oxlint: 통과
- 프런트 production build: 통과
- 전체 저장소 lint는 기존 공용 UI lint 오류 때문에 여전히 실패하며, 이번 변경 파일의 오류는 없다.
- 외부 공유 DB에는 쓰지 않았다. 로컬 Docker DB의 현재 규칙 `qualification-rules-v0.3` 계보만 추가로 준비했다.

실제 모델 평가:

- 평가 대상: 남원 합성 프로필 J13~J16, 각 6문항, 총 24턴
- 최종 일괄 실행: 23/24 COMPLETE
- J14, J15, J16: 각 6/6 COMPLETE
- J13: 5/6 COMPLETE. `준비 순서는?`에서 권장 순서 후보 두 개가 잘못된 fact 참조로 제거되어 PARTIAL이었고, 게시된 나머지 7개 주장은 모두 SUPPORTED였다.
- HTTP, case/source scope, 내부 식별자 노출, 예상하지 않은 write action 오류: 0건
- 답변 길이: 최대 945자
- 응답시간: 평균 26.92초, 최대 54.13초
- 예산 상한은 올리지 않았고 최종 일괄 실행 뒤에도 잔여 상한이 있었다.

로컬 영수증:

- `.ci-results/two-job-evaluation/engine-preparation.json`
- `.ci-results/two-job-evaluation/summary-all.json`
- `.ci-results/two-job-evaluation/J13/report.json` ~ `J16/report.json`

이 영수증은 ignore된 로컬 평가 산출물이며 커밋 대상이 아니다. 과거 v0.4 판정 결과는 현재 엔진 검증으로 재사용하지 않았다.

## UI 확인

- 두 Job과 여섯 질문만 표시됨
- 처리 중 토글, 여섯 질문, 새 대화가 비활성화됨
- 상세 근거·검토 상태는 기본 접힘
- 자유 입력 및 독립 action 메뉴 없음
- claims/status/clarification이 없는 경우 제한 사유가 핵심 영역에 표시되도록 보완함
- 제한 경로에서도 내부 `READ_*` 이름이나 오류 코드를 사용자 문장에 노출하지 않음

현재 브라우저의 기존 J05 로그인과 선택한 남원 사례의 회사 snapshot이 일치하지 않아 실제 UI 답변은 제한 경로로 확인했다. J13~J16의 내용 정확성은 별도 격리 API 실행 보고서로 검증했다.

## 남은 제한

- 구조화 모델 출력은 비결정적이므로 동일 코드 반복에서도 한 문항이 COMPLETE와 PARTIAL 사이에서 변할 수 있다. 서버는 실패 주장을 게시하지 않고 PARTIAL을 유지한다.
- 안내형 문항의 최악 응답은 60초 복구 상한에 근접할 수 있다.
- process-memory 대화 저장은 서버 재시작 시 초기화되고 단일 worker를 전제로 한다.
- 이번 작업은 커밋, push, PR 생성, 배포를 포함하지 않는다.
