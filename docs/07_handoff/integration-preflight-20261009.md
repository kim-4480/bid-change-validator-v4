# BidCheck v4 통합 사전 검증 (2026-10-09)

## 범위

Draft PR #30은 최신 `develop` 위에 미병합 PR #7, #14, #15, #20, #21, #22, #24, #28, #29를 로컬에서 결합해 검증한 작업본이다. 선행 PR을 대체하거나 한 번에 병합하지 않는다. #21은 #20 뒤에 병합해야 한다.

통합 전용 수정은 ML 추천 API/Frontend 연결과 자격분석 lineage 적용이다. 문서 재추출 후 `(document_id, extracted_text_sha256)` 집합이 달라진 분석은 ML 적격 추천에서 제외한다. 더 최근의 stale 분석이 있어도 이전 valid 분석은 선택하되, 최신 valid 분석이 `FAILED`이면 이전 성공으로 되돌리지 않는다. 기존 `NULL` fingerprint는 stale로 취급한다.

## 검증 결과

| 항목 | 결과 |
|---|---|
| 격리 PostgreSQL 17의 Alembic 025 적용 | PASS |
| Backend 전체 | 764 passed, 2 skipped |
| Engine/Eval 전체 | 648 passed |
| Golden gate | PASS: 40 cases, 138 rows, 초안 기대값 105, 안전 보류 33, 잘못된 확정 0 |
| Frontend unit / lint / TypeScript / build | PASS: unit 19 passed |
| Playwright | PASS: 15 passed, API mock 기반 |
| Draft PR #30 GitHub CI | 6개 검사 PASS |

## 아직 완료가 아닌 항목

- 실제 Browser → AWS API → 승인된 학습 모델 추론은 `NOT_RUN`이다. 사람 검수 추천 학습/holdout 데이터와 승인된 Champion 모델이 확인되지 않았다. 현재 런타임은 승인된 모델이 없으면 `lexical_fallback`으로 동작한다.
- 2026-10-09 추가 작업에서 PR #20·#21의 영향 플래너를 재검증 write 경로에 연결했다. 아래의 후속 검증 결과를 참고한다. 승인된 실제 공고/기업 데이터에서의 제품 품질 검증까지 완료했다는 뜻은 아니다.
- PR #7의 READ ONLY 감사에서 기존 분석 189건 모두 `input_fingerprint=NULL`이며 안전한 백필 가능 건수는 0이었다. 025 적용 뒤에는 재분석 전까지 stale이다. 이 데이터와 연결된 사용자 흐름의 전환 계획이 필요하다.
- AWS `/health`는 200이지만, 배포된 이미지 SHA·운영 RDS revision과 새 코드의 호환성은 이 검증만으로 증명되지 않는다.

## 안전한 후속 순서

1. 선행 PR을 각각 검토하고 사용자 승인 후 의존 순서대로 병합한다. #21은 #20 뒤에 둔다.
2. 병합된 최신 `develop`을 이 Draft 통합 브랜치에 merge하여 중복 diff를 없애고, 통합 전용 수정만 남았는지 확인한다.
3. PR #30 CI와 격리 DB 테스트를 다시 실행한다. 그 전에는 Draft를 해제하거나 병합하지 않는다.
4. 별도 승인과 백업·롤백 계획으로 운영 RDS 025 및 기존 분석 재생성 범위를 결정한다. 스키마 게이트가 API 이미지의 Alembic head를 요구하므로 API 배포를 DB migration보다 먼저 하지 않는다.
5. 사람 검수 추천 데이터와 Champion 승인 후 실제 모델 추론 및 AWS E2E를 검증한다. Fallback 결과를 모델 성능으로 보고하지 않는다.

이 문서 작성 과정에서 AWS/RDS/S3/ECR/SSM의 쓰기, 배포, PR 병합은 수행하지 않았다.

## 2026-10-09 PR #30 후속 통합 검증

- 재검증은 두 차수의 문서 ID·추출 텍스트 SHA256 fingerprint, 문서 원본 SHA256, 완전한 추출·커버리지, 현재 차수의 인용문 위치·원문·해시, 동일 기업 스냅샷·규칙·분석 계약·기준일, 기준 차수의 PROFILE 판정이 모두 확인된 요건만 재사용한다. 변경 요건은 근거가 검증될 때만 재판정하고, 미검증 근거는 변경 여부와 무관하게 UNKNOWN/REVIEW로 남긴다. 기존 판단/근거 이력은 삭제하지 않는다. 실제 LLM provider/model ID는 과거 분석에 저장되지 않았으므로 `contract_version`을 호환 토큰으로 사용하지만, 이 값 하나로 재사용을 승인하지 않는다.
- 격리 PostgreSQL 17에서 Backend 전체 **770 passed, 2 skipped**, Engine/Eval **648 passed**, Frontend 단위 **19 passed**. 근거가 없는 legacy fixture는 이전 판정을 재사용하지 않고 REVIEW, 완전한 문서/인용 fixture는 변경되지 않은 PROFILE 판정만 재사용한다. 관리자 이력 작업 조회·재대기는 `SYSTEM_ADMIN`만 허용하며 자동 재시도는 3회다. 3회 소진 상태로 중단된 RUNNING 작업은 FAILED로 전환해 관리자 재대기 대상에 포함한다.
- 로컬 복원 PostgreSQL 17(운영 DB 아님, 읽기 전용)에서 미라벨 기업 30개·현재 공고 500개를 조회해 2,000쌍과 로컬 전용 검수 양식(`local-artifacts/ml-review-20261009-verified-splits/review_template.csv`)을 만들었다. 실제 사람 승인 라벨은 **0건**. 원본 36개 기업 중 명칭상 명백한 합성/Golden 기업이 33개이므로 **실제 기업–공고 학습셋을 확보했다고 주장할 수 없다**. 분할 후보는 train 907, validation 15, test 24, review_only 1,054쌍이며 가족 단위·시간 경계·기업 분리를 적용했다. test의 기업 질의가 5개뿐이라 Champion의 최소 20개 테스트 질의 조건도 미달한다. 분할 가능성은 학습/평가 가능성이나 품질 성능을 뜻하지 않는다.
- Mock 없는 격리 브라우저 E2E에서 Web→API→PostgreSQL 공고 추천·자격검토·Copilot 저장 판정 요약이 모두 200이었다. 추천은 `lexical_fallback`을 명시하고 미검증 공고를 `needs_review_items`에만 표시했다. 관리자 화면→실제 관리자 API→PostgreSQL의 실패 작업 재대기까지 200으로 확인했다. 외부 LLM/RAG 실호출과 승인된 LightGBM/Encoder 모델 추론은 **NOT_RUN**이다.
- 로컬 복원 DB는 Alembic 024이며 분석 189건(FAILED 24, PARTIAL 93, SUCCEEDED 72), 기존 `input_fingerprint` 컬럼 없음. 근거 1,121행 중 추출 텍스트 해시는 1,120행에 있으나 분석 당시 **전체 문서 집합**을 증명하지 못한다. 안전한 무조건 백필은 **0건**으로 유지한다. 운영 025 적용과 재분석은 실행하지 않았다.

