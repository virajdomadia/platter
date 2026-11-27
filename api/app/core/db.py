"""Async engine + the per-request session dependency.

The engine is created lazily, so the app imports and serves `/health` with no DATABASE_URL.
Neon's pooled URL (PgBouncer, transaction mode) cannot keep prepared statements across
transactions, so asyncpg's statement caches are off whenever the host says `-pooler`.
"""

from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from sqlalchemy import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings

_engines: dict[str, AsyncEngine] = {}

SessionFactory = async_sessionmaker[AsyncSession]


class DatabaseNotConfigured(RuntimeError):
    pass


def normalise_url(url: str) -> str:
    """Accept the `postgresql://…?sslmode=require&channel_binding=require` string Neon hands out."""
    u = make_url(url)
    if u.drivername in ("postgres", "postgresql"):
        u = u.set(drivername="postgresql+asyncpg")
    query = dict(u.query)
    if query.pop("sslmode", None) in ("require", "verify-full", "verify-ca"):
        query["ssl"] = "require"
    query.pop("channel_binding", None)
    return u.set(query=query).render_as_string(hide_password=False)


def connect_args(url: str) -> dict[str, Any]:
    if "-pooler" not in (make_url(url).host or ""):
        return {}
    return {
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
        "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__",
    }


def make_engine(url: str, **kw: Any) -> AsyncEngine:
    url = normalise_url(url)
    return create_async_engine(url, pool_pre_ping=True, connect_args=connect_args(url), **kw)


def get_engine(settings: Settings) -> AsyncEngine:
    url = settings.database_url.get_secret_value().strip() if settings.database_url else ""
    if not url:
        raise DatabaseNotConfigured("DATABASE_URL is not set")
    if url not in _engines:
        _engines[url] = make_engine(url, pool_size=5, max_overflow=10)
    return _engines[url]


def session_factory(app: FastAPI) -> SessionFactory:
    """Streams open a short session per tick, so they need the factory, not one session.
    Tests put their own factory on `app.state.session_factory`."""
    factory = getattr(app.state, "session_factory", None)
    if factory is None:
        factory = async_sessionmaker(get_engine(app.state.settings), expire_on_commit=False)
        app.state.session_factory = factory
    return factory


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with session_factory(request.app)() as session:
        yield session


async def dispose_engines() -> None:
    for engine in list(_engines.values()):
        await engine.dispose()
    _engines.clear()
