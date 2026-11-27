"""Review 2026-11-27 H1/H2/M5: the one-tap demo roles never see or touch a real customer's order,
a real phone's GPS doesn't outlive its job or session, and one visitor can't break the shared demo
for the next."""

import datetime as dt

import pytest
from sqlalchemy import func, select, text

from app.core import clock
from app.models import Order, OrderStatus, Rider, RiderPosition, RiderTrack
from app.services import dispatch, orders, sim
from app.services.events import Actor
from tests.conftest import KORAMANGALA_5TH, item_ids, login, make_client, place, restaurant

pytestmark = pytest.mark.db
S = OrderStatus
DEMO_RIDER = "rider@platter.demo"


def fix(lat: float, lng: float, at: dt.datetime) -> dict:
    return {"lat": lat, "lng": lng, "at": at.isoformat(), "heading": 0, "speed_mps": 3.0}


async def real_order(app, db, slug: str = "bandstand-kitchen") -> Order:
    """A real sign-up placing a COD order through the API."""
    async with await make_client(app) as c:
        r = await c.post(
            "/auth/sign-up",
            json={"email": "priya@example.com", "password": "correct horse", "name": "Priya Real"},
        )
        assert r.status_code == 201, r.text
        rest = await restaurant(db, slug)
        ids = await item_ids(db, rest)
        r = await c.post(
            "/orders",
            json={
                "restaurant_id": str(rest.id),
                "items": [{"id": str(i), "qty": 1} for i in ids],
                "address": {"lat": KORAMANGALA_5TH[0], "lng": KORAMANGALA_5TH[1]},
                "address_line": "Flat 4B, 12th Main, Koramangala",
            },
        )
        assert r.status_code == 201, r.text
    order = await db.get(Order, r.json()["order"]["id"], populate_existing=True)
    assert order is not None and order.is_demo is False
    return order


async def demo_rider(db) -> Rider:  # type: ignore[no-untyped-def]
    return (await db.execute(select(Rider).where(Rider.is_sim.is_(False)))).scalar_one()


async def test_a_real_order_never_reaches_the_demo_rider_board_or_admin(world, app):
    db = world
    # The demo phone is sharing, right at the kitchen, and it is the only rider free.
    await db.execute(text("update riders set status = 'busy' where is_sim"))
    await db.execute(text("update restaurants set board_seen_at = :t"), {"t": clock.now()})
    await db.commit()
    rider = await demo_rider(db)
    await sim.upsert_position(db, rider.id, (12.9345, 77.6150), 0, 1.0)
    await db.commit()
    order = await real_order(app, db)

    # A visitor watching the board doesn't stall it: real orders always run on autopilot.
    clock.advance(46)
    await db.execute(text("update restaurants set board_seen_at = :t"), {"t": clock.now()})
    await sim.advance(db)
    await db.commit()
    order = await db.get(Order, order.id, populate_existing=True)
    assert order.status == S.accepted
    assert order.rider_id is None  # waits for a sim rather than the public phone
    oid, rid = str(order.id), str(rider.id)
    assert await dispatch.on_rider_available(db, rider) is None
    await db.rollback()

    async with await make_client(app) as c:
        await login(c, db, "owner.bandstand-kitchen@platter.demo")
        board = (await c.get("/restaurant/board")).json()
        listed = [t["id"] for col in ("new", "cooking", "ready", "out") for t in board[col]]
        assert oid not in listed
        r = await c.post(f"/restaurant/orders/{oid}/transition", json={"to": "preparing"})
        assert r.status_code == 404
    async with await make_client(app) as c:
        await login(c, db, "admin@platter.demo")
        assert all(o["id"] != oid for o in (await c.get("/admin/map")).json()["orders"])
        assert (await c.get("/admin/orders")).json() == []
        r = await c.post(f"/admin/orders/{oid}/reassign", json={"rider_id": rid})
        assert r.status_code == 404


async def test_admin_never_sees_a_sim_rider_heading_to_a_real_door(world, app):
    db = world
    order = await real_order(app, db, "dosa-camp")
    order = await orders.transition(
        db, order.id, S.accepted, Actor("restaurant", restaurant_id=order.restaurant_id)
    )
    await db.commit()
    assert order.rider_id is not None
    async with await make_client(app) as c:
        await login(c, db, "admin@platter.demo")
        riders = {r["id"]: r for r in (await c.get("/admin/riders")).json()}
    carrying = riders[str(order.rider_id)]
    assert carrying["lat"] is None and carrying["current_order"] is None


async def test_the_demo_phone_fix_is_forgotten(world, app):
    db = world
    rider = await demo_rider(db)
    async with await make_client(app) as phone:
        await login(phone, db, DEMO_RIDER)
        assert (
            await phone.post("/rider/position", json=fix(12.93, 77.62, clock.now()))
        ).status_code == 204
        async with await make_client(app) as admin:
            await login(admin, db, "admin@platter.demo")
            seen = next(
                r for r in (await admin.get("/admin/riders")).json() if r["id"] == str(rider.id)
            )
            assert seen["lat"] is not None  # live: shown
            clock.advance(121)
            seen = next(
                r for r in (await admin.get("/admin/riders")).json() if r["id"] == str(rider.id)
            )
            assert seen["lat"] is None and seen["status"] == "offline"  # stale: never shown
        # Any demo login deletes it for good.
        assert (await phone.post("/auth/demo", json={"as": "admin"})).status_code == 200
        assert await db.get(RiderPosition, rider.id, populate_existing=True) is None

    async with await make_client(app) as phone:
        await login(phone, db, DEMO_RIDER)
        await phone.post("/rider/position", json=fix(12.93, 77.62, clock.now()))
        assert await db.get(RiderPosition, rider.id, populate_existing=True) is not None
        assert (await phone.post("/auth/sign-out")).status_code == 204
    assert await db.get(RiderPosition, rider.id, populate_existing=True) is None


