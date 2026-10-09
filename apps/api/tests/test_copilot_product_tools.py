"""Read-only adapters against real persisted state, using the existing Golden seed."""

from copy import deepcopy
from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event, select

from apps.api.app.analysis_models import (
    QualificationAnalysisRun, QualificationEvidenceRecord, QualificationRequirementRecord,
)
from apps.api.app.copilot import product_tools as tools
from apps.api.app.database import SessionLocal
from apps.api.app.judgment_models import QualificationJudgmentRun
from apps.api.app.models import Company, PreflightCase
from apps.api.app.qualification.ask_back import list_questions
from apps.api.app.qualification.judgment import QualificationJudgmentError, run_qualification_judgment
from bidengine.judgment.rules import RULE_VERSION
from apps.api.tests.test_mvp_golden_e2e import _cleanup, _ground_analysis_documents, _seed_golden_case


@pytest.fixture
def state(seed_required_master_codes):
    seed = _seed_golden_case()
    try:
        with SessionLocal() as db:
            _ground_analysis_documents(db, seed)
            case = db.get(PreflightCase, seed['case_id'])
            analysis = db.get(QualificationAnalysisRun, seed['current_analysis_id'])
            document = analysis.notice_version.documents[0]
            document.extracted_blocks = [
                {**block, "page": 2} if "정보통신공사업" in block["text"] else block
                for block in document.extracted_blocks
            ]
            requirement = db.scalar(select(QualificationRequirementRecord).where(
                QualificationRequirementRecord.analysis_run_id == analysis.id,
                QualificationRequirementRecord.requirement_key == 'REQ-REGISTRATION',
            ))
            requirement.evidence_keys = ['E2', 'E1']
            for key in ['E1', 'E2', 'UNRELATED']:
                db.add(QualificationEvidenceRecord(
                    analysis_run_id=analysis.id, evidence_key=key, source_type='NOTICE_DOCUMENT',
                    document_id=str(document.id), notice_version_id=str(case.current_version_id),
                    chunk_id=f'CHUNK-{key}', location={'page': 2, 'clause_label': '3', 'display': 'p.2'},
                    quote=requirement.raw,
                    source_sha256=document.file_sha256, extracted_text_sha256=document.extracted_text_sha256,
                ))
            # Same key in another analysis must never be used as a fallback.
            db.add(QualificationEvidenceRecord(
                analysis_run_id=seed['baseline_analysis_id'], evidence_key='E1',
                source_type='NOTICE_DOCUMENT', document_id=str(uuid4()),
                notice_version_id=str(case.baseline_version_id), location={}, quote='OLD VERSION',
            ))
            db.commit()
            run = run_qualification_judgment(db, case_id=case.id, reference_date=date(2026, 9, 8))
            yield db, case, analysis, run
            db.rollback()
    finally:
        _cleanup(seed)


def test_current_summary_and_exact_snapshot(state):
    db, case, analysis, run = state
    result = tools.get_qualification_summary(db, case.id)
    assert result.provenance.model_dump() == dict(
        case_id=case.id, notice_id=case.notice_id, notice_version_id=case.current_version_id,
        version_number=2, company_id=case.company_id, analysis_run_id=analysis.id,
        judgment_run_id=run.id, analysis_status='SUCCEEDED', rule_version=run.rule_version,
    )
    assert result.overall_status == run.overall_status
    assert result.analysis_status == 'SUCCEEDED'
    assert sum(result.judgment_counts.values()) == len(run.judgments) == 4
    reqs = {r.requirement_key: r for r in analysis.requirements}
    persisted = {r.requirement_key: r for r in run.judgments}
    for item in result.judgments:
        assert item.raw == reqs[item.requirement_key].raw
        assert item.type == reqs[item.requirement_key].type
        for field in ['status', 'basis_type', 'reason_code', 'requires_evidence', 'requirement_evidence_keys']:
            assert getattr(item, field) == getattr(persisted[item.requirement_key], field)
    snapshot = deepcopy(run.profile_snapshot)
    db.get(Company, case.company_id).region_name = '변경된 현재 회사 정보'
    run.profile_snapshot = {**snapshot, 'historical_extra': {'kept': True}}
    profile = tools.get_judgment_profile_snapshot(db, case.id)
    assert profile.profile_snapshot == run.profile_snapshot
    assert profile.profile_completeness.model_dump() == snapshot['completeness']
    profile.profile_snapshot['historical_extra']['kept'] = False
    assert run.profile_snapshot['historical_extra']['kept'] is True


