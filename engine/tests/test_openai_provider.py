from types import SimpleNamespace

import pytest

from bidengine.providers.openai import OpenAIStructuredExtractor


class _FakeCompletions:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class _FakeClient:
    def __init__(self, response):
        self.chat = SimpleNamespace(completions=_FakeCompletions(response))


def _response(content='{"requirements": []}', *, refusal=None):
    message = SimpleNamespace(content=content, refusal=refusal)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def test_openai_adapter_uses_strict_json_schema_without_real_sdk():
    fake_client = _FakeClient(_response())
    created_keys = []

    def client_factory(api_key):
        created_keys.append(api_key)
        return fake_client

    extractor = OpenAIStructuredExtractor(
        api_key="test-key",
        model="test-model",
        client_factory=client_factory,
    )

    result = extractor(
        "system",
        "user",
        {
            "name": "eligibility_slots",
            "schema": {
                "type": "object",
                "properties": {"requirements": {"type": "array"}},
                "required": ["requirements"],
                "additionalProperties": False,
            },
        },
    )

    assert result == {"requirements": []}
    assert created_keys == ["test-key"]
    call = fake_client.chat.completions.calls[0]
    assert call["model"] == "test-model"
    assert call["response_format"]["type"] == "json_schema"
    assert call["response_format"]["json_schema"]["strict"] is True
    assert call["response_format"]["json_schema"]["name"] == "eligibility_slots"


def test_openai_adapter_is_lazy_and_reports_missing_key():
    extractor = OpenAIStructuredExtractor(
        api_key=None,
        model="test-model",
        client_factory=lambda api_key: (_ for _ in ()).throw(AssertionError()),
    )
    extractor.api_key = None

    assert extractor.available is False
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        extractor("system", "user", {"schema": {"type": "object"}})


def test_openai_adapter_rejects_refusal_and_invalid_json():
    refusal_client = _FakeClient(_response("{}", refusal="cannot comply"))
    refusal_extractor = OpenAIStructuredExtractor(
        api_key="key",
        client_factory=lambda api_key: refusal_client,
    )
    with pytest.raises(RuntimeError, match="refused"):
        refusal_extractor("system", "user", {"schema": {"type": "object"}})

    invalid_client = _FakeClient(_response("not-json"))
    invalid_extractor = OpenAIStructuredExtractor(
        api_key="key",
        client_factory=lambda api_key: invalid_client,
    )
    with pytest.raises(RuntimeError, match="invalid JSON"):
        invalid_extractor("system", "user", {"schema": {"type": "object"}})
