"""DB-backed fault injection: use only the verified isolated test runner."""
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from apps.api.app.database import SessionLocal, get_db
from apps.api.app.main import app
from apps.api.app.copilot.actions import propose_answer
from apps.api.app.copilot.contracts import ActionInput
from apps.api.app.judgment_models import QualificationJudgmentRun
from apps.api.app.ask_back_models import QualificationAnswer
from apps.api.tests.test_copilot_product_tools import state


def test_confirm_failure_after_flush_rolls_back_entire_request(state, monkeypatch):
    db, case, _, _ = state
    proposal = propose_answer(db, case.id, 'REQ-REGISTRATION',
                              ActionInput(satisfies_requirement=True, evidence_held=True))
    db.rollback()
    def counts(session):
        return tuple(session.scalar(select(func.count()).select_from(model).where(
            model.preflight_case_id == case.id)) for model in (QualificationJudgmentRun, QualificationAnswer))
    with SessionLocal() as observer:
        before = counts(observer)
    injected = []
    def failing_request_session():
        with SessionLocal() as request_db:
            def fail_commit():
                request_db.flush()
                inside = counts(request_db)
                assert inside == (before[0] + 1, before[1] + 1)
                injected.append(True)
                raise RuntimeError('intentional failure after SQL writes, before commit')
            monkeypatch.setattr(request_db, 'commit', fail_commit)
            yield request_db
        # Session.close rolls back the transaction, matching production get_db.
    app.dependency_overrides[get_db] = failing_request_session
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post('/api/v1/copilot/actions/confirm',
                                   json={'confirmed': True, 'action': proposal.model_dump(mode='json')})
        assert response.status_code == 500
        assert injected == [True]
    finally:
        app.dependency_overrides.pop(get_db, None)
    with SessionLocal() as observer:
        assert counts(observer) == before
