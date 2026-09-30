# E0 판정 엔진 기준선 실행 결과

- 실행 대상: 현재 32 + 이전차수 8 = 40개 Fixture
- canonical input rows: 138
- 정확 일치(MATCH_DRAFT_TARGET): 104 / 138 = 75.4%
- 안전한 보류(SAFE_ABSTENTION): 34 / 138 = 24.6%
- 위험한 확정 오류: 0 / 138
- fatal errors: 0
- 전체 상태 일치: 36 / 40 = 90.0%

## 현재 32개
- 행 일치: 80 / 104 = 76.9%
- 안전한 보류: 24 / 104 = 23.1%
- 전체 상태 일치: 29 / 32 = 90.6%

## 이전차수 8개
- 행 일치: 24 / 34 = 70.6%
- 안전한 보류: 10 / 34 = 29.4%
- 전체 상태 일치: 7 / 8 = 87.5%

## Mapping별
- ATOMIZED: 일치 51/51 (100.0%), 안전한 보류 0
- DIRECT: 일치 37/46 (80.4%), 안전한 보류 9
- REVIEW_HELD: 일치 16/41 (39.0%), 안전한 보류 25

## 전체 상태 불일치 4건
- J03: expected ineligible → actual insufficient_data
- J06: expected ineligible → actual insufficient_data
- J07: expected ineligible → actual insufficient_data
- CH04-BEFORE: expected ineligible → actual insufficient_data

4건 모두 위험한 반대 확정이 아니라, 필수 미달을 UNKNOWN으로 보류하면서 전체가 insufficient_data로 올라간 사례다.

## 안전한 보류 주요 원인
- ALTERNATIVE_OR_EXCEPTION_RULE: 19
- COMPOSITE_FLAG: 14
- COMPOSITE_PARTY_RULE: 1

## 실행 재현성 주의
현재 실행 환경은 전체 Git repository를 clone할 네트워크가 없었다. 따라서 pinned commit의 판정 경로 핵심 4개 파일을 GitHub connector로 가져와 Git blob SHA를 검증한 뒤 실행했다.

검증된 blob:
- judgment.py = 3abdc2d7930af23da316272ba6c4327a9ec03c13
- clause_safety.py = 40a33a47b2b4da4ac99e8cd6fd12e1e18bd93aa5
- contracts.py = 909703675470e58d0a7869c2fea0d7c00ee4c9a2
- extensions.py = 8cc7949c1b45af289751c70ab638085291a3ba65

네 파일 모두 패키지가 고정한 Git blob SHA와 일치했다. Fixture에는 extension trigger(SW 등급/기업집단 계열) 조건이 없었다. runner는 재구성한 로컬 checkout의 commit SHA가 pinned repository SHA와 다르므로 `--allow-code-drift`로 실행했으며, 이 차이를 숨기지 않는다. 따라서 이 결과는 **고정 판정 핵심 소스의 rule-engine 실행 결과**로 사용하고, 전체 repository/API/DB E2E 실행과는 구분한다.

또한 Fixture 자체가 독립 검토자 승인 전 DRAFT이므로 이 수치를 최종 모델 정확도나 독립 holdout 성능으로 표현하지 않는다.
