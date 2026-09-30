"""추출 호출이 흔들리지 않게 고정돼 있는지.

2026-09-14 에 같은 공고(R26BK01633750)를 14번 분석한 기록을 보니 요건 개수가
1·3·0·0·0·2·0·0·0·0·3·1·0·2 로 갈렸다. 대상 청크 39개는 매 실행 완전히 동일했고
문서도 같았다. 달랐던 것은 샘플링뿐이었다 — 호출에 temperature 도 seed 도 없어서
기본값(1.0)으로 돌고 있었다.

흔들리는 동안은 어떤 수정도 검증할 수 없다. 그래서 여기서 고정한다. 이 테스트는
**요청에 무엇이 실려 나가는지**를 잰다. 같은 입력에 같은 결과가 나오는지는 모델을 실제로
불러야 알 수 있고(`scripts/check_extraction_determinism.py`), CI 에서는 못 돈다.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from bidengine.providers.openai import DETERMINISTIC_SEED
from bidengine.providers.openai import DETERMINISTIC_TEMPERATURE
from bidengine.providers.openai import OpenAIStructuredExtractor


SCHEMA = {"name": "eligibility_slots", "schema": {"type": "object"}}


class _FakeCompletions:
    """거절할 파라미터를 미리 정해두는 가짜 엔드포인트."""

    def __init__(self, response, *, rejects: tuple[str, ...] = ()):
        self.response = response
        self.rejects = rejects
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(dict(kwargs))
        for name in self.rejects:
            if name in kwargs:
                raise RuntimeError(
                    f"400 Unsupported value: '{name}' is not supported with this model"
                )
        return self.response


class _FakeClient:
    def __init__(self, response, *, rejects: tuple[str, ...] = ()):
        self.completions = _FakeCompletions(response, rejects=rejects)
        self.chat = SimpleNamespace(completions=self.completions)


def _response(content='{"requirements": []}', *, fingerprint="fp_test"):
    message = SimpleNamespace(content=content, refusal=None)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message)], system_fingerprint=fingerprint
    )


def _extractor(client, **kwargs):
    return OpenAIStructuredExtractor(
        api_key="key", model="test-model", client_factory=lambda _: client, **kwargs
    )


def test_extraction_sends_a_fixed_temperature_and_seed(monkeypatch) -> None:
    """기본값으로 부르면 결정성 파라미터가 실려 나가야 한다."""
    monkeypatch.delenv("OPENAI_EXTRACTION_TEMPERATURE", raising=False)
    monkeypatch.delenv("OPENAI_EXTRACTION_SEED", raising=False)
    client = _FakeClient(_response())

    _extractor(client)("system", "user", SCHEMA)

    call = client.completions.calls[0]
    assert call["temperature"] == DETERMINISTIC_TEMPERATURE == 0.0
    assert call["seed"] == DETERMINISTIC_SEED


def test_the_seed_does_not_drift_between_calls() -> None:
    """실행마다 시드를 새로 만들면 고정한 의미가 없다."""
    client = _FakeClient(_response())
    extractor = _extractor(client)

    extractor("system", "user", SCHEMA)
    extractor("system", "다른 본문", SCHEMA)

    seeds = {call["seed"] for call in client.completions.calls}
    assert len(seeds) == 1


def test_environment_can_override_for_a_deliberate_sweep(monkeypatch) -> None:
    """분산을 일부러 보고 싶을 때가 있다. 기본이 고정이고 푸는 쪽이 명시적이어야 한다."""
    monkeypatch.setenv("OPENAI_EXTRACTION_TEMPERATURE", "0.7")
    monkeypatch.setenv("OPENAI_EXTRACTION_SEED", "42")
    client = _FakeClient(_response())

    _extractor(client)("system", "user", SCHEMA)

    call = client.completions.calls[0]
    assert call["temperature"] == 0.7
    assert call["seed"] == 42


def test_a_model_that_rejects_the_parameter_still_extracts() -> None:
    """흔들림을 줄이려다 추출이 아예 안 도는 것은 더 나쁘다.

    거절당한 파라미터만 빼고 다시 부르고, 무엇이 빠졌는지는 남긴다.
    """
    client = _FakeClient(_response(), rejects=("temperature",))
    extractor = _extractor(client)

    result = extractor("system", "user", SCHEMA)

    assert result == {"requirements": []}
    assert extractor.unsupported_parameters == ("temperature",)
    # 첫 호출은 temperature 를 실었고, 두 번째는 빼고 보냈다.
    assert "temperature" in client.completions.calls[0]
    assert "temperature" not in client.completions.calls[1]
    assert client.completions.calls[1]["seed"] == DETERMINISTIC_SEED


def test_the_dropped_parameter_is_not_retried_on_every_call() -> None:
    """한 번 거절당한 것을 매번 다시 보내면 호출이 두 배가 된다."""
    client = _FakeClient(_response(), rejects=("seed",))
    extractor = _extractor(client)

    extractor("system", "user", SCHEMA)
    calls_after_first = len(client.completions.calls)
    extractor("system", "user", SCHEMA)

    assert calls_after_first == 2  # 실패 1 + 재시도 1
    assert len(client.completions.calls) == 3  # 두 번째 호출은 한 번에 끝난다
    assert "seed" not in client.completions.calls[2]


def test_an_unrelated_failure_is_not_swallowed() -> None:
    """파라미터 탓이 아닌 실패까지 조용히 재시도하면 진짜 오류를 가린다."""

    class _Boom(_FakeCompletions):
        def create(self, **kwargs):
            raise RuntimeError("429 rate limit exceeded")

    client = _FakeClient(_response())
    client.chat = SimpleNamespace(completions=_Boom(_response()))

    with pytest.raises(RuntimeError, match="rate limit"):
        _extractor(client)("system", "user", SCHEMA)


def test_the_model_batch_fingerprint_is_kept() -> None:
    """같은 시드라도 모델 쪽 배치가 바뀌면 결과가 달라진다.

    그때 원인을 우리 코드에서 찾지 않도록 지문을 남긴다.
    """
    client = _FakeClient(_response(fingerprint="fp_20260914"))
    extractor = _extractor(client)

    extractor("system", "user", SCHEMA)

    assert extractor.last_system_fingerprint == "fp_20260914"
