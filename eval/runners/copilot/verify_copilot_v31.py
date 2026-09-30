"""Run existing/new no-DB tests with explicit guards and timestamped evidence."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.update(DATABASE_URL='postgresql://audit:audit@127.0.0.1:1/copilot_never_connect',
                  MIGRATION_DATABASE_URL='postgresql://audit:audit@127.0.0.1:1/copilot_never_connect',
                  OPENAI_API_KEY='', G2B_SERVICE_KEY='', PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
sys.dont_write_bytecode = True
stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
output = ROOT / '.ci-results' / ('copilot-v31-' + stamp)
output.mkdir(parents=True)


def forbidden(*args, **kwargs):
    raise AssertionError('No DB or outbound network in isolated v3.1 verification')


import sqlalchemy
sqlalchemy.engine.Engine.connect = forbidden
original_connect = socket.socket.connect
def local_event_loop_only(sock, address):
    # Windows asyncio/TestClient creates an internal loopback socketpair.
    # Database connections remain forbidden at Engine.connect, regardless of host.
    if isinstance(address, tuple) and address[0] in {'127.0.0.1', '::1'}:
        return original_connect(sock, address)
    return forbidden()
socket.socket.connect = local_event_loop_only
socket.socket.connect_ex = forbidden
import pytest

tests = ['test_copilot_narration.py', 'test_copilot_required_checks_narration.py',
         'test_copilot_v31.py', 'test_copilot_v31_readiness.py', 'test_document_rag_store.py',
         'test_copilot_chat_contract.py', 'test_copilot_semantic_router.py',
         'test_copilot_intent_resolver.py', 'test_copilot_semantic_optin.py']
code = pytest.main(['-v', '--noconftest', '-p', 'no:cacheprovider', '--tb=short',
                    '--junitxml=' + str(output / 'tests.xml'),
                    *['apps/api/tests/' + t for t in tests]])
from apps.api.tests.test_copilot_v31 import replay, FIXTURE_PATH
try:
    traces = replay()
    (output / 'replay.json').write_text(json.dumps(traces, ensure_ascii=False, indent=2), encoding='utf-8')
except Exception as error:
    code = code or 1
    (output / 'replay-error.txt').write_text(repr(error), encoding='utf-8')
paths = list((ROOT / 'apps/api/app/copilot').glob('*.py')) + list((ROOT / 'apps/api/app/document_rag').glob('*.py'))
metadata = {'started_utc': stamp, 'finished_utc': datetime.now(timezone.utc).isoformat(), 'python': sys.version,
            'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
            'tests': tests, 'exit_code': int(code), 'model': 'scripted-fake', 'database': 'blocked port 1, Engine.connect denied',
            'fixture_sha256': hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest(),
            'source_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
            'packages': {p: importlib.metadata.version(p) for p in ['pytest', 'SQLAlchemy', 'fastapi', 'openai', 'faiss-cpu']},
            'not_run': ['live DB', 'live model', 'human evaluation', 'reviewed Golden Core']}
(output / 'metadata.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
print('EVIDENCE_DIR=' + str(output))
raise SystemExit(code)
