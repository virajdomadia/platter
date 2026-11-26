"""Async Alembic environment. The target is ALEMBIC_URL and nothing else, so a bare
`alembic upgrade head` can never fall through to the app's DATABASE_URL (production)."""

import asyncio
import os

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.db import connect_args, normalise_url
from app.models import Base

config = context.config
target_metadata = Base.metadata


def database_url() -> str:
    url = os.environ.get("ALEMBIC_URL")
    if not url:
        raise SystemExit(
            "ALEMBIC_URL is not set. Name the target explicitly, e.g.\n"
            "  ALEMBIC_URL=postgresql+asyncpg://postgres@localhost:5434/platter_dev"
            " uv run alembic upgrade head"
        )
    return normalise_url(url)


def run_migrations_offline() -> None:
    context.configure(url=database_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:  # type: ignore[no-untyped-def]
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    url = database_url()
    engine = create_async_engine(url, connect_args=connect_args(url))
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
