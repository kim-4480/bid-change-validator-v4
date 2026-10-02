"""Server-owned guided Copilot jobs.

The UI may render these labels, but it does not decide which product reads are
allowed or what constitutes a complete answer. Keeping this contract on the
server also prevents a button label from silently falling back to the broad
free-text planner.
"""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict

from ..errors import ApiError
from .v31_contracts import Task, TaskPlan


ToolKind = Literal[
    "READ_JUDGMENT", "READ_PROFILE", "READ_CHECKS", "READ_DOCUMENT", "READ_CHANGES"
]


class GuidedQuestionRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str
    label: str
    order: int
    answer_scope: str
    completion_criteria: list[str]
    required_tools: list[ToolKind]
    availability: Literal["AVAILABLE", "BLOCKED"] = "AVAILABLE"
    unavailable_reason: str | None = None


class GuidedJobRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    label: str
    order: int
    questions: list[GuidedQuestionRead]


class GuidedJobCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["copilot-guided-jobs-v1"] = "copilot-guided-jobs-v1"
    jobs: list[GuidedJobRead]


@dataclass(frozen=True)
class QuestionDefinition:
    job_id: str
    job_label: str
    job_order: int
    question_id: str
    label: str
    order: int
    answer_scope: str
    completion_criteria: tuple[str, ...]
    tool_queries: tuple[tuple[ToolKind, str], ...]
    needs_changed_notice: bool = False
    response_rules: tuple[str, ...] = ()

    @property
    def required_tools(self) -> tuple[ToolKind, ...]:
        return tuple(kind for kind, _ in self.tool_queries)


QUESTIONS: tuple[QuestionDefinition, ...] = (
    QuestionDefinition(
        "changed_notice", "변경 공고 대응", 1, "what_changed", "무엇이 바뀌었나요?", 1,
        "기준 차수와 현재 차수에서 확인된 변경과 아직 확인되지 않은 영향을 쉬운 말로 구분합니다.",
        (
            "기준·현재 차수와 변경 항목을 연결한다.",
            "구조화된 판정 값 변경과 원문 표현 차이를 구분한다.",
            "추출상 추가·삭제를 법적 조항 변경으로 단정하지 않는다.",
        ),
        (("READ_CHANGES", "기준 차수와 현재 차수의 구조화 변경과 원문 표현 차이를 확인"),),
        needs_changed_notice=True,
        response_rules=(
            "첫 두 문장은 '공고문에서 확인된 변경'과 '실제 참가 자격·회사 판정에 미치는 영향은 아직 확인되지 않음'을 나누어 설명합니다.",
            "'구조화된 자격 조건'이나 '추출 원문에서 확인된 표현 차이' 같은 내부 용어를 그대로 쓰지 않고 일반 사용자가 이해할 수 있는 말로 바꿉니다.",
        ),
    ),
    QuestionDefinition(
        "changed_notice", "변경 공고 대응", 1, "company_impact", "우리 회사에 어떤 영향이 있나요?", 2,
        "동일 회사·규칙·기준일로 연결된 저장 재검증만 회사 영향으로 설명합니다.",
        (
            "요건별 영향과 종합 판정을 분리한다.",
            "동일 회사 snapshot·규칙·기준일의 연결 여부를 확인한다.",
            "연결된 비교가 없으면 과거 참가 가능 여부를 추정하지 않고 이유를 설명한다.",
        ),
        (("READ_CHANGES", "저장된 재검증 전후의 회사 영향을 확인"),
         ("READ_JUDGMENT", "현재 저장 판정과 요건별 상태를 확인"),
         ("READ_PROFILE", "판정에 사용된 회사정보 snapshot을 확인")),
        needs_changed_notice=True,
    ),
    QuestionDefinition(
        "changed_notice", "변경 공고 대응", 1, "next_checks", "무엇을 확인해야 하나요?", 3,
        "변경 설명을 반복하지 않고 남은 확인사항의 이유와 다음 행동을 구분합니다.",
        (
            "남은 확인사항마다 이유와 다음 행동을 제시한다.",
            "앱에서 확인 가능한 것과 외부 확인이 필요한 것을 구분한다.",
            "앞선 변경 내용을 그대로 반복하지 않는다.",
        ),
        (("READ_CHECKS", "현재 판정에서 남은 회사 확인사항을 확인"),
         ("READ_DOCUMENT", "공고 원문에서 외부 확인이 필요한 항목을 확인")),
        needs_changed_notice=True,
        response_rules=(
            "첫 주장에 앱에서 확인 가능한 저장 판정·요건 상태와 외부에서 확인할 실제 등록·허가·방문·제출 증빙의 경계를 명시합니다.",
        ),
    ),
    QuestionDefinition(
        "bid_preparation", "입찰 참여 준비", 2, "documents_deadlines_methods", "필요한 서류·기한·방법은?", 1,
        "공고 원문에 확인되는 제출 의무를 서류별 단계·기한·방법·제출처와 함께 설명합니다.",
        (
            "서류별 단계·기한·방법·제출처를 연결한다.",
            "원문상 필수 의무, 낙찰 시 조건부 의무, 원문에 없는 확인 필요를 구분한다.",
            "원문에 없는 값은 확인 필요로 표시한다.",
        ),
        (("READ_DOCUMENT", "제출 서류별 단계 기한 방법 제출처와 조건을 확인"),
         ("READ_CHECKS", "회사정보와 판정에서 별도로 확인할 준비 항목을 확인")),
        response_rules=(
            "각 주장 앞에 [필수], [조건부], [확인 필요] 중 맞는 분류를 표시합니다.",
            "산출내역서 등 원문에 제출 시점·제출처가 없는 문서는 입찰서와 함께 제출한다고 추정하지 않고 확인 필요로 표시합니다.",
        ),
    ),
    QuestionDefinition(
        "bid_preparation", "입찰 참여 준비", 2, "preparation_order", "준비 순서는?", 2,
        "확인된 서류와 기한을 선행조건·일정 순서로 정리하되 제안 순서와 원문상 강제 순서를 구분합니다.",
        (
            "서류·기한·방법 정보를 선행조건과 일정 순서로 재사용한다.",
            "제안 순서와 원문상 강제 순서를 구분한다.",
            "지난 기한은 실제 완료가 아니라 과거 이행 확인 대상으로 표시한다.",
        ),
        (("READ_DOCUMENT", "서류 제출 기한 방법 선행 조건과 일정 순서를 확인"),
         ("READ_CHECKS", "준비 전에 해결할 회사 확인사항을 확인")),
        response_rules=(
            "첫 주장에는 전체 흐름이 권장 또는 제안 순서임을 밝히고, 뒤의 주장에서는 원문이 강제한 선행조건·기한·조건부 단계를 구분합니다.",
        ),
    ),
    QuestionDefinition(
        "bid_preparation", "입찰 참여 준비", 2, "unresolved", "아직 확인하지 못한 것은?", 3,
        "이 Job에서 해결하지 못한 내용만 자료 부족·검색 실패·회사 확인 필요로 나누어 설명합니다.",
        (
            "미확인 항목을 자료 부족·검색 실패·회사 확인 필요로 구분한다.",
            "각 항목의 이유와 다음 행동을 제시한다.",
            "미확인 항목이 없으면 확인한 범위 안에서 없다고 한정한다.",
        ),
        (("READ_CHECKS", "현재 판정에서 해결되지 않은 회사 확인사항과 이유를 확인"),
         ("READ_DOCUMENT", "서류 기한 방법 중 원문에서 확인하지 못한 범위를 확인")),
        response_rules=(
            "각 주장은 [자료 부족], [검색 실패], [회사 확인 필요] 중 하나로 시작하고, 미확인 이유와 사용자가 취할 다음 행동을 같은 주장에 함께 씁니다.",
        ),
    ),
)


