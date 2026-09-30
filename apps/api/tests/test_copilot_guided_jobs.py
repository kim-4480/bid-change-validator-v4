from types import SimpleNamespace
from uuid import uuid4

import pytest

from apps.api.app.copilot.chat import CopilotChatRequest
from apps.api.app.copilot.job_catalog import (
    QUESTIONS,
    catalog_for_case,
    ensure_question_available,
    get_question,
    guided_plan,
)
from apps.api.app.copilot.orchestration import TASK_LABELS, plan_turn
from apps.api.app.copilot.v31_contracts import ConversationState, Scope
from apps.api.app.errors import ApiError


def _case(*, changed=True, company=True):
    current = uuid4()
    return SimpleNamespace(
        company_id=uuid4() if company else None,
        baseline_version_id=uuid4() if changed else current,
        current_version_id=current,
    )


def test_catalog_exposes_only_the_two_ordered_jobs_and_six_contract_questions():
    catalog = catalog_for_case(_case())
    assert catalog.contract_version == "copilot-guided-jobs-v1"
    assert [job.job_id for job in catalog.jobs] == ["changed_notice", "bid_preparation"]
    assert [question.label for job in catalog.jobs for question in job.questions] == [
        "무엇이 바뀌었나요?",
        "우리 회사에 어떤 영향이 있나요?",
        "무엇을 확인해야 하나요?",
        "필요한 서류·기한·방법은?",
        "준비 순서는?",
        "아직 확인하지 못한 것은?",
    ]
    assert len(QUESTIONS) == 6
    assert all(question.completion_criteria and question.required_tools for job in catalog.jobs for question in job.questions)


def test_change_summary_requires_plain_language_and_separates_confirmed_change_from_impact():
    question = get_question("changed_notice", "what_changed")
    rules = " ".join(question.response_rules)
    assert "공고문에서 확인된 변경" in rules
    assert "실제 참가 자격·회사 판정에 미치는 영향은 아직 확인되지 않음" in rules
    assert "내부 용어" in rules


def test_internal_tool_names_have_user_facing_labels():
    assert TASK_LABELS['READ_CHANGES'] == '변경 공고 비교'
    assert all(not label.startswith('READ_') for label in TASK_LABELS.values())


def test_changed_notice_questions_are_visible_but_blocked_without_two_versions():
    case = _case(changed=False)
    catalog = catalog_for_case(case)
    changed = catalog.jobs[0]
    assert all(question.availability == "BLOCKED" for question in changed.questions)
    assert all(question.unavailable_reason for question in changed.questions)
    assert all(question.availability == "AVAILABLE" for question in catalog.jobs[1].questions)

    item = get_question("changed_notice", "what_changed")
    with pytest.raises(ApiError) as blocked:
        ensure_question_available(case, item)
    assert blocked.value.code == "GUIDED_QUESTION_BLOCKED"


def test_available_question_passes_server_guard():
    case = _case(changed=True)
    item = get_question("changed_notice", "what_changed")
    assert ensure_question_available(case, item) is None


def test_unknown_or_partial_guided_selection_is_rejected():
    with pytest.raises(ApiError) as partial:
        get_question("changed_notice", None)
    assert partial.value.code == "GUIDED_QUESTION_INCOMPLETE"
    with pytest.raises(ApiError) as unknown:
        get_question("changed_notice", "not_verified")
    assert unknown.value.code == "GUIDED_QUESTION_NOT_AVAILABLE"


def test_guided_question_uses_server_plan_without_model_classification():
    item = get_question("bid_preparation", "documents_deadlines_methods")
    request = CopilotChatRequest(
        case_id=uuid4(), message="client controlled text", response_version="3.1",
        job_id=item.job_id, question_id=item.question_id,
    )
    scope = Scope(case_id=request.case_id, company_id=uuid4(), notice_id=uuid4(), notice_version_id=uuid4())
    state = ConversationState(conversation_id=uuid4(), owner="user", scope=scope)

    class NeverCalled:
        def call(self, *args, **kwargs):
            pytest.fail("guided planning called the free-text model planner")

    plan, fallback = plan_turn(request, state, NeverCalled())
    assert not fallback
    assert plan == guided_plan(item)
    assert [task.kind for task in plan.tasks] == ["READ_DOCUMENT", "READ_CHECKS"]
