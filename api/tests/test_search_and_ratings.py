"""v2 L4: search (name, cuisine or a dish on the menu), cuisine / veg filters and sort; reorder
with what was dropped explained; one rating per delivered order, and a demo visitor's rating never
moves a public score."""

import pytest
from sqlalchemy import text

from app.core import clock
from app.models import Order, OrderStatus
from tests.conftest import KORAMANGALA_5TH, login, make_client, place

pytestmark = pytest.mark.db
S = OrderStatus
PIN = f"lat={KORAMANGALA_5TH[0]}&lng={KORAMANGALA_5TH[1]}"


async def slugs(client, query: str) -> list[str]:  # type: ignore[no-untyped-def]
    r = await client.get(f"/restaurants?{PIN}&{query}")
    assert r.status_code == 200, r.text
    return [c["slug"] for c in r.json()]


async def test_search_finds_a_kitchen_by_a_dish_on_its_menu(world, client):
    # Bandstand's name and cuisines don't say paneer; its menu does.
    assert "bandstand-kitchen" in await slugs(client, "q=paneer tikka")
    found = await slugs(client, "q=dosa")
    assert "dosa-camp" in found and "burger-barn" not in found
    assert await slugs(client, "q=zzzz-no-such-dish") == []
    # the user's % and _ are matched literally, not as wildcards
    assert await slugs(client, "q=%25") == []
    assert await slugs(client, "q=_") == []


async def test_cuisine_veg_and_sort(world, client):
    south = await slugs(client, "cuisine=south indian")
    assert set(south) == {"dosa-camp", "idli-hut"}
    veg = (await client.get(f"/restaurants?{PIN}&veg=true")).json()
    assert veg and all(c["is_veg"] for c in veg)
    by_rating = [
        c for c in (await client.get(f"/restaurants?{PIN}&sort=rating")).json() if c["orderable"]
    ]
    stars = [c["rating"] or 0 for c in by_rating]
    assert stars == sorted(stars, reverse=True)
    assert (await client.get(f"/restaurants?{PIN}&sort=cheapest")).status_code == 422


async def delivered(db, email: str = "ananya@platter.demo", slug: str = "dosa-camp") -> Order:  # type: ignore[no-untyped-def]
    order = await place(db, slug=slug, email=email)
    await db.execute(
        text("update orders set status = 'delivered', delivered_at = :t where id = :o"),
        {"t": clock.now(), "o": order.id},
    )
    await db.commit()
    return order


async def test_one_rating_per_delivered_order(world, app):
    db = world
    order = await place(db)
    async with await make_client(app) as c:
        await login(c, db, "ananya@platter.demo")
        r = await c.post(f"/orders/{order.id}/rating", json={"restaurant_stars": 5})
        assert r.status_code == 409 and r.json()["error"]["code"] == "not_delivered"
        await db.execute(
            text("update orders set status = 'delivered' where id = :o"), {"o": order.id}
        )
        await db.commit()
        for bad in (
            {"restaurant_stars": 0},
            {"restaurant_stars": 6},
            {"restaurant_stars": 4, "rider_stars": 9},
        ):
            assert (await c.post(f"/orders/{order.id}/rating", json=bad)).status_code == 422
        r = await c.post(
            f"/orders/{order.id}/rating", json={"restaurant_stars": 4, "line": " Crisp! "}
        )
        assert r.status_code == 201 and r.json()["rating"]["line"] == "Crisp!"
        r = await c.post(f"/orders/{order.id}/rating", json={"restaurant_stars": 1})
        assert r.status_code == 409 and r.json()["error"]["code"] == "already_rated"
        assert (await c.get(f"/orders/{order.id}")).json()["rating"]["restaurant_stars"] == 4
    async with await make_client(app) as stranger:
        await login(stranger, db, "priya.sharma@customers.platter.demo")
        assert (
            await stranger.post(f"/orders/{order.id}/rating", json={"restaurant_stars": 1})
        ).status_code == 404


async def card(client, slug: str) -> dict:  # type: ignore[no-untyped-def]
    return next(c for c in (await client.get(f"/restaurants?{PIN}")).json() if c["slug"] == slug)


async def test_a_demo_rating_never_moves_the_public_score_but_a_real_one_does(world, app, client):
    from tests.test_demo_isolation import real_order

    db = world
    before = (await card(client, "bandstand-kitchen"))["rating"]
    demo = await delivered(db, slug="bandstand-kitchen")
    async with await make_client(app) as c:
        await login(c, db, "ananya@platter.demo")
        assert (
            await c.post(f"/orders/{demo.id}/rating", json={"restaurant_stars": 1})
        ).status_code == 201
    assert (await card(client, "bandstand-kitchen"))["rating"] == before

    real = await real_order(app, db)
    await db.execute(text("update orders set status = 'delivered' where id = :o"), {"o": real.id})
    await db.commit()
    async with await make_client(app) as c:
        r = await c.post(
            "/auth/sign-in", json={"email": "priya@example.com", "password": "correct horse"}
        )
        assert r.status_code == 200
        assert (
            await c.post(f"/orders/{real.id}/rating", json={"restaurant_stars": 1})
        ).status_code == 201
    after = (await card(client, "bandstand-kitchen"))["rating"]
    assert after < before  # one real 1-star, blended with the seeded score (counted as ten)
    assert after == round((before * 10 + 1) / 11, 1)


async def test_reorder_explains_what_was_dropped(world, app):
    db = world
    order = await delivered(db)
    lines = (
        await db.execute(
            text("select menu_item_id, name from order_items where order_id = :o"), {"o": order.id}
        )
    ).all()
    gone, kept = lines[0], lines[1]
    await db.execute(
        text("update menu_items set is_available = false where id = :i"), {"i": gone[0]}
    )
    await db.execute(
        text("update menu_items set price_paise = 99900 where id = :i"), {"i": kept[0]}
    )
    await db.commit()
    async with await make_client(app) as c:
        await login(c, db, "ananya@platter.demo")
        r = await c.post(f"/orders/{order.id}/reorder")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["restaurant"]["slug"] == "dosa-camp"
        assert body["dropped"] == [gone[1]]
        assert [x["id"] for x in body["lines"]] == [str(kept[0])]
        assert body["lines"][0]["price_paise"] == 99900  # today's price; checkout quotes it again
    async with await make_client(app) as stranger:
        await login(stranger, db, "priya.sharma@customers.platter.demo")
        assert (await stranger.post(f"/orders/{order.id}/reorder")).status_code == 404


async def test_the_rider_rating_needs_a_rider(world, app):
    db = world
    order = await delivered(db)
    assert order.rider_id is None
    async with await make_client(app) as c:
        await login(c, db, "ananya@platter.demo")
        r = await c.post(
            f"/orders/{order.id}/rating", json={"restaurant_stars": 5, "rider_stars": 5}
        )
        assert r.status_code == 201 and r.json()["rating"]["rider_stars"] is None
