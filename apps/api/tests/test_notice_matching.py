from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from apps.api.app.qualification.matching import match_cached_notices


def test_notice_matching_loads_runs_in_batch_without_per_notice_scalar_queries() -> None:
    company_id = uuid4()
    notice_id = uuid4()
    run_id = uuid4()
    notice = SimpleNamespace(
        id=notice_id,
        bid_notice_no="R26BK00000001",
        title="테스트 공고",
        announcing_institution_name="테스트 기관",
    )
    version = SimpleNamespace(version_number=1)
    run = SimpleNamespace(
        id=run_id,
        status="SUCCEEDED",
        created_at=datetime.now(timezone.utc),
    )
    analysis = SimpleNamespace(requirements=[], evidence=[])
    evaluation = SimpleNamespace(overall_status="eligible", judgments=[])

    db = MagicMock()
    db.execute.return_value.all.return_value = [(notice, version, run)]
    db.get.return_value = None

    with (
        patch("apps.api.app.qualification.matching._load_company", return_value=object()),
        patch("apps.api.app.qualification.matching._record_to_completeness", return_value=None),
        patch("apps.api.app.qualification.matching.build_company_profile_snapshot", return_value=object()),
        patch("apps.api.app.qualification.matching.analysis_run_response", return_value=analysis),
        patch("apps.api.app.qualification.matching.judge_requirements", return_value=evaluation),
    ):
        result = match_cached_notices(db, company_id=company_id, limit=12)

    assert result.analyzed_notice_count == 1
    assert result.returned_count == 1
    assert result.items[0].analysis_run_id == run_id
    db.execute.assert_called_once()
    db.scalar.assert_not_called()
