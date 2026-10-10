import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = (relative: string) => readFileSync(new URL(relative, import.meta.url), 'utf8');

void test('AWS Caddy keeps API requests on the authenticated FastAPI service', () => {
  const caddy = read('../../../deploy/aws/Caddyfile');
  assert.match(caddy, /handle \/api\/\*/);
  assert.match(caddy, /reverse_proxy api:8000/);
  assert.match(caddy, /reverse_proxy web:3000/);
});

void test('AWS compose and Dockerfile keep single HTTPS origin and Secure Cookie', () => {
  const compose = read('../../../deploy/aws/docker-compose.yml');
  const dockerfile = read('../Dockerfile.aws');
  assert.match(compose, /NEXT_PUBLIC_API_BASE_URL: https:\/\//);
  assert.match(compose, /AUTH_COOKIE_SECURE: "true"/);
  assert.match(compose, /CORS_ORIGINS: https:\/\//);
  assert.match(dockerfile, /NEXT_PUBLIC_API_BASE_URL/);
});

void test('AWS deployment requires successful develop push CI or explicit manual dispatch', () => {
  const workflow = read('../../../.github/workflows/aws-deploy.yml');
  assert.match(workflow, /workflow_dispatch/);
  assert.match(workflow, /workflow_run:/);
  assert.match(workflow, /github\.event\.workflow_run\.event == 'push'/);
  assert.match(workflow, /github\.event\.workflow_run\.head_branch == 'develop'/);
  assert.match(workflow, /github\.event\.workflow_run\.conclusion == 'success'/);
  assert.match(workflow, /github\.event_name == 'workflow_run' \|\| inputs\.deploy == true/);
  assert.match(workflow, /Skip superseded develop commit/);
  assert.match(workflow, /Skip if a newer commit reached develop during build/);
});

void test('private document URL contract is served through the authenticated backend', () => {
  const models = read('../../../apps/api/app/models.py');
  const api = read('./api.ts');
  assert.match(models, /\/api\/v1\/preflight-cases\//);
  assert.match(models, /\/api\/v1\/notices\//);
  assert.match(api, /credentials: target\.origin === base\.origin \? 'include' : 'omit'/);
});
