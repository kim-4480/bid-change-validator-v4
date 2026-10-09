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
- PR #20·#21의 영향 플래너와 API adapter는 테스트되었지만 현재 재검증 write 경로에 연결되어 있지 않다. 재검증 통합을 완료했다고 주장하지 않는다.
- PR #7의 READ ONLY 감사에서 기존 분석 189건 모두 `input_fingerprint=NULL`이며 안전한 백필 가능 건수는 0이었다. 025 적용 뒤에는 재분석 전까지 stale이다. 이 데이터와 연결된 사용자 흐름의 전환 계획이 필요하다.
- AWS `/health`는 200이지만, 배포된 이미지 SHA·운영 RDS revision과 새 코드의 호환성은 이 검증만으로 증명되지 않는다.

## 안전한 후속 순서

1. 선행 PR을 각각 검토하고 사용자 승인 후 의존 순서대로 병합한다. #21은 #20 뒤에 둔다.
2. 병합된 최신 `develop`을 이 Draft 통합 브랜치에 merge하여 중복 diff를 없애고, 통합 전용 수정만 남았는지 확인한다.
3. PR #30 CI와 격리 DB 테스트를 다시 실행한다. 그 전에는 Draft를 해제하거나 병합하지 않는다.
4. 별도 승인과 백업·롤백 계획으로 운영 RDS 025 및 기존 분석 재생성 범위를 결정한다. 스키마 게이트가 API 이미지의 Alembic head를 요구하므로 API 배포를 DB migration보다 먼저 하지 않는다.
5. 사람 검수 추천 데이터와 Champion 승인 후 실제 모델 추론 및 AWS E2E를 검증한다. Fallback 결과를 모델 성능으로 보고하지 않는다.

이 문서 작성 과정에서 AWS/RDS/S3/ECR/SSM의 쓰기, 배포, PR 병합은 수행하지 않았다.
