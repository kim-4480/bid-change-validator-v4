# 공고 표본 수집과 기본값 전환 비교 (실행 안내)

클라우드 세션에서는 공공데이터포털·나라장터가 연결 직후 끊긴다(해외 IP 차단으로 추정, 2026-10-01). 표본 수집은 **국내 네트워크의 PC**에서 하고, 결과를 커밋하면 비교는 어디서든 돌릴 수 있다.

## 1. 표본 수집 (로컬 PC)

수집 단계는 `apps/api` 의존성만 있으면 된다(`bidengine`·`bideval` 은 2단계에서만 쓴다). 인증키는 환경변수 `G2B_SERVICE_KEY` 또는 **저장소 루트의 `.env`** 에서 읽고, 공공데이터포털이 주는 퍼센트 인코딩 형태를 스크립트가 한 번 풀어 쓴다(인코딩된 키를 그대로 두면 된다).

Git Bash / macOS / Linux:

```bash
pip install -r apps/api/requirements-dev.txt
PYTHONPATH=$PWD python eval/experiments/collect_notice_sample.py \
    --days 7 --notices 12 --changed 6 \
    --out eval/golden/notice-sample-$(date +%Y%m%d)
```

Windows PowerShell (`python3` 은 스토어 스텁이라 `python` 을 쓴다):

```powershell
pip install -r apps/api/requirements-dev.txt
$env:PYTHONPATH = (Get-Location).Path
python eval/experiments/collect_notice_sample.py --days 7 --notices 12 --changed 6 `
    --out "eval/golden/notice-sample-$(Get-Date -Format yyyyMMdd)"
```

- 등록공고: 용역·물품·공사에서 공고문(HWP/HWPX/PDF/DOCX)이 추출되는 공고 `--notices` 건.
- 변경공고: 최근 변경된 공고 `--changed` 건의 **모든 차수**. 차수 비교(S4) 검증에 쓴다.
- 남는 것은 텍스트 블록(JSON)과 출처(URL·파일 해시)뿐이다. 원본 파일은 저장하지 않는다.
- 결과 디렉터리를 커밋·push 한다.

## 2. 비교 (OpenAI 접속이 되는 곳)

이 단계는 엔진·측정 패키지가 필요하다: `pip install -e engine -e eval`.

```bash
python eval/experiments/sample_compare.py \
    --sample eval/golden/notice-sample-YYYYMMDD \
    --runs 3 --models gpt-5.6-luna gpt-6-luna --out artifacts/sample_compare.json
```

호출 수 = 차수 수 × 2(방식) × 모델 수 × runs. 결과는 계산 전에 먼저 저장되고 `--reuse` 로 다시 계산할 수 있다.

| 지표 | 뜻 |
| --- | --- |
| anchor_stability | 요건을 (유형, 원문 조항)으로 식별한 반복 일치도 |
| value_stability | (유형, 연산자, 값, 기간, 분야)로 식별한 반복 일치도 |
| rerun_false_change_rate | 같은 차수를 다시 추출해 차수 비교했을 때 UNCHANGED 가 아닌 비율 |
| change_detection_agreement | 변경공고 차수 쌍마다 실행 조합별 변경 집합의 일치도 |
| judged_mean / coverage_complete_rate | 판정 요건 수 / 커버리지 완료율 |

## 3. 전환 기준

clause 가 legacy 보다 anchor_stability·rerun_false_change_rate·change_detection_agreement 에서 낫고 judged_mean 이 떨어지지 않으면 배포 설정을 바꾼다.

```bash
BIDENGINE_EXTRACTION_MODE=clause
OPENAI_MODEL_DEFAULT=<더 나은 모델>
```

## 레포 실데이터셋으로 한 시험 (2026-10-01, gpt-6-luna, 2회)

공고 4건 + G2 1·2차를 수집기 표본 형식으로 바꿔 러너를 끝까지 돌렸다.

| 지표 | legacy | clause |
| --- | --- | --- |
| anchor_stability | 0.35 | **1.00** |
| value_stability | 0.867 | **0.933** |
| rerun_false_change_rate | 0.474 | **0.048** |
| change_detection_agreement | 0.556 | **1.00** |
| judged_mean | 2.83 | **3.50** |
| coverage_complete_rate | 0.167 | 0.167 |
| seconds_mean | 30.4 | **24.8** |