def test_newer_baseline_judgment_is_never_current(state):
    db, case, analysis, run = state
    baseline = QualificationJudgmentRun(
        preflight_case_id=case.id, notice_version_id=case.baseline_version_id,
        analysis_run_id=db.scalar(select(QualificationAnalysisRun.id).where(
            QualificationAnalysisRun.notice_version_id == case.baseline_version_id)),
        company_id=case.company_id, overall_status='eligible', rule_version=run.rule_version,
        reference_date=run.reference_date, profile_snapshot=run.profile_snapshot,
        analysis_status='SUCCEEDED', created_at=run.created_at + timedelta(days=1),
    )
    db.add(baseline)
    db.flush()
    assert tools.get_qualification_summary(db, case.id).provenance.judgment_run_id == run.id
    run.notice_version_id = case.baseline_version_id
    db.flush()
    with pytest.raises(QualificationJudgmentError) as error:
        tools.get_qualification_summary(db, case.id)
    assert error.value.code == 'CURRENT_JUDGMENT_REQUIRED'


def test_later_judgment_for_older_current_analysis_does_not_hide_latest_analysis_judgment(state):
    db, case, analysis, run = state
    older_analysis = QualificationAnalysisRun(
        notice_version_id=case.current_version_id,
        contract_version=analysis.contract_version,
        analysis_kind=analysis.analysis_kind,
        status='SUCCEEDED',
        input_fingerprint=analysis.input_fingerprint,
        created_at=analysis.created_at - timedelta(days=1),
    )
    db.add(older_analysis)
    db.flush()
    later_old_judgment = QualificationJudgmentRun(
        preflight_case_id=case.id,
        notice_version_id=case.current_version_id,
        analysis_run_id=older_analysis.id,
        company_id=case.company_id,
        overall_status='eligible',
        rule_version=run.rule_version,
        reference_date=run.reference_date,
        profile_snapshot=deepcopy(run.profile_snapshot),
        analysis_status='SUCCEEDED',
        created_at=run.created_at + timedelta(days=1),
    )
    db.add(later_old_judgment)
    db.flush()

    result = tools.get_qualification_summary(db, case.id)
    assert result.provenance.analysis_run_id == analysis.id
    assert result.provenance.judgment_run_id == run.id
    assert result.overall_status == run.overall_status


def test_previous_rule_only_is_not_returned(state):
    db, case, _, run = state
    run.rule_version = 'qualification-rules-v0.2'
    db.flush()
    with pytest.raises(QualificationJudgmentError) as error:
        tools.get_qualification_summary(db, case.id)
    assert error.value.code == 'CURRENT_JUDGMENT_REQUIRED'


def test_newer_previous_rule_is_skipped_for_current_rule(state):
    db, case, analysis, run = state
    assert run.rule_version == RULE_VERSION
    stale = QualificationJudgmentRun(
        preflight_case_id=case.id,
        analysis_run_id=analysis.id,
        company_id=case.company_id,
        notice_version_id=case.current_version_id,
        overall_status='ineligible',
        rule_version='qualification-rules-v0.2',
        reference_date=run.reference_date,
        profile_snapshot=deepcopy(run.profile_snapshot),
        analysis_status=run.analysis_status,
        created_at=run.created_at + timedelta(days=1),
    )
    db.add(stale)
    db.flush()
    result = tools.get_qualification_summary(db, case.id)
    assert result.provenance.judgment_run_id == run.id
    assert result.provenance.rule_version == RULE_VERSION


@pytest.mark.parametrize('operation', [
    tools.get_qualification_summary, tools.get_required_checks, tools.get_judgment_profile_snapshot,
    lambda db, case_id: tools.get_requirement_evidence(db, case_id, 'REQ-REGISTRATION'),
])
def test_stale_analysis_blocks_every_tool(state, operation):
    db, case, analysis, _ = state
    db.add(QualificationAnalysisRun(
        notice_version_id=case.current_version_id, contract_version=analysis.contract_version,
        analysis_kind=analysis.analysis_kind, status='SUCCEEDED',
        input_fingerprint=analysis.input_fingerprint,
        created_at=analysis.created_at + timedelta(days=1),
    ))
    db.flush()
    with pytest.raises(QualificationJudgmentError) as error:
        operation(db, case.id)
    assert error.value.code == 'STALE_JUDGMENT'


