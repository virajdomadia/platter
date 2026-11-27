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
from app.core.errors import ApiError, not_found
from app.models import MenuCategory, MenuItem, Order, OrderStatus, Restaurant
from app.routers import sse
from app.routers.discovery import menu_item
from app.services import auth, demo, hours, limits, orders, sim, views
from app.services import menu as menu_service
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
                    Order.is_demo.is_(True),  # every board login is the public demo
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
    if order is None or order.restaurant_id != owner.restaurant.id or not order.is_demo:
        raise not_found("No such order")
    actor = Actor("restaurant", user_id=owner.user.id, restaurant_id=owner.restaurant.id)
    owner.restaurant.board_seen_at = clock.now()
    order = await orders.transition(db, order_id, OrderStatus(body.to), actor, reason=body.reason)
    await db.commit()
    return await views.ticket(db, order)


async def _menu_out(db: AsyncSession, r: Restaurant) -> s.MenuOut:
    categories = (
        (
            await db.execute(
                select(MenuCategory)
                .where(MenuCategory.restaurant_id == r.id)
                .order_by(MenuCategory.sort, MenuCategory.name)
            )
        )
        .scalars()
        .all()
    )
    items = (
        (
            await db.execute(
                select(MenuItem)
                .where(MenuItem.restaurant_id == r.id)
                .order_by(MenuItem.sort, MenuItem.name)
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
        details=s.RestaurantDetails(
            hours=r.hours, is_open=r.is_open, prep_min=r.prep_min, cover=views.photo(r.cover_url)
        ),
        sandbox=r.is_sandbox,
    )


async def _editing(owner: auth.RestaurantOwner, db: AsyncSession) -> Restaurant:
    return await menu_service.editable(db, owner.user, owner.restaurant)


async def _limit(request: Request, db: AsyncSession, settings: Settings) -> None:
    await limits.hit(db, f"menu:{limits.client_ip(request, settings)}", 120)


async def _saved(db: AsyncSession, settings: Settings, r: Restaurant) -> s.MenuOut:
    """Commit, drop the public page cache (the live restaurant only), answer the whole menu."""
    await db.commit()
    if not r.is_sandbox:
        await revalidate(settings, r.slug)
    return await _menu_out(db, r)


def _uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise not_found("No such category") from exc


@router.get("/menu", response_model=s.MenuOut)
async def menu(
    owner: auth.RestaurantOwner = Depends(auth.require_restaurant),
    db: AsyncSession = Depends(get_session),
) -> s.MenuOut:
    r = await _editing(owner, db)
    await db.commit()  # the demo kitchen's sandbox is made on first use
    return await _menu_out(db, r)


@router.get("/photos", response_model=list[str])
async def photos(
    _: auth.RestaurantOwner = Depends(auth.require_restaurant),
    db: AsyncSession = Depends(get_session),
) -> list[str]:
    """The photo library a dish or cover can use."""
    return await menu_service.library(db)


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
async def update_item(
    item_id: uuid.UUID,
    body: s.AvailabilityIn,
    request: Request,
    owner: auth.RestaurantOwner = Depends(auth.require_restaurant),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(current_settings),
) -> s.MenuItemOut:
    """Switch a dish on / off, or edit it. Off → gone from the customer menu, refused at order."""
    await _limit(request, db, settings)
    r = await _editing(owner, db)
    item = await menu_service.item_of(db, r, item_id)
    patch = body.model_dump(exclude_unset=True)
    if "photo_url" in patch:
        await menu_service.check_photo(db, body.photo_url)
    if body.category_id is not None:
        item.category_id = (await menu_service.category_of(db, r, _uuid(body.category_id))).id
    for field in ("is_available", "name", "description", "price_paise", "is_veg", "photo_url"):
        if field in patch and (patch[field] is not None or field in ("description", "photo_url")):
            value = patch[field]
            setattr(item, field, value.strip() if isinstance(value, str) else value)
    item.description = item.description or None
    await db.commit()
    if not r.is_sandbox:
        await revalidate(settings, r.slug)
    return menu_item(item)


@router.post("/items", response_model=s.MenuOut, status_code=201)
async def add_item(
    body: s.ItemIn,
    request: Request,
    owner: auth.RestaurantOwner = Depends(auth.require_restaurant),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(current_settings),
) -> s.MenuOut:
    await _limit(request, db, settings)
    r = await _editing(owner, db)
    category = await menu_service.category_of(db, r, _uuid(body.category_id))
    await menu_service.check_photo(db, body.photo_url)
    db.add(
        MenuItem(
            id=uuid.uuid4(),
            restaurant_id=r.id,
            category_id=category.id,
            name=body.name.strip(),
            description=(body.description or "").strip() or None,
            price_paise=body.price_paise,
            is_veg=body.is_veg,
            photo_url=body.photo_url,
            is_available=body.is_available,
            sort=await menu_service.next_sort(db, MenuItem, category_id=category.id),
        )
    )
    return await _saved(db, settings, r)


@router.delete("/items/{item_id}", response_model=s.MenuOut)
async def delete_item(
    item_id: uuid.UUID,
    request: Request,
    owner: auth.RestaurantOwner = Depends(auth.require_restaurant),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(current_settings),
) -> s.MenuOut:
    """Past orders keep their own copy of the dish (order_items is a snapshot)."""
    await _limit(request, db, settings)
    r = await _editing(owner, db)
    await db.delete(await menu_service.item_of(db, r, item_id))
    return await _saved(db, settings, r)


@router.post("/categories", response_model=s.MenuOut, status_code=201)
async def add_category(
    body: s.CategoryIn,
    request: Request,
    owner: auth.RestaurantOwner = Depends(auth.require_restaurant),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(current_settings),
) -> s.MenuOut:
    await _limit(request, db, settings)
    r = await _editing(owner, db)
    db.add(
        MenuCategory(
            id=uuid.uuid4(),
            restaurant_id=r.id,
            name=body.name.strip(),
            sort=await menu_service.next_sort(db, MenuCategory, restaurant_id=r.id),
        )
    )
    return await _saved(db, settings, r)


@router.patch("/categories/{category_id}", response_model=s.MenuOut)
async def rename_category(
    category_id: uuid.UUID,
    body: s.CategoryIn,
    request: Request,
    owner: auth.RestaurantOwner = Depends(auth.require_restaurant),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(current_settings),
) -> s.MenuOut:
    await _limit(request, db, settings)
    r = await _editing(owner, db)
    (await menu_service.category_of(db, r, category_id)).name = body.name.strip()
    return await _saved(db, settings, r)


@router.delete("/categories/{category_id}", response_model=s.MenuOut)
async def delete_category(
    category_id: uuid.UUID,
    request: Request,
    owner: auth.RestaurantOwner = Depends(auth.require_restaurant),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(current_settings),
) -> s.MenuOut:
    """Only an empty category: deleting one never takes dishes with it."""
    await _limit(request, db, settings)
    r = await _editing(owner, db)
    c = await menu_service.category_of(db, r, category_id)
    used = select(func.count()).select_from(MenuItem).where(MenuItem.category_id == c.id)
    if (await db.execute(used)).scalar_one():
        raise ApiError(409, "category_not_empty", "Move or delete its dishes first")
    await db.delete(c)
    return await _saved(db, settings, r)


@router.put("/categories/order", response_model=s.MenuOut)
async def order_categories(
    body: s.CategoryOrderIn,
    request: Request,
    owner: auth.RestaurantOwner = Depends(auth.require_restaurant),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(current_settings),
) -> s.MenuOut:
    """`ids`: every category of the menu, in the new order."""
    await _limit(request, db, settings)
    r = await _editing(owner, db)
    cats = {
        str(c.id): c
        for c in (
            await db.execute(select(MenuCategory).where(MenuCategory.restaurant_id == r.id))
        ).scalars()
    }
    if sorted(body.ids) != sorted(cats) or len(set(body.ids)) != len(body.ids):
        raise ApiError(422, "validation", "Send every category exactly once")
    for i, cid in enumerate(body.ids):
        cats[cid].sort = i
    return await _saved(db, settings, r)


@router.patch("", response_model=s.MenuOut)
async def update_details(
    body: s.DetailsIn,
    request: Request,
    owner: auth.RestaurantOwner = Depends(auth.require_restaurant),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(current_settings),
) -> s.MenuOut:
    """Hours per weekday, the open / closed switch, prep time, cover photo."""
    await _limit(request, db, settings)
    r = await _editing(owner, db)
    if body.hours is not None:
        menu_service.check_hours(body.hours)
        r.hours = body.hours
    if body.cover_url is not None:
        await menu_service.check_photo(db, body.cover_url)
        r.cover_url = body.cover_url
    if body.is_open is not None:
        r.is_open = body.is_open
    if body.prep_min is not None:
        r.prep_min = body.prep_min
    return await _saved(db, settings, r)


@router.get("/events", response_class=StreamingResponse)
async def events(
    request: Request,
    since: str | None = Query(default=None),
    owner: auth.RestaurantOwner = Depends(auth.require_restaurant),
    db: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    restaurant_id = owner.restaurant.id
    settings: Settings = request.app.state.settings

    async def ambient(tick_db: AsyncSession, tick: int) -> None:
        if settings.ambient_orders and tick % AMBIENT_EVERY == 5:
            r = await tick_db.get(Restaurant, restaurant_id)
            await demo.keep_alive(tick_db, prefer=r)

    return await sse.respond(
        request, db, stream_service.Scope("restaurant", restaurant_id), since, ambient
    )
