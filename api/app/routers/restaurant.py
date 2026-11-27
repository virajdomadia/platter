"""The restaurant board 🍽 (06 §C): tickets, transitions, item availability, the board's stream.
Everything is scoped to the signed-in owner's restaurant; anyone else gets 404."""

import logging
import uuid
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import schemas as s
from app.core import clock
from app.core.config import Settings, current_settings
from app.core.db import get_session
from app.core.errors import not_found
from app.models import MenuCategory, MenuItem, Order, OrderStatus, Restaurant
from app.routers import sse
from app.routers.discovery import menu_item
from app.services import auth, demo, hours, orders, sim, views
from app.services import stream as stream_service
from app.services.events import Actor

router = APIRouter(prefix="/restaurant", tags=["restaurant"])
log = logging.getLogger(__name__)
S = OrderStatus
IST = ZoneInfo("Asia/Kolkata")
AMBIENT_EVERY = 20  # stream ticks


def board_restaurant(r: Restaurant) -> s.BoardRestaurant:
    return s.BoardRestaurant(
        id=str(r.id),
        slug=r.slug,
        name=r.name,
        area=r.area,
        is_open=orders.is_open(r),
        hours_label=hours.label(r.hours, clock.now()),
    )


async def today(db: AsyncSession, restaurant_id: uuid.UUID) -> s.BoardToday:
    start = clock.now().astimezone(IST).replace(hour=0, minute=0, second=0, microsecond=0)
    row = (
        await db.execute(
            select(
                func.count(),
                func.coalesce(func.sum(Order.subtotal_paise), 0),
                func.avg(func.extract("epoch", Order.accepted_at - Order.placed_at)),
            ).where(
                Order.restaurant_id == restaurant_id,
                Order.placed_at >= start,
                Order.status.not_in((S.rejected, S.cancelled, S.expired, S.pending_payment)),
            )
        )
    ).one()
    return s.BoardToday(
        orders=int(row[0]),
        revenue_paise=int(row[1]),
        avg_accept_s=int(row[2]) if row[2] is not None else None,
    )


@router.get("/board", response_model=s.Board)
async def board(
    owner: auth.RestaurantOwner = Depends(auth.require_restaurant),
    db: AsyncSession = Depends(get_session),
) -> s.Board:
    r = owner.restaurant
    r.board_seen_at = clock.now()
    await sim.advance(db, restaurant_id=r.id)
    await db.commit()
    rows = (
        (
            await db.execute(
                select(Order)
                .where(
                    Order.restaurant_id == r.id,
                    Order.status.in_((S.placed, S.accepted, S.preparing, S.ready, S.picked_up)),
                )
                .order_by(Order.placed_at)
            )
        )
        .scalars()
        .all()
    )
    tickets = {o.id: await views.ticket(db, o) for o in rows}
    return s.Board(
        restaurant=board_restaurant(r),
        new=[tickets[o.id] for o in rows if o.status == S.placed],
        cooking=[tickets[o.id] for o in rows if o.status in (S.accepted, S.preparing)],
        ready=[tickets[o.id] for o in rows if o.status == S.ready],
        out=[tickets[o.id] for o in rows if o.status == S.picked_up],
        today=await today(db, r.id),
        seq=await views.max_seq(db),
    )


@router.post("/orders/{order_id}/transition", response_model=s.Ticket)
async def transition(
    order_id: uuid.UUID,
    body: s.RestaurantTransitionIn,
    owner: auth.RestaurantOwner = Depends(auth.require_restaurant),
    db: AsyncSession = Depends(get_session),
) -> s.Ticket:
    order = await db.get(Order, order_id)
    if order is None or order.restaurant_id != owner.restaurant.id:
        raise not_found("No such order")
    actor = Actor("restaurant", user_id=owner.user.id, restaurant_id=owner.restaurant.id)
    owner.restaurant.board_seen_at = clock.now()
    order = await orders.transition(db, order_id, OrderStatus(body.to), actor, reason=body.reason)
    await db.commit()
    return await views.ticket(db, order)


@router.get("/menu", response_model=s.MenuOut)
async def menu(
    owner: auth.RestaurantOwner = Depends(auth.require_restaurant),
    db: AsyncSession = Depends(get_session),
) -> s.MenuOut:
    r = owner.restaurant
    categories = (
        (
            await db.execute(
                select(MenuCategory)
                .where(MenuCategory.restaurant_id == r.id)
                .order_by(MenuCategory.sort)
            )
        )
        .scalars()
        .all()
    )
    items = (
        (
            await db.execute(
                select(MenuItem).where(MenuItem.restaurant_id == r.id).order_by(MenuItem.sort)
            )
        )
        .scalars()
        .all()
    )
    return s.MenuOut(
        restaurant=board_restaurant(r),
        categories=[
            s.CategoryOut(
                id=str(c.id),
                name=c.name,
                items=[menu_item(i) for i in items if i.category_id == c.id],
            )
            for c in categories
        ],
    )


async def revalidate(settings: Settings, slug: str) -> None:
    """Tell the web to drop its cached copy of the restaurant page (best effort)."""
    if not settings.revalidate_secret:
        return
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            await client.post(
                f"{settings.web_url}/api/revalidate",
                json={
                    "tags": [f"restaurant:{slug}"],
                    "secret": settings.revalidate_secret.get_secret_value(),
                },
            )
    except httpx.HTTPError as exc:
        log.warning("revalidate failed: %s", type(exc).__name__)


@router.patch("/items/{item_id}", response_model=s.MenuItemOut)
async def set_availability(
    item_id: uuid.UUID,
    body: s.AvailabilityIn,
    owner: auth.RestaurantOwner = Depends(auth.require_restaurant),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(current_settings),
) -> s.MenuItemOut:
    item = await db.get(MenuItem, item_id)
    if item is None or item.restaurant_id != owner.restaurant.id:
        raise not_found("No such item")
    item.is_available = body.is_available
    await db.commit()
    await revalidate(settings, owner.restaurant.slug)
    return menu_item(item)


@router.get("/events", response_class=StreamingResponse)
async def events(
    request: Request,
    since: str | None = Query(default=None),
    owner: auth.RestaurantOwner = Depends(auth.require_restaurant),
    db: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    restaurant_id = owner.restaurant.id
    settings: Settings = request.app.state.settings
    await db.close()

    async def ambient(tick_db: AsyncSession, tick: int) -> None:
        if settings.ambient_orders and tick % AMBIENT_EVERY == 5:
            r = await tick_db.get(Restaurant, restaurant_id)
            await demo.keep_alive(tick_db, prefer=r)

    return sse.respond(request, stream_service.Scope("restaurant", restaurant_id), since, ambient)
