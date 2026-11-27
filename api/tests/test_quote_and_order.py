"""04 §12 test_quote_and_order + R3: the order total equals the quote; client prices are never read;
unavailable items 422; the radius is straight-line (5.1 km → 422) while the fee is the road
distance (4.9 km straight / 6.2 km by road → accepted with the road fee); fee steps."""

import pytest
from sqlalchemy import update

from app.models import MenuItem
from app.services import orders, routing
from tests.conftest import KORAMANGALA_5TH, item_ids, login, restaurant

pytestmark = pytest.mark.db

DEG = 1 / 111_320


@pytest.mark.parametrize(
    ("km", "rupees"),
    [(1.9, 25), (2.0, 25), (2.1, 33), (3.0, 33), (4.0, 41), (4.01, 49), (6.2, 65)],
)
def test_fee_steps(km, rupees):
    assert orders.delivery_fee_paise(round(km * 1000)) == rupees * 100


async def body(db, slug="dosa-camp", drop=KORAMANGALA_5TH, qty=1):  # type: ignore[no-untyped-def]
    r = await restaurant(db, slug)
    ids = await item_ids(db, r)
    return {
        "restaurant_id": str(r.id),
        "items": [{"id": str(i), "qty": qty} for i in ids],
        "address": {"lat": drop[0], "lng": drop[1]},
    }


async def test_order_total_equals_quote_and_ignores_client_prices(world, client):
    await login(client, world, "ananya@platter.demo")
    b = await body(world, qty=2)
    quote = (await client.post("/orders/quote", json=b)).json()
    tampered = {
        **b,
        "items": [{**i, "price_paise": 1} for i in b["items"]],
        "total_paise": 100,
        "address_line": "1st Cross, Koramangala 5th Block",
        "payment": "cod",
    }
    r = await client.post("/orders", json=tampered)
    assert r.status_code == 201, r.text
    order = r.json()["order"]
    assert order["status"] == "placed"
    assert order["number"].startswith("PL-")
    assert order["totals"]["total_paise"] == quote["total_paise"]
    assert order["totals"]["subtotal_paise"] == quote["subtotal_paise"] > 100
    assert quote["platform_fee_paise"] == 500
    assert quote["total_paise"] == quote["subtotal_paise"] + quote["delivery_fee_paise"] + 500


async def test_unavailable_item_is_refused(world, client):
    await login(client, world, "ananya@platter.demo")
    b = await body(world)
    await world.execute(
        update(MenuItem).where(MenuItem.id == b["items"][0]["id"]).values(is_available=False)
    )
    await world.commit()
    r = await client.post("/orders/quote", json=b)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "item_unavailable"
    assert r.json()["error"]["details"]["ids"] == [b["items"][0]["id"]]
    r = await client.post("/orders", json={**b, "address_line": "somewhere", "payment": "cod"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "item_unavailable"


async def test_an_item_from_another_restaurant_is_refused(world, client):
    await login(client, world, "ananya@platter.demo")
    b = await body(world)
    other = await item_ids(world, await restaurant(world, "biryani-bhatti"), 1)
    b["items"].append({"id": str(other[0]), "qty": 1})
    r = await client.post("/orders/quote", json=b)
    assert r.status_code == 422 and r.json()["error"]["code"] == "item_unavailable"


async def test_out_of_range_is_straight_line(world, client, monkeypatch):
    await login(client, world, "ananya@platter.demo")
    dosa = (12.9345, 77.6182)
    far = (dosa[0] + 5100 * DEG, dosa[1])
    r = await client.post("/orders/quote", json=await body(world, drop=far))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "out_of_range"

    # 4.9 km straight but 6.2 km by road: accepted, and the fee is the road's.
    near = (dosa[0] + 4900 * DEG, dosa[1])

    async def road(points):  # type: ignore[no-untyped-def]
        return {"geometry": routing.encode(points), "distance": 6200.0, "duration": 900.0}

    monkeypatch.setattr(routing, "fetch_osrm", road)
    r = await client.post("/orders/quote", json=await body(world, drop=near))
    assert r.status_code == 200, r.text
    q = r.json()
    assert q["distance_m"] == 6200
    assert q["method"] == "osrm"
    assert q["delivery_fee_paise"] == 2500 + 800 * 5


async def test_line_fallback_when_osrm_is_down(world, client):
    await login(client, world, "ananya@platter.demo")
    q = (await client.post("/orders/quote", json=await body(world))).json()
    straight = routing.haversine((12.9345, 77.6182), KORAMANGALA_5TH)
    assert q["method"] == "line"
    assert abs(q["distance_m"] - straight * 1.3) <= 1


async def test_closed_restaurant_is_refused(world, client):
    import datetime as dt

    from app.core import clock

    await login(client, world, "ananya@platter.demo")
    clock.set_fake(dt.datetime(2026, 11, 25, 12, 0, tzinfo=dt.UTC))  # 17:30 IST
    r = await client.post("/orders/quote", json=await body(world, slug="thali-ghar"))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "restaurant_closed"
    assert r.json()["error"]["details"]["opens"] == "Opens at 19:00"


async def test_quote_needs_a_session(world, client):
    r = await client.post("/orders/quote", json=await body(world))
    assert r.status_code == 401
