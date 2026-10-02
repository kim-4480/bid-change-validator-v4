import pytest

from apps.api.app.database import SessionLocal
from apps.api.app.scripts.product_data_inventory import collect_product_data_inventory


pytestmark = pytest.mark.usefixtures("seed_required_master_codes")


def test_product_data_inventory_shape() -> None:
    db = SessionLocal()
    try:
        inventory = collect_product_data_inventory(db)
    finally:
        db.close()

    assert set(inventory) == {
        "notices",
        "documents",
        "collection_runs",
        "companies",
        "preflight",
        "qualification",
    }

    assert inventory["notices"]["count"] >= 0
    assert inventory["notices"]["versions"] >= 0
    assert inventory["notices"]["with_multiple_versions"] >= 0
    assert inventory["documents"]["count"] >= 0
    assert inventory["collection_runs"]["count"] >= 0
    assert inventory["companies"]["count"] >= 0
    assert inventory["preflight"]["cases"] >= 0
    assert inventory["preflight"]["proposal_documents"] >= 0
    assert inventory["qualification"]["analysis_runs"] >= 0
    assert inventory["qualification"]["requirements"] >= 0
    assert inventory["qualification"]["evidence"] >= 0
    assert inventory["qualification"]["judgment_runs"] >= 0
    assert inventory["qualification"]["judgments"] >= 0
    assert inventory["qualification"]["answers"] >= 0
    assert inventory["qualification"]["revalidation_runs"] >= 0
