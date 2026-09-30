"""Explicitly budgeted real-model evaluation against synthetic, DB-free evidence.

Run from repository root with the verification venv. Reads only the API key/model
from .env; never loads DATABASE_URL from it. No production data is transmitted.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
parser = argparse.ArgumentParser()
parser.add_argument('--max-usd', type=float, required=True)
parser.add_argument('--verifier-only', action='store_true')
args = parser.parse_args()
if not 0 < args.max_usd <= 10:
    parser.error('Budget must be greater than zero and at most the authorized $10.')
os.environ.update(DATABASE_URL='postgresql://audit:audit@127.0.0.1:1/copilot_never_connect',
                  MIGRATION_DATABASE_URL='postgresql://audit:audit@127.0.0.1:1/copilot_never_connect')
from dotenv import dotenv_values
configuration = dotenv_values(ROOT / '.env')
key = os.environ.get('OPENAI_API_KEY') or configuration.get('OPENAI_API_KEY')
model = os.environ.get('COPILOT_MODEL') or configuration.get('OPENAI_MODEL_DEFAULT')
if not key or model != 'gpt-5.6-luna':
    raise SystemExit('A configured key and the priced gpt-5.6-luna model are required.')
os.environ['OPENAI_API_KEY'] = key
import sqlalchemy
def forbidden(*a, **kw):
    raise AssertionError('Live-model evaluation must not access any database')
sqlalchemy.engine.Engine.connect = forbidden

from apps.api.tests.test_copilot_v31 import REPLAY, FIXTURE_PATH, ReplayTools, scope, bundle
from apps.api.app.copilot.chat import CopilotChatRequest
from apps.api.app.copilot.conversation_state import ConversationRepository
from apps.api.app.copilot.model_gateway import ModelGateway
from apps.api.app.copilot.orchestration import coordinate

stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
output = ROOT / '.ci-results' / ('copilot-v31-live-' + stamp)
output.mkdir(parents=True)
# Official model page checked 2026-09-14 KST. Uncached input pricing is a
# conservative usage cost estimate; unknown usage is charged the call maximum.
prices = {'input_per_million': 0.20, 'output_per_million': 1.20,
          'url': 'https://developers.openai.com/api/docs/models/gpt-5.6-luna'}
call_upper = (16000 * prices['input_per_million'] + 3000 * prices['output_per_million']) / 1_000_000
charged = 0.0
rows = []
source_hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in (ROOT / 'apps/api/app/copilot').glob('*.py')}
repository = ConversationRepository()
result = None
for i, turn in enumerate([] if args.verifier_only else REPLAY['turns']):
    # One plan plus four answer-quality calls; no embedding calls in ReplayTools.
    if charged + 5 * call_upper > args.max_usd:
        rows.append({'turn': i + 1, 'status': 'NOT_RUN_BUDGET'})
        break
    request = CopilotChatRequest(case_id=scope().case_id, message=turn['question'], response_version='3.1',
                                allow_external_processing=True,
                                conversation_id=result.conversation_id if result else None,
                                context_revision=result.context_revision if result else None)
    gateway = ModelGateway(model=model)
    row = {'turn': i + 1, 'question': turn['question'], 'expected_fact_ids': turn['facts']}
    try:
        result, _ = coordinate(request, 'synthetic-live-eval-user', ReplayTools(), repository=repository, gateway=gateway)
        row['envelope'] = result.model_dump(mode='json')
        actual = {fid for c in result.claims for fid in c.fact_ids}
        row['required_fact_coverage'] = set(turn['facts']) <= actual
        row['scope'] = 'real planner/generator/verifier; synthetic read adapters; no database'
    except Exception as error:
        row['error_type'] = type(error).__name__
    row['calls'] = gateway.calls
    cost = 0
    for call in gateway.calls:
        usage = call['usage']
        cost += ((usage['prompt_tokens'] * 0.20 + usage['completion_tokens'] * 1.20) / 1_000_000) if usage else call_upper
    charged += cost
    row['usage_cost_upper_usd'] = cost
    rows.append(row)
    (output / 'results.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'turn': i + 1, 'task_status': row.get('envelope', {}).get('processing', {}).get('task_status'),
                      'fact_coverage': row.get('required_fact_coverage'), 'calls': len(gateway.calls),
                      'error_type': row.get('error_type'), 'cumulative_usd_upper': round(charged, 6)}), flush=True)

if args.verifier_only:
    from apps.api.app.copilot.answer_validation import verify
    from apps.api.app.copilot.v31_contracts import Draft, DraftClaim
    examples = [
        ('contradicted-status', '참가 가능합니다.', 'judgment', 'CONTRADICTED'),
        ('wrong-exception', '병원 급식 실적도 인정됩니다.', 'exception', 'CONTRADICTED'),
        ('wrong-number', '하루 평균 80식이면 실적 식수 조건을 충족합니다.', 'exception', 'CONTRADICTED'),
        ('wrong-operator', '2개 이상 운영 또는 1년 운영 중 하나만 충족하면 됩니다.', 'exception', 'CONTRADICTED'),
        ('good-negative', '병원·학교·군부대·사회복지시설 실적은 제외됩니다.', 'exception', 'SUPPORTED'),
        ('good-paraphrase', '공고일 기준 최근 2년 동안 관공서나 기업체의 단체급식소 2개 이상에서 하루 평균 800식 이상을 1년 이상 운영한 실적이 요구됩니다.', 'exception', 'SUPPORTED'),
        ('invented-profile', '회사는 단체급식업 등록증을 보유하고 있지 않습니다.', 'judgment', 'INSUFFICIENT'),
    ]
    if call_upper > args.max_usd:
        raise SystemExit('Insufficient budget for verifier call')
    draft = Draft(claims=[DraftClaim(claim_id=cid, text=text, fact_ids=[fid], source_ids=['s-' + fid]) for cid, text, fid, _ in examples])
    gateway = ModelGateway(model=model)
    claims, events = verify(draft, bundle(), gateway)
    rows = [{'id': cid, 'text': text, 'expected': expected, 'actual': claim.validation, 'reason': claim.reason,
             'matches_expectation': claim.validation == expected}
            for (cid, text, _, expected), claim in zip(examples, claims, strict=True)]
    charged = sum(((c['usage']['prompt_tokens'] * .20 + c['usage']['completion_tokens'] * 1.20) / 1_000_000)
                  if c['usage'] else call_upper for c in gateway.calls)
    (output / 'results.json').write_text(json.dumps({'claims': rows, 'calls': gateway.calls, 'events': events}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'verifier_matches': sum(r['matches_expectation'] for r in rows), 'cases': len(rows), 'usd_upper': charged}), flush=True)

metadata = {'model': model, 'prices': prices, 'max_usd': args.max_usd,
            'mode': 'verifier' if args.verifier_only else 'dialogue',
            'usage_cost_upper_usd': charged, 'not_an_invoice': True,
            'unknown_usage_policy': 'charge maximum input/output per attempted call',
            'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
            'fixture_sha256': hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest(),
            'source_sha256_at_start': source_hashes,
            'started_utc': stamp, 'finished_utc': datetime.now(timezone.utc).isoformat(),
            'not_run': ['live DB', 'reviewed Golden Core', 'human usability evaluation']}
(output / 'metadata.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
print('EVIDENCE_DIR=' + str(output))
