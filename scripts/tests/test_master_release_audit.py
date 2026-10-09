"""Isolated regression tests; never contact AWS or GitHub."""
import unittest
from scripts.master_release_audit import audit, on_events, job_text

MANUAL = """name: AWS deploy
on:
  workflow_dispatch:
    inputs:
      deploy:
        type: boolean
jobs:
  build:
    if: github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/develop'
    runs-on: ubuntu-latest
  deploy:
    if: github.event_name == 'workflow_dispatch' && inputs.deploy == true
    needs: build
"""
AUTO = MANUAL.replace("on:\n  workflow_dispatch:", "on:\n  push:\n    branches: [develop]\n  workflow_dispatch:")
CI = """on:
  push:
    branches: [develop]
jobs:
  engine:
    runs-on: ubuntu-latest
  eval:
    runs-on: ubuntu-latest
  backend:
    services:
      postgres:
        image: postgres:17
    steps:
      - run: python -m alembic upgrade head
  frontend:
    steps:
      - run: pnpm lint
"""
INTEGRATION = "services:\n  postgres:\n    image: postgres:17\n"


class ReleaseAuditTests(unittest.TestCase):
    def test_manual_workflow_is_allowed(self):
        self.assertEqual(on_events(MANUAL), {"workflow_dispatch"})
        self.assertTrue(all(x["result"] == "PASS" for x in audit(MANUAL, CI, INTEGRATION)))

    def test_auto_publish_is_blocked_even_if_deploy_is_manual(self):
        checks = {x["check"]: x["result"] for x in audit(AUTO, CI, INTEGRATION)}
        self.assertEqual(checks["manual_aws_trigger"], "BLOCKED")
        self.assertEqual(checks["explicit_aws_deploy_guard"], "PASS")

    def test_automatic_deploy_is_blocked(self):
        bad = MANUAL.replace("if: github.event_name == 'workflow_dispatch' && inputs.deploy == true",
                             "if: github.ref == 'refs/heads/develop'")
        self.assertEqual(audit(bad, CI)[2]["result"], "BLOCKED")

    def test_lint_must_fail_closed(self):
        bad_ci = CI.replace("- run: pnpm lint", "- run: pnpm lint\n        continue-on-error: true")
        values = {x["check"]: x["result"] for x in audit(MANUAL, bad_ci)}
        self.assertEqual(values["frontend_lint_fail_closed"], "BLOCKED")

    def test_pg17_required(self):
        ci = CI.replace("postgres:17", "postgres:16")
        values = {x["check"]: x["result"] for x in audit(MANUAL, ci)}
        self.assertEqual(values["postgres17_backend_ci"], "BLOCKED")

    def test_job_isolation(self):
        self.assertIn("pnpm lint", job_text(CI, "frontend"))
        self.assertNotIn("pnpm lint", job_text(CI, "backend"))


if __name__ == "__main__":
    unittest.main()
