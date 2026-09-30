from collections.abc import Generator
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from .config import Settings, get_settings


def database_engine_options(settings: Settings) -> dict[str, Any]:
    """Return a bounded pool, or Supavisor transaction-mode-safe options."""

    url = make_url(settings.sqlalchemy_database_url)
    transaction_mode = settings.database_pool_mode == "transaction" or (
        settings.database_pool_mode == "auto" and url.port == 6543
    )
    if transaction_mode:
        return {
            "pool_pre_ping": True,
            "poolclass": NullPool,
            "connect_args": {"prepare_threshold": None},
        }
    return {
        "pool_pre_ping": True,
        "pool_size": settings.database_pool_size,
        "max_overflow": settings.database_max_overflow,
        "pool_timeout": settings.database_pool_timeout_seconds,
        "pool_recycle": settings.database_pool_recycle_seconds,
    }


settings = get_settings()
engine = create_engine(
    settings.sqlalchemy_database_url,
    **database_engine_options(settings),
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
