# migrations/env.py
from __future__ import annotations

from logging.config import fileConfig
from typing import Optional

from alembic import context
from sqlalchemy.engine import Connection

# Make sure this import path matches your app layout
from app.database import Base, engine  # ← your SQLAlchemy Base + Engine

# ---------- ALEMBIC CONFIG ----------

# Alembic Config object, provides access to values in alembic.ini
config = context.config  # type: ignore[attr-defined]

# If you want Alembic to use the same URL as your engine, set it here
if config is not None:
    config.set_main_option("sqlalchemy.url", str(engine.url))

# Interpret the config file for logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata from your models
target_metadata = Base.metadata


# ---------- OFFLINE MIGRATIONS ----------

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL and not an Engine.
    """
    url: Optional[str] = (
        config.get_main_option("sqlalchemy.url") if config is not None else None
    )
    if not url:
        url = str(engine.url)

    context.configure(  # type: ignore[attr-defined]
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():  # type: ignore[attr-defined]
        context.run_migrations()  # type: ignore[attr-defined]


# ---------- ONLINE MIGRATIONS ----------

def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    Uses your existing SQLAlchemy Engine.
    """
    connectable = engine

    with connectable.connect() as connection:  # type: ignore[call-arg]
        context.configure(  # type: ignore[attr-defined]
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():  # type: ignore[attr-defined]
            context.run_migrations()  # type: ignore[attr-defined]


# ---------- ENTRY POINT ----------

if context.is_offline_mode():  # type: ignore[attr-defined]
    run_migrations_offline()
else:
    run_migrations_online()
