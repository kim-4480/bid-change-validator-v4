from __future__ import annotations

import argparse
import hashlib
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, selectinload, sessionmaker
from sqlalchemy.pool import NullPool

from ..auth import hash_password
from ..auth_models import AppUser
from ..config import get_settings
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
    ProposalDocument,
)

KST = ZoneInfo("Asia/Seoul")
DEFAULT_NOTICE_NO = "R26BK01715087"
DEMO_COMPANY_NAME = "그린브릿지 글로벌 주식회사"
DEMO_BUSINESS_NO = "9909080908"
DEMO_CASE_TITLE = "Golden Demo · 청년그린창업 해외진출 제안 검토"
DEMO_USERNAME = "golden-demo"
DEMO_PASSWORD = "golden-demo"

PROPOSAL_TEXT = """2026년 청년그린창업 스프링캠프 해외진출 기획 및 운영 용역 제안서 초안

1. 회사 개요
그린브릿지 글로벌 주식회사는 공공·창업 지원 프로그램과 해외진출 프로그램을 기획·운영하는 중소기업입니다.

2. 수행 전략
- 참여기업 진단 및 국가별 시장 적합성 분석
- 현지 바이어·투자자 매칭
- 해외 현지 프로그램 운영 및 결과 보고

3. 수행 조직
총괄 PM 1명, 프로그램 운영 4명, 해외 파트너십 3명, 콘텐츠·디자인 2명이 참여합니다.

4. 유사 수행 실적
최근 3년간 공공기관 및 창업지원기관의 글로벌 액셀러레이팅·해외진출 프로그램을 수행했습니다.

5. 제출 예정 자료
정성제안서, 정량제안서, 사업자등록 관련 서류, 국세·지방세 완납증명서, 참여인력 재직증명서와 자격 증빙을 제출합니다.

6. 확인 필요
발표자료 최종본과 정량평가 자기평가표 일부 증빙은 현재 취합 중입니다.
"""


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _is_connection_limit(error: Exception) -> bool:
    text_value = str(error).upper()
    return "EMAXCONNSESSION" in text_value or (
        "MAX CLIENTS" in text_value and "POOL_SIZE" in text_value
    )


def _supabase_transaction_pooler_url(database_url: str) -> str | None:
    """Switch the same Supabase pooler from session mode 5432 to transaction mode 6543."""

    url = make_url(database_url)
    host = (url.host or "").lower()
    if not host.endswith(".pooler.supabase.com") or url.port != 5432:
        return None
    return url.set(port=6543).render_as_string(hide_password=False)


def _is_supabase_transaction_pooler(database_url: str) -> bool:
    url = make_url(database_url)
    return (url.host or "").lower().endswith(".pooler.supabase.com") and url.port == 6543


def _create_seed_engine(database_url: str):
    from sqlalchemy import create_engine

    connect_args: dict[str, object] = {"connect_timeout": 10}
    if _is_supabase_transaction_pooler(database_url):
        connect_args["prepare_threshold"] = None
    return create_engine(
        database_url,
        poolclass=NullPool,
        pool_pre_ping=True,
        connect_args=connect_args,
    )


def _prepare_seed_engine(database_url: str):
    """Preflight DB access and fallback only for Supabase session-pool exhaustion."""

    engine = _create_seed_engine(database_url)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return engine, "CONFIGURED", None
    except OperationalError as error:
        engine.dispose()
        fallback_url = _supabase_transaction_pooler_url(database_url)
        if not (_is_connection_limit(error) and fallback_url):
            raise

        fallback = _create_seed_engine(fallback_url)
        try:
            with fallback.connect() as connection:
                connection.execute(text("SELECT 1"))
            return fallback, "SUPABASE_TRANSACTION_POOLER_FALLBACK", str(error)
        except Exception:
            fallback.dispose()
            raise