@pytest.mark.parametrize('status', ['PARTIAL', 'FAILED'])
def test_analysis_status_is_not_promoted(state, status):
    db, case, analysis, run = state
    analysis.status = run.analysis_status = status
    if status == 'FAILED':
        with pytest.raises(QualificationJudgmentError) as error:
            tools.get_qualification_summary(db, case.id)
        assert error.value.code == 'QUALIFICATION_ANALYSIS_FAILED'
    else:
        result = tools.get_qualification_summary(db, case.id)
        assert result.analysis_status == result.provenance.analysis_status == 'PARTIAL'
        assert result.overall_status == run.overall_status


def test_canonical_evidence_order_and_metadata(state):
    db, case, analysis, _ = state
    result = tools.get_requirement_evidence(db, case.id, 'REQ-REGISTRATION')
    assert [item.evidence_key for item in result.evidence] == ['E2', 'E1']
    expected = {e.evidence_key: e for e in analysis.evidence}
    for item in result.evidence:
        original = expected[item.evidence_key]
        assert item.quote == original.quote
        assert item.chunk_id == original.chunk_id
        assert item.document_id == original.document_id
        assert item.notice_version_id == str(case.current_version_id)
        assert item.location.display == original.location['display']
        assert item.location.page == 2 and item.location.clause_label == '3'
        document = analysis.notice_version.documents[0]
        assert item.source_sha256 == document.file_sha256
        assert item.extracted_text_sha256 == document.extracted_text_sha256


def test_cross_version_evidence_fails_closed(state):
    db, case, analysis, _ = state
    analysis.evidence[0].notice_version_id = str(case.baseline_version_id)
    with pytest.raises(QualificationJudgmentError) as error:
        tools.get_requirement_evidence(db, case.id, 'REQ-REGISTRATION')
    assert error.value.code == 'EVIDENCE_VERSION_MISMATCH'


def test_required_checks_reuses_askability_and_keeps_nonaskable(state):
    db, case, analysis, run = state
    reqs = {r.requirement_key: r for r in analysis.requirements}
    reqs['REQ-STAFF'].raw = '공동수급체 구성원 모두 인력을 보유하여야 한다.'
    for record in run.judgments:
        record.status = {
            'REQ-REGION': 'SATISFIED', 'REQ-PERFORMANCE-AMOUNT': 'UNSATISFIED',
            'REQ-STAFF': 'UNKNOWN', 'REQ-REGISTRATION': 'UNKNOWN',
        }[record.requirement_key]
        # Migration 017 makes the UNKNOWN reason mandatory only for UNKNOWN.
        # Keep this synthetic state internally valid; do not relax the DB check.
        record.unknown_reason = 'profile_missing' if record.status == 'UNKNOWN' else None
        record.reason_code = {
            'SATISFIED': 'RULE_MATCH', 'UNSATISFIED': 'RULE_MISMATCH',
            'UNKNOWN': 'INSUFFICIENT_DATA',
        }[record.status]
    db.flush()
    expected = list_questions(db, case_id=case.id, source_judgment_run_id=run.id)
    result = tools.get_required_checks(db, case.id)
    assert result.questions == expected
    assert {q.requirement_key for q in result.questions} == {'REQ-STAFF', 'REQ-REGISTRATION'}
    assert {q.askable for q in result.questions} == {True, False}
    assert result.user_answer_requires_askable is True


@pytest.mark.parametrize('corruption,code', [
    ('analysis_version', 'ANALYSIS_VERSION_MISMATCH'),
    ('company', 'JUDGMENT_CASE_MISMATCH'),
    ('status', 'ANALYSIS_STATUS_MISMATCH'),
    ('missing_judgment', 'REQUIREMENT_JUDGMENT_MISMATCH'),
    ('missing_evidence', 'EVIDENCE_NOT_FOUND'),
])
def test_corrupt_context_is_not_silently_returned(state, corruption, code):
    db, case, analysis, run = state
    if corruption == 'analysis_version':
        analysis.notice_version_id = case.baseline_version_id
    elif corruption == 'company':
        case.company_id = uuid4()
    elif corruption == 'status':
        run.analysis_status = 'PARTIAL'
    elif corruption == 'missing_judgment':
        run.judgments.pop()
    else:
        analysis.requirements[0].evidence_keys = ['MISSING']
    with pytest.raises(QualificationJudgmentError) as error:
        tools.get_qualification_summary(db, case.id)
    assert error.value.code == code


