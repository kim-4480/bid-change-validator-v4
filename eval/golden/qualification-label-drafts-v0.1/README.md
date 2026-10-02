# 참가자격·위험조항 라벨 검토 시안 v0.1

실제 공고 snapshot을 바탕으로 작성한 **사람 검토 전 후보 라벨**입니다.
`qualification-real-v0.1`의 승인된 정답이 아니며, 평가 점수 산출에 사용하지 않습니다.

## 검토 상태

- `DRAFT`: 자동 초안. 정답으로 사용 금지
- `REVIEWED`: 사람이 원문과 위치를 확인함
- `APPROVED`: 팀이 평가용 정답으로 승인함
- `REJECTED`: 오탐 또는 잘못된 구조화로 확인됨

각 항목의 `review_decision`을 `APPROVE`, `EDIT`, `REJECT` 중 하나로 바꾸고
`reviewer_note`에 수정 이유를 적어 주세요. 현재 값 `PENDING`은 미검토 상태입니다.

## 파일 구성

- `cases/C01.json`: 공고 `R26BK01705963`의 첫 검토 시안
  - 참가자격 원문 후보 8건
  - canonical 변환 후보 4건
  - canonical 비대상 후보 4건
  - 계약 위험조항 판정 후보 5건

## 라벨 해석

- `source_requirements`: 공고의 참가자격 섹션에서 확인한 원문 조건
- `canonical_candidate`: 회사 프로필과 코드로 대조할 수 있는 8종 요건 후보
- `expected_diagnostic`: 원문 조건이지만 현재 8종으로 안전하게 표현할 수 없는 항목
- `risk_findings`: 9종 계약 위험조항의 기대 판정 후보
- `confidence`: 초안 작성 확신도이며 정답 확률이나 모델 점수가 아님

`category`/`categories`에는 오류 코드, `risk_type`/`risk_types`에는 현재 API가
반환하는 한글 라벨을 기록합니다. 대표값은 판정 우선순위
`NEEDS_REVIEW → UNDETERMINED → COMPLIANT`, 동률이면 9종 고정 순서를 따릅니다.

## 검토 시 특히 볼 항목

1. `Q-C01-004`: 대기업·중견기업 배제를 `COMPANY_SIZE` 하나로 표현해도 되는지
2. `Q-C01-007`: 소프트웨어사업자 신고와 실적 등록을 하나의 등록요건으로 볼지
3. `R-C01-004`: 지급기한 수치가 없으므로 `PAYMENT_TERMS` 탐지 자체를 오탐으로 볼지
4. `R-C01-005`: 제3자 지식재산권 침해 배상을 일반 손해배상 과다로 볼지

