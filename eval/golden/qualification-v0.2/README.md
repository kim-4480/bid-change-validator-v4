# 골든셋 v0.2 — frozen fixture

팀 공용 폴더 `협업자료-3차프로젝트/golden_runner_v02` 의 **사본**이다. 원본은 그쪽이고,
여기 있는 것은 CI 가 매 PR 마다 판정 코드의 회귀를 재기 위한 고정본이다.

| 파일 | 뜻 |
|---|---|
| `fixture_bundle.json` | 공고 20건 · 회사 입력 32세트 · 이전차수 8 · 변경 비교 8. 기대값은 **독립 검토자 승인 전 초안** |
| `baseline_993e5cf.json` | 골든셋 v0.2 최초 실행 결과(2026-09-12). 추출 재현율 하네스가 판정 결과를 읽는 데 쓴다 |
| `checksums.sha256` | 위 두 파일의 sha256. 실행기가 먼저 대조하고, 다르면 멈춘다 |
| `summary.json` | 회귀 기준선과 게이트. 상세 결과는 여기 두지 않는다 |

## 돌리는 법

```
python scripts/run_golden_regression.py                       # 게이트 적용, 통과/실패
python scripts/run_golden_regression.py --no-gate --out r.json  # 결과만
```

게이트는 둘이다 — **잘못된 확정 0**, **초안 기대값 일치가 기준선 아래로 내려가지
않음**. 보류 자체에 별도 상한을 두지는 않지만, 기준 일치였던 행이 UNKNOWN 으로 바뀌어
일치 수가 기준선 아래로 내려가는 회귀는 막는다.

workflow는 누락되는 판정 의존 모듈이 없도록 `develop`·`main` 대상 모든 PR에서 실행한다.
실제 merge 차단에는 GitHub ruleset에서 `golden-regression / judge`를 required status
check로 별도 지정해야 한다. workflow 파일만으로 required check가 설정되지는 않는다.

## 원본이 바뀌면

팀 폴더의 골든셋이 갱신되면 두 파일을 다시 복사하고 `checksums.sha256` 과
`summary.json` 의 `fixture_sha256` 을 함께 갱신한다. 셋이 어긋나면 실행기가 멈춘다.

## 이 숫자가 보증하지 않는 것

이 실행기는 골든셋의 canonical 요건을 판정 코드에 **직접 넣는다.** 제품이 실제로 그
요건을 첨부에서 추출해 내는지는 재지 않는다. #128 에서 정답 요건 3개가 원문에 다 있는데
판정 코드에 도달한 것이 0개인 공고가 나왔고, 이 실행기는 그것을 볼 수 없었다. 그 구간은
`scripts/run_extraction_recall.py --source live` 가 재며, DB 와 OPENAI_API_KEY 가 필요해
CI 밖에서 돌린다. 두 숫자를 같이 읽어야 한다.
