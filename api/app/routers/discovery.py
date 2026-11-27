"""Public discovery (06 §C): geocoding proxy, restaurants near a pin, one restaurant's menu."""

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import schemas as s
from app.core.db import get_session
from app.core.errors import not_found
from app.models import MenuCategory, MenuItem, Restaurant
from app.services import geo, limits, orders, views

router = APIRouter(tags=["discovery"])

DEFAULT_PIN = (12.9352, 77.6195)  # Koramangala 5th Block


@router.get("/geo/search", response_model=list[s.Place])
async def geo_search(
    request: Request,
    q: str = Query(min_length=2, max_length=120),
    lat: float | None = Query(default=None, ge=-90, le=90),
    lng: float | None = Query(default=None, ge=-180, le=180),
    db: AsyncSession = Depends(get_session),
) -> list[s.Place]:
    await limits.hit(
        db, f"geo:{limits.client_ip(request, request.app.state.settings)}", geo.LIMIT_PER_MIN
    )
    return await geo.search(q, lat, lng)


@router.get("/geo/reverse", response_model=s.Place)
async def geo_reverse(
    request: Request,
    lat: float = Query(ge=-90, le=90),
    lng: float = Query(ge=-180, le=180),
    db: AsyncSession = Depends(get_session),
) -> s.Place:
    await limits.hit(
        db, f"geo:{limits.client_ip(request, request.app.state.settings)}", geo.LIMIT_PER_MIN
    )
    return await geo.reverse(lat, lng)


@router.get("/restaurants", response_model=list[s.RestaurantCard])
async def restaurants(
    response: Response,
    lat: float = Query(default=DEFAULT_PIN[0], ge=-90, le=90),
    lng: float = Query(default=DEFAULT_PIN[1], ge=-180, le=180),
    db: AsyncSession = Depends(get_session),
) -> list[s.RestaurantCard]:
    response.headers["Cache-Control"] = "private, max-age=30"
    return await geo.nearby(db, lat, lng)


@router.get("/restaurants/{slug}", response_model=s.RestaurantOut)
async def restaurant(
    slug: str,
    lat: float | None = Query(default=None, ge=-90, le=90),
    lng: float | None = Query(default=None, ge=-180, le=180),
    db: AsyncSession = Depends(get_session),
) -> s.RestaurantOut:
    r = (await db.execute(select(Restaurant).where(Restaurant.slug == slug))).scalar_one_or_none()
    if r is None or r.is_sandbox:
        raise not_found("No such restaurant")
    pin = (lat, lng) if lat is not None and lng is not None else DEFAULT_PIN
    distance = await orders.straight_distance(db, r.id, pin[0], pin[1])
    card = views.restaurant_card(r, distance_m=distance)
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
    return s.RestaurantOut(
        **card.model_dump(),
        address=r.address,
        hours=r.hours,
        categories=[
            s.CategoryOut(
                id=str(c.id),
                name=c.name,
                items=[menu_item(i) for i in items if i.category_id == c.id],
            )
            for c in categories
        ],
    )


def menu_item(i: MenuItem) -> s.MenuItemOut:
    return s.MenuItemOut(
        id=str(i.id),
        name=i.name,
        description=i.description,
        price_paise=i.price_paise,
        is_veg=i.is_veg,
        photo=views.photo(i.photo_url),
        is_available=i.is_available,
    )
