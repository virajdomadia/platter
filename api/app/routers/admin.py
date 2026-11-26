"""The admin 👑 (06 §C): live map, orders with stuck flags, riders by distance, reassign, stream."""

import uuid

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app import schemas as s
from app.core import clock
from app.core.config import Settings
from app.core.db import get_session
from app.core.errors import ApiError
from app.models import Order, Restaurant, User
from app.routers import sse
from app.services import admin, auth, demo, dispatch, sim
from app.services import stream as stream_service
from app.services.events import Actor

router = APIRouter(prefix="/admin", tags=["admin"])
AMBIENT_EVERY = 20  # stream ticks


@router.get("/map", response_model=s.AdminMap)
async def live_map(
    _: User = Depends(auth.require_admin), db: AsyncSession = Depends(get_session)
) -> s.AdminMap:
    await sim.advance(db)
    await db.commit()
    return await admin.live_map(db)


@router.get("/orders", response_model=list[s.AdminOrder])
async def list_orders(
    status: str | None = Query(default=None),
    stuck: bool = Query(default=False),
    _: User = Depends(auth.require_admin),
    db: AsyncSession = Depends(get_session),
) -> list[s.AdminOrder]:
    await sim.advance(db)
    await db.commit()
    try:
        return await admin.active_orders(db, only_stuck=stuck, status=status)
    except ValueError as exc:
        raise ApiError(422, "validation", "Unknown status") from exc


@router.get("/riders", response_model=list[s.AdminRider])
async def riders(
    near: str | None = Query(default=None, description="lat,lng"),
    _: User = Depends(auth.require_admin),
    db: AsyncSession = Depends(get_session),
) -> list[s.AdminRider]:
    return await admin.riders(db, admin.parse_near(near))


@router.post("/orders/{order_id}/reassign", response_model=s.AdminOrder)
async def reassign(
    order_id: uuid.UUID,
    body: s.ReassignIn,
    user: User = Depends(auth.require_admin),
    db: AsyncSession = Depends(get_session),
) -> s.AdminOrder:
    try:
        rider_id = uuid.UUID(body.rider_id)
    except ValueError as exc:
        raise ApiError(404, "not_found", "No such rider") from exc
    order = await dispatch.reassign(db, order_id, rider_id, Actor("admin", user_id=user.id))
    await db.commit()
    restaurant = await db.get(Restaurant, order.restaurant_id)
    assert restaurant is not None  # noqa: S101
    fresh = await db.get(Order, order.id, populate_existing=True)
    assert fresh is not None  # noqa: S101
    return await admin.admin_order(db, fresh, restaurant, clock.now())


@router.get("/events", response_class=StreamingResponse)
async def events(
    request: Request,
    since: str | None = Query(default=None),
    _: User = Depends(auth.require_admin),
    db: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    settings: Settings = request.app.state.settings
    await db.close()

    async def ambient(tick_db: AsyncSession, tick: int) -> None:
        if settings.ambient_orders and tick % AMBIENT_EVERY == 10:
            await demo.keep_alive(tick_db)

    return sse.respond(request, stream_service.Scope("admin"), since, ambient)