async def test_delivery_by_the_demo_phone_deletes_its_fix_and_trail(world, app):
    db = world
    await db.execute(text("update riders set status = 'busy' where is_sim"))
    await db.commit()
    rider = await demo_rider(db)
    async with await make_client(app) as phone:
        await login(phone, db, DEMO_RIDER)
        await phone.post("/rider/position", json=fix(12.9345, 77.6150, clock.now()))

        order = await place(db, slug="bandstand-kitchen")  # the demo customer: a demo order
        kitchen = Actor("restaurant", restaurant_id=order.restaurant_id)
        for to in (S.accepted, S.preparing, S.ready):
            order = await orders.transition(db, order.id, to, kitchen)
        await db.commit()
        assert order.rider_id == rider.id
        for to in ("picked_up", "delivered"):
            clock.advance(3)
            await phone.post("/rider/position", json=fix(12.9346, 77.6151, clock.now()))
            r = await phone.post(f"/rider/orders/{order.id}/transition", json={"to": to})
            assert r.status_code == 200, r.text
    assert await db.get(RiderPosition, rider.id, populate_existing=True) is None
    trail = (
        await db.execute(select(func.count()).where(RiderTrack.rider_id == rider.id))
    ).scalar_one()
    assert trail == 0


async def test_old_trails_are_pruned_on_the_next_demo_login(world, app, client):
    db = world

    order = await place(db)
    sim_rider = (await db.execute(select(Rider).where(Rider.is_sim).limit(1))).scalar_one()
    await db.execute(
        text(
            "insert into rider_track (order_id, rider_id, at, loc) values (:o, :r, :t,"
            " ST_SetSRID(ST_MakePoint(77.62, 12.93), 4326)::geography)"
        ),
        {"o": order.id, "r": sim_rider.id, "t": clock.now()},
    )
    await orders.transition(db, order.id, S.cancelled, Actor("customer", user_id=order.user_id))
    await db.commit()
    clock.advance(6 * 86400)
    assert (await client.post("/auth/demo", json={"as": "admin"})).status_code == 200
    count = select(func.count()).where(RiderTrack.order_id == order.id)
    assert (await db.execute(count)).scalar_one() == 1
    clock.advance(86400 + 1)
    assert (await client.post("/auth/demo", json={"as": "admin"})).status_code == 200
    assert (await db.execute(count)).scalar_one() == 0


async def test_admin_cannot_hand_an_order_to_a_phone_that_is_not_sharing(world, app):
    db = world

    order = await place(db)  # demo, waiting with no rider
    await db.execute(text("update riders set status = 'busy' where is_sim"))
    await db.commit()
    await orders.transition(
        db, order.id, S.accepted, Actor("restaurant", restaurant_id=order.restaurant_id)
    )
    await db.commit()
    rider = await demo_rider(db)  # the seed's fix is a day old
    async with await make_client(app) as c:
        await login(c, db, "admin@platter.demo")
        r = await c.post(f"/admin/orders/{order.id}/reassign", json={"rider_id": str(rider.id)})
        assert r.status_code == 409


async def test_a_future_phone_clock_cannot_freeze_the_demo_phone(world, app):
    async with await make_client(app) as phone:
        await login(phone, world, DEMO_RIDER)
        r = await phone.post(
            "/rider/position", json=fix(12.93, 77.62, clock.now().replace(year=2099))
        )
        assert r.status_code == 204
        clock.advance(31)
        r = await phone.post("/rider/position", json=fix(12.9301, 77.6201, clock.now()))
        assert "x-ignored" not in r.headers


async def test_one_visitor_cannot_break_the_shared_demo(world, app):
    async with await make_client(app) as c:
        await login(c, world, "ananya@platter.demo")
        home = (await c.get("/addresses")).json()[0]
        assert (await c.delete(f"/addresses/{home['id']}")).status_code == 409
    async with await make_client(app) as c:
        await login(c, world, "owner.bandstand-kitchen@platter.demo")
        menu = (await c.get("/restaurant/menu")).json()
        for item in (i for cat in menu["categories"] for i in cat["items"]):
            await c.patch(f"/restaurant/items/{item['id']}", json={"is_available": False})
        assert (await c.post("/auth/demo", json={"as": "restaurant"})).status_code == 200
        menu = (await c.get("/restaurant/menu")).json()
        assert all(i["is_available"] for cat in menu["categories"] for i in cat["items"])


async def test_nobody_can_sign_up_into_the_demo_domains(world, client):
    for email in ("eve@customers.platter.demo", "owner.new@platter.demo"):
        r = await client.post(
            "/auth/sign-up", json={"email": email, "password": "long enough", "name": "Eve"}
        )
        assert r.status_code == 422
