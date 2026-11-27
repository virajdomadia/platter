"""The menu editor's rules (v2 L3).

* **Which restaurant an owner edits.** A real owner edits their live restaurant. The public demo
  kitchen login edits a private **sandbox copy** (`restaurants.is_sandbox`): never listed, no public
  page, no orders, and rebuilt from the live menu on every demo sign-in. So an anonymous visitor
  can try every part of the editor without changing what real customers see.
* **Photos come from the library** — the CC dish photos already served by the web (every seeded
  dish and cover). An upload would let an anonymous visitor host files on the platform.
  shortcut: no uploads, until real (non-demo) owners exist; then the Blob client token of 06 §B.
"""

import re
import uuid

from sqlalchemy import delete, func, select, text, union
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.errors import ApiError, not_found
from app.models import MenuCategory, MenuItem, Restaurant, Role, User
from app.services import hours

SANDBOX_SUFFIX = "-sandbox"
TIME = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$|^24:00$")


async def library(db: AsyncSession) -> list[str]:
    """Every photo the live restaurants use: the dish and cover library."""
    q = union(
        select(MenuItem.photo_url)
        .join(Restaurant, Restaurant.id == MenuItem.restaurant_id)
        .where(MenuItem.photo_url.is_not(None), Restaurant.is_sandbox.is_(False)),
        select(Restaurant.cover_url).where(
            Restaurant.cover_url.is_not(None), Restaurant.is_sandbox.is_(False)
        ),
    )
    return sorted(u for u in (await db.execute(q)).scalars() if u)


async def check_photo(db: AsyncSession, url: str | None) -> None:
    if url is not None and url not in await library(db):
        raise ApiError(422, "validation", "Pick a photo from the library")


def check_hours(value: dict[str, list[list[str]]]) -> None:
    for day, ranges in value.items():
        if day not in hours.DAYS or len(ranges) > 3:
            raise ApiError(422, "validation", "Hours: one to three ranges per weekday")
        for r in ranges:
            if len(r) != 2 or not all(TIME.match(t) for t in r) or r[0] == "24:00":
                raise ApiError(422, "validation", 'Hours look like ["11:00", "23:00"]')


async def sandbox_of(db: AsyncSession, live: Restaurant) -> Restaurant:
    slug = f"{live.slug}{SANDBOX_SUFFIX}"
    found = (
        await db.execute(select(Restaurant).where(Restaurant.slug == slug))
    ).scalar_one_or_none()
    return found or await reset_sandbox(db, live)


async def reset_sandbox(db: AsyncSession, live: Restaurant) -> Restaurant:
    """(Re)build the demo kitchen's sandbox from the live restaurant: details, categories, items.
    One at a time per kitchen (overlapping demo sign-ins would otherwise both create it, or both
    re-copy the menu into it)."""
    slug = f"{live.slug}{SANDBOX_SUFFIX}"
    await db.execute(text("select pg_advisory_xact_lock(hashtext(:k))"), {"k": slug})
    sb = (await db.execute(select(Restaurant).where(Restaurant.slug == slug))).scalar_one_or_none()
    if sb is None:
        owner = User(
            id=uuid.uuid4(),
            email=f"sandbox.{live.slug}@platter.demo",
            name=f"{live.name} (demo sandbox)",
            role=Role.restaurant,
            is_demo=True,
            created_at=clock.now(),
        )
        db.add(owner)
        await db.flush()
        # SQL, so the location is copied as-is (no geometry round trip through Python).
        sb_id = uuid.uuid4()
        await db.execute(
            text(
                "insert into restaurants (id, owner_user_id, slug, name, area, cuisines, is_veg,"
                " loc, address, prep_min, hours, is_open, cover_url, rating, is_sandbox,"
                " created_at)"
                " select :id, :owner, :slug, name, area, cuisines, is_veg, loc, address, prep_min,"
                " hours, is_open, cover_url, rating, true, :now from restaurants where id = :live"
            ),
            {"id": sb_id, "owner": owner.id, "slug": slug, "now": clock.now(), "live": live.id},
        )
        sb = await db.get(Restaurant, sb_id)
        assert sb is not None  # noqa: S101 - just inserted
    else:
        sb.name, sb.prep_min, sb.hours = live.name, live.prep_min, live.hours
        sb.is_open, sb.cover_url = live.is_open, live.cover_url
    await db.flush()
    await db.execute(delete(MenuCategory).where(MenuCategory.restaurant_id == sb.id))
    cats = (
        await db.execute(select(MenuCategory).where(MenuCategory.restaurant_id == live.id))
    ).scalars()
    for c in list(cats):
        copy = MenuCategory(id=uuid.uuid4(), restaurant_id=sb.id, name=c.name, sort=c.sort)
        db.add(copy)
        await db.flush()
        await db.execute(
            text(
                "insert into menu_items (id, restaurant_id, category_id, name, description,"
                " price_paise, is_veg, photo_url, is_available, sort)"
                " select gen_random_uuid(), :sb, :cat, name, description, price_paise, is_veg,"
                " photo_url, true, sort from menu_items where category_id = :src"
            ),
            {"sb": sb.id, "cat": copy.id, "src": c.id},
        )
    await db.flush()
    return sb


async def editable(db: AsyncSession, owner: User, live: Restaurant) -> Restaurant:
    """The restaurant this owner's editor writes to: the sandbox for the public demo login."""
    return await sandbox_of(db, live) if owner.is_demo else live


async def category_of(db: AsyncSession, r: Restaurant, category_id: uuid.UUID) -> MenuCategory:
    c = await db.get(MenuCategory, category_id)
    if c is None or c.restaurant_id != r.id:
        raise not_found("No such category")
    return c


async def item_of(db: AsyncSession, r: Restaurant, item_id: uuid.UUID) -> MenuItem:
    i = await db.get(MenuItem, item_id)
    if i is None or i.restaurant_id != r.id:
        raise not_found("No such item")
    return i


async def next_sort(db: AsyncSession, model: type, **where: uuid.UUID) -> int:
    q = select(func.coalesce(func.max(model.sort), -1) + 1).where(
        *(getattr(model, k) == v for k, v in where.items())
    )
    return int((await db.execute(q)).scalar_one())
