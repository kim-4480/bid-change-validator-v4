"""Consent boundary regression for the v3.1 coordinator."""
from types import SimpleNamespace
from uuid import uuid4

from apps.api.app.copilot import orchestration
from apps.api.app.copilot.chat import CopilotChatRequest
from apps.api.app.copilot.v31_contracts import AnswerEnvelope, Processing


def test_v31_semantic_opt_out_keeps_v31_and_disables_model(monkeypatch):
    seen = {}

    class FakeGateway:
        def __init__(self):
            self.enabled = True
            self.calls = []
            self.model = 'fixture-model'

    class FakeTools:
        summary = None

    def fake_coordinate(request, owner, tools, *, gateway=None, **kwargs):
        seen['response_version'] = request.response_version
        seen['owner'] = owner
        seen['gateway_enabled'] = gateway.enabled
        return AnswerEnvelope(
            conversation_id=uuid4(),
            context_revision=1,
            message_id='fixture-message',
            processing=Processing(model=gateway.model, calls=list(gateway.calls)),
        ), tools

    monkeypatch.setattr(orchestration, 'ModelGateway', FakeGateway)
    monkeypatch.setattr(orchestration, 'ProductTools', lambda *args, **kwargs: FakeTools())
    monkeypatch.setattr(orchestration, 'coordinate', fake_coordinate)

    request = CopilotChatRequest(case_id=uuid4(), message='현재 결과 알려줘', response_version='3.1')
    response = orchestration.chat_v31(
        db=object(),
        request=request,
        user=SimpleNamespace(id=uuid4()),
        case=SimpleNamespace(),
        semantic_processing=False,
    )

    assert seen['response_version'] == '3.1'
    assert seen['gateway_enabled'] is False
    assert response.envelope is not None and response.envelope.version == '3.1'
    assert response.envelope.context_revision == 1
    assert response.external_processing_used is False
