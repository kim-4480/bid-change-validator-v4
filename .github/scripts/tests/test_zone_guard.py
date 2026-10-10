"""Regression tests for zone-guard policy."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from zone_guard import main, zone_of


class ZoneGuardTest(unittest.TestCase):
    def check(self, paths: list[str], approved: bool = False) -> int:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "changed.txt"
            path.write_text(chr(10).join(paths), encoding="utf-8")
            return main(str(path), allow_cross_zone=approved)

    def test_web_only_pass(self):
        self.assertEqual(0, self.check(["apps/web/app/page.tsx", "apps/web/lib/api.ts"]))

    def test_api_web_fail(self):
        self.assertEqual(1, self.check(["apps/web/app/page.tsx", "apps/api/app/main.py"]))

    def test_api_web_approved_pass(self):
        self.assertEqual(0, self.check(["apps/web/app/page.tsx", "apps/api/app/main.py"], True))

    def test_docs_only_pass(self):
        self.assertEqual(0, self.check(["README.md", "docs/arch.md"]))

    def test_deploy_workflows_same_zone(self):
        self.assertEqual(0, self.check([".github/workflows/ci.yml", "deploy/aws/deploy.sh"]))

    def test_copilot_engine_same_zone(self):
        self.assertEqual("llm", zone_of("apps/api/app/copilot/chat.py"))
        self.assertEqual(0, self.check(["apps/api/app/copilot/chat.py", "engine/bidengine/rag/store.py"]))

    def test_infra_and_web_fail(self):
        self.assertEqual(1, self.check([".github/workflows/ci.yml", "apps/web/app/page.tsx"]))


if __name__ == "__main__":
    unittest.main()