def choose_demo_industry(db: Session) -> IndustryCode | None:
    for keyword in ("행사", "전시", "광고", "컨설팅", "정보통신"):
        row = db.scalar(
            select(IndustryCode)
            .where(IndustryCode.active.is_(True), IndustryCode.name.ilike(f"%{keyword}%"))
            .order_by(IndustryCode.code)
            .limit(1)
        )
        if row is not None:
            return row
    return db.scalar(
        select(IndustryCode).where(IndustryCode.active.is_(True)).order_by(IndustryCode.code).limit(1)
    )


def _usable_fallback_notice(db: Session) -> tuple[BidNotice, list[BidNoticeVersion]] | None:
    """Pick an existing service notice suitable for a local Stage 11 dry-run.

    The frozen demo notice may not exist in every shared DB snapshot. A fallback
    must have extracted text on its current version; multi-version notices are
    preferred so the same case can exercise the Changes UI. This is only a
    usability-test fixture selector, not a claim that the notice has a meaningful
    qualification change.
    """

    notices = list(
        db.scalars(
            select(BidNotice)
            .options(selectinload(BidNotice.versions).selectinload(BidNoticeVersion.documents))
            .where(BidNotice.business_type == "SERVICE")
            .order_by(BidNotice.last_seen_at.desc())
            .limit(300)
        ).all()
    )
    candidates: list[tuple[tuple[int, int, int, int], BidNotice, list[BidNoticeVersion]]] = []
    for notice in notices:
        versions = sorted(notice.versions, key=lambda item: item.version_number)
        if not versions:
            continue
        current = next((item for item in versions if item.is_current), versions[-1])
        current_extracted = [
            document
            for document in current.documents
            if document.extraction_status == "EXTRACTED" and (document.extracted_text or "").strip()
        ]
        if not current_extracted:
            continue
        current_chars = sum(document.extracted_char_count or 0 for document in current_extracted)
        score = (
            1 if len(versions) >= 2 else 0,
            len(versions),
            len(current_extracted),
            current_chars,
        )
        candidates.append((score, notice, versions))

    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    _, notice, versions = candidates[0]
    return notice, versions


def _get_notice_versions(
    db: Session,
    bid_notice_no: str,
    *,
    allow_fallback: bool = False,
) -> tuple[BidNotice, list[BidNoticeVersion], bool]:
    notice = db.scalar(select(BidNotice).where(BidNotice.bid_notice_no == bid_notice_no))
    fallback_used = False
    if notice is None:
        if not allow_fallback:
            raise ValueError(f"notice not found: {bid_notice_no}")
        fallback = _usable_fallback_notice(db)
        if fallback is None:
            raise ValueError(
                f"notice not found: {bid_notice_no}; no fallback SERVICE notice with extracted current documents was found"
            )
        notice, versions = fallback
        fallback_used = True
        return notice, versions, fallback_used

    versions = list(
        db.scalars(
            select(BidNoticeVersion)
            .where(BidNoticeVersion.notice_id == notice.id)
            .order_by(BidNoticeVersion.version_number)
        ).all()
    )
    if not versions:
        raise ValueError(f"notice has no versions: {bid_notice_no}")
    return notice, versions, fallback_used


