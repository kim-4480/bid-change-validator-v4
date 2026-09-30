"""Run frozen Copilot contract cases with existing fake Product fixtures.

No production/default DB fallback: --noconftest excludes DB-seeding fixtures,
and Engine.connect plus non-loopback network are blocked before importing tests.
"""
import hashlib
import json
import socket
import sys
import time
from pathlib import Path


def main():
    import pytest
    from sqlalchemy.engine import Engine
    root = Path(__file__).resolve().parents[4]
    dataset = root / "apps/api/eval/copilot_v1.json"
    data = json.loads(dataset.read_text(encoding="utf-8"))
    assert len(data["single_turn"]) == 80 and len(data["multi_turn"]) == 20
    assert sum(c["split"] == "dev" for c in data["single_turn"]) == 40
    assert sum(c["split"] == "holdout" for c in data["single_turn"]) == 40

    def forbidden(*args, **kwargs):
        raise AssertionError("Evaluation must not connect to a DB or network")

    original_connect = socket.socket.connect

    def local_only(sock, address):
        # Windows asyncio creates its self-pipe through a loopback socket pair.
        if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1"):
            return original_connect(sock, address)
        return forbidden()

    class Results:
        def __init__(self):
            self.groups = {name: {"passed": 0, "failed": 0, "skipped": 0} for name in ("dev", "holdout", "scenario")}
            self.failures = []

        def pytest_runtest_logreport(self, report):
            if report.when != "call" and not report.failed:
                return
            group = "holdout" if "[holdout-" in report.nodeid else "dev" if "[dev-" in report.nodeid else "scenario"
            self.groups[group][report.outcome] += 1
            if report.failed:
                self.failures.append(report.nodeid)

    results = Results()
    start = time.perf_counter()
    with pytest.MonkeyPatch.context() as guard:
        guard.setattr(Engine, "connect", forbidden)
        guard.setattr(socket.socket, "connect", local_only)
        code = pytest.main(["-q", "--noconftest", "-p", "no:cacheprovider", "--tb=short",
                            str(root / "apps/api/tests/test_copilot_v1_evaluation.py"), "-k", "test_single or test_multi"], plugins=[results])
    print(json.dumps({"fixture_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
                      "results": results.groups, "failures": results.failures,
                      "elapsed_seconds": round(time.perf_counter() - start, 2),
                      "human_evaluation": "not performed"}, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
