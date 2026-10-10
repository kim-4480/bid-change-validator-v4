"""자유 대화: 저장된 판정을 평문 한 장으로 만들어 모델에 한 번 묻는다(2026-10-10)."""

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from bidengine.contracts import Evidence, EvidenceLocation, Judgment, QualificationRequirement
from bidengine.pipeline.analysis_result import AnalysisCoverage, CoverageGap

from apps.api.app.copilot.chat import CopilotChatRequest
from apps.api.app.copilot.contracts import FreeChatTurn
from apps.api.app.copilot.free_chat import (
    CONSENT_ANSWER,
    OUT_OF_SCOPE_ANSWER,
    SCHEMA,
    SYSTEM_PROMPT,
    answer_free_question,
    render_case_briefing,
)
from apps.api.app.copilot import router as copilot_router


def _version():
    notice = SimpleNamespace(title="정보보안 모니터링 용역", bid_notice_no="R26BK01748957",
                             announcing_institution_name="한국과학기술원", demanding_institution_name=None)
    return SimpleNamespace(notice=notice, bid_notice_order="000", version_number=1, contract_method="제한경쟁",
                           bid_closed_at=datetime(2026, 10, 20, 14, 0, tzinfo=timezone.utc), estimated_price=Decimal("159090909"))


def _requirement(key, type_, value, raw, **extra):
    return QualificationRequirement(requirement_key=key, notice_version_id="v", type=type_, operator="MATCH", value=value,
                                    raw=raw, evidence_keys=[f"E-{key}"], **extra)


def _judgment(key, status, reason):
    return Judgment(judgment_key=f"J-{key}", preflight_case_id="c", notice_version_id="v", requirement_key=key,
                    status=status, basis_type="PROFILE", reason_code=reason)


def _analysis_and_judgment(overall="needs_review"):
    requirements = [
        _requirement("R1", "INDUSTRY", "0036", "마. 정보통신공사업(업종코드:0036)으로 등록된 업체"),
        _requirement("R2", "REGION", "대전광역시", "가. 본점 소재지가 대전광역시인 업체"),
        _requirement("R3", "REGISTRATION_CERTIFICATION", "ISO 27001", "바. ISO 27001 인증을 보유한 업체"),
    ]
    evidence = [Evidence(evidence_key=f"E-{r.requirement_key}", source_type="NOTICE_DOCUMENT", document_id="d", notice_version_id="v",
                         location=EvidenceLocation(display="공고문 3쪽"), quote=r.raw) for r in requirements]
    coverage = AnalysisCoverage(
        section_selection="anchored",
        gaps=[
            CoverageGap(kind="UNCLASSIFIED", raw="사. 기관 소재지에 신속한 현장 대응이 가능한 업체", blocks_verdict=False,
                        category="STAFF", summary="신속한 현장 대응과 기술지원 체계를 갖추어야 합니다."),
            CoverageGap(kind="UNREPRESENTABLE", raw="라. 대기업인 소프트웨어사업자 참여 하한 준수", reason="UNMAPPED_INDUSTRY/CANDIDATE_UNUSED"),
        ],
        ignored=[CoverageGap(kind="DROPPED", raw="아. 공동수급 및 하도급 불가", reason="GAP_JOINT_CONTRACT_NOTE")],
    )
    analysis = SimpleNamespace(
        status="PARTIAL", requirements=requirements, evidence=evidence, coverage=coverage,
        requirement_tiers={"R1": "VERDICT", "R2": "VERDICT", "R3": "CHECKLIST"},
    )
    judgment = SimpleNamespace(
        overall_status=overall,
        judgments=[_judgment("R1", "SATISFIED", "RULE_MATCH"), _judgment("R2", "UNSATISFIED", "RULE_MISMATCH"),
                   _judgment("R3", "UNKNOWN", "NEEDS_REVIEW")],
        profile_snapshot={"region_name": "서울특별시 중구", "company_size": "SMALL",
                          "industries": [{"code": "0036", "name": "정보통신공사업", "verified": True}]},
    )
    return analysis, judgment


