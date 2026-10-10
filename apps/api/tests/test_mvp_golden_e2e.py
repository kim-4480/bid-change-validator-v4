from datetime import date, datetime, timezone
from decimal import Decimal
from hashlib import sha256
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from apps.api.app.analysis_models import QualificationAnalysisRun, QualificationEvidenceRecord, QualificationRequirementRecord
from apps.api.app.database import SessionLocal
from apps.api.app.main import app
from apps.api.app.models import (
    BidNotice,
    BidNoticeVersion,
    Company,
    CompanyPerformance,
    CompanyStaff,
    CompanyStaffRole,
    NoticeDocument,
    PreflightCase,
)
from apps.api.app.qualification.analysis import qualification_analysis_version_fingerprint
from apps.api.app.qualification.judgment import run_qualification_judgment
from apps.api.app.qualification.revalidation import run_qualification_revalidation
from apps.api.app.revalidation_schemas import QualificationRevalidationCreate
from bidengine.pipeline.analysis_result import AnalysisCoverage


pytestmark = pytest.mark.usefixtures("seed_required_master_codes")


client = TestClient(app)
REFERENCE_DATE = "2026-09-08"


def _persist_analysis(db, *, version: BidNoticeVersion, performance_amount: int) -> QualificationAnalysisRun:
    run = QualificationAnalysisRun(
        id=uuid4(),
        notice_version_id=version.id,
        contract_version="ai-analysis-v0.2",
        analysis_kind="QUALIFICATION_REQUIREMENTS",
        status="SUCCEEDED",
        target_chunk_ids=[],
        diagnostics=[],
        input_fingerprint=qualification_analysis_version_fingerprint(version),
    )
    db.add(run)
    db.flush()

    requirements = [
        {
            "requirement_key": "REQ-REGION",
            "requirement_group_key": "REQ-REGION-GROUP",
            "group_operator": "ALL_OF",
            "type": "REGION",
            "operator": "MATCH",
            "value_json": "서울특별시",
            "unit": None,
            "period_months": None,
            "scope": {},
            "raw": "서울특별시에 소재한 업체만 참가할 수 있다.",
        },
        {
            "requirement_key": "REQ-STAFF",
            "requirement_group_key": "REQ-STAFF-GROUP",
            "group_operator": "ALL_OF",
            "type": "STAFF",
            "operator": ">=",
            "value_json": 5,
            "unit": "PERSON",
            "period_months": None,
            "scope": {"role": "개발"},
            "raw": "개발 인력 5명 이상을 보유하여야 한다.",
        },
        {
            "requirement_key": "REQ-PERFORMANCE-AMOUNT",
            "requirement_group_key": "REQ-PERFORMANCE-GROUP",
            "group_operator": "ALL_OF",
            "type": "PERFORMANCE_AMOUNT",
            "operator": ">=",
            "value_json": performance_amount,
            "unit": "KRW",
            "period_months": Decimal("36"),
            "scope": {"aggregation": "UNSPECIFIED", "client_requirement": "공공기관"},
            "raw": f"최근 3년간 공공기관 수행실적 {performance_amount // 100_000_000}억원 이상을 보유하여야 한다.",
        },
        {
            "requirement_key": "REQ-REGISTRATION",
            "requirement_group_key": "REQ-REGISTRATION-GROUP",
            "group_operator": "ALL_OF",
            "type": "REGISTRATION_CERTIFICATION",
            "operator": "MATCH",
            "value_json": "정보통신공사업",
            "unit": None,
            "period_months": None,
            "scope": {"kind": "REGISTRATION"},
            "raw": "정보통신공사업 등록업체이어야 한다.",
        },
    ]

    for item in requirements:
        db.add(
            QualificationRequirementRecord(
                id=uuid4(),
                analysis_run_id=run.id,
                requirement_key=item["requirement_key"],
                requirement_group_key=item["requirement_group_key"],
                group_operator=item["group_operator"],
                type=item["type"],
                operator=item["operator"],
                value_json=item["value_json"],
                unit=item["unit"],
                period_months=item["period_months"],
                scope=item["scope"],
                required=True,
                raw=item["raw"],
                confidence=Decimal("1.0"),
                evidence_keys=[],
            )
        )
    db.commit()
    return run


