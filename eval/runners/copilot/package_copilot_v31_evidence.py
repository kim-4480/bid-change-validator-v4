"""Preserve this implementation's logs and hashes without staging or committing."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / '.ci-results'
DEST = ROOT / 'docs/07_handoff/ai-copilot-v3.1/implementation-evidence'
final_test = RESULTS / 'copilot-v31-20260913T194111Z'
final_live = RESULTS / 'copilot-v31-live-20260913T194132Z'
live_metadata = json.loads((final_live / 'metadata.json').read_text(encoding='utf-8'))
for path, expected in live_metadata['source_sha256_at_start'].items():
    assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected, path
DEST.mkdir(parents=True, exist_ok=False)
(DEST / '.gitignore').write_text('!*.log\n', encoding='utf-8')
for source in (final_test, *sorted(RESULTS.glob('copilot-v31-live-*'))):
    shutil.copytree(source, DEST / source.name)
for name in ('copilot-v31-final-tests-2.log', 'copilot-v31-browser-final.log',
             'copilot-v31-expanded.log', 'copilot-v31-expanded-2.log', 'copilot-v31-expanded-3.log', 'copilot-v31-expanded-4.log'):
    shutil.copy2(RESULTS / name, DEST / name)
for name in ('build-verified.log', 'browser-final.png'):
    shutil.copy2(RESULTS / 'copilot-v31-ui' / name, DEST / name)

def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True, encoding='utf-8').strip()

tracked_changes = git('diff', '--name-only').splitlines()
new_code = [p for p in git('ls-files', '--others', '--exclude-standard').splitlines()
            if p.startswith(('apps/', 'scripts/'))]
source_paths = sorted(set(tracked_changes + new_code))
manifest = {p: {'sha256': hashlib.sha256((ROOT / p).read_bytes()).hexdigest(), 'bytes': (ROOT / p).stat().st_size}
            for p in source_paths if (ROOT / p).is_file()}
(DEST / 'source-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
patch = subprocess.check_output(['git', 'diff', 'HEAD', '--', *tracked_changes], cwd=ROOT)
for path in new_code:
    result = subprocess.run(['git', 'diff', '--no-index', '--', 'NUL', path], cwd=ROOT, capture_output=True)
    if result.returncode not in (0, 1):
        raise RuntimeError('Cannot capture new source diff: ' + path)
    patch += result.stdout
(DEST / 'implementation.patch').write_bytes(patch)

test_xml = ET.parse(final_test / 'tests.xml')
cases = list(test_xml.iter('testcase'))
by_file = {}
for case in cases:
    key = case.attrib['classname']
    by_file[key] = by_file.get(key, 0) + 1
live_runs = []
for folder in sorted(RESULTS.glob('copilot-v31-live-*')):
    metadata = json.loads((folder / 'metadata.json').read_text(encoding='utf-8'))
    live_runs.append({'run': folder.name, 'cost_upper_usd': metadata['usage_cost_upper_usd'],
                      'model': metadata['model'], 'mode': metadata.get('mode', 'dialogue')})
rows = json.loads((final_live / 'results.json').read_text(encoding='utf-8'))
summary = {'created_utc': datetime.now(timezone.utc).isoformat(), 'head': git('rev-parse', 'HEAD'),
    'branch': git('branch', '--show-current'), 'uncommitted': True,
    'final_test_run': final_test.name, 'tests': len(cases), 'failures': len(list(test_xml.iter('failure'))),
    'errors': len(list(test_xml.iter('error'))), 'skips': len(list(test_xml.iter('skipped'))), 'by_file': by_file,
    'final_model_run': final_live.name,
    'final_model_turns': [{'turn': r['turn'], 'status': r['envelope']['processing']['task_status'],
                           'elapsed_ms': r['envelope']['processing']['elapsed_ms'], 'calls': len(r['calls']),
                           'expected_fact_coverage': r['required_fact_coverage']} for r in rows],
    'live_runs': live_runs, 'cost_upper_usd_total': sum(r['cost_upper_usd'] for r in live_runs),
    'budget_authorized_usd': 10, 'not_an_invoice': True,
    'not_run': ['live PostgreSQL 16', 'real DB transaction/rollback', 'reviewed Golden Core/holdout', 'human evaluation'],
    'preserved_stashes': git('stash', 'list', '--format=%H').splitlines(),
    'worktrees': git('worktree', 'list', '--porcelain')}
(DEST / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
(DEST / 'frontend-verification.txt').write_text('Recorded from actual tool output, 2026-09-14 KST.\n'
    'Node v24.14.0; pnpm 11.19.0; package lock unchanged.\n'
    'node scripts/check-copilot.mjs: exit 0, client/view-model checks; 11 response mocks + 1 error fixture.\n'
    'node scripts/check-copilot-target-memory.mjs: exit 0.\n'
    'node node_modules/typescript/bin/tsc --noEmit --incremental false: exit 0, no output.\n'
    'node node_modules/oxlint/bin/oxlint [five modified/new files]: exit 0, no output.\n'
    'Build and actual Chrome mock-API results: adjacent raw logs.\n'
    'Python 3.12.14 verification venv pip check: No broken requirements found.\n', encoding='utf-8')
print(json.dumps(summary, ensure_ascii=False, indent=2))
