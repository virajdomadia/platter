"""Review 2026-11-27 (code + security): the event lock is never held across OSRM, payments that
can't place an order are refused loudly, rate limits, quantities after merging, the order stream's
404, the Origin check and a malformed webhook."""

import asyncio
import hashlib
import hmac
import time

import pytest
from sqlalchemy import select

from app.core import clock
from app.models import Order, OrderStatus
from app.services import orders, routing
from app.services.events import Actor
from tests.conftest import KORAMANGALA_5TH, item_ids, login, make_client, place, restaurant
from tests.test_mark_paid import fake_razorpay, signature, start, webhook  # noqa: F401

pytestmark = pytest.mark.db
S = OrderStatus


async def test_a_slow_osrm_call_does_not_block_other_transitions(world, factory, monkeypatch):
    slow = await place(world)
    other = await place(world, slug="thali-ghar")

    async def osrm(points):  # type: ignore[no-untyped-def]
        await asyncio.sleep(1.5)
        return None

    monkeypatch.setattr(routing, "fetch_osrm", osrm)

    async def accept() -> None:  # dispatch draws a leg → OSRM, inside the accept transaction
        async with factory() as db:
            kitchen = Actor("restaurant", restaurant_id=slow.restaurant_id)
            await orders.transition(db, slow.id, S.accepted, kitchen)
            await db.commit()

    async def cancel() -> float:
        await asyncio.sleep(0.3)  # the accept is now waiting on OSRM
        t0 = time.monotonic()
        async with factory() as db:
            await orders.transition(
                db, other.id, S.cancelled, Actor("customer", user_id=other.user_id)
            )
            await db.commit()
        return time.monotonic() - t0

    _, took = await asyncio.gather(accept(), cancel())
    assert took < 1.0


async def test_a_late_payment_is_refused_and_kept_for_refund(world, client):
    data = await start(world, client)
    oid, rp = data["order"]["id"], data["razorpay"]["order_id"]
    clock.advance(16 * 60)
    assert (await client.get(f"/orders/{oid}")).json()["status"] == "expired"
    r = await client.post(
        f"/orders/{oid}/verify",
        json={"razorpay_payment_id": "pay_late", "razorpay_signature": signature(rp, "pay_late")},
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "payment_late"
    order = await world.get(Order, oid, populate_existing=True)
    assert order.status == S.expired and order.razorpay_payment_id == "pay_late"


async def test_a_paid_order_cannot_be_cancelled(world, client):
    data = await start(world, client)
    oid, rp = data["order"]["id"], data["razorpay"]["order_id"]
    await client.post(
        f"/orders/{oid}/verify",
        json={"razorpay_payment_id": "pay_9", "razorpay_signature": signature(rp, "pay_9")},
    )
    r = await client.post(f"/orders/{oid}/cancel")
    assert r.status_code == 409


async def test_a_malformed_signed_webhook_is_a_400(world, client):
    body = b"not json"
    _, headers = webhook("x", "y", "evt_bad")
    headers["x-razorpay-signature"] = hmac.new(b"hook-secret", body, hashlib.sha256).hexdigest()
    r = await client.post("/webhooks/razorpay", content=body, headers=headers)
    assert r.status_code == 400


async def test_quantity_cap_applies_after_merging_lines(world, client):
    await login(client, world, "ananya@platter.demo")
    r = await restaurant(world, "dosa-camp")
    item = (await item_ids(world, r, 1))[0]
    res = await client.post(
        "/orders/quote",
        json={
            "restaurant_id": str(r.id),
            "items": [{"id": str(item), "qty": 20}] * 2,
            "address": {"lat": KORAMANGALA_5TH[0], "lng": KORAMANGALA_5TH[1]},
        },
    )
    assert res.status_code == 422


async def test_sign_in_is_rate_limited_per_email(world, client):
    for _ in range(10):
        r = await client.post(
            "/auth/sign-in", json={"email": "ananya@platter.demo", "password": "wrong"}
        )
        assert r.status_code == 401
    r = await client.post("/auth/sign-in", json={"email": "ananya@platter.demo", "password": "x"})
    assert r.status_code == 429
    clock.advance(61)
    r = await client.post("/auth/sign-in", json={"email": "ananya@platter.demo", "password": "x"})
    assert r.status_code == 401


async def test_someone_elses_order_stream_is_a_404(world, app):
    order = await place(world)
    async with await make_client(app) as c:
        await login(c, world, "ravi.kumar@customers.platter.demo")
        assert (await c.get(f"/orders/{order.id}/events")).status_code == 404


async def test_unsafe_requests_from_another_origin_are_refused(world, client):
    r = await client.post(
        "/auth/demo", json={"as": "customer"}, headers={"origin": "https://evil.example"}
    )
    assert r.status_code == 403
    ok = await client.post(
        "/auth/demo", json={"as": "admin"}, headers={"origin": "http://localhost:3000"}
    )
    assert ok.status_code == 200


async def test_rider_stream_drops_route_frames_of_a_leg_that_is_not_theirs(world):
    from app.models import OrderEvent, Rider
    from app.services import dispatch
    from app.services import stream as st

    db = world
    order = await place(db)
    order = await orders.transition(
        db, order.id, S.accepted, Actor("restaurant", restaurant_id=order.restaurant_id)
    )
    await db.commit()
    first = await db.get(Rider, order.rider_id)
    other = (
        await db.execute(select(Rider).where(Rider.is_sim, Rider.status == "available").limit(1))
    ).scalar_one()
    await dispatch.reassign(db, order.id, other.id, Actor("admin"))
    await db.commit()
    q = st._scope_filter(select(OrderEvent), st.Scope("rider", first.id))
    kinds = [e.kind for e in (await db.execute(q.order_by(OrderEvent.seq))).scalars()]
    assert kinds.count("route") == 1  # its own leg only, not the new rider's
    assert "rider_reassigned" in kinds


async def test_place_refuses_a_total_the_checkout_did_not_show(world, client):
    await login(client, world, "ananya@platter.demo")
    r = await restaurant(world, "dosa-camp")
    ids = await item_ids(world, r)
    body = {
        "restaurant_id": str(r.id),
        "items": [{"id": str(i), "qty": 1} for i in ids],
        "address": {"lat": KORAMANGALA_5TH[0], "lng": KORAMANGALA_5TH[1]},
        "address_line": "1st Cross",
    }
    shown = (await client.post("/orders/quote", json=body)).json()["total_paise"]
    res = await client.post("/orders", json={**body, "expected_total_paise": shown + 800})
    assert res.status_code == 409 and res.json()["error"]["code"] == "price_changed"
    assert res.json()["error"]["details"]["quote"]["total_paise"] == shown
    res = await client.post("/orders", json={**body, "expected_total_paise": shown})
    assert res.status_code == 201


async def test_stream_opens_are_rate_limited_per_browser(world, app):
    order = await place(world)
    async with await make_client(app) as c:
        await login(c, world, "ananya@platter.demo")
        app.state.settings.stream_lifetime_s = 0  # each stream closes at once
        codes = [(await c.get(f"/orders/{order.id}/events")).status_code for _ in range(7)]
    assert codes == [200] * 6 + [429]
