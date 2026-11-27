"""04 §12 test_rbac + R1: sign up / in / out; a customer never sees the board, the rider app or
the admin (404, not 403); a restaurant sees only its own orders; a rider touches only its job;
the four demo logins each land on something alive."""

import pytest
from sqlalchemy import select, text

from app.models import Order, OrderStatus
from app.services import orders
from app.services.events import Actor
from tests.conftest import login, make_client, place, take_offer

pytestmark = pytest.mark.db
S = OrderStatus


async def test_sign_up_in_me_out(world, client):
    r = await client.post(
        "/auth/sign-up",
        json={"email": "Neha@Example.com", "password": "correct horse", "name": "Neha"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["role"] == "customer" and r.json()["email"] == "neha@example.com"
    cookie = r.headers["set-cookie"]
    assert "pl_session=" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert "Max-Age=2592000" in cookie  # 30 days
    assert (await client.get("/auth/me")).json()["name"] == "Neha"
    dup = await client.post(
        "/auth/sign-up", json={"email": "neha@example.com", "password": "x" * 8, "name": "N"}
    )
    assert dup.status_code == 409
    assert (await client.post("/auth/sign-out")).status_code == 204
    assert (await client.get("/auth/me")).status_code == 401
    bad = await client.post(
        "/auth/sign-in", json={"email": "neha@example.com", "password": "wrong pass"}
    )
    assert bad.status_code == 401
    ok = await client.post(
        "/auth/sign-in", json={"email": "neha@example.com", "password": "correct horse"}
    )
    assert ok.status_code == 200


async def test_sessions_expire_after_30_days(world, client):
    from app.core import clock

    await login(client, world, "ananya@platter.demo")
    assert (await client.get("/auth/me")).status_code == 200
    clock.advance(30 * 86400 + 1)
    assert (await client.get("/auth/me")).status_code == 401


ROLE_ROUTES = [
    ("GET", "/restaurant/board"),
    ("GET", "/restaurant/menu"),
    ("GET", "/rider/me"),
    ("GET", "/admin/map"),
    ("GET", "/admin/orders"),
    ("GET", "/admin/riders"),
]


async def test_the_wrong_role_gets_404_everywhere(world, app):
    expected_ok = {
        "ananya@platter.demo": set(),
        "owner.bandstand-kitchen@platter.demo": {"/restaurant/board", "/restaurant/menu"},
        "rider@platter.demo": {"/rider/me"},
        "admin@platter.demo": {"/admin/map", "/admin/orders", "/admin/riders"},
    }
    for email, allowed in expected_ok.items():
        async with await make_client(app) as c:
            await login(c, world, email)
            for method, path in ROLE_ROUTES:
                r = await c.request(method, path)
                if path in allowed:
                    assert r.status_code == 200, (email, path, r.text)
                else:
                    assert r.status_code == 404, (email, path)
                    assert r.json()["error"]["code"] == "not_found"
    async with await make_client(app) as anon:
        for method, path in ROLE_ROUTES:
            assert (await anon.request(method, path)).status_code == 404


async def test_a_restaurant_sees_and_moves_only_its_own_orders(world, app):
    mine = await place(world, slug="bandstand-kitchen")
    theirs = await place(world, slug="dosa-camp")
    async with await make_client(app) as c:
        await login(c, world, "owner.bandstand-kitchen@platter.demo")
        board = (await c.get("/restaurant/board")).json()
        assert [t["id"] for t in board["new"]] == [str(mine.id)]
        assert board["new"][0]["customer_first_name"] == "Ananya"
        r = await c.post(f"/restaurant/orders/{theirs.id}/transition", json={"to": "accepted"})
        assert r.status_code == 404
        r = await c.post(f"/restaurant/orders/{mine.id}/transition", json={"to": "accepted"})
        assert r.status_code == 200 and r.json()["status"] == "accepted"
        r = await c.post(f"/restaurant/orders/{mine.id}/transition", json={"to": "ready"})
        assert r.status_code == 409 and r.json()["error"]["details"] == {
            "from": "accepted",
            "to": "ready",
        }


async def test_a_customer_cannot_read_or_cancel_someone_elses_order(world, app):
    order = await place(world)
    async with await make_client(app) as c:
        await login(c, world, "ravi.kumar@customers.platter.demo")
        assert (await c.get(f"/orders/{order.id}")).status_code == 404
        assert (await c.post(f"/orders/{order.id}/cancel")).status_code == 404
        assert str(order.id) not in (await c.get("/orders")).text
    async with await make_client(app) as c:
        await login(c, world, "ananya@platter.demo")
        assert (await c.post(f"/orders/{order.id}/cancel")).json()["status"] == "cancelled"


async def test_a_rider_touches_only_its_own_job(world, app):
    db = world
    await db.execute(text("update riders set status = 'busy' where is_sim"))
    from app.services import sim

    divya_id = (await db.execute(text("select id from riders where name = 'Divya S'"))).scalar_one()
    await sim.upsert_position(db, divya_id, (12.9356, 77.6143), 0, 0.0)
    await db.execute(text("update restaurants set board_seen_at = now() + interval '1 day'"))
    await db.commit()
    order = await place(db, slug="bandstand-kitchen")
    kitchen = Actor("restaurant", restaurant_id=order.restaurant_id)
    order = await orders.transition(db, order.id, S.accepted, kitchen)
    await db.commit()
    order = await take_offer(db, order.id)
    assert order.rider_id == divya_id
    other = await place(db, slug="dosa-camp")
    async with await make_client(app) as c:
        await login(c, db, "rider@platter.demo")
        me = (await c.get("/rider/me")).json()
        assert me["job"]["order_id"] == str(order.id)
        assert me["job"]["phase"] in ("to_restaurant", "waiting")
        # not mine → 404
        assert (
            await c.post(f"/rider/orders/{other.id}/transition", json={"to": "picked_up"})
        ).status_code == 404
        # picked up before ready → 409 (the button is disabled in the app)
        r = await c.post(f"/rider/orders/{order.id}/transition", json={"to": "picked_up"})
        assert r.status_code == 409
        await orders.transition(db, order.id, S.preparing, kitchen)
        await orders.transition(db, order.id, S.ready, kitchen)
        await db.commit()
        r = await c.post(f"/rider/orders/{order.id}/transition", json={"to": "picked_up"})
        assert r.status_code == 200 and r.json()["phase"] == "to_customer"
        r = await c.post(f"/rider/orders/{order.id}/transition", json={"to": "delivered"})
        assert r.status_code == 200 and r.json() is None
        me = (await c.get("/rider/me")).json()
        assert me["job"] is None and me["today"]["deliveries"] == 1


async def test_demo_logins_land_on_something_alive(world, app):
    for role in ("customer", "restaurant", "rider", "admin"):
        async with await make_client(app) as c:
            r = await c.post("/auth/demo", json={"as": role})
            assert r.status_code == 200, r.text
            assert r.json()["role"] == role
    db = world
    ananya = (
        await db.execute(text("select id from users where email = 'ananya@platter.demo'"))
    ).scalar_one()
    active = (
        (
            await db.execute(
                select(Order).where(
                    Order.user_id == ananya,
                    Order.status.in_((S.picked_up, S.accepted, S.preparing, S.ready)),
                )
            )
        )
        .scalars()
        .all()
    )
    assert active, "the demo customer has an order on the way"
    kitchen = (
        await db.execute(text("select id from restaurants where slug = 'bandstand-kitchen'"))
    ).scalar_one()
    tickets = (
        (await db.execute(select(Order.status).where(Order.restaurant_id == kitchen)))
        .scalars()
        .all()
    )
    assert S.placed in tickets
    divya = (await db.execute(text("select id from riders where name = 'Divya S'"))).scalar_one()
    assert (
        await db.execute(select(Order).where(Order.rider_id == divya))
    ).scalars().first() is not None


async def test_bad_demo_role_is_refused(world, client):
    assert (await client.post("/auth/demo", json={"as": "superuser"})).status_code == 422
