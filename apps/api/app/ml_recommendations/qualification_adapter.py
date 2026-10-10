"""Non-persisting, bounded deterministic qualification judgment for ML results.

Only a current successful and coverage-complete analysis may yield core_met.
No run, partial, failed, stale or uncertain coverage is ever core_met.
"""
from __future__ import annotations
from datetime import date
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from bidengine.judgment.rules import judge_requirements
from ..models import Company
from ..analysis_models import QualificationAnalysisRun
from ..judgment_models import CompanyQualificationProfileCompleteness
from ..qualification.judgment import _load_company,_record_to_completeness,build_company_profile_snapshot,grounded_keys_for_analysis
from ..qualification.analysis import analysis_run_response

def company_query(company):
    bits=[company.name,company.region_name,company.region_code,company.company_size]
    bits.extend(x.industry.name or x.industry_code for x in company.industries)
    bits.extend(x.name for x in company.certifications)
    bits.extend(x.name for x in company.performances)
    bits.extend(x.role_name for x in company.staff_roles)
    return " ".join(str(x) for x in bits if x)

def evaluate(db,company_id,items,reference_date=None):
    """Return notice_id -> deterministic state; this never writes a JudgmentRun."""
    if not items:return {}
    company=_load_company(db,company_id)
    completeness=_record_to_completeness(db.get(CompanyQualificationProfileCompleteness,company_id))
    snapshot=build_company_profile_snapshot(company,completeness)
    ids=[UUID(item["analysis_run_id"]) for item in items if item.get("analysis_run_id") and not item.get("is_stale")]
    runs={}
    if ids:
        fetched=db.scalars(select(QualificationAnalysisRun)
            .where(QualificationAnalysisRun.id.in_(ids))
            .options(selectinload(QualificationAnalysisRun.notice_version),
                     selectinload(QualificationAnalysisRun.requirements),
                     selectinload(QualificationAnalysisRun.evidence))).all()
        runs={str(run.id):run for run in fetched}
    result={}
    for item in items:
        key=item["notice_id"]
        if item.get("is_stale"):
            result[key]={"state":"stale","rule_version":None,"reason":"Old analysis version"}
            continue
        run=runs.get(item.get("analysis_run_id"))
        if not run or run.status!="SUCCEEDED":
            result[key]={"state":"UNKNOWN","rule_version":None,"reason":"No successful current-version analysis"}
            continue
        try:
            analysis=analysis_run_response(run)
            if analysis.verdict_complete is not True or not analysis.requirements:
                result[key]={"state":"UNKNOWN","rule_version":None,"reason":"Unverified requirement coverage"}
                continue
            evaluation=judge_requirements(analysis.requirements,snapshot,
                preflight_case_id="ML:"+str(company_id)+":"+str(key),
                reference_date=reference_date or date.today(),analysis_status=run.status,
                coverage_complete=analysis.verdict_complete,
                grounded_requirement_keys=grounded_keys_for_analysis(run, analysis))
            state=evaluation.overall_status
            if state not in ("core_met", "core_unmet", "needs_review"):
                state="UNKNOWN"
            result[key]={"state":state,
                         "rule_version":getattr(evaluation,"rule_version",None),
                         "reason":"Current analysis; deterministic requirement judgment"}
        except (ValueError,TypeError,AttributeError,KeyError):
            result[key]={"state":"UNKNOWN","rule_version":None,"reason":"Judgment unavailable"}
    return result