def seed_product_golden_demo(
    db: Session,
    *,
    bid_notice_no: str = DEFAULT_NOTICE_NO,
    allow_notice_fallback: bool = False,
) -> dict[str, object]:
    if get_settings().app_environment == "production":
        raise RuntimeError("Product Golden demo seed cannot run in production")

    notice, versions, fallback_used = _get_notice_versions(
        db,
        bid_notice_no,
        allow_fallback=allow_notice_fallback,
    )
    baseline = versions[0]
    current = next((item for item in versions if item.is_current), versions[-1])

    company = db.scalar(
        select(Company).where(Company.business_registration_number == DEMO_BUSINESS_NO)
    )
    created_company = company is None
    if company is None:
        company = Company(
            name=DEMO_COMPANY_NAME,
            business_registration_number=DEMO_BUSINESS_NO,
            region_code="11",
            region_name="서울특별시",
            company_size="SMALL",
        )
        db.add(company)
        db.flush()

        industry = choose_demo_industry(db)
        if industry is not None:
            db.add(CompanyIndustry(company_id=company.id, industry_code=industry.code, verified=True))

        db.add(CompanyStaff(company_id=company.id, total_count=18, verified=True))
        db.add_all(
            [
                CompanyStaffRole(company_id=company.id, role_name="PM", headcount=2, verified=True),
                CompanyStaffRole(company_id=company.id, role_name="프로그램 운영", headcount=6, verified=True),
                CompanyStaffRole(company_id=company.id, role_name="해외 파트너십", headcount=4, verified=True),
            ]
        )

        performance = CompanyPerformance(
            company_id=company.id,
            name="공공기관 글로벌 액셀러레이팅 프로그램 운영",
            client_name="합성 공공기관",
            client_institution_code=None,
            amount=Decimal("520000000"),
            started_at=date(2025, 3, 1),
            completed_at=date(2025, 11, 30),
            description="청년창업기업 해외진출·바이어 매칭·현지 프로그램 운영",
            verified=True,
        )
        db.add(performance)
        db.flush()
        db.add_all(
            [
                CompanyPerformanceField(performance_id=performance.id, field_name="해외진출"),
                CompanyPerformanceField(performance_id=performance.id, field_name="창업지원"),
                CompanyPerformanceField(performance_id=performance.id, field_name="행사운영"),
            ]
        )

        db.add_all(
            [
                CompanyCertification(
                    company_id=company.id,
                    name="중소기업확인서",
                    certificate_number="DEMO-SME-2026-001",
                    issuer_name="중소벤처기업부",
                    issued_at=date(2026, 1, 1),
                    expires_at=date(2026, 12, 31),
                    verified=True,
                ),
                CompanyCertification(
                    company_id=company.id,
                    name="직접생산확인증명서",
                    certificate_number="DEMO-DIRECT-2026-001",
                    issuer_name="중소기업유통센터",
                    issued_at=date(2026, 1, 1),
                    expires_at=date(2027, 12, 31),
                    verified=True,
                ),
            ]
        )
        db.add(
            CompanyQualificationProfileCompleteness(
                company_id=company.id,
                region_complete=True,
                company_size_complete=True,
                industries_complete=True,
                staff_total_complete=True,
                staff_roles_complete=True,
                performances_complete=True,
                certifications_complete=True,
            )
        )
        db.flush()

    user = db.scalar(select(AppUser).where(AppUser.username == DEMO_USERNAME))
    created_user = user is None
    if user is None:
        user = AppUser(
            username=DEMO_USERNAME,
            password_hash=hash_password(DEMO_PASSWORD),
            company_id=company.id,
            role="ADMIN",
            active=True,
        )
        db.add(user)
    else:
        user.password_hash = hash_password(DEMO_PASSWORD)
        user.company_id = company.id
        user.role = "ADMIN"
        user.active = True

    case = db.scalar(
        select(PreflightCase).where(
            PreflightCase.company_id == company.id,
            PreflightCase.notice_id == notice.id,
            PreflightCase.title == DEMO_CASE_TITLE,
        )
    )
    created_case = case is None
    if case is None:
        case = PreflightCase(
            company_id=company.id,
            notice_id=notice.id,
            baseline_version_id=baseline.id if baseline.id != current.id else None,
            current_version_id=current.id,
            title=DEMO_CASE_TITLE,
            status="READY",
        )
        db.add(case)
        db.flush()

    proposal = db.scalar(
        select(ProposalDocument).where(
            ProposalDocument.case_id == case.id,
            ProposalDocument.name == "Golden Demo 제안서 초안.txt",
        )
    )
    created_proposal = proposal is None
    if proposal is None:
        settings = get_settings()
        storage_key = f"product-golden/{case.id}/proposal-draft.txt"
        if settings.document_storage_backend.strip().upper() == "LOCAL":
            target = Path(settings.document_storage_path) / storage_key
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(PROPOSAL_TEXT, encoding="utf-8")

        now = datetime.now(KST)
        text_sha = _sha256_text(PROPOSAL_TEXT)
        proposal = ProposalDocument(
            case_id=case.id,
            document_order=0,
            role="PROPOSAL",
            name="Golden Demo 제안서 초안.txt",
            storage_status="STORED",
            storage_key=storage_key,
            content_type="text/plain; charset=utf-8",
            file_size_bytes=len(PROPOSAL_TEXT.encode("utf-8")),
            file_sha256=text_sha,
            stored_at=now,
            storage_error=None,
            extraction_status="EXTRACTED",
            extracted_text=PROPOSAL_TEXT,
            extracted_blocks=[{"block_index": 0, "kind": "text", "text": PROPOSAL_TEXT}],
            extracted_char_count=len(PROPOSAL_TEXT),
            extracted_text_sha256=text_sha,
            text_extractor="PLAIN_TEXT",
            extracted_at=now,
            extraction_error=None,
        )
        db.add(proposal)

    db.commit()
    return {
        "notice": {
            "requested_bid_notice_no": bid_notice_no,
            "bid_notice_no": notice.bid_notice_no,
            "title": notice.title,
            "versions": len(versions),
            "fallback_used": fallback_used,
        },
        "company": {"id": str(company.id), "name": company.name, "created": created_company},
        "login": {
            "username": DEMO_USERNAME,
            "password": DEMO_PASSWORD,
            "created": created_user,
        },
        "case": {
            "id": str(case.id),
            "title": case.title,
            "baseline_version": baseline.version_number if baseline.id != current.id else None,
            "current_version": current.version_number,
            "created": created_case,
        },
        "proposal": {"name": proposal.name, "created": created_proposal},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the Product Golden demo into the configured DB.")
    parser.add_argument(
        "--notice-no",
        default=None,
        help=(
            "Explicit notice number. When omitted, the frozen demo notice is tried first and a usable existing "
            "SERVICE notice is selected if the frozen notice is absent."
        ),
    )
    args = parser.parse_args()

    requested_notice_no = args.notice_no or DEFAULT_NOTICE_NO
    configured_url = get_settings().sqlalchemy_database_url
    engine, database_connection_mode, initial_connection_error = _prepare_seed_engine(configured_url)
    SessionMaker = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = SessionMaker()
    try:
        result = seed_product_golden_demo(
            db,
            bid_notice_no=requested_notice_no,
            allow_notice_fallback=args.notice_no is None,
        )
        case_id = result["case"]["id"]
        print("Product Golden demo ready")
        print(f"database_connection_mode: {database_connection_mode}")
        if initial_connection_error:
            print("session_pooler_preflight_failed: true")
        if result["notice"]["fallback_used"]:
            print(f"fallback_notice_selected: {result['notice']['bid_notice_no']}")
            print("fallback_notice_note: current extracted documents are available; meaningful qualification change is not implied")
        print(f"notice: {result['notice']['bid_notice_no']} / versions={result['notice']['versions']}")
        print(f"company: {result['company']['name']}")
        print(f"login: {result['login']['username']} / {result['login']['password']}")
        print(f"case: {result['case']['title']}")
        print(f"case_id: {case_id}")
        baseline_version = result["case"]["baseline_version"]
        if baseline_version is None:
            print(f"versions: current=v{result['case']['current_version']} / baseline=none")
        else:
            print(f"versions: v{baseline_version} -> v{result['case']['current_version']}")
        print(f"proposal: {result['proposal']['name']}")
        print(f"qualification: http://localhost:3000/qualification?caseId={case_id}")
        print(f"evidence: http://localhost:3000/evidence?caseId={case_id}")
        print(f"changes: http://localhost:3000/changes?caseId={case_id}")
    finally:
        db.close()
        engine.dispose()


if __name__ == "__main__":
    main()
