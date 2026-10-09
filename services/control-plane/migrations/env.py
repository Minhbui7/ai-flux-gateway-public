from alembic import context

from aiflux.config import get_settings
from aiflux.db import engine_for
from aiflux.models import Base

settings = get_settings()
if not settings.database_url:
    raise RuntimeError("AIFLUX_DATABASE_URL is required for migrations")

if context.is_offline_mode():
    context.configure(
        url=settings.database_url, target_metadata=Base.metadata, literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    with engine_for(settings.database_url).connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
