from sqlalchemy.pool import NullPool

from apps.api.app.config import Settings
from apps.api.app.database import database_engine_options


def test_session_pooler_uses_small_bounded_application_pool() -> None:
    settings = Settings(
        _env_file=None,
        database_url=(
            "postgresql://postgres.project:password@"
            "aws-0-ap-northeast-2.pooler.supabase.com:5432/postgres"
        ),
        database_pool_size=2,
        database_max_overflow=0,
    )

    options = database_engine_options(settings)

    assert options["pool_size"] == 2
    assert options["max_overflow"] == 0
    assert options["pool_pre_ping"] is True
    assert "poolclass" not in options


def test_transaction_pooler_disables_client_pool_and_prepared_statements() -> None:
    settings = Settings(
        _env_file=None,
        database_url=(
            "postgresql://postgres.project:password@"
            "aws-0-ap-northeast-2.pooler.supabase.com:6543/postgres"
        ),
    )

    options = database_engine_options(settings)

    assert options["poolclass"] is NullPool
    assert options["connect_args"] == {"prepare_threshold": None}
    assert "pool_size" not in options


def test_migration_url_can_stay_on_session_pooler() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql://runtime:password@pooler.example:6543/postgres",
        migration_database_url="postgresql://migration:password@pooler.example:5432/postgres",
    )

    assert settings.sqlalchemy_database_url.endswith(":6543/postgres")
    assert settings.sqlalchemy_migration_database_url.endswith(":5432/postgres")
