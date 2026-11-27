"""v2 L3: the menu editor and restaurant details. A real owner's edits reach the live page; the
public demo kitchen login edits a private sandbox copy that no customer, list, page or order can
reach, and that starts again from the live menu on every demo sign-in."""

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from tests.conftest import KORAMANGALA_5TH, item_ids, login, make_client, restaurant

pytestmark = pytest.mark.db
DEMO_KITCHEN = "owner.bandstand-kitchen@platter.demo"
REAL_OWNER = "owner.dosa-camp@platter.demo"


async def real_owner(app, db) -> AsyncClient:  # type: ignore[no-untyped-def]
    """Dosa Camp's owner as a real (non-demo) account: their edits are live."""
    await db.execute(text("update users set is_demo = false where email = :e"), {"e": REAL_OWNER})
    await db.commit()
    c = await make_client(app)
    await login(c, db, REAL_OWNER)
    return c


async def a_photo(c: AsyncClient) -> str:
    photos = (await c.get("/restaurant/photos")).json()
    assert len(photos) > 20 and all(p.startswith("/") for p in photos)
    return photos[0]


async def test_a_real_owner_adds_a_dish_with_a_photo_and_customers_see_it(world, app):
    c = await real_owner(app, world)
    menu = (await c.get("/restaurant/menu")).json()
    assert menu["sandbox"] is False
    cat = menu["categories"][0]["id"]
    photo = await a_photo(c)
    r = await c.post(
        "/restaurant/items",
        json={
            "category_id": cat,
            "name": "Ghee Podi Dosa",
            "price_paise": 14000,
            "is_veg": True,
            "photo_url": photo,
            "description": "Crisp, with gunpowder",
        },
    )
    assert r.status_code == 201, r.text
    async with await make_client(app) as anon:
        page = (await anon.get("/restaurants/dosa-camp")).json()
    added = [i for cat in page["categories"] for i in cat["items"] if i["name"] == "Ghee Podi Dosa"]
    assert added and added[0]["photo"]["url"] == photo and added[0]["price_paise"] == 14000
    await c.aclose()


async def test_marking_closed_takes_it_out_of_open_now_and_refuses_orders(world, app):
    db = world
    c = await real_owner(app, db)
    assert (await c.patch("/restaurant", json={"is_open": False})).status_code == 200
    async with await make_client(app) as anon:
        cards = (
            await anon.get(f"/restaurants?lat={KORAMANGALA_5TH[0]}&lng={KORAMANGALA_5TH[1]}")
        ).json()
        dosa = next(x for x in cards if x["slug"] == "dosa-camp")
        assert dosa["orderable"] is False and dosa["reason"] == "closed"
    async with await make_client(app) as customer:
        await login(customer, db, "ananya@platter.demo")
        r_ = await restaurant(db, "dosa-camp")
        ids = await item_ids(db, r_)
        q = await customer.post(
            "/orders/quote",
            json={
                "restaurant_id": str(r_.id),
                "items": [{"id": str(ids[0]), "qty": 1}],
                "address": {"lat": KORAMANGALA_5TH[0], "lng": KORAMANGALA_5TH[1]},
            },
        )
        assert q.status_code == 422 and q.json()["error"]["code"] == "restaurant_closed"
    await c.aclose()


