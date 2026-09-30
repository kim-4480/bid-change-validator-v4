#!/usr/bin/env bash
set -euo pipefail
ROOT=$(git rev-parse --show-toplevel)
cd "$ROOT"
mkdir -p .ci-results
unset OPENAI_API_KEY G2B_SERVICE_KEY
python - <<'PY'
import os
from urllib.parse import urlsplit
value = os.environ.get('DATABASE_URL', '')
url = urlsplit(value)
assert os.environ.get('GITHUB_ACTIONS') == 'true', 'This runner is restricted to isolated CI'
assert url.hostname in {'localhost', '127.0.0.1'} and url.path == '/copilot_ci', 'Explicit CI database required'
print('Verified isolated CI database target (connection values omitted)')
PY
python -m pip install -r apps/api/requirements-dev.txt -e engine -e eval > .ci-results/pip.log 2>&1
(cd apps/api && python -m alembic upgrade head) 2>&1 | tee .ci-results/migration.log
python -m pytest -q apps/api/tests --junitxml=.ci-results/backend.xml 2>&1 | tee .ci-results/backend.log
python -m apps.api.app.scripts.evaluate_copilot_v1 2>&1 | tee .ci-results/copilot-evaluation.log
python -m apps.api.app.scripts.evaluate_copilot_e2_routing --validate-only 2>&1 | tee .ci-results/copilot-e2-routing-dataset.log
cd apps/web
pnpm install --frozen-lockfile > "$ROOT/.ci-results/pnpm.log" 2>&1
pnpm exec tsc --noEmit 2>&1 | tee "$ROOT/.ci-results/typecheck.log"
node scripts/check-copilot.mjs 2>&1 | tee "$ROOT/.ci-results/client.log"
node scripts/check-copilot-actions.mjs 2>&1 | tee "$ROOT/.ci-results/actions.log"
node scripts/check-copilot-integration.mjs 2>&1 | tee "$ROOT/.ci-results/integration.log"
node scripts/check-copilot-semantic.mjs 2>&1 | tee "$ROOT/.ci-results/semantic-optin.log"
node scripts/check-copilot-target-memory.mjs 2>&1 | tee "$ROOT/.ci-results/target-memory.log"
mapfile -t changed < <(git -C "$ROOT" diff --name-only "${COPILOT_BASE_SHA:?Pinned baseline is required}" -- apps/web | grep -E '\.(ts|tsx|mjs|cjs)$' | sed 's#^apps/web/##')
if [ "${#changed[@]}" -gt 0 ]; then pnpm exec oxlint "${changed[@]}" 2>&1 | tee "$ROOT/.ci-results/changed-lint.log"; fi
# Existing unrelated debt remains visible, never counted as a clean repository.
pnpm lint > "$ROOT/.ci-results/baseline-lint.log" 2>&1 || true
pnpm build 2>&1 | tee "$ROOT/.ci-results/build.log"
npm install --prefix "$RUNNER_TEMP/copilot-browser" --no-save playwright@1.56.1 > "$ROOT/.ci-results/playwright-install.log" 2>&1
"$RUNNER_TEMP/copilot-browser/node_modules/.bin/playwright" install --with-deps chromium >> "$ROOT/.ci-results/playwright-install.log" 2>&1
pnpm dev --host localhost --port 3000 > "$ROOT/.ci-results/web-server.log" 2>&1 &
WEB_PID=$!
trap 'kill "$WEB_PID" 2>/dev/null || true' EXIT
READY=0
for n in $(seq 1 60); do
  if ! kill -0 "$WEB_PID" 2>/dev/null; then cat "$ROOT/.ci-results/web-server.log"; exit 1; fi
  if curl -fsS http://localhost:3000/ -o /dev/null; then READY=1; break; fi
  sleep 2
done
if [ "$READY" != 1 ]; then cat "$ROOT/.ci-results/web-server.log"; echo 'UI did not become ready'; exit 1; fi
mkdir -p "$ROOT/.ci-results/screenshots"
COPILOT_UI_URL=http://localhost:3000 COPILOT_SCREENSHOT_DIR="$ROOT/.ci-results/screenshots" PLAYWRIGHT_MODULE="$RUNNER_TEMP/copilot-browser/node_modules/playwright" node scripts/check-copilot-design-browser.cjs 2>&1 | tee "$ROOT/.ci-results/browser.log"
COPILOT_UI_URL=http://localhost:3000 \
COPILOT_REPLAY_FILE="$ROOT/docs/07_handoff/ai-copilot-v3.1/implementation-evidence/copilot-v31-20260913T194111Z/replay.json" \
COPILOT_SCREENSHOT_FILE="$ROOT/.ci-results/screenshots/copilot-v31.png" \
PLAYWRIGHT_MODULE="$RUNNER_TEMP/copilot-browser/node_modules/playwright" \
node scripts/check-copilot-v31-browser.mjs 2>&1 | tee "$ROOT/.ci-results/browser-v31.log"
