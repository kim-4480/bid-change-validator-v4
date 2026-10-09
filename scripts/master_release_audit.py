"""Read-only release policy audit. No AWS / Git / network mutations."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re


def on_events(yaml_text: str) -> set[str]:
    """Extract root workflow event names without a PyYAML dependency."""
    lines = yaml_text.splitlines()
    start = next((i for i, line in enumerate(lines) if re.fullmatch(r"on:\s*", line)), None)
    if start is None:
        return set()
    events: set[str] = set()
    for line in lines[start + 1:]:
        if line and not line[0].isspace() and not line.lstrip().startswith("#"):
            break
        match = re.match(r"^  ([A-Za-z_][A-Za-z_0-9-]*):", line)
        if match:
            events.add(match.group(1))
    return events


def job_text(yaml_text: str, name: str) -> str:
    """Isolate a two-space indented job body."""
    match = re.search(r"^  " + re.escape(name) + r":\s*$", yaml_text, re.M)
    if not match:
        return ""
    following = yaml_text[match.end():]
    lines = []
    for line in following.splitlines():
        if re.match(r"^  [A-Za-z_][\w-]*:\s*$", line):
            break
        lines.append(line)
    return "\n".join(lines)


def audit(aws_yml: str, ci_yml: str, integration_yml: str = "") -> list[dict[str, str]]:
    results = []

    def emit(check: str, ok: bool, reason: str):
        results.append(dict(check=check, result="PASS" if ok else "BLOCKED", detail=reason))

    events = on_events(aws_yml)
    emit("manual_aws_trigger", events == {"workflow_dispatch"},
         f"AWS workflow trigger events: {', '.join(sorted(events)) or 'NONE'}")
    build = job_text(aws_yml, "build")
    deploy = job_text(aws_yml, "deploy")
    emit("manual_aws_build_guard",
         bool(build) and "github.event_name == 'workflow_dispatch'" in build,
         "Build job must explicitly check workflow_dispatch")
    emit("explicit_aws_deploy_guard",
         bool(deploy) and "github.event_name == 'workflow_dispatch'" in deploy and
         "inputs.deploy == true" in deploy,
         "Deploy job must require manual dispatch AND deploy=true")
    emit("postgres17_backend_ci",
         "postgres:17" in ci_yml and "alembic upgrade head" in ci_yml,
         "Backend CI must use isolated PostgreSQL 17 with migrations")
    frontend = job_text(ci_yml, "frontend")
    emit("frontend_lint_fail_closed",
         "pnpm lint" in frontend and "continue-on-error: true" not in frontend,
         "Frontend lint must block the job on failure")
    emit("engine_and_eval_ci",
         bool(job_text(ci_yml, "engine")) and bool(job_text(ci_yml, "eval")),
         "Engine and Eval CI jobs must exist")
    if integration_yml:
        emit("copilot_postgres17_ci", "postgres:17" in integration_yml,
             "Copilot integration must use isolated PostgreSQL 17")
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    workflow = args.root / ".github" / "workflows"
    try:
        check = audit(
            (workflow / "aws-deploy.yml").read_text(encoding="utf-8"),
            (workflow / "ci.yml").read_text(encoding="utf-8"),
            (workflow / "copilot-integration.yml").read_text(encoding="utf-8"),
        )
    except (OSError, UnicodeError) as exc:
        print(f"NOT_RUN: cannot read workflow: {type(exc).__name__}")
        return 3
    if args.json:
        print(json.dumps(check, ensure_ascii=False, indent=2))
    else:
        for entry in check:
            print(f"{entry['result']:7s} {entry['check']}: {entry['detail']}")
    return 2 if any(x["result"] != "PASS" for x in check) else 0


if __name__ == "__main__":
    raise SystemExit(main())