def _seed_golden_case():
    db = SessionLocal()
    now = datetime.now(timezone.utc)
    company_id = uuid4()
    notice_id = uuid4()
    baseline_version_id = uuid4()
    current_version_id = uuid4()
    case_id = uuid4()

    company = Company(
        id=company_id,
        name="Golden Demo Systems",
        business_registration_number=None,
        region_code="11",
        region_name="서울특별시",
        company_size="SMALL",
    )
    db.add(company)
    db.add(CompanyStaff(company_id=company_id, total_count=8, verified=True))
    db.add(CompanyStaffRole(company_id=company_id, role_name="PM", headcount=2, verified=True))
    db.add(CompanyStaffRole(company_id=company_id, role_name="개발", headcount=5, verified=True))
    db.add(
        CompanyPerformance(
            id=uuid4(),
            company_id=company_id,
            name="공공기관 정보시스템 구축",
            client_name="데모 공공기관",
            client_institution_code=None,
            amount=Decimal("500000000"),
            started_at=date(2026, 1, 1),
            completed_at=date(2026, 6, 30),
            description=None,
            verified=True,
        )
    )

    notice = BidNotice(
        id=notice_id,
        bid_notice_no=f"GOLDEN-{uuid4().hex[:12]}",
        title="Golden 변경공고 자격검증",
        business_type="SERVICE",
        notice_kind="일반공고",
        announcing_institution_code=None,
        announcing_institution_name="Golden 발주기관",
        demanding_institution_code=None,
        demanding_institution_name=None,
        first_seen_at=now,
        last_seen_at=now,
    )
    db.add(notice)
    baseline = BidNoticeVersion(
        id=baseline_version_id,
        notice_id=notice_id,
        version_number=1,
        bid_notice_order="00",
        is_current=False,
        notice_kind="일반공고",
        registration_type="등록",
        is_reannouncement=False,
        posted_at=now,
        changed_at=None,
        bid_started_at=None,
        bid_closed_at=None,
        opened_at=None,
        allocated_budget=None,
        estimated_price=None,
        contract_method=None,
        change_reason=None,
        detail_url=None,
        source_endpoint="golden-e2e",
        payload_hash="1" * 64,
        raw_json={"fixture": "baseline"},
        collected_at=now,
    )
    current = BidNoticeVersion(
        id=current_version_id,
        notice_id=notice_id,
        version_number=2,
        bid_notice_order="01",
        is_current=True,
        notice_kind="변경공고",
        registration_type="변경",
        is_reannouncement=False,
        posted_at=now,
        changed_at=now,
        bid_started_at=None,
        bid_closed_at=None,
        opened_at=None,
        allocated_budget=None,
        estimated_price=None,
        contract_method=None,
        change_reason="실적 기준 변경",
        detail_url=None,
        source_endpoint="golden-e2e",
        payload_hash="2" * 64,
        raw_json={"fixture": "current"},
        collected_at=now,
    )
    db.add_all([baseline, current])
    db.flush()

    case = PreflightCase(
        id=case_id,
        company_id=company_id,
        notice_id=notice_id,
        baseline_version_id=baseline_version_id,
        current_version_id=current_version_id,
        title="Golden E2E 자격검토",
        status="READY",
    )
    db.add(case)
    db.flush()

    baseline_run = _persist_analysis(db, version=baseline, performance_amount=400_000_000)
    current_run = _persist_analysis(db, version=current, performance_amount=600_000_000)
    db.close()
    return {
        "company_id": company_id,
        "notice_id": notice_id,
        "case_id": case_id,
        "baseline_analysis_id": baseline_run.id,
        "current_analysis_id": current_run.id,
    }


def _cleanup(seed):
    db = SessionLocal()
    try:
        notice = db.get(BidNotice, seed["notice_id"])
        if notice is not None:
            db.delete(notice)
            db.commit()
        company = db.get(Company, seed["company_id"])
        if company is not None:
            db.delete(company)
            db.commit()
    finally:
        db.close()


