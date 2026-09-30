"""Audit-only runner: existing tests, no database or network access."""
import os
from pathlib import Path
import socket
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / '.venv/Lib/site-packages'))
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
os.chdir(ROOT)
os.environ.update(
    DATABASE_URL='postgresql://audit:audit@127.0.0.1:1/audit_never_connect',
    MIGRATION_DATABASE_URL='postgresql://audit:audit@127.0.0.1:1/audit_never_connect',
    OPENAI_API_KEY='', G2B_SERVICE_KEY='', PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',
)

def forbidden(*args, **kwargs):
    raise AssertionError('Audit forbids database/network connections')

socket.socket.connect = forbidden
socket.socket.connect_ex = forbidden
socket.create_connection = forbidden
import sqlalchemy
sqlalchemy.engine.Engine.connect = forbidden
import pytest

print('Python:', sys.version)
print('DB: loopback port 1 / audit_never_connect; Engine.connect and sockets blocked')
print('Fixtures: existing synthetic objects; model: injected fake extractor')
if '--probe' in sys.argv:
    import json
    from types import SimpleNamespace
    from apps.api.app.copilot import narration
    from apps.api.app.copilot.chat import CopilotChatRequest
    from apps.api.tests.test_copilot_required_checks_narration import _fixture

    def unavailable(*args):
        raise RuntimeError('injected provider failure')

    summary, checks, profile, result = _fixture(with_question=True)
    checks.questions[0].askable = False
    narration.get_qualification_summary = lambda *args: summary
    narration.get_judgment_profile_snapshot = lambda *args: profile
    request = CopilotChatRequest(case_id=summary.provenance.case_id, message='what remains?')
    output = narration.apply_product_narration(SimpleNamespace(), request, result, extractor=unavailable)
    print(json.dumps({'probe': 'askable_false', 'askable': checks.questions[0].askable,
                      'answer': output.answer}, ensure_ascii=False))

    summary, checks, profile, result = _fixture()
    def manual(*args):
        return {'status': 'ineligible', 'conclusion': 'Manual review required',
                'points': [{'requirement_key': None, 'text': 'Check basic participation qualification'}],
                'caveat': None, 'next_action': None}
    output = narration.apply_product_narration(SimpleNamespace(), request, result, extractor=manual)
    print(json.dumps({'probe': 'manual_citation', 'input_evidence_count': len(summary.analysis_scope.notice_facts[0].evidence),
                      'output_source_count': len(output.sources),
                      'reason_refs': [r.evidence_refs for r in output.presentation.reasons]}))

    summary, checks, profile, result = _fixture()
    def contradict(*args):
        return {'status': 'ineligible', 'conclusion': '참가 가능합니다.',
                'points': [], 'caveat': None, 'next_action': None}
    output = narration.apply_product_narration(SimpleNamespace(), request, result, extractor=contradict)
    print(json.dumps({'probe': 'contradictory_prose', 'stored_summary_status': summary.overall_status,
                      'accepted_conclusion': output.presentation.conclusion}, ensure_ascii=False))
    raise SystemExit(0)
raise SystemExit(pytest.main([
    '-v', '--noconftest', '-p', 'no:cacheprovider', '--tb=short',
    '--junitxml=docs/07_handoff/ai-copilot-v3.1/audit-evidence/narration.xml',
    'apps/api/tests/test_copilot_narration.py',
    'apps/api/tests/test_copilot_required_checks_narration.py',
]))