async def test_the_demo_kitchen_edits_a_private_copy_customers_never_see(world, app):
    db = world
    async with await make_client(app) as c:
        await login(c, db, DEMO_KITCHEN)
        menu = (await c.get("/restaurant/menu")).json()
        assert menu["sandbox"] is True
        cat = menu["categories"][0]["id"]
        first = menu["categories"][0]["items"][0]
        r = await c.post(
            "/restaurant/items",
            json={
                "category_id": cat,
                "name": "Visit evil.example",
                "price_paise": 100,
                "is_veg": True,
            },
        )
        assert r.status_code == 201
        await c.patch(
            f"/restaurant/items/{first['id']}", json={"name": "Defaced", "is_available": False}
        )
        await c.patch("/restaurant", json={"is_open": False, "prep_min": 90})
        assert any(
            i["name"] == "Visit evil.example"
            for cat in (await c.get("/restaurant/menu")).json()["categories"]
            for i in cat["items"]
        )

    async with await make_client(app) as anon:
        page = (await anon.get("/restaurants/bandstand-kitchen")).json()
        names = {i["name"] for cat in page["categories"] for i in cat["items"]}
        assert "Visit evil.example" not in names and "Defaced" not in names
        assert all(i["is_available"] for cat in page["categories"] for i in cat["items"])
        assert page["orderable"] is True and page["prep_min"] != 90
        # The copy itself has no public page, isn't listed, and takes no orders.
        assert (await anon.get("/restaurants/bandstand-kitchen-sandbox")).status_code == 404
        cards = (await anon.get("/restaurants")).json()
        assert [x["slug"] for x in cards].count("bandstand-kitchen") == 1
        assert not any(x["slug"].endswith("-sandbox") for x in cards)
    sandbox_id = (
        await db.execute(text("select id from restaurants where is_sandbox"))
    ).scalar_one()
    async with await make_client(app) as customer:
        await login(customer, db, "ananya@platter.demo")
        q = await customer.post(
            "/orders/quote",
            json={
                "restaurant_id": str(sandbox_id),
                "items": [{"id": first["id"], "qty": 1}],
                "address": {"lat": KORAMANGALA_5TH[0], "lng": KORAMANGALA_5TH[1]},
            },
        )
        assert q.status_code == 404
    async with await make_client(app) as admin:
        await login(admin, db, "admin@platter.demo")
        rests = (await admin.get("/admin/map")).json()["restaurants"]
        assert not any(x["slug"].endswith("-sandbox") for x in rests)


async def test_the_next_demo_sign_in_starts_from_the_live_menu_again(world, app):
    async with await make_client(app) as c:
        await login(c, world, DEMO_KITCHEN)
        menu = (await c.get("/restaurant/menu")).json()
        await c.post(
            "/restaurant/items",
            json={
                "category_id": menu["categories"][0]["id"],
                "name": "Leftover",
                "price_paise": 500,
                "is_veg": True,
            },
        )
        await c.patch("/restaurant", json={"is_open": False})
        assert (await c.post("/auth/demo", json={"as": "restaurant"})).status_code == 200
        menu = (await c.get("/restaurant/menu")).json()
        names = {i["name"] for cat in menu["categories"] for i in cat["items"]}
        assert "Leftover" not in names and menu["details"]["is_open"] is True


async def test_an_owner_can_never_reach_another_kitchen(world, app):
    db = world
    other = await restaurant(db, "dosa-camp")
    other_item = (await item_ids(db, other))[0]
    live = await restaurant(db, "bandstand-kitchen")
    live_item = (await item_ids(db, live))[0]
    cat = (
        await db.execute(
            text("select id from menu_categories where restaurant_id = :r limit 1"), {"r": other.id}
        )
    ).scalar_one()
    async with await make_client(app) as c:
        await login(c, db, DEMO_KITCHEN)
        # another restaurant's dish, and the public Bandstand menu itself: both out of reach
        for item in (other_item, live_item):
            assert (
                await c.patch(f"/restaurant/items/{item}", json={"name": "x"})
            ).status_code == 404
            assert (await c.delete(f"/restaurant/items/{item}")).status_code == 404
        r = await c.post(
            "/restaurant/items",
            json={"category_id": str(cat), "name": "Sneaky", "price_paise": 500, "is_veg": True},
        )
        assert r.status_code == 404
        assert (await c.delete(f"/restaurant/categories/{cat}")).status_code == 404
    async with await make_client(app) as customer:
        await login(customer, db, "ananya@platter.demo")
        assert (await customer.get("/restaurant/menu")).status_code == 404


