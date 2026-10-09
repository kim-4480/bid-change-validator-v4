"""Optional product-truth narration for the bootcamp Copilot demo.

The model may *explain* an already persisted product decision, but it never owns
eligibility, requirement status, provenance, or write execution. The existing
product response remains the fallback whenever narration is unavailable or its
structured output violates the observed product context. REQUIRED_CHECKS uses a
compact deterministic fallback because the legacy full-scope dump is itself a
user-facing ambiguity ("nothing to answer" followed by many manual-review items).
"""

from __future__ import annotations

import json
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from bidengine.providers.openai import OpenAIStructuredExtractor
from .chat import CopilotChatRequest, CopilotChatResponse
from .context import compact
from .contracts import QualificationSummary, RequiredChecksResult
from .presentation import NextAction, Presentation, Reason, render_answer
from .product_tools import get_judgment_profile_snapshot, get_qualification_summary, matching_provenance
from .source_map import SourceMap, cited_sources


class NarratedPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_key: str | None = Field(default=None, max_length=200)
    text: str = Field(min_length=1, max_length=500)


class ProductNarration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Locked by a per-request JSON-schema enum. This field is deliberately
    # separate from prose so the model never gets to choose product truth.
    status: str
    conclusion: str = Field(min_length=1, max_length=500)
    points: list[NarratedPoint] = Field(default_factory=list, max_length=3)
    caveat: str | None = Field(default=None, max_length=500)
    next_action: str | None = Field(default=None, max_length=300)


SYSTEM_PROMPT = """당신은 나라장터 입찰 검토 서비스의 설명 전용 AI다.
입력 JSON의 저장된 판정과 요건 상태를 절대 새로 계산하거나 변경하지 않는다.
당신의 역할은 이미 확정된 Product Truth를 사용자가 이해하기 쉬운 한국어로 짧게 설명하는 것이다.

규칙:
1. status, requirement status, reason_code는 입력값이 진실이다. 반대 결론을 만들지 않는다.
2. 입력 JSON에 없는 회사 사실·공고 사실·법률 해석·자격 조건을 만들지 않는다.
3. 사용자가 '왜?'처럼 이유만 물으면 UNSATISFIED 요건을 우선하고, 없으면 UNKNOWN 요건만 설명한다.
4. 핵심 요건 상태 요약에서는 핵심 이유를 최대 3개만 보여준다. 입찰 참가 가능·불가능을 법적으로 확정하지 않는다.
5. SATISFIED 요건은 사용자의 질문에 도움이 될 때만 짧게 언급한다.
6. '추가로 답변할 회사정보가 없음'과 '사람이 직접 확인할 판정 밖 항목이 있음'을 같은 뜻으로 쓰지 않는다.
7. intent가 REQUIRED_CHECKS이면 required_checks가 사용자 입력으로 판정을 갱신할 수 있는 항목이다.
   - required_checks가 비어 있고 manual_review가 있으면, '추가로 입력할 회사정보는 없지만 직접 확인할 공고 항목은 있다'고 명확히 구분한다.
   - 이 경우 points는 manual_review의 실제 원문/근거만 최대 3개 요약하고 requirement_key는 반드시 null로 둔다.
   - product_truth의 미달 요건을 required_checks인 것처럼 다시 제시하지 않는다.
8. analysis_status가 PARTIAL이면 판정의 직접 원인이 없다는 식으로 말하지 않는다. 대신 자동 검토 범위가 완전하지 않다고만 설명한다.
9. company_profile은 판정 당시 snapshot이며, 제공된 필드만 사용한다. 식별자를 추정하거나 복원하지 않는다.
10. requirement_key가 필요한 points는 입력의 허용된 요건만 사용한다. 판정 밖 수동 확인사항을 요약할 때는 requirement_key를 null로 둔다.
11. 저장·반영·재검증을 실행했다고 말하지 않는다. next_action은 조회·확인 안내만 작성한다.
12. 짧고 대화체로 답한다. 시스템 내부 용어, JSON, reason_code를 그대로 노출하지 않는다.
"""

StructuredCall = Callable[[str, str, dict[str, Any]], dict[str, Any]]


STATUS_CONCLUSION = {
    "core_met": "현재 저장된 판정은 핵심 요건 충족입니다. 법적 입찰 참가 가능을 보증하지 않습니다.",
    "core_unmet": "현재 저장된 판정은 핵심 요건 미충족입니다. 법적 입찰 참가 불가능을 확정하지 않습니다.",
    "needs_review": "현재 자료로는 핵심 요건 상태를 확정할 수 없습니다. 확인이 필요합니다.",
}


