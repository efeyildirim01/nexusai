import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Migrations run as the owner role, never as the runtime app role.
url = config.get_main_option("sqlalchemy.url") or os.environ.get("NEXUS_MIGRATIONS_DATABASE_URL")
if not url:
    raise RuntimeError("Set NEXUS_MIGRATIONS_DATABASE_URL to the owner role's connection URL")


def run_migrations_online() -> None:
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run_migrations_online()
