"""Profile → notice matching over cached qualification analyses.

This is intentionally staged. It never labels an unanalyzed notice as matched.
The service reuses the same deterministic qualification rules used by a
PreflightCase, but does not persist a JudgmentRun until the user starts a review.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased, selectinload

from bidengine.judgment.rules import judge_requirements
from ..analysis_models import QualificationAnalysisRun
from ..judgment_models import CompanyQualificationProfileCompleteness
from ..matching_schemas import NoticeMatchRead, NoticeMatchSearchResponse
from ..models import BidNotice, BidNoticeVersion
from .analysis import analysis_run_response
from .judgment import _load_company, _record_to_completeness, build_company_profile_snapshot


_STATUS_ORDER = {"eligible": 0, "insufficient_data": 1, "ineligible": 2}


def match_cached_notices(
    db: Session,
    *,
    company_id: UUID,
    reference_date: date | None = None,
    limit: int = 50,
) -> NoticeMatchSearchResponse:
    company = _load_company(db, company_id)
    completeness = _record_to_completeness(db.get(CompanyQualificationProfileCompleteness, company_id))
    profile = build_company_profile_snapshot(company, completeness)
    ref_date = reference_date or date.today()

    latest_run = aliased(QualificationAnalysisRun)
    latest_run_id = (
        select(latest_run.id)
        .where(latest_run.notice_version_id == BidNoticeVersion.id)
        .order_by(latest_run.created_at.desc(), latest_run.id.desc())
        .limit(1)
        .correlate(BidNoticeVersion)
        .scalar_subquery()
    )

    analyzed_versions = db.execute(
        select(BidNotice, BidNoticeVersion, QualificationAnalysisRun)
        .join(BidNoticeVersion, BidNoticeVersion.notice_id == BidNotice.id)
        .join(QualificationAnalysisRun, QualificationAnalysisRun.id == latest_run_id)
        .where(
            BidNoticeVersion.is_current.is_(True),
            QualificationAnalysisRun.status != "FAILED",
        )
        .options(
            selectinload(QualificationAnalysisRun.requirements),
            selectinload(QualificationAnalysisRun.evidence),
        )
        .order_by(BidNotice.last_seen_at.desc())
    ).all()

    items: list[NoticeMatchRead] = []
    for notice, version, run in analyzed_versions:
        analysis = analysis_run_response(run)
        evaluation = judge_requirements(
            analysis.requirements,
            profile,
            preflight_case_id=f"MATCH:{company_id}:{notice.id}",
            reference_date=ref_date,
            analysis_status=run.status,
        )
        overall = evaluation.overall_status

        satisfied = sum(item.status == "SATISFIED" for item in evaluation.judgments)
        unknown = sum(item.status == "UNKNOWN" for item in evaluation.judgments)
        unsatisfied = sum(item.status == "UNSATISFIED" for item in evaluation.judgments)
        items.append(
            NoticeMatchRead(
                notice_id=notice.id,
                bid_notice_no=notice.bid_notice_no,
                title=notice.title,
                institution_name=notice.announcing_institution_name,
                version_number=version.version_number,
                analysis_run_id=run.id,
                analysis_status=run.status,
                overall_status=overall,
                satisfied_count=satisfied,
                unknown_count=unknown,
                unsatisfied_count=unsatisfied,
                requirement_count=len(analysis.requirements),
                evidence_count=len(analysis.evidence),
                analyzed_at=run.created_at,
            )
        )

    items.sort(
        key=lambda item: (
            _STATUS_ORDER[item.overall_status],
            item.unsatisfied_count,
            item.unknown_count,
            -item.satisfied_count,
            item.bid_notice_no,
        )
    )
    return NoticeMatchSearchResponse(
        company_id=company_id,
        analyzed_notice_count=len(items),
        returned_count=min(len(items), limit),
        items=items[:limit],
    )