def _profile_for_ai(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Drop internal identifiers while keeping qualification-relevant demo facts."""
    staff = snapshot.get("staff")
    performances = snapshot.get("performances") or []
    certifications = snapshot.get("certifications") or []
    return {
        "region_code": snapshot.get("region_code"),
        "region_name": snapshot.get("region_name"),
        "company_size": snapshot.get("company_size"),
        "industries": [
            {key: item.get(key) for key in ("code", "name", "verified")}
            for item in (snapshot.get("industries") or [])[:20]
            if isinstance(item, dict)
        ],
        "staff": (
            {
                "total_count": staff.get("total_count"),
                "verified": staff.get("verified"),
                "roles": [
                    {key: role.get(key) for key in ("role_name", "headcount", "career_years", "verified")}
                    for role in (staff.get("roles") or [])[:20]
                    if isinstance(role, dict)
                ],
            }
            if isinstance(staff, dict)
            else None
        ),
        "performances": [
            {key: item.get(key) for key in ("name", "amount", "completed_year", "fields", "verified")}
            for item in performances[:10]
            if isinstance(item, dict)
        ],
        "certifications": [
            {key: item.get(key) for key in ("name", "certification_code", "issuer_name", "expires_at", "verified")}
            for item in certifications[:20]
            if isinstance(item, dict)
        ],
        "completeness": snapshot.get("completeness"),
    }


def _manual_review(summary: QualificationSummary) -> list[dict[str, Any]]:
    """Give narration the actual manual-review content, not repeated scope labels."""
    scope = summary.analysis_scope
    if scope is None:
        return []
    items: list[dict[str, Any]] = []
    for item in scope.notice_facts:
        items.append({
            "kind": "NOTICE_FACT",
            "code": item.code,
            "message": item.message,
            "evidence_quotes": [evidence.quote for evidence in item.evidence[:2]],
        })
    for item in scope.dropped_requirements:
        if item.raw.strip():
            items.append({
                "kind": "DROPPED_REQUIREMENT",
                "reason_code": item.reason_code,
                "text": item.raw,
            })
    return items[:8]


def _manual_review_count(summary: QualificationSummary) -> int:
    scope = summary.analysis_scope
    if scope is None:
        return 0
    return len(scope.notice_facts) + len(scope.dropped_requirements)


def _summary_payload(summary: QualificationSummary) -> dict[str, Any]:
    return {
        "overall_status": summary.overall_status,
        "analysis_status": summary.analysis_status,
        "judgment_counts": summary.judgment_counts,
        "requirements": [
            {
                "requirement_key": item.requirement_key,
                "type": item.type,
                "text": item.raw,
                "status": item.status,
                "reason_code": item.reason_code,
                "basis_type": item.basis_type,
            }
            for item in summary.judgments
        ],
        "manual_review_count": _manual_review_count(summary),
        "manual_review": _manual_review(summary),
    }


def _schema(status: str) -> dict[str, Any]:
    return {
        "name": "copilot_product_narration",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "status": {"type": "string", "enum": [status]},
                "conclusion": {"type": "string", "minLength": 1, "maxLength": 500},
                "points": {
                    "type": "array",
                    "maxItems": 3,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "requirement_key": {"type": ["string", "null"], "maxLength": 200},
                            "text": {"type": "string", "minLength": 1, "maxLength": 500},
                        },
                        "required": ["requirement_key", "text"],
                    },
                },
                "caveat": {"type": ["string", "null"], "maxLength": 500},
                "next_action": {"type": ["string", "null"], "maxLength": 300},
            },
            "required": ["status", "conclusion", "points", "caveat", "next_action"],
        },
    }


def _allowed_keys(request: CopilotChatRequest, summary: QualificationSummary, checks: RequiredChecksResult | None) -> set[str]:
    if checks is not None:
        return {item.requirement_key for item in checks.questions}
    text = compact(request.message)
    if text in {"왜", "왜그래", "이유는"}:
        blockers = {item.requirement_key for item in summary.judgments if item.status == "UNSATISFIED"}
        if blockers:
            return blockers
        return {item.requirement_key for item in summary.judgments if item.status == "UNKNOWN"}
    return {item.requirement_key for item in summary.judgments}


def _recompose(
    result: CopilotChatResponse,
    narration: ProductNarration,
    allowed_keys: set[str],
) -> CopilotChatResponse | None:
    old_presentation = result.presentation
    if old_presentation is None:
        return None

    # Preserve only evidence that belongs to model-selected, already-visible
    # product requirements. The model never creates source identities.
    old_reasons = {
        reason.requirement_key: reason
        for reason in old_presentation.reasons
        if reason.requirement_key
    }
    old_sources = {source.ref: source for source in result.sources}
    mapping = SourceMap()
    reasons: list[Reason] = []
    for point in narration.points:
        key = point.requirement_key
        if key is not None and key not in allowed_keys:
            return None
        evidence_ids: list[str] = []
        if key is not None:
            original = old_reasons.get(key)
            if original is None:
                return None
            for ref in original.evidence_refs:
                source = old_sources.get(ref)
                if source is None:
                    return None
                evidence_ids.append(mapping.add(source))
        reasons.append(Reason(text=point.text, requirement_key=key, evidence_refs=evidence_ids))

    presentation = Presentation(
        conclusion=narration.conclusion,
        reasons=reasons,
        limitations=[narration.caveat] if narration.caveat else [],
        next_action=(
            NextAction(kind="SELECT_REQUIREMENT", label=narration.next_action)
            if narration.next_action
            else None
        ),
    )
    result.presentation = presentation
    result.sources = mapping.finalize(presentation)
    result.answer = render_answer(presentation, result.sources)
    result.citations = cited_sources(result.answer, presentation, result.sources)
    return result


def _compact_required_checks_fallback(
    result: CopilotChatResponse,
    summary: QualificationSummary,
    checks: RequiredChecksResult,
) -> CopilotChatResponse:
    """Keep REQUIRED_CHECKS useful even when optional narration fails."""
    manual_count = _manual_review_count(summary)
    answerable_count = sum(item.askable for item in checks.questions)
    unanswerable_count = sum(not item.askable for item in checks.questions)
    status = STATUS_CONCLUSION[summary.overall_status]

    if answerable_count:
        conclusion = f"{status} 추가로 답변해 판정을 갱신할 회사정보는 {answerable_count}건입니다."
    elif manual_count:
        conclusion = (
            f"{status} 추가로 입력해 판정을 갱신할 회사정보는 없습니다. "
            f"다만 공고 원문에서 직접 확인해야 할 항목이 {manual_count}건 있습니다."
        )
    else:
        conclusion = f"{status} 현재 시스템이 추가 답변을 받을 항목은 0건입니다."

    allowed = {item.requirement_key for item in checks.questions}
    old_presentation = result.presentation
    old_sources = {source.ref: source for source in result.sources}
    mapping = SourceMap()
    reasons: list[Reason] = []
    if old_presentation is not None:
        for reason in old_presentation.reasons:
            if reason.requirement_key not in allowed:
                continue
            evidence_ids: list[str] = []
            for ref in reason.evidence_refs:
                source = old_sources.get(ref)
                if source is not None:
                    evidence_ids.append(mapping.add(source))
            reasons.append(reason.model_copy(update={"evidence_refs": evidence_ids}))

    limitations = []
    if unanswerable_count:
        limitations.append(f"현재 입력으로 해결할 수 없는 항목은 {unanswerable_count}건이며 별도 확인이 필요합니다.")
    if manual_count:
        limitations.append("자동 판정에 포함되지 않은 항목은 참가자격 화면에서 원문과 함께 확인해 주세요.")
    presentation = Presentation(conclusion=conclusion, reasons=reasons, limitations=limitations)
    result.presentation = presentation
    result.sources = mapping.finalize(presentation)
    result.answer = render_answer(presentation, result.sources)
    result.citations = cited_sources(result.answer, presentation, result.sources)
    return result


def apply_product_narration(
    db: Session,
    request: CopilotChatRequest,
    result: CopilotChatResponse,
    *,
    extractor: StructuredCall | None = None,
) -> CopilotChatResponse:
    """Narrate read-only Product Truth and fail closed to a safe presentation."""
    if result.intent not in {"QUALIFICATION_SUMMARY", "REQUIRED_CHECKS"}:
        return result

    checks = result.product_state if isinstance(result.product_state, RequiredChecksResult) else None
    summary = result.product_state if isinstance(result.product_state, QualificationSummary) else None
    if summary is None:
        try:
            summary = get_qualification_summary(db, request.case_id)
        except Exception:
            return result

    try:
        profile = get_judgment_profile_snapshot(db, request.case_id)
    except Exception:
        return _compact_required_checks_fallback(result, summary, checks) if checks is not None else result
    if not matching_provenance(summary, profile):
        return _compact_required_checks_fallback(result, summary, checks) if checks is not None else result

    provider = extractor or OpenAIStructuredExtractor()
    if extractor is None and not provider.available:
        return _compact_required_checks_fallback(result, summary, checks) if checks is not None else result

    allowed_keys = _allowed_keys(request, summary, checks)
    body = {
        "question": request.message,
        "intent": result.intent,
        "product_truth": _summary_payload(summary),
        "company_profile": _profile_for_ai(profile.profile_snapshot),
        "required_checks": (
            [
                {
                    "requirement_key": item.requirement_key,
                    "question": item.question,
                    "askable": item.askable,
                    "askability_reason": item.askability_reason,
                }
                for item in checks.questions
            ]
            if checks is not None
            else None
        ),
    }

    try:
        raw = provider(SYSTEM_PROMPT, json.dumps(body, ensure_ascii=False, default=str), _schema(summary.overall_status))
        narration = ProductNarration.model_validate(raw)
        if narration.status != summary.overall_status:
            return _compact_required_checks_fallback(result, summary, checks) if checks is not None else result
        narrated = _recompose(result, narration, allowed_keys)
        if narrated is not None:
            return narrated
    except Exception:
        pass

    # Narration is an optional presentation layer. Provider failures, validation
    # failures or unsafe target selection never replace Product Truth. For
    # REQUIRED_CHECKS the fallback is compact because the legacy full-scope dump
    # contradicts the user's task even though its facts are technically correct.
    return _compact_required_checks_fallback(result, summary, checks) if checks is not None else result
