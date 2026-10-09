"""Read-only company-to-notice recommendations.

The shared FastAPI app/Frontend must be connected by the integration owner.
No automatic qualification analysis is triggered by this router.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import re
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, load_only

from ..auth import authorize_company_access, get_optional_current_user
from ..auth_models import AppUser
from ..database import get_db
from ..analysis_models import QualificationAnalysisRun
from ..models import BidNotice, BidNoticeVersion
from .qualification_adapter import _load_company, company_query, evaluate
from .runtime import score_notices

router = APIRouter(prefix="/api/v1/recommendations", tags=["ml recommendations"])

UNKNOWN_DEADLINE_DAYS = 40
QUALIFICATION_BATCH_SIZE = 100
CANDIDATE_BATCH_SIZE = 500


class MLRecommendationRequest(BaseModel):
    query: str | None = Field(default=None, min_length=2, max_length=500)
    company_id: UUID | None = None
    limit: int = Field(default=20, ge=1, le=50)


class MLNoticeRecommendation(BaseModel):
    notice_id: UUID
    title: str
    rank: int
    relevance_score: float = Field(description="Business relevance only; not eligibility or win probability")
    reason: str
    version_number: int
    analysis_run_id: UUID | None = None
    analysis_version: str | None = None
    analysis_status: str = "UNKNOWN"
    qualification_state: Literal["eligible", "ineligible", "insufficient_data", "UNKNOWN", "stale"] = "UNKNOWN"
    qualification_reason: str | None = None
    rule_version: str | None = None
    is_stale: bool = False
    deadline_source: Literal["explicit", "assumed_40_days"] = "explicit"
    effective_deadline: datetime | None = None


class MLRecommendationResponse(BaseModel):
    model_version: str | None
    dataset_version: str | None
    scoring_source: Literal["local_lightgbm", "local_hf", "remote_inference", "lexical_fallback"]
    input_sha256: str | None = None
    fallback_reason: str | None = None
    fallback_used: bool = True
    total_valid_candidates: int = 0
    note: str = "Relevance is not eligibility or award probability; missing deadlines use a 40-day proxy."
    # Only verified eligible notices. Query-only requests have no verified eligibility.
    items: list[MLNoticeRecommendation]
    # UNKNOWN, insufficient_data and stale remain visible but are never certified eligible.
    needs_review_items: list[MLNoticeRecommendation] = Field(default_factory=list)


def _not_cancelled(notice_kind: str | None) -> bool:
    value = (notice_kind or "").lower()
    return not any(token in value for token in ("취소", "cancel", "무효"))


def eligible_window(version, *, now: datetime) -> tuple[str, datetime] | None:
    """Apply explicit close date or conservative posted+40d assumption.

    Unknown posting date with no explicit deadline is not an active notice.
    """
    if not _not_cancelled(version.notice_kind):
        return None
    deadline = version.bid_closed_at
    if deadline is not None:
        return ("explicit", deadline) if deadline > now else None
    posted = version.posted_at
    if posted is None:
        return None
    deadline = posted + timedelta(days=UNKNOWN_DEADLINE_DAYS)
    return ("assumed_40_days", deadline) if posted <= now and deadline > now else None


def candidates(db: Session, *, now: datetime | None = None) -> list[dict]:
    """Scan *all* currently valid notices, never just the last 150.

    Scan in bounded DB batches and never perform any analysis/DB writes.
    """
    now = now or datetime.now(timezone.utc)
    v = BidNoticeVersion
    n = BidNotice
    stmt = (
        select(n, v)
        .join(v, v.notice_id == n.id)
        .where(
            v.is_current.is_(True),
            or_(
                v.bid_closed_at > now,
                and_(
                    v.bid_closed_at.is_(None),
                    v.posted_at.is_not(None),
                    v.posted_at <= now,
                    v.posted_at > now - timedelta(days=UNKNOWN_DEADLINE_DAYS),
                ),
            ),
            ~func.lower(func.coalesce(v.notice_kind, n.notice_kind, "")).like("%취소%"),
            ~func.lower(func.coalesce(v.notice_kind, n.notice_kind, "")).like("%cancel%"),
            ~func.lower(func.coalesce(v.notice_kind, n.notice_kind, "")).like("%무효%"),
        )
        .options(
            load_only(n.id, n.title, n.business_type, n.announcing_institution_name,
                      n.demanding_institution_name, n.last_seen_at),
            load_only(v.id, v.notice_id, v.version_number, v.is_current, v.notice_kind,
                      v.posted_at, v.bid_closed_at, v.contract_method, v.allocated_budget),
        )
        .order_by(n.last_seen_at.desc(), n.id)
        .execution_options(yield_per=CANDIDATE_BATCH_SIZE)
    )
    output: list[dict] = []
    batch: list[tuple] = []

    def flush():
        if not batch:
            return
        version_ids = [version.id for _, version in batch]
        notice_ids = [notice.id for notice, _ in batch]
        previous = set(db.scalars(
            select(BidNoticeVersion.notice_id)
            .join(QualificationAnalysisRun, QualificationAnalysisRun.notice_version_id == BidNoticeVersion.id)
            .where(BidNoticeVersion.notice_id.in_(notice_ids),
                   BidNoticeVersion.is_current.is_(False))
        ).all())
        runs = db.scalars(
            select(QualificationAnalysisRun)
            .where(QualificationAnalysisRun.notice_version_id.in_(version_ids))
            .order_by(QualificationAnalysisRun.created_at.desc(), QualificationAnalysisRun.id.desc())
        ).all()
        latest = {}
        for run in runs:
            latest.setdefault(run.notice_version_id, run)
        for notice, version in batch:
            window = eligible_window(version, now=now)
            if not window or not _not_cancelled(notice.notice_kind):
                continue
            run = latest.get(version.id)
            search_text = " ".join(str(field) for field in (
                notice.title, notice.business_type, notice.announcing_institution_name,
                notice.demanding_institution_name, version.contract_method
            ) if field)
            output.append({
                "notice_id": str(notice.id), "title": notice.title,
                "notice_text": search_text, "version_number": version.version_number,
                "analysis_run_id": str(run.id) if run else None,
                "analysis_version": run.contract_version if run else None,
                "analysis_status": run.status if run else "UNKNOWN",
                "is_stale": run is None and notice.id in previous,
                "deadline_source": window[0], "effective_deadline": window[1],
            })
        batch.clear()

    for record in db.execute(stmt):
        batch.append(record)
        if len(batch) >= CANDIDATE_BATCH_SIZE:
            flush()
    flush()
    return output


def make_item(row: dict, state: dict, rank: int, source: str,
              query: str | None = None) -> MLNoticeRecommendation:
    qstate = state.get("state", "stale" if row["is_stale"] else "UNKNOWN")
    # Deterministic, auditable feature explanation (not a legal verdict).
    query_terms = set(re.findall(r"[\\uac00-\\ud7a3A-Za-z0-9]+", (query or "").lower()))
    notice_terms = set(re.findall(r"[\\uac00-\\ud7a3A-Za-z0-9]+",
                                  (row.get("notice_text") or row["title"]).lower()))
    matched = sorted(t for t in query_terms & notice_terms if len(t) >= 2)
    if matched:
        reason = "Shared company/notice terms: " + ", ".join(matched[:5])
    elif source == "lexical_fallback":
        reason = "No strong shared keywords; lexical fallback only"
    else:
        reason = "Model-generated text similarity; no directly matching keyword identified"
    reason += "; independent eligibility judgment required"
    return MLNoticeRecommendation(
        notice_id=row["notice_id"], title=row["title"], rank=rank,
        relevance_score=row["score"], reason=reason,
        version_number=row["version_number"],
        analysis_run_id=row["analysis_run_id"],
        analysis_version=row["analysis_version"],
        analysis_status=row["analysis_status"],
        qualification_state=qstate,
        qualification_reason=state.get("reason", "No verified current analysis"),
        rule_version=state.get("rule_version"), is_stale=row["is_stale"],
        deadline_source=row.get("deadline_source", "explicit"), effective_deadline=row.get("effective_deadline"),
    )


def partition_ranked(db, company_id, ranked: list[dict], limit: int,
                     source: str, query: str | None = None):
    eligible: list[MLNoticeRecommendation] = []
    needs_review: list[MLNoticeRecommendation] = []
    for start in range(0, len(ranked), QUALIFICATION_BATCH_SIZE):
        batch = ranked[start:start + QUALIFICATION_BATCH_SIZE]
        qualifications = evaluate(db, company_id, batch) if company_id is not None else {}
        for row in batch:
            state = qualifications.get(row["notice_id"], {})
            q = state.get("state", "UNKNOWN")
            if q == "ineligible":
                continue
            if q == "eligible" and company_id is not None:
                if len(eligible) < limit:
                    eligible.append(make_item(row, state, len(eligible) + 1, source, query))
            elif len(needs_review) < limit:
                needs_review.append(make_item(row, state, len(needs_review) + 1, source, query))
        if len(eligible) >= limit and len(needs_review) >= limit:
            break
    return eligible, needs_review


@router.post("/ml", response_model=MLRecommendationResponse)
def recommend_ml(
    request: MLRecommendationRequest,
    db: Session = Depends(get_db),
    user: AppUser | None = Depends(get_optional_current_user),
):
    query = request.query
    if request.company_id is not None:
        authorize_company_access(user, request.company_id)
        try:
            company = _load_company(db, request.company_id)
        except (LookupError, ValueError) as error:
            raise HTTPException(status_code=404, detail="Company not found") from error
        if query is None:
            query = company_query(company)
    if not query or not query.strip():
        raise HTTPException(status_code=422, detail="Either query or company_id with a populated profile is required")

    rows = candidates(db)
    ranked, model, dataset, source, fallback_reason = score_notices(query, rows)
    primary, needs_review = partition_ranked(db, request.company_id, ranked, request.limit, source, query)
    return MLRecommendationResponse(
        model_version=model, dataset_version=dataset,
        scoring_source=source, fallback_reason=fallback_reason,
        fallback_used=source == "lexical_fallback",
        input_sha256=hashlib.sha256(query.encode("utf-8")).hexdigest(),
        total_valid_candidates=len(rows), items=primary, needs_review_items=needs_review,
    )