def test_briefing_carries_the_stored_verdict_reasons_and_quotes() -> None:
    analysis, judgment = _analysis_and_judgment("core_unmet")
    text = render_case_briefing(_version(), analysis, judgment)
    assert "[공고] 정보보안 모니터링 용역" in text and "R26BK01748957-000" in text
    assert "입찰 마감: 2026-10-20 14:00" in text and "추정가격: 159,090,909원" in text
    assert "[참가자격 종합 판정] 핵심 자격 미충족" in text
    assert "충족 1 / 미충족 1 / 확인 필요 1" in text
    assert "[충족] 업종: 마. 정보통신공사업(업종코드:0036)으로 등록된 업체" in text
    assert "[미충족] 지역: 가. 본점 소재지가 대전광역시인 업체" in text and "사유: 회사 정보가 요건과 다름" in text
    assert "공고 원문 (공고문 3쪽): “가. 본점 소재지가 대전광역시인 업체”" in text
    # 확인 항목·판정을 막는 조항·참고 정보가 구분되어 들어간다.
    assert text.index("[사용자가 확인할 항목") < text.index("[확인 필요] 등록·인증: 바. ISO 27001")
    assert "[직접 확인] 인력: 신속한 현장 대응과 기술지원 체계를 갖추어야 합니다." in text
    assert "[판정을 확정하지 못하게 한 조항" in text and "대기업인 소프트웨어사업자 참여 하한" in text
    assert "[참고 정보" in text and "공동수급 및 하도급 불가" in text
    assert "소재지: 서울특별시 중구 / 기업 규모: SMALL" in text and "정보통신공사업(0036)" in text
    # 내부 사유 코드는 모델에게 주지 않는다.
    assert "RULE_MISMATCH" not in text and "NEEDS_REVIEW" not in text


def test_briefing_without_a_stored_judgment_says_so() -> None:
    text = render_case_briefing(_version(), None, None)
    assert "[공고] 정보보안 모니터링 용역" in text and "아직 저장된 판정이 없습니다" in text


def test_the_model_sees_only_the_briefing_history_and_question() -> None:
    seen = {}

    def model(system, body, schema):
        seen.update(system=system, body=body, schema=schema)
        return {"scope": "CASE", "answer": "지역 요건이 맞지 않아 미충족입니다."}

    result = answer_free_question(
        "왜 미충족이야?", "BRIEFING", extractor=model, passages=["제출 서류는 입찰서와 산출내역서입니다."],
        history=[FreeChatTurn(question="참가할 수 있어?", answer="현재 판정은 핵심 자격 미충족입니다.")],
    )
    assert result.status == "OK" and result.scope == "CASE" and result.answer == "지역 요건이 맞지 않아 미충족입니다."
    assert seen["system"] == SYSTEM_PROMPT and seen["schema"] == SCHEMA
    assert "절대 새로 판정하지 않는다" in seen["system"] and "OUT_OF_SCOPE" in seen["system"]
    body = seen["body"]
    assert body.startswith("[현재 상태]\nBRIEFING")           # 현재 상태가 항상 맨 앞 — 앞선 답변이 사실의 출처가 되지 않게
    assert "[공고문 발췌]\n- 제출 서류는 입찰서와 산출내역서입니다." in body
    assert "[이전 질문]\n참가할 수 있어?" in body and body.rstrip().endswith("[담당자 질문]\n왜 미충족이야?")


def test_unrelated_questions_get_the_fixed_refusal_not_the_models_text() -> None:
    result = answer_free_question("오늘 날씨 어때?", "BRIEFING",
                                  extractor=lambda *_: {"scope": "OUT_OF_SCOPE", "answer": "오늘은 맑습니다."})
    assert result.scope == "OUT_OF_SCOPE" and result.status == "OK"
    assert result.answer == OUT_OF_SCOPE_ANSWER and "맑습니다" not in result.answer
    general = answer_free_question("지체상금이 뭐야?", "BRIEFING",
                                   extractor=lambda *_: {"scope": "DOMAIN", "answer": "계약 이행이 늦어질 때 내는 금액입니다."})
    assert general.scope == "DOMAIN" and "늦어질 때" in general.answer


def test_failures_become_statuses_and_never_raise() -> None:
    def broken(*_):
        raise RuntimeError("boom")

    assert answer_free_question("  ", "B", extractor=broken).status == "EMPTY_QUESTION"
    assert answer_free_question("질문", "B", extractor=None).status == "MODEL_UNAVAILABLE"
    assert answer_free_question("질문", "B", extractor=broken).status == "FAILED"
    assert answer_free_question("질문", "B", extractor=lambda *_: {"scope": "MAYBE", "answer": "x"}).status == "FAILED"
    assert answer_free_question("질문", "B", extractor=lambda *_: {"scope": "CASE", "answer": " "}).status == "FAILED"


