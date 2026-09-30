"""Synthetic API contract evaluation. Standalone: --noconftest; no DB or LLM."""
import copy
import json
import re
from pathlib import Path
from uuid import uuid4

import pytest

from apps.api.tests.test_copilot_chat_contract import local, real_proposals, changed_notice, ask, hints  # noqa: F401
from apps.api.app.copilot import chat as flow
from apps.api.app.copilot.contracts import JudgmentProfileResult

DATA = json.loads((Path(__file__).parents[1] / "eval/copilot_v1.json").read_text(encoding="utf-8"))


@pytest.fixture
def evaluation(real_proposals, changed_notice, monkeypatch):
    profile = JudgmentProfileResult(provenance=real_proposals.summary.provenance,
                                    profile_snapshot={"name": "SYNTHETIC_ONLY"}, profile_completeness={})
    monkeypatch.setattr(flow, "get_judgment_profile_snapshot", lambda *args: profile.model_copy(deep=True))
    return real_proposals


def verify(response, expected):
    assert response["answer"] and response["presentation"]["conclusion"]
    assert response["answer"].startswith(response["presentation"]["conclusion"])
    assert not response["external_processing_used"]
    if "intent" in expected:
        assert response["intent"] == expected["intent"]
    if "status" in expected:
        assert response["reply_context"]["status"] == expected["status"]
    if "focus" in expected:
        assert response["reply_context"]["requirement_key"] == expected["focus"]
    action = expected.get("action")
    assert [a["action_type"] for a in response["actions"]] == ([action] if action else [])
    if action == "ANSWER_REQUIREMENT":
        assert response["actions"][0]["user_input"]["satisfies_requirement"] is False
        assert response["actions"][0]["user_input"]["evidence_held"] is False
    sources = {s["ref"]: s for s in response["sources"]}
    assert len(sources) == len(response["sources"])
    assert list(sources) == [f"S{i+1}" for i in range(len(sources))]
    used = list(dict.fromkeys(re.findall(r"\[(S\d+)\]", response["answer"])))
    assert response["citations"] == [sources[ref] for ref in used]
    for reason in response["presentation"]["reasons"]:
        assert all(ref in sources and ref in used for ref in reason["evidence_refs"])
    assert "None" not in response["answer"]


@pytest.mark.parametrize("case", DATA["single_turn"], ids=lambda row: row["split"] + "-" + row["id"])
def test_single(evaluation, case):
    verify(ask(evaluation, **case["request"]), case["expected"])


@pytest.mark.parametrize("case", DATA["multi_turn"], ids=lambda row: row["id"])
def test_multi(evaluation, case):
    previous = None
    for turn in case["turns"]:
        request = copy.deepcopy(turn["request"])
        if turn.get("use_previous"):
            context = hints(previous)
            if turn.get("stale_field"):
                target = context["last_read_receipt"]["provenance"]
                path = turn["stale_field"].split(".")
                for field in path[:-1]:
                    target = target[field]
                target[path[-1]] = str(uuid4())
            request["conversation_context"] = context
        previous = ask(evaluation, **request)
        verify(previous, turn["expected"])


@pytest.mark.parametrize("message", ["저장된 프로필", "반영된 회사정보", "재검증에 사용한 프로필"])
def test_profile_read_does_not_become_action(evaluation, message):
    verify(ask(evaluation, message), {"intent": "PROFILE_SNAPSHOT", "action": None})


def test_profile_action_and_prohibition_keep_their_boundaries(evaluation):
    for message, action in [("회사정보 반영해줘", "ANSWER_REQUIREMENT"), ("회사정보 반영하지 마", None)]:
        verify(ask(evaluation, message, requirement_key="R2",
                   user_input={"satisfies_requirement": False, "evidence_held": False}),
               {"intent": "ACTION_REQUEST", "action": action})


def test_historical_ui_source_button_cannot_reinterpret_old_focus(evaluation):
    first = ask(evaluation, "근거", requirement_key="R2")
    evaluation.summary.provenance.judgment_run_id = uuid4()
    response = ask(evaluation, "그 조건 근거 보여줘", intent="REQUIREMENT_EVIDENCE",
                   requirement_key="R2", conversation_context=hints(first))
    verify(response, {"status": "STALE_CONTEXT", "focus": None, "action": None})
