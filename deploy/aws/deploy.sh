#!/usr/bin/env bash
set -euo pipefail
umask 077

SHA="${1:?Usage: deploy.sh <immutable-git-sha>}"
cd /opt/bidcheck

python3 prepare-env.py "$SHA"
aws ecr get-login-password --region ap-northeast-2 | docker login \
  --username AWS --password-stdin 226234259348.dkr.ecr.ap-northeast-2.amazonaws.com >/dev/null

docker compose --env-file .env -f docker-compose.yml pull --quiet api web
docker compose --env-file .env -f docker-compose.yml up --no-deps --abort-on-container-exit \
  --exit-code-from schema-check schema-check

if [ -f .release ]; then cp -p .release .previous-release; fi
SERVICES=(api web caddy)
PROFILE_ARGS=()
if [ -f collector.enabled ]; then
  PROFILE_ARGS=(--profile collector)
  SERVICES+=(notice-poller)
fi

if ! docker compose --env-file .env -f docker-compose.yml "${PROFILE_ARGS[@]}" up -d --wait "${SERVICES[@]}" || \
   ! curl --fail --silent --show-error --max-time 20 \
       --resolve 15-165-249-43.sslip.io:443:127.0.0.1 \
       https://15-165-249-43.sslip.io/health >/dev/null; then
  if [ -s .previous-release ]; then
    PREVIOUS="$(cat .previous-release)"
    echo "DEPLOY_FAILED_ROLLING_BACK_IMAGE" "$PREVIOUS" >&2
    python3 prepare-env.py "$PREVIOUS"
    docker compose --env-file .env -f docker-compose.yml "${PROFILE_ARGS[@]}" up -d --wait "${SERVICES[@]}" || true
    printf '%s\n' "$PREVIOUS" > .release
  fi
  exit 1
fi

printf '%s\n' "$SHA" > .release
echo DEPLOY_HEALTHY "$SHA"
