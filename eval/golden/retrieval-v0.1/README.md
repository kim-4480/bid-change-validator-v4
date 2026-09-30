# 참가자격 검색 골든셋 v0.1

청크 ID 대신 원문 문자열 스팬을 라벨로 사용합니다. 청킹 방식이 바뀌어도 공백을 제거한
문자열이 청크 안에 남아 있으면 같은 라벨로 측정됩니다.

- `POSITIVE`: 실제 참가자격 요건
- `TRAP`: 참가자격 어휘를 포함하지만 요건이 아닌 목차·벌칙·평가 문언
- `document_id`: 동일 문언이 중복 문서에 있을 때 라벨의 출처를 고정
- `role`: `NOTICE`, `RFP`, `FORM`, `DUPLICATE`
- `expected_type` 등 `expected_*`: 선택 항목. 값이 있으면 단순 생존 여부가 아니라
  canonical 필드와 판정 결과까지 정확히 비교합니다.
- 판정 단계까지 측정할 케이스는 `profile_path`와 ISO 날짜 `reference_date`를 케이스에
  추가하고, 스팬에 `expected_judgment`를 지정합니다. 셋 중 하나라도 없으면 판정 칸은
  정직하게 `null`로 남습니다.

현재는 하네스 기준선을 검증하기 위한 공고 1건, POSITIVE 4개, TRAP 2개가 들어 있습니다.
품질 비교를 주장하기 전 목표는 공고 8~10건, POSITIVE 60~90개, TRAP 40개입니다.

```bash
python -m apps.api.app.scripts.retrieval_report \
  --goldenset samples/golden/retrieval-v0.1 --retriever default --json
```

기본/실험 청커 A/B와 승격 게이트:

```bash
python -m apps.api.app.scripts.retrieval_report \
  --goldenset samples/golden/retrieval-v0.1 --compare-chunkers --json
```

실제 구조화 깔때기는 명시적으로 켭니다. 모델 호출 결과가 흔들리므로 기본 3회이며,
각 실행값과 평균을 모두 출력합니다.

```bash
python -m apps.api.app.scripts.retrieval_report \
  --goldenset samples/golden/retrieval-v0.1 --chunker default \
  --with-extraction --runs 3 --json
```

캐시된 공고에서 사람이 `POSITIVE`/`TRAP`을 판정할 후보를 뽑는 명령:

```bash
python -m apps.api.app.scripts.goldenset_span_proposer --max-per-document 30
```

제안기의 `review_hint`는 정답이 아닙니다. `LIKELY_TRAP`도 반드시 사람이 원문을 보고
확정한 뒤 `spans.json`에 옮깁니다.