async def test_the_editor_validates_what_it_saves(world, app):
    c = await real_owner(app, world)
    menu = (await c.get("/restaurant/menu")).json()
    cat = menu["categories"][0]
    base = {"category_id": cat["id"], "name": "Ok", "price_paise": 5000, "is_veg": True}
    assert (await c.post("/restaurant/items", json={**base, "price_paise": 0})).status_code == 422
    assert (await c.post("/restaurant/items", json={**base, "name": ""})).status_code == 422
    bad_photo = {**base, "photo_url": "https://evil.example/x.jpg"}
    assert (await c.post("/restaurant/items", json=bad_photo)).status_code == 422
    assert (await c.patch("/restaurant", json={"cover_url": "/dishes/nope.jpg"})).status_code == 422
    for hours in (
        {"mon": [["25:00", "23:00"]]},
        {"funday": [["10:00", "11:00"]]},
        {"mon": [["10:00"]]},
    ):
        assert (await c.patch("/restaurant", json={"hours": hours})).status_code == 422, hours
    assert (await c.patch("/restaurant", json={"prep_min": 2})).status_code == 422
    ok = {"mon": [["11:00", "15:00"], ["18:00", "23:30"]], "sun": [["00:00", "24:00"]]}
    r = await c.patch("/restaurant", json={"hours": ok, "prep_min": 20})
    assert r.status_code == 200 and r.json()["details"]["hours"]["mon"][1] == ["18:00", "23:30"]
    # a category with dishes is never deleted along with them
    r = await c.delete(f"/restaurant/categories/{cat['id']}")
    assert r.status_code == 409 and r.json()["error"]["code"] == "category_not_empty"
    await c.aclose()


async def test_categories_add_rename_reorder_and_delete(world, app):
    c = await real_owner(app, world)
    menu = (await c.post("/restaurant/categories", json={"name": "Specials"})).json()
    ids = [x["id"] for x in menu["categories"]]
    new = next(x["id"] for x in menu["categories"] if x["name"] == "Specials")
    assert ids[-1] == new
    r = await c.put("/restaurant/categories/order", json={"ids": [new, *ids[:-1]]})
    assert r.status_code == 200 and r.json()["categories"][0]["name"] == "Specials"
    assert (await c.put("/restaurant/categories/order", json={"ids": ids[:-1]})).status_code == 422
    r = await c.patch(f"/restaurant/categories/{new}", json={"name": "Chef's specials"})
    assert r.json()["categories"][0]["name"] == "Chef's specials"
    r = await c.delete(f"/restaurant/categories/{new}")
    assert r.status_code == 200 and all(x["id"] != new for x in r.json()["categories"])
    await c.aclose()


async def test_deleting_a_dish_keeps_past_orders_intact(world, app):
    from tests.conftest import place

    db = world
    order = await place(db, slug="dosa-camp")
    line = (
        await db.execute(
            text("select menu_item_id, name from order_items where order_id = :o limit 1"),
            {"o": order.id},
        )
    ).one()
    c = await real_owner(app, db)
    assert (await c.delete(f"/restaurant/items/{line[0]}")).status_code == 200
    kept = (
        await db.execute(
            text("select name, menu_item_id from order_items where order_id = :o and name = :n"),
            {"o": order.id, "n": line[1]},
        )
    ).one()
    assert kept[0] == line[1] and kept[1] is None
    await c.aclose()


async def test_blank_names_are_refused(world, app):
    c = await real_owner(app, world)
    menu = (await c.get("/restaurant/menu")).json()
    cat = menu["categories"][0]
    body = {"category_id": cat["id"], "name": "   ", "price_paise": 5000, "is_veg": True}
    assert (await c.post("/restaurant/items", json=body)).status_code == 422
    assert (await c.post("/restaurant/categories", json={"name": "  "})).status_code == 422
    item = cat["items"][0]["id"]
    assert (await c.patch(f"/restaurant/items/{item}", json={"name": " "})).status_code == 422
    await c.aclose()


async def test_overlapping_demo_sign_ins_build_one_sandbox_menu(world, app):
    import asyncio

    async def sign_in() -> int:
        async with await make_client(app) as c:
            return (await c.post("/auth/demo", json={"as": "restaurant"})).status_code

    assert await asyncio.gather(*(sign_in() for _ in range(4))) == [200] * 4
    live, sandbox = (
        await world.execute(
            text(
                "select count(*) filter (where not r.is_sandbox),"
                " count(*) filter (where r.is_sandbox)"
                " from menu_items i join restaurants r on r.id = i.restaurant_id"
                " where r.slug like 'bandstand-kitchen%'"
            )
        )
    ).one()
    assert sandbox == live
    n = (await world.execute(text("select count(*) from restaurants where is_sandbox"))).scalar()
    assert n == 1