### 189건 전환·복구 계획 (운영 적용 아님)

1. 운영 변경 전 동일 시점 DB 백업, 공고·분석·판정·근거 건수와 해시 기준선, 적용될 API 이미지 SHA, 025 migration head를 승인받는다.
2. 025를 별도 승인된 유지보수 창에 적용한다. 과거 189건은 NULL fingerprint로 보수적으로 stale 처리하고 자동 백필·일괄 재분석·삭제를 하지 않는다. UI/API는 과거 결과를 최신으로 노출하지 않아야 한다.
3. 활성·발표 대상 공고부터 문서 추출 완전성/원본 해시를 확인한 뒤 비용·동시성 한도를 둔 소량 재분석을 수행한다. 새 분석 fingerprint·requirements·evidence를 검증하고 각 기업 판정은 새 분석 및 당시/현재 프로필을 구별하여 다시 생성한다. 기존 기록은 이력으로 보존한다.
4. 배치마다 valid/stale/FAILED, 근거 hash, 판정 차이를 검수하고 실패하면 해당 배치 중지한다. 복구는 기존 DB 백업·기존 API 이미지로 서비스 조합을 되돌리되, 025 컬럼을 임의로 drop하지 않는다. 운영 RDS 쓰기·배포는 별도 사용자 승인 전 금지한다.

### 22개 고도화 영역 상태 점검

| # | 영역 | 확인된 구현 / 남은 검증 |
|---|---|---|
| 1 | 공고 수집 | poller·history backfill 존재. AWS 수집 E2E 미검증 |
| 2 | PDF/HWP/HWPX | 추출·재처리 서비스 존재. 실제 실패 전수 미검증 |
| 3 | 자격요건 구조화 | 분석 파이프라인 존재. 승인 Golden recall 목표 미측정 |
| 4 | 판정·Ask-back | API와 회귀 존재. 실제 복잡 공고 품질 미완료 |
| 5 | 변경 추적·영향 | PR #30에서 플래너를 재검증 실행에 연결. 실데이터 검수 필요 |
| 6 | 맞춤 추천 | API·UI 연결, Fallback 확인. 학습 모델 없음 |
| 7 | ML/DL 학습 | 학습기 존재. 승인 라벨 0건으로 실제 학습/검증 차단 |
| 8 | Hybrid RAG | 검색 모듈 존재. 비Mock 제품 E2E 미검증 |
| 9 | AI Copilot | 저장 판정 요약 브라우저 E2E 통과. LLM 상세/근거 검색 미검증 |
| 10 | LLM 최적화 | 비용/캐시 모듈 일부. 공급자별 동시성·지연 실측 미검증 |
| 11 | OpenAI·GLM 비교 | OpenAI adapter 존재. GLM 실호출 비교 결과 없음 |
| 12 | PostgreSQL Job Queue | history backfill 영속 큐·관리자 조회/재대기 연결. 범용 분석/추출 큐 없음 |
| 13 | 캐시·증분 | 문서/분석 fingerprint 일부. 제품 전체 증분 검증 미완료 |
| 14 | DB 조회 성능 | 추천 SQL 배치/분석 이력 제한 구현. 실데이터 부하 검증 필요 |
| 15 | OpenSearch·Nori | 로컬 비교 코드 존재. 실측 결과 없음 |
| 16 | Golden 평가 | 회귀 gate 존재. 인간 승인 정답과 3회 반복 측정 미확보 |
| 17 | MLflow | 로컬 기록 코드 존재. 실제 승인 모델 실험 없음 |
| 18 | 관리자·라벨링 | history 작업만 UI/API 연결. Golden 승인·감사 이력 API 없음 |
| 19 | CI/CD | CI와 AWS workflow 존재, 자동 게시 차단 유지. 실배포 갱신 없음 |
| 20 | AWS/Terraform | AWS 리소스는 기존 환경으로 존재. 저장소 내 Terraform `.tf` 파일 미확인 |
| 21 | 관측성 | 로그는 존재. OpenTelemetry/제품 지표 E2E 미확인 |
| 22 | 보안·복구 | 기존 인증/RBAC·백업 계획 일부. 운영 복구 실습 미실행 |

이 표는 코드·이번 격리 검증에서 확인한 최소 사실만 적은 것으로, 22개가 완료되었다는 뜻이 아니다.