def _ground_analysis_documents(db, seed):
    """Attach complete, version-specific extracted texts and grounded evidence."""
    for run_id in (seed["baseline_analysis_id"], seed["current_analysis_id"]):
        run = db.get(QualificationAnalysisRun, run_id)
        version = db.get(BidNoticeVersion, run.notice_version_id)
        requirements = sorted(run.requirements, key=lambda item: item.requirement_key)
        blocks = [{"block_index": index, "text": item.raw} for index, item in enumerate(requirements)]
        text = "\n".join(item.raw for item in requirements)
        file_hash = sha256(f"file:{version.id}:{text}".encode()).hexdigest()
        text_hash = sha256(text.encode()).hexdigest()
        document = NoticeDocument(
            id=uuid4(), notice_version_id=version.id, document_order=0,
            name="notice.pdf", url=f"https://example.invalid/{version.id}.pdf",
            source_field="fixture_document", download_status="DOWNLOADED",
            file_sha256=file_hash, extraction_status="EXTRACTED",
            extracted_text=text, extracted_blocks=blocks,
            extracted_text_sha256=text_hash,
        )
        db.add(document)
        db.flush()
        for index, requirement in enumerate(requirements):
            key = f"EVD:{requirement.requirement_key}"
            requirement.evidence_keys = [key]
            db.add(QualificationEvidenceRecord(
                id=uuid4(), analysis_run_id=run.id, evidence_key=key,
                source_type="NOTICE_DOCUMENT", document_id=str(document.id),
                notice_version_id=str(version.id), location={"block_start": index, "block_end": index},
                quote=requirement.raw, source_sha256=file_hash,
                extracted_text_sha256=text_hash,
            ))
        run.coverage = AnalysisCoverage(section_selection="anchored").model_dump(mode="json")
        db.flush()
        db.expire(version, ["documents"])
        run.input_fingerprint = qualification_analysis_version_fingerprint(version)
    db.commit()


def test_revalidation_reuses_only_fully_grounded_unchanged_profile_judgments(monkeypatch):
    seed = _seed_golden_case()
    try:
        with SessionLocal() as db:
            _ground_analysis_documents(db, seed)
            case = db.get(PreflightCase, seed["case_id"])
            current_id = case.current_version_id
            case.current_version_id = case.baseline_version_id
            db.commit()
            source = run_qualification_judgment(db, case_id=case.id, reference_date=date.fromisoformat(REFERENCE_DATE))
            case.current_version_id = current_id
            db.commit()

            from apps.api.app.qualification import revalidation as module
            original = module.judge_requirement
            recalculated = []

            def tracked(requirement, *args, **kwargs):
                recalculated.append(requirement.requirement_key)
                return original(requirement, *args, **kwargs)

            monkeypatch.setattr(module, "judge_requirement", tracked)
            result = run_qualification_revalidation(db, case_id=case.id, payload=QualificationRevalidationCreate(
                source_judgment_run_id=source.id,
                baseline_analysis_run_id=seed["baseline_analysis_id"],
                current_analysis_run_id=seed["current_analysis_id"],
                reference_date=date.fromisoformat(REFERENCE_DATE),
            ))
            assert result.revalidated_keys == ["REQ-PERFORMANCE-AMOUNT", "REQ-REGISTRATION"]
            assert recalculated == result.revalidated_keys
            by_key = {item.requirement_key: item for item in result.result.judgments}
            assert by_key["REQ-REGION"].status == "SATISFIED"
            assert by_key["REQ-STAFF"].status == "SATISFIED"
            assert by_key["REQ-PERFORMANCE-AMOUNT"].status == "UNKNOWN"
            assert by_key["REQ-REGISTRATION"].status == "UNKNOWN"
    finally:
        _cleanup(seed)


def test_revalidation_reviews_unchanged_requirement_with_unverified_current_quote():
    seed = _seed_golden_case()
    try:
        with SessionLocal() as db:
            _ground_analysis_documents(db, seed)
            case = db.get(PreflightCase, seed["case_id"])
            current_id = case.current_version_id
            case.current_version_id = case.baseline_version_id
            db.commit()
            source = run_qualification_judgment(db, case_id=case.id, reference_date=date.fromisoformat(REFERENCE_DATE))
            case.current_version_id = current_id
            current = db.get(QualificationAnalysisRun, seed["current_analysis_id"])
            next(item for item in current.evidence if item.evidence_key == "EVD:REQ-REGION").quote = "원문에 없는 인용"
            next(item for item in current.evidence if item.evidence_key == "EVD:REQ-PERFORMANCE-AMOUNT").quote = "원문에 없는 변경 조건"
            db.commit()
            result = run_qualification_revalidation(db, case_id=case.id, payload=QualificationRevalidationCreate(
                source_judgment_run_id=source.id,
                baseline_analysis_run_id=seed["baseline_analysis_id"],
                current_analysis_run_id=seed["current_analysis_id"],
                reference_date=date.fromisoformat(REFERENCE_DATE),
            ))
            by_key = {item.requirement_key: item for item in result.result.judgments}
            assert by_key["REQ-REGION"].status == "UNKNOWN"
            assert by_key["REQ-REGION"].reason_code == "NEEDS_REVIEW"
            assert "REQ-REGION" not in result.revalidated_keys
            assert by_key["REQ-PERFORMANCE-AMOUNT"].status == "UNKNOWN"
            assert by_key["REQ-PERFORMANCE-AMOUNT"].reason_code == "NEEDS_REVIEW"
            assert "REQ-PERFORMANCE-AMOUNT" not in result.revalidated_keys
            assert by_key["REQ-STAFF"].status == "SATISFIED"
    finally:
        _cleanup(seed)


