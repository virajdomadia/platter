"""v2 L2: Web Push. Who hears what, the demo wall (a demo visitor never notifies a real person, a
real order never reaches the public demo board / phone), no free text on a lock screen, a push
service that fails never fails the order action, dead endpoints go, and a subscription lives and
dies with its browser session."""

import json

import pytest
from sqlalchemy import func, select, text

from app.models import OrderStatus, PushSubscription
from app.services import orders, push
from app.services.events import Actor
from tests.conftest import login, make_client, place, take_offer

pytestmark = pytest.mark.db
S = OrderStatus
DEMO_CUSTOMER = "ananya@platter.demo"
BOARD = "owner.bandstand-kitchen@platter.demo"


def sub(n: int) -> dict:
    return {
        "endpoint": f"https://fcm.googleapis.com/fcm/send/device-{n}",
        "keys": {"p256dh": "B" + "x" * 86, "auth": "a" * 22},
    }


class Sent(list):
    """What was sent, as (endpoint, payload); `status` scripts a push service's answer."""

    status: dict[str, int]


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """Push switched on, with the network replaced by a recorder."""
    from app.core.config import get_settings

    monkeypatch.setenv("VAPID_PUBLIC_KEY", "BPublicKeyForTests")
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "private-key-for-tests")
    get_settings.cache_clear()
    out = Sent()
    out.status = {}

    async def deliver(m: push.Message) -> int:
        out.append((m.endpoint, json.loads(m.payload)))
        if out.status.get(m.endpoint) == -1:
            raise RuntimeError("push service down")
        return out.status.get(m.endpoint, 201)

    monkeypatch.setattr(push, "deliver", deliver)
    yield out
    get_settings.cache_clear()


async def subscribe(app, db, email: str, n: int):  # type: ignore[no-untyped-def]
    c = await make_client(app)
    await login(c, db, email)
    r = await c.post("/push/subscribe", json=sub(n))
    assert r.status_code == 204, r.text
    return c


async def test_the_customer_hears_accepted_and_picked_up_after_commit(sent, world, app):
    db = world
    c = await subscribe(app, db, DEMO_CUSTOMER, 1)
    order = await place(db, slug="bandstand-kitchen")
    async with await make_client(app) as board:
        await login(board, db, BOARD)
        r = await board.post(f"/restaurant/orders/{order.id}/transition", json={"to": "accepted"})
        assert r.status_code == 200
    assert [p["title"] for _, p in sent] == ["Bandstand Kitchen accepted your order"]
    assert sent[0][1]["url"] == f"/orders/{order.id}"
    await c.aclose()


async def test_a_reject_reason_typed_on_the_public_board_never_reaches_a_lock_screen(
    sent, world, app
):
    db = world
    await subscribe(app, db, DEMO_CUSTOMER, 1)
    order = await place(db, slug="bandstand-kitchen")
    async with await make_client(app) as board:
        await login(board, db, BOARD)
        r = await board.post(
            f"/restaurant/orders/{order.id}/transition",
            json={"to": "rejected", "reason": "visit evil.example for a refund"},
        )
        assert r.status_code == 200
    assert len(sent) == 1 and "evil" not in json.dumps(sent[0][1])


async def test_a_real_order_never_notifies_the_public_demo_board(sent, world, app):
    from tests.test_demo_isolation import real_order

    db = world
    await subscribe(app, db, BOARD, 7)  # a visitor turned on notifications on the demo board
    await real_order(app, db)  # a real customer orders at the demo restaurant
    assert sent == []
    await place(db, slug="bandstand-kitchen")  # a demo order: the board does hear that one
    await push.drain(db)
    assert [e for e, _ in sent] == ["https://fcm.googleapis.com/fcm/send/device-7"]


