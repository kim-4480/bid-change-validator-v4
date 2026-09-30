import os
from pathlib import Path
import subprocess
import sys

import pytest

from apps.api.app.scripts.quality_eval_report import build_report

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "eval/golden/qualification-quality-v0.1"


def test_selection_only_does_not_claim_extraction():
    report = build_report(DATA)
    assert report["model_quality_claim"] is False
    case = report["cases"][0]
    assert case["analysis"] is None
    assert case["metrics"]["canonical_match"]["value"] is None


def test_synthetic_pipeline_preserves_unmapped_evidence():
    report = build_report(DATA, synthetic_extraction=True)
    assert report["mode"] == "synthetic-harness-check"
    case = report["cases"][0]
    assert case["metrics"]["canonical_match"]["value"] == 1
    assert case["metrics"]["evidence_preserved"]["value"] == 1
    # UNMAPPED_REQUIREMENT 는 "공고에서 확인했으나 닫힌 유형으로 판정할 성질이
    # 아님" 이라는 정상 결과다. 파이프라인이 요건을 잃은 것과는 뜻이 다르므로
    # 분석 품질 저하(PARTIAL)로 보지 않는다 — 근거는 남기고 상태는 SUCCEEDED.
    assert case["analysis_status"] == "SUCCEEDED"
    fact = next(
        d for d in case["analysis"]["diagnostics"] if d["code"] == "UNMAPPED_REQUIREMENT"
    )
    assert fact["kind"] == "NOTICE_FACT"
    assert fact["evidence_keys"], "판정 대상이 아니어도 근거는 보존되어야 한다"
    assert case["extractor_calls"] == 1


def test_cli_runs_without_db_demo_or_network_modules():
    code = '''
import runpy, sys
def deny_network(event, args):
    if event in {"socket.connect", "socket.getaddrinfo"}:
        raise AssertionError("offline evaluation attempted network access")
sys.addaudithook(deny_network)
sys.argv = ["quality_eval_report", "--dataset", "eval/golden/qualification-quality-v0.1", "--synthetic-extraction"]
runpy.run_module("apps.api.app.scripts.quality_eval_report", run_name="__main__")
assert not any(".demo" in name or "sqlalchemy" in name or "fastapi" in name for name in sys.modules)
'''
    # 리포트에 한글 진단 문구가 들어간다. Windows 기본 인코딩(cp949)으로 읽으면
    # UnicodeDecodeError 로 캡처 자체가 실패해 stdout 이 None 이 된다.
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run([sys.executable, "-B", "-c", code], cwd=ROOT, env=env,
                            capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    assert result.returncode == 0, result.stderr
    assert '"model_quality_claim": false' in result.stdout


# ── 반복 측정 ────────────────────────────────────────────────────────────
# 모델은 같은 입력에도 매번 다르게 답한다. 한 번 돌린 수치를 정확도라고 부르면
# 다음 실행에서 달라지므로, 여러 번 돌려 평균과 개별 값을 함께 남긴다.
def _synthetic_extractor(case, *, flaky=False):
    import copy

    state = {"calls": 0}

    def extractor(_system, _body, _schema):
        state["calls"] += 1
        slots = copy.deepcopy(case.spec.synthetic_slots)
        # 두 번째 호출만 빈 결과를 준다 — 모델이 흔들리는 상황을 흉내낸다.
        if flaky and state["calls"] == 2:
            return {"requirements": []}
        return {"requirements": slots}

    return extractor


def _synthetic_case():
    from bideval.golden.fixtures import load_dataset

    return load_dataset(DATA).cases[0]


def test_repeated_runs_keep_each_value_next_to_the_mean() -> None:
    from bideval.runner import evaluate_case_runs

    case = _synthetic_case()
    report = evaluate_case_runs(
        case, structured_extract=_synthetic_extractor(case, flaky=True), runs=3
    )

    assert report["run_count"] == 3
    assert len(report["runs"]) == 3

    canonical = report["metrics"]["canonical_match"]
    # 개별 값이 남아야 "3번 중 2번" 과 "매번 66%" 를 구분할 수 있다.
    assert len(canonical["runs"]) == 3
    measured = [v for v in canonical["runs"] if v is not None]
    assert canonical["value"] == sum(measured) / len(measured)

    # 이 케이스의 판정 가능한 요건은 업종코드 1468 하나다. 모델이 빈 결과를 준 실행에서도
    # 코드가 원문에서 채우므로 일치율은 안 떨어진다 — 그게 의도다. 모델이 실제로
    # 흔들렸다는 사실은 채운 횟수로 남아야 한다: 두 번째 실행에서만 1.
    assert [r["salvaged_from_source"] for r in report["runs"]] == [0, 1, 0],         "흔들리는 추출기인데 코드가 채운 흔적이 없다"


def test_deterministic_stages_are_verified_not_averaged() -> None:
    """청킹·컨텍스트는 모델을 타지 않는다. 달라지면 측정기가 흔들린 것이다."""
    from bideval import runner

    case = _synthetic_case()
    report = runner.evaluate_case_runs(
        case, structured_extract=_synthetic_extractor(case), runs=2
    )
    # 평균이 아니라 원래 값 그대로다.
    assert "runs" not in report["metrics"]["span_containment"]
    assert report["chunk_health"]["count"] > 0

    original = runner.evaluate_case

    def drifting(case, *, structured_extract=None):
        result = original(case, structured_extract=structured_extract)
        drifting.seen += 1
        if drifting.seen > 1:
            result["chunk_health"] = {**result["chunk_health"], "count": 999}
        return result

    drifting.seen = 0
    runner.evaluate_case = drifting
    try:
        with pytest.raises(ValueError, match="deterministic stage varied"):
            runner.evaluate_case_runs(
                case, structured_extract=_synthetic_extractor(case), runs=2
            )
    finally:
        runner.evaluate_case = original


def test_repeated_runs_require_an_extractor() -> None:
    from bideval.runner import evaluate_case_runs

    with pytest.raises(ValueError, match="extractor is required"):
        evaluate_case_runs(_synthetic_case(), structured_extract=None, runs=3)
