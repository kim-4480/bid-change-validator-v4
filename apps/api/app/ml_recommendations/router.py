"""Opt-in FastAPI router, register once in the shared app via integration owner.

Read-only inference. Nothing is persisted; no training on AWS EC2.
"""
from __future__ import annotations
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter,Depends
from pydantic import BaseModel,Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import authorize_company_access,get_optional_current_user
from ..auth_models import AppUser
from ..database import get_db
from ..analysis_models import QualificationAnalysisRun
from ..models import BidNotice,BidNoticeVersion,Company
from .runtime import score_notices

router=APIRouter(prefix="/api/v1/recommendations",tags=["ml recommendations"])

class MLRecommendationRequest(BaseModel):
    query: str=Field(min_length=2,max_length=500)
    company_id: UUID | None=None
    limit: int=Field(default=20,ge=1,le=50)

class MLNoticeRecommendation(BaseModel):
    notice_id: UUID
    title: str
    rank: int
    relevance_score: float=Field(description="Ranking score, never eligibility or win probability")
    reason: str
    version_number: int
    analysis_run_id: UUID | None=None
    analysis_version: str | None=None
    analysis_status: str="UNKNOWN"
    qualification_state: Literal["UNKNOWN","stale"]="UNKNOWN"
    is_stale: bool=False

class MLRecommendationResponse(BaseModel):
    model_version: str | None
    dataset_version: str | None
    scoring_source: Literal["local_lightgbm","remote_inference","rule_fallback"]
    fallback_reason: str | None
    note: str="Relevance ranking is not a legal eligibility or award probability assessment."
    items: list[MLNoticeRecommendation]

def candidates(db:Session,limit=150):
    # Bounded result-set, no full notice corpus download.
    rows=db.execute(select(BidNotice,BidNoticeVersion)
        .join(BidNoticeVersion,BidNoticeVersion.notice_id==BidNotice.id)
        .where(BidNoticeVersion.is_current.is_(True))
        .order_by(BidNotice.last_seen_at.desc()).limit(limit)).all()
    versions=[v.id for _,v in rows]
    existing={}
    previous=set()
    if versions:
        runs=db.scalars(select(QualificationAnalysisRun)
             .where(QualificationAnalysisRun.notice_version_id.in_(versions))
             .order_by(QualificationAnalysisRun.created_at.desc())).all()
        for run in runs:
            existing.setdefault(run.notice_version_id,run)
        # Stale if an analysis is available only on an obsolete notice version.
        ids=[n.id for n,_ in rows]
        previous=set(db.scalars(select(BidNoticeVersion.notice_id)
            .join(QualificationAnalysisRun,QualificationAnalysisRun.notice_version_id==BidNoticeVersion.id)
            .where(BidNoticeVersion.notice_id.in_(ids),BidNoticeVersion.is_current.is_(False))).all())
    payload=[]
    for n,v in rows:
        run=existing.get(v.id)
        stale=run is None and n.id in previous
        payload.append(dict(notice_id=str(n.id),title=n.title,version_number=v.version_number,
            analysis_run_id=str(run.id) if run else None,
            analysis_version=run.contract_version if run else None,
            analysis_status=run.status if run else "UNKNOWN",
            is_stale=stale))
    return payload

@router.post("/ml",response_model=MLRecommendationResponse)
def recommend_ml(
    request:MLRecommendationRequest,
    db:Session=Depends(get_db),
    user:AppUser | None=Depends(get_optional_current_user),
):
    if request.company_id is not None:
        authorize_company_access(user,request.company_id)
        if db.get(Company,request.company_id) is None:
            from fastapi import HTTPException
            raise HTTPException(status_code=404,detail="Company not found")
    rows=candidates(db)
    ranked,model,dataset,source,reason=score_notices(request.query,rows)
    items=[]
    for idx,row in enumerate(ranked[:request.limit],1):
        items.append(MLNoticeRecommendation(
            notice_id=row["notice_id"],title=row["title"],rank=idx,
            relevance_score=row["score"],
            reason="Textual relevance; eligibility unverified" if source!="rule_fallback" else "Rule-based lexical fallback; eligibility unverified",
            version_number=row["version_number"],
            analysis_run_id=row["analysis_run_id"],analysis_version=row["analysis_version"],
            analysis_status=row["analysis_status"],
            qualification_state="stale" if row["is_stale"] else "UNKNOWN",
            is_stale=row["is_stale"]))
    return MLRecommendationResponse(model_version=model,dataset_version=dataset,
        scoring_source=source,fallback_reason=reason,items=items)
