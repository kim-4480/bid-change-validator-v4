"""OpenAI Structured Output adapter for qualification extraction.

This is intentionally isolated under `app.ai.providers` so the Backend team's
routers/services/settings remain untouched. The SDK import is lazy: importing the
AI package does not require `openai` to be installed until an actual model call is
made.

The adapter matches `StructuredExtractor` from requirement_extraction.py:

    extractor(system_prompt, user_body, json_schema) -> dict

It uses Chat Completions Structured Outputs because that is the same contract used
by the current LLM/RAG PoC. A future migration to another OpenAI endpoint only
needs to change this provider, not the analysis pipeline.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any

ClientFactory = Callable[[str], Any]


def _default_client_factory(api_key: str) -> Any:
    try:
        from openai import OpenAI
    except ImportError as error:  # pragma: no cover - depends on runtime extras
        raise RuntimeError(
            "OpenAI provider requires the optional `openai` package at runtime"
        ) from error
    return OpenAI(api_key=api_key)


# [재현 2026-09-14] 같은 공고를 14번 분석한 기록에서 요건 개수가 1·3·0·0·0·2·0·0·0·0·3·1·0·2
# 로 갈렸다. 청크 39개는 매 실행 동일했고 문서도 같았다. 달랐던 것은 샘플링뿐이다 —
# 이 호출에 temperature 도 seed 도 없어서 기본값(1.0)으로 돌고 있었다.
#
# 흔들리는 동안은 어떤 수정도 검증할 수 없다. "고쳤는데 어떤 실행에서는 여전히 걸린다" 가
# 되어서, 고친 것이 효과가 있었는지조차 말할 수 없다. 재현되지 않는 버그는 고칠 수 없다.
#
# 완전한 결정성은 아니다(모델 쪽 배치·버전이 바뀌면 달라질 수 있고 system_fingerprint 로만
# 알 수 있다). 그래도 우리 쪽에서 통제할 수 있는 변인은 여기서 없앤다.
DETERMINISTIC_TEMPERATURE = 0.0
DETERMINISTIC_SEED = 20260914  # 값 자체에 뜻은 없다. 바뀌지 않는다는 것이 중요하다.


def _env_float(name: str, fallback: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return fallback
    try:
        return float(raw)
    except ValueError:
        return fallback


def _env_int(name: str, fallback: int | None) -> int | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return fallback
    try:
        return int(raw)
    except ValueError:
        return fallback


class OpenAIStructuredExtractor:
    """Callable adapter that returns strict JSON-schema model output as a dict."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        client_factory: ClientFactory | None = None,
        temperature: float | None = None,
        seed: int | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model or os.getenv("OPENAI_MODEL_DEFAULT") or "gpt-5.6-luna"
        self.temperature = (
            _env_float("OPENAI_EXTRACTION_TEMPERATURE", DETERMINISTIC_TEMPERATURE)
            if temperature is None
            else temperature
        )
        self.seed = (
            _env_int("OPENAI_EXTRACTION_SEED", DETERMINISTIC_SEED)
            if seed is None
            else seed
        )
        self._client_factory = client_factory or _default_client_factory
        self._client: Any | None = None
        # 모델이 이 파라미터를 안 받으면 한 번 걸러내고 기억한다. 아래 __call__ 참고.
        self._unsupported: set[str] = set()
        self.last_system_fingerprint: str | None = None

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _get_client(self) -> Any:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        if self._client is None:
            self._client = self._client_factory(self.api_key)
        return self._client

    def _create_with_fallback(self, request: dict[str, Any]) -> Any:
        """결정성 파라미터를 안 받는 모델이면 그것만 빼고 한 번 더 시도한다.

        temperature·seed 는 모델마다 지원이 갈린다. 안 받는 모델에 보내면 호출 자체가
        실패하는데, 그러면 추출이 통째로 멈춘다 — 흔들림을 줄이려다 아예 안 도는 것은
        더 나쁘다. 거절당한 파라미터만 빼고 다시 부르고, 뺀 것을 기억해 다음 호출부터는
        처음부터 안 보낸다. 무엇이 빠졌는지는 남는다(`unsupported_parameters`).
        """
        client = self._get_client()
        while True:
            try:
                return client.chat.completions.create(**request)
            except Exception as error:  # noqa: BLE001 - SDK 예외 타입은 런타임 의존
                message = str(error).lower()
                dropped = next(
                    (
                        name
                        for name in ("temperature", "seed")
                        if name in request and name in message
                    ),
                    None,
                )
                if dropped is None:
                    raise
                request.pop(dropped)
                self._unsupported.add(dropped)

    @property
    def unsupported_parameters(self) -> tuple[str, ...]:
        """모델이 거절해서 빼고 보내는 파라미터. 비어 있어야 결정성이 걸린 것이다."""
        return tuple(sorted(self._unsupported))

    def __call__(
        self,
        system_prompt: str,
        user_body: str,
        json_schema: dict[str, Any],
    ) -> dict[str, Any]:
        if "schema" not in json_schema:
            raise ValueError("json_schema must contain a `schema` field")

        request: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_body},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": json_schema.get("name", "result"),
                    "strict": True,
                    "schema": json_schema["schema"],
                },
            },
        }
        if self.temperature is not None and "temperature" not in self._unsupported:
            request["temperature"] = self.temperature
        if self.seed is not None and "seed" not in self._unsupported:
            request["seed"] = self.seed

        response = self._create_with_fallback(request)

        # 모델 쪽 배치가 바뀌면 같은 seed 라도 결과가 달라진다. 그때 원인을 우리 코드에서
        # 찾지 않도록 지문을 남긴다.
        self.last_system_fingerprint = getattr(response, "system_fingerprint", None)

        choices = getattr(response, "choices", None)
        if not choices:
            raise RuntimeError("OpenAI response did not contain any choices")

        message = choices[0].message
        refusal = getattr(message, "refusal", None)
        if refusal:
            raise RuntimeError("OpenAI structured extraction was refused")

        content = getattr(message, "content", None)
        if not content:
            raise RuntimeError("OpenAI structured extraction returned empty content")

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as error:
            raise RuntimeError(
                "OpenAI structured extraction returned invalid JSON content"
            ) from error

        if not isinstance(parsed, dict):
            raise RuntimeError("OpenAI structured extraction must return a JSON object")
        return parsed


# NOTE(LLM/RAG 이식): 공고 요약·판정 브리핑·질의응답처럼 모델이 산문을 쓰는 경로가
# 필요해서 추가했습니다. OpenAIStructuredExtractor는 JSON 스키마 고정 출력 전용이라
# 자유 서술에 쓰면 디코딩 단계가 하나 더 붙고 실패 지점만 늘어납니다.
# 기존 클래스는 건드리지 않았습니다.
class OpenAINarrator:
    """Plain-text chat adapter for prose output (summaries, follow-up wording).

    Kept separate from the structured extractor because the two have opposite
    requirements: extraction must be schema-locked and verifiable, narration must
    be free text. Sharing one class would mean one of them carrying a JSON
    contract it does not want.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model or os.getenv("OPENAI_MODEL_DEFAULT") or "gpt-5.6-luna"
        self._client_factory = client_factory or _default_client_factory
        self._client: Any | None = None

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _get_client(self) -> Any:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        if self._client is None:
            self._client = self._client_factory(self.api_key)
        return self._client

    def __call__(self, system_prompt: str, user_body: str) -> str:
        response = self._get_client().chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_body},
            ],
        )
        choices = getattr(response, "choices", None)
        if not choices:
            raise RuntimeError("OpenAI response did not contain any choices")
        return getattr(choices[0].message, "content", None) or ""
