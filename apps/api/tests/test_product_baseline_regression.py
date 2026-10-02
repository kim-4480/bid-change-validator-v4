"""Service regressions share the existing deterministic Golden seed and cleanup."""

import pytest
from sqlalchemy import select

from apps.api.app.analysis_models import QualificationAnalysisRun, QualificationRequirementRecord
from apps.api.app.database import SessionLocal
from apps.api.app.judgment_models import QualificationJudgmentRun
from bidengine.judgment.rules import RULE_VERSION
from apps.api.tests.test_mvp_golden_e2e import _seed_golden_case, _cleanup, client, REFERENCE_DATE


pytestmark = pytest.mark.usefixtures("seed_required_master_codes")


@pytest.fixture
def scenario():
    seed = _seed_golden_case()
    try:
        yield seed
    finally:
        _cleanup(seed)


def judge(seed):
    response = client.post(f"/api/v1/preflight-cases/{seed['case_id']}/qualification-judgments", json={"analysis_run_id": str(seed['baseline_analysis_id']), "reference_date": REFERENCE_DATE})
    assert response.status_code == 200, response.text
    return response.json()


def answer(seed, source):
    return client.post(f"/api/v1/preflight-cases/{seed['case_id']}/qualification-answers", json={"source_judgment_run_id": source['id'], "requirement_key": "REQ-REGISTRATION", "satisfies_requirement": True, "apply_to_profile": False})


def test_partial_answer_keeps_abstention_and_rejects_stale_overwrite(scenario):
    with SessionLocal() as db:
        db.get(QualificationAnalysisRun, scenario['baseline_analysis_id']).status = 'PARTIAL'
        db.commit()
    original = judge(scenario)
    response = answer(scenario, original)
    assert response.status_code == 200, response.text
    result = response.json()['result']
    assert result['overall_status'] == 'insufficient_data'
    assert result['analysis_status'] == 'PARTIAL'
    assert next(j for j in result['judgments'] if j['requirement_key'] == 'REQ-REGISTRATION')['basis_type'] == 'USER_ANSWER'
    assert answer(scenario, original).status_code == 409
    company = client.get(f"/api/v1/companies/{scenario['company_id']}").json()
    assert company['certifications'] == []


def test_unsafe_clause_cannot_be_resolved_by_direct_answer_api(scenario):
    with SessionLocal() as db:
        row = db.scalar(select(QualificationRequirementRecord).where(QualificationRequirementRecord.analysis_run_id == scenario['baseline_analysis_id'], QualificationRequirementRecord.requirement_key == 'REQ-REGISTRATION'))
        row.raw = '공동수급체 구성원 모두 정보통신공사업 등록업체이어야 한다.'
        db.commit()
    source = judge(scenario)
    response = answer(scenario, source)
    assert response.status_code == 422, response.text
    assert response.json()['error']['code'] == 'REQUIREMENT_NOT_ASKABLE'


@pytest.mark.parametrize('override,code', [
    ({'reference_date': '2026-09-09'}, 'REFERENCE_DATE_CHANGED_FULL_REJUDGMENT_REQUIRED'),
    ({'baseline_analysis_run_id': '00000000-0000-0000-0000-000000000000'}, 'SOURCE_ANALYSIS_MISMATCH'),
])
def test_revalidation_refuses_incompatible_source(scenario, override, code):
    source = judge(scenario)
    payload = {'source_judgment_run_id': source['id'], 'current_analysis_run_id': str(scenario['current_analysis_id']), **override}
    response = client.post(f"/api/v1/preflight-cases/{scenario['case_id']}/qualification-revalidation", json=payload)
    assert response.status_code in (409, 422), response.text
    assert response.json()['error']['code'] == code


def test_revalidation_refuses_source_from_previous_rule_version(scenario):
    source = judge(scenario)
    assert source['rule_version'] == RULE_VERSION == 'qualification-rules-v0.3'

    with SessionLocal() as db:
        run = db.get(QualificationJudgmentRun, source['id'])
        run.rule_version = 'qualification-rules-v0.2'
        db.commit()

    response = client.post(
        f"/api/v1/preflight-cases/{scenario['case_id']}/qualification-revalidation",
        json={
            'source_judgment_run_id': source['id'],
            'current_analysis_run_id': str(scenario['current_analysis_id']),
            'reference_date': REFERENCE_DATE,
        },
    )
    assert response.status_code == 409, response.text
    assert response.json()['error']['code'] == 'RULE_CHANGED_FULL_REJUDGMENT_REQUIRED'


@pytest.mark.parametrize("operation", ["qualification-judgments", "qualification-revalidation"])
def test_missing_analysis_returns_api_error(scenario, operation):
    from uuid import uuid4
    if operation == "qualification-judgments":
        payload = {"analysis_run_id": str(uuid4())}
    else:
        payload = {"source_judgment_run_id": judge(scenario)["id"], "current_analysis_run_id": str(uuid4())}
    response = client.post(f"/api/v1/preflight-cases/{scenario['case_id']}/{operation}", json=payload)
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "ANALYSIS_RUN_NOT_FOUND"
