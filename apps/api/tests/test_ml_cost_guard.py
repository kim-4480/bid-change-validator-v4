from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest
from app.ml_recommendations.cost_guard import require_isolated_data_url,require_bounded_limit

def test_remote_rds_disallowed_without_opt_in():
    with pytest.raises(ValueError,match="blocked"):
        require_isolated_data_url("postgresql://test@sample.rds.amazonaws.com:5432/db")
def test_remote_rds_may_only_be_explicitly_opted_in():
    assert require_isolated_data_url("postgresql://test@sample.rds.amazonaws.com:5432/db",allow_remote=True)
def test_local_db_allowed():
    assert require_isolated_data_url("postgresql://u:p@localhost:5432/db")
def test_limit_bounded():
    with pytest.raises(ValueError):
        require_bounded_limit(30000)
