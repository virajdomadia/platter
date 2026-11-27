"""Fixtures: a migrated PostGIS test database, the seeded neighbourhood (no history), a frozen
clock, no network (OSRM answers nothing → straight-line legs, unless a test scripts it), and an
in-process client with cookie sessions.

Tests marked `db` need TEST_DATABASE_URL (a Postgres with PostGIS). Without it they are skipped —
unless REQUIRE_DB_TESTS=1 (CI), where a missing URL fails the run instead.
"""

import datetime as dt
import os
import uuid
from collections.abc import AsyncIterator, Iterator

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core import clock
from app.core.config import Settings, get_settings
from app.main import create_app
from app.models import Base, Restaurant, Rider, User
from app.seed import seed
from app.services import routing

API_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
# A Wednesday, 13:00 in Bengaluru: every seeded restaurant with lunch hours is open.
NOON = dt.datetime(2026, 11, 25, 7, 30, tzinfo=dt.UTC)
KORAMANGALA_5TH = (12.9352, 77.6195)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "db: needs TEST_DATABASE_URL (Postgres + PostGIS)")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if TEST_DATABASE_URL:
        return
    if os.environ.get("REQUIRE_DB_TESTS") == "1" and any("db" in i.keywords for i in items):
        raise pytest.UsageError("REQUIRE_DB_TESTS=1 but TEST_DATABASE_URL is not set")
    skip = pytest.mark.skip(reason="TEST_DATABASE_URL not set")
    for item in items:
        if "db" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def frozen_clock() -> Iterator[None]:
    clock.set_fake(NOON)
    yield
    clock.set_fake(None)


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_osrm(points):  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr(routing, "fetch_osrm", no_osrm)
    monkeypatch.setenv("OSRM_URL", "off")
    monkeypatch.setenv("PHOTON_URL", "off")
    get_settings.cache_clear()


def test_settings() -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        osrm_url="off",
        photon_url="off",
        ambient_orders=False,
        razorpay_key_id="rzp_test_key",
        razorpay_key_secret="test-secret",  # type: ignore[arg-type]
        razorpay_webhook_secret="hook-secret",  # type: ignore[arg-type]
    )


@pytest.fixture(scope="session")
def migrated_url() -> Iterator[str]:
    assert TEST_DATABASE_URL
    os.environ["ALEMBIC_URL"] = TEST_DATABASE_URL
    cfg = Config(os.path.join(API_DIR, "alembic.ini"))
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield TEST_DATABASE_URL


@pytest.fixture
async def engine(migrated_url: str) -> AsyncIterator[AsyncEngine]:
    # A pool per test (asyncpg connections belong to the test's event loop); streams open a
    # session per tick, and a fresh connection each time would dominate the run time.
    eng = create_async_engine(migrated_url, pool_size=5, max_overflow=10)
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    async with eng.begin() as conn:
        await conn.execute(text(f"truncate table {tables} restart identity cascade"))
        await conn.execute(text("alter sequence order_number_seq restart with 1001"))
    yield eng
    await eng.dispose()


@pytest.fixture
def factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
async def db(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        yield session


@pytest.fixture
async def world(db: AsyncSession) -> AsyncSession:
    """The seeded neighbourhood: 12 restaurants, menus, 8 sim riders + the demo rider, the demo
    customer and sim customers — no past or live orders."""
    await seed.seed_people(db)
    await seed.seed_restaurants(db)
    await seed.seed_riders(db)
    await db.commit()
    return db


@pytest.fixture
def app(factory: async_sessionmaker[AsyncSession]) -> FastAPI:
    application = create_app(test_settings())
    application.state.session_factory = factory
    return application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def make_client(app: FastAPI) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    )


# --- helpers -------------------------------------------------------------------------------------


async def restaurant(db: AsyncSession, slug: str) -> Restaurant:
    return (await db.execute(select(Restaurant).where(Restaurant.slug == slug))).scalar_one()


async def user(db: AsyncSession, email: str) -> User:
    return (await db.execute(select(User).where(User.email == email))).scalar_one()


async def rider_named(db: AsyncSession, name: str) -> Rider:
    return (await db.execute(select(Rider).where(Rider.name == name))).scalar_one()


async def item_ids(db: AsyncSession, r: Restaurant, n: int = 2) -> list[uuid.UUID]:
    rows = await db.execute(
        text("select id from menu_items where restaurant_id = :r order by sort, name limit :n"),
        {"r": r.id, "n": n},
    )
    return list(rows.scalars())


async def sign_in_as(client: AsyncClient, role: str) -> None:
    r = await client.post("/auth/demo", json={"as": role})
    assert r.status_code == 200, r.text


async def login(client: AsyncClient, db: AsyncSession, email: str) -> User:
    """A session for `email` without the demo scenes."""
    from app.services import auth

    u = await user(db, email)
    token, _ = await auth.open_session(db, u)
    client.cookies.set(auth.COOKIE, token)
    return u


async def place(
    db: AsyncSession,
    *,
    slug: str = "dosa-camp",
    email: str = "ananya@platter.demo",
    drop: tuple[float, float] = KORAMANGALA_5TH,
    payment: str = "cod",
):  # type: ignore[no-untyped-def]
    """A COD (or pending Razorpay) order through the real quote + create."""
    from app.models import PaymentKind
    from app.services import orders
    from app.services.events import Actor

    r = await restaurant(db, slug)
    customer = await user(db, email)
    ids = await item_ids(db, r)
    q = await orders.quote(db, r.id, [(i, 1) for i in ids], drop[0], drop[1])
    order = await orders.create(
        db,
        customer.id,
        q,
        lat=drop[0],
        lng=drop[1],
        address_line="1st Cross, Koramangala 5th Block",
        payment=PaymentKind(payment),
        note=None,
        actor=Actor("customer", user_id=customer.id),
    )
    await db.commit()
    return order