def test_missing_case_and_requirement(state):
    db, case, _, _ = state
    for case_id, key, code in [
        (uuid4(), 'REQ-REGISTRATION', 'PREFLIGHT_CASE_NOT_FOUND'),
        (case.id, 'MISSING', 'REQUIREMENT_NOT_FOUND'),
    ]:
        with pytest.raises(QualificationJudgmentError) as error:
            tools.get_requirement_evidence(db, case_id, key)
        assert error.value.code == code


def test_loaded_judgment_version_is_rechecked(state, monkeypatch):
    db, case, _, run = state
    load = tools.load_qualification_judgment_run
    def wrong_version(db, run_id):
        loaded = load(db, run_id)
        loaded.notice_version_id = case.baseline_version_id
        return loaded
    monkeypatch.setattr(tools, 'load_qualification_judgment_run', wrong_version)
    with pytest.raises(QualificationJudgmentError) as error:
        tools.get_qualification_summary(db, case.id)
    assert error.value.code == 'JUDGMENT_VERSION_MISMATCH'


def test_all_tools_are_select_only_even_with_pending_changes(state, monkeypatch):
    db, case, _, _ = state
    company = db.get(Company, case.company_id)
    db.autoflush = True
    company.region_name = '호출자가 아직 저장하지 않은 값'
    before = (set(db.new), set(db.dirty), set(db.deleted))
    def reject_write(*args, **kwargs):
        pytest.fail('adapter attempted transaction mutation')
    monkeypatch.setattr(db, 'commit', reject_write)
    monkeypatch.setattr(db, 'flush', reject_write)
    statements = []
    def check_sql(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)
        assert statement.lstrip().upper().startswith('SELECT'), statement
    connection = db.connection()
    event.listen(connection, 'before_cursor_execute', check_sql)
    try:
        tools.get_qualification_summary(db, case.id)
        tools.get_requirement_evidence(db, case.id, 'REQ-REGISTRATION')
        tools.get_required_checks(db, case.id)
        tools.get_judgment_profile_snapshot(db, case.id)
        assert statements
        assert (set(db.new), set(db.dirty), set(db.deleted)) == before
    finally:
        event.remove(connection, 'before_cursor_execute', check_sql)


def test_explanation_batch_preserves_scope_order_and_metadata(state):
    db, case, _, _ = state
    keys = [item.requirement_key for item in tools.get_qualification_summary(db, case.id).judgments]
    bundles = tools.get_explanation_evidence(db, case.id, keys)
    assert [item.requirement.requirement_key for item in bundles] == keys
    assert tools.matching_provenance(*bundles)
    for item in bundles:
        assert item == tools.get_requirement_evidence(db, case.id, item.requirement.requirement_key)
        assert all(e.notice_version_id == str(case.current_version_id) for e in item.evidence)


def test_matching_provenance_rejects_different_reads_without_db():
    from types import SimpleNamespace
    from apps.api.app.copilot.contracts import ProductProvenance
    provenance = ProductProvenance(
        case_id=uuid4(), notice_id=uuid4(), notice_version_id=uuid4(), version_number=1,
        company_id=uuid4(), analysis_run_id=uuid4(), judgment_run_id=uuid4(),
        analysis_status='PARTIAL', rule_version='rule-1',
    )
    first = SimpleNamespace(provenance=provenance)
    assert tools.matching_provenance(first, SimpleNamespace(provenance=provenance.model_copy()))
    for field, value in [('judgment_run_id', uuid4()), ('analysis_run_id', uuid4()),
                         ('notice_version_id', uuid4()), ('rule_version', 'rule-2'), ('analysis_status', 'SUCCEEDED')]:
        assert not tools.matching_provenance(first, SimpleNamespace(provenance=provenance.model_copy(update={field: value})))
    assert not tools.matching_provenance()
