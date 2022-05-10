import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(BASE_DIR, "src"))

from core import settings  # noqa
from core.database import ModelBase  # noqa
from modules.podcast import models  # noqa
from modules.auth import models  # noqa
from modules.media import models  # noqa

config = context.config
DB_DSN = "postgresql://{username}:{password}@{host}:{port}/{database}".format(**settings.DATABASE)
config.set_main_option("sqlalchemy.url", DB_DSN)
fileConfig(config.config_file_name)
target_metadata = ModelBase.metadata


def run_migrations_offline():
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    engine = engine_from_config(config.get_section(config.config_ini_section), prefix="sqlalchemy.")

    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
