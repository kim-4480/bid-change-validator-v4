"""Seed Golden Set v0.2 companies and login accounts for product testing.

The Golden bundle remains the source of truth. This script only adapts its
company profiles to the normalized backend tables. It is intentionally blocked
in production and does not contact G2B or OpenAI.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, NAMESPACE_URL, uuid5

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..analysis_models import (
    QualificationAnalysisRun,
    QualificationEvidenceRecord,
    QualificationRequirementRecord,
)
from ..auth import hash_password
from ..auth_models import AppUser, AuthSession
from ..config import get_settings
from ..database import SessionLocal
from ..judgment_models import CompanyQualificationProfileCompleteness
from ..models import (
    BidNotice,
    BidNoticeVersion,
    Company,
    CompanyCertification,
    CompanyIndustry,
    CompanyPerformance,
    CompanyPerformanceField,
    CompanyStaff,
    CompanyStaffRole,
    IndustryCode,
    PreflightCase,
)


GOLDEN_CONTRACT_VERSION = "golden-v0.2-draft"
DEFAULT_PASSWORD = "golden-test"
CASE_PATTERN = re.compile(r"J\d{2}")


def golden_username(case_id: str) -> str:
    if CASE_PATTERN.fullmatch(case_id) is None:
        raise ValueError(f"unsupported Golden case id: {case_id}")
    return f"golden-{case_id.casefold()}"


def golden_business_number(case_id: str) -> str:
    return f"9902{int(case_id[1:]):06d}"


def synthetic_industry_code(case_id: str, index: int) -> str:
    return f"GOLDEN-{case_id}-{index:02d}"


def load_golden_bundle(bundle_dir: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    bundle_path = bundle_dir / "fixture_bundle.json"
    evidence_path = bundle_dir / "sources" / "evidence_all.json"
    if not bundle_path.is_file():
        raise FileNotFoundError(f"Golden bundle not found: {bundle_path}")
    if not evidence_path.is_file():
        raise FileNotFoundError(f"Golden evidence not found: {evidence_path}")

    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    cases = [item for item in bundle.get("cases", []) if CASE_PATTERN.fullmatch(item.get("case_id", ""))]
    if not cases:
        raise ValueError("Golden bundle has no J01~J32 cases")
    case_ids = [item["case_id"] for item in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("Golden bundle contains duplicate case ids")

    evidence_rows = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence = {item["evidence_id"]: item for item in evidence_rows}
    return sorted(cases, key=lambda item: item["case_id"]), evidence


def _as_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _replace_company_profile(db: Session, case: dict[str, Any]) -> Company:
    case_id = case["case_id"]
    profile = case["profile"]
    company_id = UUID(profile["company_id"])
    company = db.get(Company, company_id)
    if company is None:
        company = Company(id=company_id, name=case["profile_name"], company_size=profile["company_size"])
        db.add(company)
    company.name = case["profile_name"]
    company.business_registration_number = golden_business_number(case_id)
    company.region_code = profile.get("region_code")
    company.region_name = profile.get("region_name")
    company.company_size = profile["company_size"]
    db.flush()

    performance_ids = select(CompanyPerformance.id).where(CompanyPerformance.company_id == company_id)
    db.execute(delete(CompanyPerformanceField).where(CompanyPerformanceField.performance_id.in_(performance_ids)))
    db.execute(delete(CompanyPerformance).where(CompanyPerformance.company_id == company_id))
    db.execute(delete(CompanyCertification).where(CompanyCertification.company_id == company_id))
    db.execute(delete(CompanyStaffRole).where(CompanyStaffRole.company_id == company_id))
    db.execute(delete(CompanyStaff).where(CompanyStaff.company_id == company_id))
    db.execute(delete(CompanyIndustry).where(CompanyIndustry.company_id == company_id))

    now = datetime.now(timezone.utc)
    for index, item in enumerate(profile.get("industries", []), start=1):
        industry_code = str(item.get("code") or synthetic_industry_code(case_id, index))
        industry = db.get(IndustryCode, industry_code)
        if industry is None:
            industry = IndustryCode(
                code=industry_code,
                name=str(item.get("name") or industry_code),
                active=True,
                changed_at=None,
                source_window="golden-v0.2",
                collected_at=now,
                raw_json={"source": "golden-v0.2", "case_id": case_id},
            )
            db.add(industry)
        db.add(
            CompanyIndustry(
                company_id=company_id,
                industry_code=industry_code,
                verified=bool(item.get("verified", False)),
            )
        )

    staff = profile.get("staff")
    if staff is not None:
        db.add(
            CompanyStaff(
                company_id=company_id,
                total_count=int(staff.get("total_count", 0)),
                verified=bool(staff.get("verified", False)),
            )
        )
        for role in staff.get("roles", []):
            db.add(
                CompanyStaffRole(
                    company_id=company_id,
                    role_name=role["role_name"],
                    headcount=int(role["headcount"]),
                    career_years=(
                        Decimal(str(role["career_years"]))
                        if role.get("career_years") is not None
                        else None
                    ),
                    verified=bool(role.get("verified", False)),
                )
            )

    for item in profile.get("performances", []):
        performance = CompanyPerformance(
            id=uuid5(NAMESPACE_URL, f"bidcheck:golden-v0.2:{case_id}:performance:{item['ref']}"),
            company_id=company_id,
            name=item["name"],
            client_name=item.get("client_name"),
            client_institution_code=item.get("client_institution_code"),
            amount=Decimal(str(item["amount"])),
            started_at=_as_date(item.get("started_at")),
            completed_at=_as_date(item.get("completed_at")),
            completed_year=item.get("completed_year"),
            description=None,
            verified=bool(item.get("verified", False)),
        )
        db.add(performance)
        for field in item.get("fields", []):
            db.add(CompanyPerformanceField(performance_id=performance.id, field_name=field))

    for item in profile.get("certifications", []):
        db.add(
            CompanyCertification(
                id=uuid5(NAMESPACE_URL, f"bidcheck:golden-v0.2:{case_id}:certification:{item['ref']}"),
                company_id=company_id,
                name=item["name"],
                certification_code=item.get("certification_code"),
                certificate_number=item.get("ref"),
                issuer_name=item.get("issuer_name"),
                issued_at=_as_date(item.get("issued_at")),
                expires_at=_as_date(item.get("expires_at")),
                verified=bool(item.get("verified", False)),
            )
        )

    completeness = profile.get("completeness", {})
    record = db.get(CompanyQualificationProfileCompleteness, company_id)
    if record is None:
        record = CompanyQualificationProfileCompleteness(company_id=company_id)
        db.add(record)
    for source, target in (
        ("region", "region_complete"),
        ("company_size", "company_size_complete"),
        ("industries", "industries_complete"),
        ("staff_total", "staff_total_complete"),
        ("staff_roles", "staff_roles_complete"),
        ("performances", "performances_complete"),
        ("certifications", "certifications_complete"),
    ):
        setattr(record, target, bool(completeness.get(source, False)))
    return company


def _upsert_login(db: Session, *, company: Company, case_id: str, password: str) -> AppUser:
    username = golden_username(case_id)
    user = db.scalar(select(AppUser).where(AppUser.username == username))
    if user is None:
        user = AppUser(username=username, password_hash="", role="ADMIN", active=True)
        db.add(user)
        db.flush()
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    user.password_hash = hash_password(password)
    user.company_id = company.id
    user.role = "ADMIN"
    user.active = True
    user.failed_login_attempts = 0
    user.locked_until = None
    return user


def _ensure_notice_version(
    db: Session,
    case: dict[str, Any],
    *,
    create_missing_notices: bool,
) -> BidNoticeVersion | None:
    version_id = UUID(case["notice_version_id"])
    version = db.get(BidNoticeVersion, version_id)
    if version is not None or not create_missing_notices:
        return version

    notice = db.scalar(select(BidNotice).where(BidNotice.bid_notice_no == case["notice_no"]))
    now = datetime.now(timezone.utc)
    if notice is None:
        notice = BidNotice(
            id=uuid5(NAMESPACE_URL, f"bidcheck:golden-v0.2:notice:{case['notice_no']}"),
            bid_notice_no=case["notice_no"],
            title=case["title"],
            business_type="SERVICE",
            notice_kind="골든셋 테스트",
            announcing_institution_code=None,
            announcing_institution_name="골든셋 테스트",
            demanding_institution_code=None,
            demanding_institution_name=None,
            first_seen_at=now,
            last_seen_at=now,
        )
        db.add(notice)
        db.flush()
    max_version = db.scalar(
        select(func.max(BidNoticeVersion.version_number)).where(BidNoticeVersion.notice_id == notice.id)
    ) or 0
    db.execute(
        BidNoticeVersion.__table__.update()
        .where(BidNoticeVersion.notice_id == notice.id)
        .values(is_current=False)
    )
    version = BidNoticeVersion(
        id=version_id,
        notice_id=notice.id,
        version_number=max_version + 1,
        bid_notice_order=case["source_order"],
        is_current=True,
        notice_kind="골든셋 테스트",
        registration_type="테스트",
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
        source_endpoint="golden-v0.2",
        payload_hash=hashlib.sha256(f"golden-v0.2:{version_id}".encode()).hexdigest(),
        raw_json={"source": "golden-v0.2", "draft": True},
        collected_at=now,
    )
    db.add(version)
    db.flush()
    return version


def _replace_analysis(
    db: Session,
    *,
    case: dict[str, Any],
    version: BidNoticeVersion,
    evidence: dict[str, dict[str, Any]],
) -> QualificationAnalysisRun:
    existing = db.scalar(
        select(QualificationAnalysisRun).where(
            QualificationAnalysisRun.notice_version_id == version.id,
            QualificationAnalysisRun.contract_version == GOLDEN_CONTRACT_VERSION,
        )
    )
    if existing is not None:
        db.delete(existing)
        db.flush()

    run = QualificationAnalysisRun(
        notice_version_id=version.id,
        contract_version=GOLDEN_CONTRACT_VERSION,
        analysis_kind="QUALIFICATION_REQUIREMENTS",
        status=case.get("analysis_status", "PARTIAL"),
        target_chunk_ids=[],
        diagnostics=[{"code": "GOLDEN_DRAFT", "message": "독립 검토자 승인 전 골든셋 초안"}],
        dropped_requirements=[],
    )
    db.add(run)
    db.flush()

    used_evidence: set[str] = set()
    for canonical in case.get("canonical_inputs", []):
        requirement = canonical["requirement"]
        db.add(
            QualificationRequirementRecord(
                analysis_run_id=run.id,
                requirement_key=requirement["requirement_key"],
                requirement_group_key=requirement.get("requirement_group_key"),
                group_operator=requirement.get("group_operator"),
                type=requirement["type"],
                operator=requirement.get("operator"),
                value_json=requirement.get("value"),
                unit=requirement.get("unit"),
                period_months=(
                    Decimal(str(requirement["period_months"]))
                    if requirement.get("period_months") is not None
                    else None
                ),
                scope=requirement.get("scope", {}),
                requirement_role=requirement.get("requirement_role", "mandatory"),
                condition_complexity=requirement.get("condition_complexity", "simple"),
                required=bool(requirement.get("required", True)),
                raw=requirement["raw"],
                confidence=(
                    Decimal(str(requirement["confidence"]))
                    if requirement.get("confidence") is not None
                    else None
                ),
                evidence_keys=requirement.get("evidence_keys", []),
            )
        )
        used_evidence.update(requirement.get("evidence_keys", []))

    for evidence_key in sorted(used_evidence):
        item = evidence.get(evidence_key)
        if item is None:
            raise ValueError(f"missing evidence {evidence_key} for {case['case_id']}")
        db.add(
            QualificationEvidenceRecord(
                analysis_run_id=run.id,
                evidence_key=evidence_key,
                source_type="NOTICE_DOCUMENT",
                document_id=item["document_id"],
                notice_version_id=str(version.id),
                case_id=None,
                chunk_id=evidence_key,
                location={"display": item.get("location")},
                quote=item["quote"],
                source_sha256=None,
                extracted_text_sha256=None,
            )
        )
    return run


def _preserved_baseline_id(
    baseline: BidNoticeVersion | None,
    *,
    current: BidNoticeVersion,
) -> UUID | None:
    """Keep only a real earlier version of the same notice as the comparison baseline."""

    if baseline is None:
        return None
    if baseline.notice_id != current.notice_id:
        return None
    if baseline.version_number >= current.version_number:
        return None
    return baseline.id


def seed_golden_v02_accounts(
    db: Session,
    *,
    bundle_dir: Path,
    password: str = DEFAULT_PASSWORD,
    include_analysis: bool = False,
    create_missing_notices: bool = False,
) -> dict[str, Any]:
    if get_settings().app_environment == "production":
        raise RuntimeError("Golden Set accounts cannot be seeded in production")
    if len(password) < 8:
        raise ValueError("Golden test password must be at least 8 characters")
    if create_missing_notices and not include_analysis:
        raise ValueError("--create-missing-notices requires --include-analysis")

    cases, evidence = load_golden_bundle(bundle_dir)
    versions: dict[UUID, tuple[BidNoticeVersion, QualificationAnalysisRun | None]] = {}
    seeded_cases: list[dict[str, str]] = []
    missing_versions: list[dict[str, str]] = []

    for case in cases:
        company = _replace_company_profile(db, case)
        user = _upsert_login(db, company=company, case_id=case["case_id"], password=password)
        version = _ensure_notice_version(
            db,
            case,
            create_missing_notices=create_missing_notices,
        )
        analysis = None
        if version is None:
            missing_versions.append(
                {"case_id": case["case_id"], "notice_version_id": case["notice_version_id"]}
            )
        else:
            if include_analysis:
                cached = versions.get(version.id)
                if cached is None:
                    analysis = _replace_analysis(db, case=case, version=version, evidence=evidence)
                    versions[version.id] = (version, analysis)
                else:
                    analysis = cached[1]
            title = f"Golden v0.2 {case['case_id']} · {case['focus']}"
            preflight_case = db.scalar(
                select(PreflightCase).where(
                    PreflightCase.company_id == company.id,
                    PreflightCase.title == title,
                )
            )
            if preflight_case is None:
                preflight_case = PreflightCase(
                    company_id=company.id,
                    notice_id=version.notice_id,
                    baseline_version_id=None,
                    current_version_id=version.id,
                    title=title,
                    status="READY",
                )
                db.add(preflight_case)
                db.flush()
            else:
                existing_baseline = (
                    db.get(BidNoticeVersion, preflight_case.baseline_version_id)
                    if preflight_case.baseline_version_id is not None
                    else None
                )
                preflight_case.notice_id = version.notice_id
                preflight_case.baseline_version_id = _preserved_baseline_id(
                    existing_baseline,
                    current=version,
                )
                preflight_case.current_version_id = version.id
                preflight_case.status = "READY"
            seeded_cases.append(
                {
                    "case_id": case["case_id"],
                    "username": user.username,
                    "company_id": str(company.id),
                    "preflight_case_id": str(preflight_case.id),
                    "analysis_run_id": str(analysis.id) if analysis is not None else "",
                }
            )
        if version is None:
            seeded_cases.append(
                {
                    "case_id": case["case_id"],
                    "username": user.username,
                    "company_id": str(company.id),
                    "preflight_case_id": "",
                    "analysis_run_id": "",
                }
            )

    db.commit()
    return {
        "account_count": len(cases),
        "case_count": sum(bool(item["preflight_case_id"]) for item in seeded_cases),
        "analysis_count": len(versions),
        "password": password,
        "accounts": seeded_cases,
        "missing_versions": missing_versions,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="골든셋 v0.2 회사 프로필과 테스트 계정을 적재합니다.")
    parser.add_argument("--bundle-dir", type=Path, required=True)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument(
        "--include-analysis",
        action="store_true",
        help="고정 Canonical Requirement와 검토 건도 함께 적재합니다.",
    )
    parser.add_argument(
        "--create-missing-notices",
        action="store_true",
        help="로컬 테스트 DB에 공고가 없을 때 최소 공고/버전을 생성합니다.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        result = seed_golden_v02_accounts(
            db,
            bundle_dir=args.bundle_dir.resolve(),
            password=args.password,
            include_analysis=args.include_analysis,
            create_missing_notices=args.create_missing_notices,
        )
        print("Golden Set v0.2 test accounts ready")
        print(f"accounts: {result['account_count']}")
        print(f"preflight cases: {result['case_count']}")
        print(f"analysis runs: {result['analysis_count']}")
        print(f"login pattern: golden-j01 ~ golden-j32 / {result['password']}")
        if result["missing_versions"]:
            print(f"missing notice versions: {len(result['missing_versions'])}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