def test_only_typed_questions_take_the_free_chat_path() -> None:
    case_id = uuid4()
    typed = CopilotChatRequest(case_id=case_id, message="입찰 마감이 언제야?", free_chat=True)
    assert copilot_router.is_free_chat(typed, None)
    assert not copilot_router.is_free_chat(typed.model_copy(update={"free_chat": False}), None)   # 버튼 질문
    assert not copilot_router.is_free_chat(typed, object())                                        # 안내형 질문
    # 저장·재검증 실행 요청은 제안과 확인을 거치는 기존 경로로 간다.
    assert not copilot_router.is_free_chat(typed.model_copy(update={"message": "재검증 해줘"}), None)
    assert copilot_router.is_free_chat(typed.model_copy(update={"message": "재검증이 왜 필요해?"}), None)
    # '공고문 근거 답변' 만 켠 요청은 회사 정보를 모델에 보내지 않는 공고문 전용 경로로 간다.
    document_only = typed.model_copy(update={"allow_external_processing": True})
    assert not copilot_router.is_free_chat(document_only, None, semantic_processing=False)
    assert copilot_router.is_free_chat(document_only, None, semantic_processing=True)
    assert copilot_router.is_free_chat(typed, None, semantic_processing=False)      # 둘 다 끈 경우 — 동의 안내를 돌려준다


def test_no_model_call_without_consent(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(copilot_router, "load_briefing", lambda db, case: ("BRIEFING", None))
    monkeypatch.setattr(copilot_router, "document_passages", lambda *a: calls.append("rag") or [])
    payload = CopilotChatRequest(case_id=uuid4(), message="참가할 수 있어?", free_chat=True, allow_external_processing=True)

    def model(*_):
        calls.append("model")
        return {"scope": "CASE", "answer": "현재 판정은 확인 필요입니다."}

    off = copilot_router.free_chat_response(None, payload, SimpleNamespace(), False, extractor=model)
    assert off.answer == CONSENT_ANSWER and not off.external_processing_used and calls == []
    on = copilot_router.free_chat_response(None, payload, SimpleNamespace(), True, extractor=model)
    assert on.answer == "현재 판정은 확인 필요입니다." and on.external_processing_used and calls == ["rag", "model"]
    # 공고문 근거 답변을 켜지 않으면 문서 검색을 하지 않는다.
    calls.clear()
    copilot_router.free_chat_response(None, payload.model_copy(update={"allow_external_processing": False}), SimpleNamespace(), True, extractor=model)
    assert calls == ["model"]


def test_copies_of_the_same_clause_appear_once_and_markdown_is_stripped() -> None:
    analysis, judgment = _analysis_and_judgment()
    analysis.coverage = AnalysisCoverage(
        section_selection="anchored",
        gaps=[CoverageGap(kind="UNREPRESENTABLE", raw="라. 대기업 참여 하한 준수", reason="UNMAPPED_INDUSTRY/CANDIDATE_UNUSED"),
              CoverageGap(kind="UNREPRESENTABLE", raw="다. 대기업 참여 하한 준수", reason="UNMAPPED_INDUSTRY/CANDIDATE_UNUSED")],
        ignored=[CoverageGap(kind="DROPPED", raw=raw, reason="GAP_JOINT_CONTRACT_NOTE")
                 for raw in ("아. 공동수급 및 하도급 불가", "아 . 공동수급 및 하도급 불가", "사. 공동수급 및 하도급 불가")],
    )
    text = render_case_briefing(_version(), analysis, judgment)
    assert text.count("대기업 참여 하한 준수") == 1 and text.count("공동수급 및 하도급 불가") == 1

    newline = chr(10)
    raw = newline.join(["## 결론", "저장된 판정은 **핵심 자격 미충족**입니다.", "- `0036` 업종을 확인하세요."])
    result = answer_free_question("참가할 수 있어?", "B", extractor=lambda *_: {"scope": "CASE", "answer": raw})
    assert result.answer == newline.join(["결론", "저장된 판정은 핵심 자격 미충족입니다.", "- 0036 업종을 확인하세요."])
