"""App factory. Vercel's FastAPI preset imports the module-level `app`."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import Settings, get_settings
from app.core.db import dispose_engines
from app.core.errors import install_error_handlers
from app.routers import addresses, admin, auth, discovery, orders, restaurant, rider, system

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await dispose_engines()


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(
        title="Platter API",
        version="1.0.0",
        description=(
            "Food delivery with live tracking: customers, restaurants, riders and an admin on one"
            " order state machine. Postgres (PostGIS) is the bus: `order_events` is the durable"
            " log every stream reads by seq."
        ),
        docs_url="/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings or get_settings()
    install_error_handlers(app)
    for r in (system, auth, discovery, addresses, orders, restaurant, rider, admin):
        app.include_router(r.router)
    return app


app = create_app()
