"""Profile → notice matching over cached qualification analyses.

This is intentionally staged. It never labels an unanalyzed notice as matched.
The service reuses the same deterministic qualification rules used by a
PreflightCase, but does not persist a JudgmentRun until the user starts a review.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from bidengine.judgment.rules import judge_requirements
from ..analysis_models import QualificationAnalysisRun
from ..judgment_models import CompanyQualificationProfileCompleteness
from ..matching_schemas import NoticeMatchRead, NoticeMatchSearchResponse
from ..models import BidNotice, BidNoticeVersion
from .analysis import analysis_run_response, is_qualification_analysis_run_stale
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

    analyzed_versions = db.execute(
        select(BidNotice, BidNoticeVersion, QualificationAnalysisRun)
        .join(BidNoticeVersion, BidNoticeVersion.notice_id == BidNotice.id)
        .join(
            QualificationAnalysisRun,
            QualificationAnalysisRun.notice_version_id == BidNoticeVersion.id,
        )
        .where(
            BidNoticeVersion.is_current.is_(True),
        )
        .options(
            selectinload(QualificationAnalysisRun.notice_version).selectinload(
                BidNoticeVersion.documents
            ),
            selectinload(QualificationAnalysisRun.requirements),
            selectinload(QualificationAnalysisRun.evidence),
        )
        .order_by(
            BidNotice.last_seen_at.desc(),
            QualificationAnalysisRun.created_at.desc(),
            QualificationAnalysisRun.id.desc(),
        )
    ).all()

    items: list[NoticeMatchRead] = []
    selected_notices: set[UUID] = set()
    for notice, version, run in analyzed_versions:
        if notice.id in selected_notices or is_qualification_analysis_run_stale(run):
            continue
        selected_notices.add(notice.id)
        if run.status == "FAILED":
            continue
        analysis = analysis_run_response(run)
        evaluation = judge_requirements(
            analysis.requirements,
            profile,
            preflight_case_id=f"MATCH:{company_id}:{notice.id}",
            reference_date=ref_date,
            analysis_status=run.status,
            coverage_complete=analysis.verdict_complete,
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