_BY_KEY = {(item.job_id, item.question_id): item for item in QUESTIONS}


def get_question(job_id: str | None, question_id: str | None) -> QuestionDefinition | None:
    if job_id is None and question_id is None:
        return None
    if not job_id or not question_id:
        raise ApiError(422, "GUIDED_QUESTION_INCOMPLETE", "Job과 질문을 함께 선택해 주세요.")
    item = _BY_KEY.get((job_id, question_id))
    if item is None:
        raise ApiError(422, "GUIDED_QUESTION_NOT_AVAILABLE", "검증된 질문 목록에서 다시 선택해 주세요.")
    return item


def unavailable_reason(case, item: QuestionDefinition) -> str | None:
    if item.needs_changed_notice and (
        not case.company_id
        or not case.baseline_version_id
        or case.baseline_version_id == case.current_version_id
    ):
        return "기준 차수와 현재 차수가 다른 변경 공고를 먼저 선택해 주세요."
    if not case.company_id:
        return "검토할 회사를 먼저 선택해 주세요."
    return None


def ensure_question_available(case, item: QuestionDefinition) -> None:
    reason = unavailable_reason(case, item)
    if reason:
        raise ApiError(409, "GUIDED_QUESTION_BLOCKED", reason)


def guided_plan(item: QuestionDefinition) -> TaskPlan:
    return TaskPlan(
        goal=item.label,
        tasks=[Task(kind=kind, question=query) for kind, query in item.tool_queries],
    )


def catalog_for_case(case) -> GuidedJobCatalog:
    jobs: list[GuidedJobRead] = []
    grouped: dict[str, list[QuestionDefinition]] = {}
    for item in QUESTIONS:
        grouped.setdefault(item.job_id, []).append(item)
    for items in grouped.values():
        first = items[0]
        questions: list[GuidedQuestionRead] = []
        for item in items:
            reason = unavailable_reason(case, item)
            questions.append(GuidedQuestionRead(
                question_id=item.question_id,
                label=item.label,
                order=item.order,
                answer_scope=item.answer_scope,
                completion_criteria=list(item.completion_criteria),
                required_tools=list(item.required_tools),
                availability="BLOCKED" if reason else "AVAILABLE",
                unavailable_reason=reason,
            ))
        jobs.append(GuidedJobRead(
            job_id=first.job_id,
            label=first.job_label,
            order=first.job_order,
            questions=questions,
        ))
    return GuidedJobCatalog(jobs=sorted(jobs, key=lambda job: job.order))
