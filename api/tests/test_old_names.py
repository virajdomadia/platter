"""Migration 0007: the pre-#8 restaurants (real brands' names) leave a database seeded before the
rename; a real customer's order is never deleted with them."""

import importlib.util
import pathlib
import uuid

import pytest
from sqlalchemy import text

from tests.conftest import place

pytestmark = pytest.mark.db
_path = pathlib.Path(__file__).parents[1] / "alembic" / "versions" / "0007_retire_old_names.py"
_spec = importlib.util.spec_from_file_location("retire_old_names", _path)
assert _spec and _spec.loader
retire = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(retire)


async def old_restaurant(db, slug: str, name: str) -> uuid.UUID:  # type: ignore[no-untyped-def]
    """A pre-#8 row: the old slug and the brand name, copied from today's renamed kitchen."""
    owner, rid = uuid.uuid4(), uuid.uuid4()
    await db.execute(
        text(
            "insert into users (id, email, name, role, is_demo, created_at)"
            " values (:id, :e, 'Old owner', 'restaurant', true, now())"
        ),
        {"id": owner, "e": f"owner.{slug}@platter.demo"},
    )
    await db.execute(
        text(
            "insert into restaurants (id, owner_user_id, slug, name, area, cuisines, is_veg, loc,"
            " address, prep_min, hours, is_open, created_at)"
            " select :id, :owner, :slug, :name, area, cuisines, is_veg, loc, address, prep_min,"
            " hours, is_open, now() from restaurants where slug = 'dosa-camp'"
        ),
        {"id": rid, "owner": owner, "slug": slug, "name": name},
    )
    await db.commit()
    return rid


async def run(db) -> None:  # type: ignore[no-untyped-def]
    for statement in retire.UPGRADE.split(";"):
        if statement.strip():
            await db.execute(text(statement))
    await db.commit()


async def test_old_brand_names_leave_and_real_orders_stay(world, client):
    db = world
    gone = await old_restaurant(db, "pizza-bakery", "Pizza Bakery")
    kept = await old_restaurant(db, "chai-point", "Chai Point")
    demo_order = await place(db)
    real_order = await place(db)
    await db.execute(
        text("update orders set restaurant_id = :r where id = :o"), {"r": gone, "o": demo_order.id}
    )
    await db.execute(
        text("update orders set restaurant_id = :r, is_demo = false where id = :o"),
        {"r": kept, "o": real_order.id},
    )
    await db.commit()

    await run(db)
    await run(db)  # idempotent

    names = {c["name"] for c in (await client.get("/restaurants")).json()}
    assert not names & {"Pizza Bakery", "Chai Point", "Koramangala Social"}
    rows = dict(
        (
            await db.execute(
                text(
                    "select slug, name from restaurants"
                    " where slug in ('pizza-bakery', 'chai-point')"
                )
            )
        ).all()
    )
    assert rows == {"chai-point": "Tapri Tales"}  # kept for the real order, renamed and hidden
    assert (
        await db.execute(text("select count(*) from orders where id = :o"), {"o": real_order.id})
    ).scalar() == 1
    assert (
        await db.execute(text("select count(*) from orders where id = :o"), {"o": demo_order.id})
    ).scalar() == 0
    owners = (
        await db.execute(text("select email from users where email like 'owner.pizza-bakery%'"))
    ).all()
    assert owners == []


async def test_reorder_from_a_retired_kitchen_adds_nothing(world, app):
    from tests.conftest import login, make_client

    db = world
    kept = await old_restaurant(db, "chai-point", "Chai Point")
    order = await place(db)
    await db.execute(
        text("update orders set restaurant_id = :r, is_demo = false where id = :o"),
        {"r": kept, "o": order.id},
    )
    await db.commit()
    await run(db)
    async with await make_client(app) as c:
        await login(c, db, "ananya@platter.demo")
        body = (await c.post(f"/orders/{order.id}/reorder")).json()
    assert body["lines"] == [] and len(body["dropped"]) >= 1
