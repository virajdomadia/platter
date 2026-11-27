"""The rider uplink rules (04 §3) and the admin (R9): stale and jumping fixes are dropped; a stuck
order is flagged at the right age (fake clock); reassigning releases the old rider and draws a
new leg; riders by distance for the picker."""

import datetime as dt

import pytest
from sqlalchemy import func, select, text

from app.core import clock
from app.models import Order, OrderEvent, OrderStatus, Rider, RiderTrack
from app.services import admin, orders
from app.services.events import Actor
from tests.conftest import login, make_client, place, take_offer

pytestmark = pytest.mark.db
S = OrderStatus


def fix(lat: float, lng: float, at: dt.datetime, **extra: object) -> dict:
    return {"lat": lat, "lng": lng, "at": at.isoformat(), "heading": 90, "speed_mps": 4.2, **extra}


async def test_position_rules(world, app):
    async with await make_client(app) as c:
        await login(c, world, "rider@platter.demo")
        t0 = clock.now()
        r = await c.post("/rider/position", json=fix(12.9349, 77.6200, t0))
        assert r.status_code == 204 and "x-ignored" not in r.headers
        clock.advance(1)
        # an older phone timestamp than the last fix → dropped
        r = await c.post(
            "/rider/position", json=fix(12.9350, 77.6201, t0 - dt.timedelta(seconds=5))
        )
        assert r.headers.get("x-ignored") == "stale"
        # 300 m away one second later → a GPS jump, dropped
        r = await c.post(
            "/rider/position", json=fix(12.9376, 77.6200, t0 + dt.timedelta(seconds=1))
        )
        assert r.headers.get("x-ignored") == "jump"
        clock.advance(3)
        r = await c.post(
            "/rider/position", json=fix(12.9352, 77.6203, t0 + dt.timedelta(seconds=4))
        )
        assert r.status_code == 204 and "x-ignored" not in r.headers
        me = (await c.get("/rider/me")).json()
        assert me["last_fix_s"] == 0  # server time, not the phone's
        # a rider can't claim another rider's position: the uplink is the session's rider only
    async with await make_client(app) as anon:
        assert (await anon.post("/rider/position", json=fix(1, 1, clock.now()))).status_code == 404


async def test_fixes_on_a_job_draw_the_trail(world, app):
    db = world
    await db.execute(text("update riders set status = 'busy' where is_sim"))
    await db.commit()
    async with await make_client(app) as c:
        await login(c, db, "rider@platter.demo")
        await c.post("/rider/position", json=fix(12.9354, 77.6150, clock.now()))
        order = await place(db, slug="bandstand-kitchen")
        await orders.transition(
            db, order.id, S.accepted, Actor("restaurant", restaurant_id=order.restaurant_id)
        )
        await db.commit()
        await take_offer(db, order.id)
        for i in range(3):
            clock.advance(3)
            await c.post("/rider/position", json=fix(12.9354 + i * 0.0001, 77.6148, clock.now()))
    track = (
        await db.execute(select(func.count()).where(RiderTrack.order_id == order.id))
    ).scalar_one()
    assert track == 3
    # within 60 m of the kitchen → "at the door"
    leg_arrived = (
        await db.execute(
            text("select arrived_at from rider_legs where order_id = :o"), {"o": order.id}
        )
    ).scalar_one()
    assert leg_arrived is not None


async def test_stuck_flags_at_the_right_age(world):
    db = world
    await db.execute(
        text("update restaurants set board_seen_at = :t"),
        {"t": clock.now() + dt.timedelta(hours=1)},
    )
    await db.execute(text("update riders set status = 'busy'"))
    await db.commit()
    order = await place(db)
    clock.advance(4 * 60 + 59)
    assert admin.stuck(await db.get(Order, order.id, populate_existing=True), clock.now()) is None
    clock.advance(2)
    assert (
        admin.stuck(await db.get(Order, order.id, populate_existing=True), clock.now())
        == "unaccepted"
    )
    order = await orders.transition(
        db, order.id, S.accepted, Actor("restaurant", restaurant_id=order.restaurant_id)
    )
    await db.commit()
    assert order.rider_id is None
    clock.advance(179)
    assert admin.stuck(order, clock.now()) is None
    clock.advance(2)
    assert admin.stuck(order, clock.now()) == "no_rider"
    listed = await admin.active_orders(db, only_stuck=True)
    assert [o.stuck for o in listed] == ["no_rider"]


async def test_reassign_releases_the_old_rider_and_redraws(world, app):
    db = world
    await db.execute(
        text("update restaurants set board_seen_at = :t"),
        {"t": clock.now() + dt.timedelta(hours=1)},
    )
    await db.commit()
    order = await place(db)
    order = await orders.transition(
        db, order.id, S.accepted, Actor("restaurant", restaurant_id=order.restaurant_id)
    )
    await db.commit()
    order = await take_offer(db, order.id)
    old = order.rider_id
    async with await make_client(app) as c:
        await login(c, db, "admin@platter.demo")
        riders = (await c.get("/admin/riders?near=12.9345,77.6182")).json()
        available = [r for r in riders if r["status"] == "available"]
        assert [r["distance_m"] for r in available] == sorted(r["distance_m"] for r in available)
        target = available[-1]
        r = await c.post(f"/admin/orders/{order.id}/reassign", json={"rider_id": target["id"]})
        assert r.status_code == 200, r.text
        assert r.json()["rider_id"] == target["id"]
        assert r.json()["legs"][0]["kind"] == "to_restaurant"
        # a busy rider can't be chosen
        busy = await c.post(f"/admin/orders/{order.id}/reassign", json={"rider_id": target["id"]})
        assert busy.status_code == 409
        m = (await c.get("/admin/map")).json()
        assert any(o["id"] == str(order.id) for o in m["orders"])
        assert len(m["riders"]) == 9 and len(m["restaurants"]) == 12
    old_rider = await db.get(Rider, old, populate_existing=True)
    assert old_rider.status == "available"
    kinds = (
        (
            await db.execute(
                select(OrderEvent.kind)
                .where(OrderEvent.order_id == order.id)
                .order_by(OrderEvent.seq)
            )
        )
        .scalars()
        .all()
    )
    assert kinds[-2:] == ["rider_reassigned", "route"]


async def test_a_kitchen_running_late_is_stuck_and_the_autopilot_takes_over(world):
    from app.services import sim

    db = world
    watched = {"t": clock.now() + dt.timedelta(hours=3)}  # someone keeps the board open
    await db.execute(text("update restaurants set board_seen_at = :t"), watched)
    await db.commit()
    order = await place(db)
    kitchen = Actor("restaurant", restaurant_id=order.restaurant_id)
    order = await orders.transition(db, order.id, S.accepted, kitchen)
    await db.commit()
    await take_offer(db, order.id)
    order = await orders.transition(db, order.id, S.preparing, kitchen)
    await db.commit()
    prep = (
        await db.execute(
            text("select prep_min from restaurants where id = :r"), {"r": order.restaurant_id}
        )
    ).scalar_one()
    clock.advance(prep * 60 + 5 * 60 + 1)
    listed = await admin.active_orders(db, only_stuck=True)
    assert [o.stuck for o in listed] == ["kitchen_late"]
    await sim.advance(db)
    await db.commit()
    assert (await db.get(Order, order.id, populate_existing=True)).status == S.preparing
    clock.advance(5 * 60)
    await sim.advance(db)
    await db.commit()
    # ready (and a waiting sim rider may already have carried it on)
    assert (await db.get(Order, order.id, populate_existing=True)).ready_at is not None
