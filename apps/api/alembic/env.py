from alembic import context
from sqlalchemy import engine_from_config, pool

from mc_shared.db import Base
from mc_shared import models  # noqa: F401
from mc_shared.settings import get_settings

config = context.config
config.set_main_option("sqlalchemy.url", get_settings().sync_database_url)
target_metadata = Base.metadata


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
