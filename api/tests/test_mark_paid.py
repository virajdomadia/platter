"""04 §12 test_mark_paid: verify-then-webhook and webhook-then-verify → exactly one `placed`;
a replayed webhook is a no-op; an unpaid order expires at 15 min and never reaches the board."""

import hashlib
import hmac
import json

import pytest
from sqlalchemy import func, select

from app.core import clock
from app.models import Order, OrderEvent
from app.services import razorpay
from tests.conftest import KORAMANGALA_5TH, item_ids, login, restaurant

pytestmark = pytest.mark.db


@pytest.fixture(autouse=True)
def fake_razorpay(monkeypatch: pytest.MonkeyPatch) -> None:
    counter = iter(range(1, 1000))

    async def create_order(settings, *, amount_paise, receipt):  # type: ignore[no-untyped-def]
        return f"order_test_{next(counter)}"

    monkeypatch.setattr(razorpay, "create_order", create_order)


async def start(world, client):  # type: ignore[no-untyped-def]
    await login(client, world, "ananya@platter.demo")
    r = await restaurant(world, "dosa-camp")
    ids = await item_ids(world, r)
    res = await client.post(
        "/orders",
        json={
            "restaurant_id": str(r.id),
            "items": [{"id": str(i), "qty": 1} for i in ids],
            "address": {"lat": KORAMANGALA_5TH[0], "lng": KORAMANGALA_5TH[1]},
            "address_line": "1st Cross",
            "payment": "razorpay",
        },
    )
    assert res.status_code == 201, res.text
    data = res.json()
    assert data["order"]["status"] == "pending_payment"
    assert data["razorpay"]["key_id"] == "rzp_test_key"
    assert data["razorpay"]["amount_paise"] == data["order"]["totals"]["total_paise"]
    return data


def signature(order_id: str, payment_id: str) -> str:
    return razorpay.payment_signature("test-secret", order_id, payment_id)


def webhook(rp_order: str, payment_id: str, event_id: str) -> tuple[bytes, dict]:
    body = json.dumps(
        {
            "event": "payment.captured",
            "payload": {"payment": {"entity": {"id": payment_id, "order_id": rp_order}}},
        }
    ).encode()
    sig = hmac.new(b"hook-secret", body, hashlib.sha256).hexdigest()
    return body, {
        "x-razorpay-signature": sig,
        "x-razorpay-event-id": event_id,
        "content-type": "application/json",
    }


async def placed_events(world, order_id: str) -> int:
    return (
        await world.execute(
            select(func.count()).where(OrderEvent.order_id == order_id, OrderEvent.kind == "placed")
        )
    ).scalar_one()


async def test_verify_then_webhook_places_once(world, client):
    data = await start(world, client)
    oid, rp = data["order"]["id"], data["razorpay"]["order_id"]
    r = await client.post(
        f"/orders/{oid}/verify",
        json={"razorpay_payment_id": "pay_1", "razorpay_signature": signature(rp, "pay_1")},
    )
    assert r.status_code == 200 and r.json()["status"] == "placed"
    body, headers = webhook(rp, "pay_1", "evt_1")
    assert (
        await client.post("/webhooks/razorpay", content=body, headers=headers)
    ).status_code == 200
    body, headers = webhook(rp, "pay_1", "evt_1")  # replay
    assert (await client.post("/webhooks/razorpay", content=body, headers=headers)).json() == {
        "status": "duplicate"
    }
    assert await placed_events(world, oid) == 1


async def test_webhook_then_verify_places_once(world, client):
    data = await start(world, client)
    oid, rp = data["order"]["id"], data["razorpay"]["order_id"]
    body, headers = webhook(rp, "pay_2", "evt_2")
    assert (
        await client.post("/webhooks/razorpay", content=body, headers=headers)
    ).status_code == 200
    r = await client.post(
        f"/orders/{oid}/verify",
        json={"razorpay_payment_id": "pay_2", "razorpay_signature": signature(rp, "pay_2")},
    )
    assert r.status_code == 200 and r.json()["status"] == "placed"
    assert await placed_events(world, oid) == 1


async def test_bad_signatures_are_refused(world, client):
    data = await start(world, client)
    oid, rp = data["order"]["id"], data["razorpay"]["order_id"]
    r = await client.post(
        f"/orders/{oid}/verify", json={"razorpay_payment_id": "pay_3", "razorpay_signature": "nope"}
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "bad_signature"
    body, headers = webhook(rp, "pay_3", "evt_3")
    headers["x-razorpay-signature"] = "0" * 64
    assert (
        await client.post("/webhooks/razorpay", content=body, headers=headers)
    ).status_code == 400
    assert await placed_events(world, oid) == 0


async def test_unpaid_orders_expire_and_never_reach_the_board(world, client):
    data = await start(world, client)
    oid = data["order"]["id"]
    owner = await world.get(Order, oid)
    # the kitchen never sees it
    board_client = client
    await login(board_client, world, "owner.dosa-camp@platter.demo")
    board = (await board_client.get("/restaurant/board")).json()
    assert all(t["id"] != oid for t in board["new"])
    clock.advance(14 * 60)
    await login(client, world, "ananya@platter.demo")
    assert (await client.get(f"/orders/{oid}")).json()["status"] == "pending_payment"
    clock.advance(61)
    assert (await client.get(f"/orders/{oid}")).json()["status"] == "expired"
    assert owner is not None
