from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import get_settings
from app.models import Base


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ConfigParser (used internally by Alembic Config) treats '%' as the start of
# interpolation syntax (e.g. '%(foo)s'). A DB password containing a literal '%'
# (common with percent-encoded characters like %2F for '/') breaks set_main_option
# unless we escape it as '%%' first; ConfigParser un-escapes it back on read.
db_url = get_settings().sqlalchemy_migration_database_url
config.set_main_option("sqlalchemy.url", db_url.replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