def test_mvp_golden_path_judgment_ask_back_and_revalidation() -> None:
    seed = _seed_golden_case()
    try:
        with SessionLocal() as db:
            _ground_analysis_documents(db, seed)
        completeness = client.patch(
            f"/api/v1/companies/{seed['company_id']}/qualification-profile-completeness",
            json={
                "staff_roles": True,
                "performances": True,
                "certifications": False,
            },
        )
        assert completeness.status_code == 200, completeness.text

        baseline_response = client.post(
            f"/api/v1/preflight-cases/{seed['case_id']}/qualification-judgments",
            json={
                "analysis_run_id": str(seed["baseline_analysis_id"]),
                "reference_date": REFERENCE_DATE,
            },
        )
        assert baseline_response.status_code == 200, baseline_response.text
        baseline = baseline_response.json()
        assert baseline["overall_status"] == "needs_review"
        by_key = {item["requirement_key"]: item for item in baseline["judgments"]}
        assert by_key["REQ-REGION"]["status"] == "SATISFIED"
        assert by_key["REQ-STAFF"]["status"] == "SATISFIED"
        assert by_key["REQ-PERFORMANCE-AMOUNT"]["status"] == "SATISFIED"
        assert by_key["REQ-REGISTRATION"]["status"] == "UNKNOWN"

        questions_response = client.get(
            f"/api/v1/preflight-cases/{seed['case_id']}/qualification-questions",
            params={"source_judgment_run_id": baseline["id"]},
        )
        assert questions_response.status_code == 200, questions_response.text
        questions = questions_response.json()
        assert [item["requirement_key"] for item in questions] == ["REQ-REGISTRATION"]

        answer_response = client.post(
            f"/api/v1/preflight-cases/{seed['case_id']}/qualification-answers",
            json={
                "source_judgment_run_id": baseline["id"],
                "requirement_key": "REQ-REGISTRATION",
                "satisfies_requirement": True,
                "normalized_value": "정보통신공사업",
                "evidence_held": True,
                "apply_to_profile": False,
            },
        )
        assert answer_response.status_code == 200, answer_response.text
        answered = answer_response.json()["result"]
        assert answered["overall_status"] == "core_met"
        answered_by_key = {item["requirement_key"]: item for item in answered["judgments"]}
        assert answered_by_key["REQ-REGISTRATION"]["status"] == "SATISFIED"
        assert answered_by_key["REQ-REGISTRATION"]["basis_type"] == "USER_ANSWER"

        revalidation_response = client.post(
            f"/api/v1/preflight-cases/{seed['case_id']}/qualification-revalidation",
            json={
                "source_judgment_run_id": answered["id"],
                "baseline_analysis_run_id": str(seed["baseline_analysis_id"]),
                "current_analysis_run_id": str(seed["current_analysis_id"]),
                "reference_date": REFERENCE_DATE,
            },
        )
        assert revalidation_response.status_code == 200, revalidation_response.text
        revalidation = revalidation_response.json()

        changes = {item.get("current_key") or item.get("baseline_key"): item for item in revalidation["changes"]}
        assert changes["REQ-PERFORMANCE-AMOUNT"]["change_type"] == "MODIFIED"
        assert changes["REQ-REGION"]["change_type"] == "UNCHANGED"
        assert changes["REQ-STAFF"]["change_type"] == "UNCHANGED"
        assert changes["REQ-REGISTRATION"]["change_type"] == "UNCHANGED"
        # The modified performance requirement must be recalculated, not copied.
        assert "REQ-PERFORMANCE-AMOUNT" in revalidation["revalidated_keys"]

        result = revalidation["result"]
        # 실적 금액은 확인 항목이다(2026-10-07). 미달로 확정돼도 '부적합' 을 확정하지 않고 '적합' 도 주지 않는다.
        assert result["overall_status"] == "needs_review"
        result_by_key = {item["requirement_key"]: item for item in result["judgments"]}
        assert result_by_key["REQ-PERFORMANCE-AMOUNT"]["status"] == "UNSATISFIED"
    finally:
        _cleanup(seed)