async def test_a_demo_visitor_never_notifies_a_real_customer(sent, world, app):
    from tests.test_demo_isolation import real_order

    db = world
    order = await real_order(app, db)
    real = await db.get(type(order), order.id)
    async with await make_client(app) as c:
        # the real customer subscribes from their own browser
        r = await c.post(
            "/auth/sign-in", json={"email": "priya@example.com", "password": "correct horse"}
        )
        assert r.status_code == 200
        assert (await c.post("/push/subscribe", json=sub(9))).status_code == 204
    # Every demo role tries to touch the real order: all refused, nothing sent.
    for email, path, body in (
        (BOARD, f"/restaurant/orders/{order.id}/transition", {"to": "rejected"}),
        ("admin@platter.demo", f"/admin/orders/{order.id}/reassign", {"rider_id": str(order.id)}),
        ("rider@platter.demo", f"/rider/orders/{order.id}/transition", {"to": "picked_up"}),
    ):
        async with await make_client(app) as demo:
            await login(demo, db, email)
            assert (await demo.post(path, json=body)).status_code == 404
    assert sent == []
    # The platform itself (the kitchen autopilot) accepting does notify the real customer.
    await orders.transition(db, real.id, S.accepted, Actor("system"))  # type: ignore[union-attr]
    await db.commit()
    await push.drain(db)
    assert [e for e, _ in sent] == ["https://fcm.googleapis.com/fcm/send/device-9"]


async def test_the_rider_hears_the_offer_and_the_board_hears_a_new_order(sent, world, app):
    from tests.test_offers import accept_at_kitchen, only_the_demo_phone_is_free

    db = world
    await only_the_demo_phone_is_free(db)
    await subscribe(app, db, "rider@platter.demo", 3)
    await subscribe(app, db, BOARD, 4)
    order = await accept_at_kitchen(db)  # placed (board) then offered (rider)
    await push.drain(db)
    titles = {e.rsplit("-", 1)[1]: p["title"] for e, p in sent}
    assert titles["3"] == "New job offer"
    assert any(p["title"] == f"New order {order.number}" for _, p in sent)
    sent.clear()
    await take_offer(db, order.id)
    await push.drain(db)
    assert [p["title"] for _, p in sent] == ["New job"]


async def test_a_failing_push_service_never_fails_the_order_action(sent, world, app):
    db = world
    await subscribe(app, db, DEMO_CUSTOMER, 1)
    sent.status[sub(1)["endpoint"]] = -1
    order = await place(db, slug="bandstand-kitchen")
    async with await make_client(app) as board:
        await login(board, db, BOARD)
        r = await board.post(f"/restaurant/orders/{order.id}/transition", json={"to": "accepted"})
    assert r.status_code == 200
    status = await db.execute(text("select status from orders where id = :o"), {"o": order.id})
    assert status.scalar_one() == "accepted"


async def test_a_dead_endpoint_is_removed(sent, world, app):
    db = world
    await subscribe(app, db, DEMO_CUSTOMER, 1)
    sent.status[sub(1)["endpoint"]] = 410
    order = await place(db, slug="bandstand-kitchen")
    await orders.transition(db, order.id, S.accepted, Actor("system"))
    await db.commit()
    await push.drain(db)
    assert len(sent) == 1
    count = select(func.count()).select_from(PushSubscription)
    assert (await db.execute(count)).scalar_one() == 0


async def test_a_subscription_goes_with_its_session(sent, world, app):
    db = world
    c = await subscribe(app, db, DEMO_CUSTOMER, 1)
    assert (await c.post("/auth/sign-out")).status_code == 204
    count = select(func.count()).select_from(PushSubscription)
    assert (await db.execute(count)).scalar_one() == 0
    await c.aclose()


async def test_only_browser_push_services_can_be_subscribed(sent, world, app):
    async with await make_client(app) as c:
        await login(c, world, DEMO_CUSTOMER)
        for endpoint in (
            "http://fcm.googleapis.com/fcm/send/x",  # not https
            "https://169.254.169.254/latest/meta-data",  # internal address (SSRF)
            "https://fcm.googleapis.com.evil.example/x",
            "https://fcm.googleapis.com:8443/x",
        ):
            body = {**sub(1), "endpoint": endpoint}
            r = await c.post("/push/subscribe", json=body)
            assert r.status_code == 422, endpoint
        assert (await c.post("/push/subscribe", json=sub(1))).status_code == 204
        assert (await c.get("/push/key")).json() == {"key": "BPublicKeyForTests"}


async def test_push_is_off_without_keys(world, client):
    assert (await client.get("/push/key")).json() == {"key": None}
