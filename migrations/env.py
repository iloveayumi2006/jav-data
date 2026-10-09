"""Run migrations against the configured database."""

from alembic import context

from jav_data.config import Settings
from jav_data.database import Base, make_engine
from jav_data.models import Movie  # noqa: F401 — register tables for autogeneration

settings = context.config.attributes.get("settings") or Settings.load()
settings.prepare()
target_metadata = Base.metadata

if context.is_offline_mode():
    from sqlalchemy import URL

    context.configure(
        url=URL.create("sqlite", database=str(settings.database_path)),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = make_engine(settings)
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()
