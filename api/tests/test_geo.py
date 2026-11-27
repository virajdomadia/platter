"""04 §12 test_geo: restaurants by distance, the 5 km / 8 km boundaries, nearest-rider KNN, and
`skip locked` never double-booking a rider under concurrent accepts."""

import asyncio

import pytest
from sqlalchemy import select, text

from app.models import Offer, Order, OrderStatus, Rider
from app.services import dispatch, geo, orders, routing
from app.services.events import Actor
from tests.conftest import KORAMANGALA_5TH, place, restaurant

pytestmark = pytest.mark.db


async def test_koramangala_5th_block_sees_9_orderable_and_3_too_far(world):
    cards = await geo.nearby(world, *KORAMANGALA_5TH)
    assert len(cards) == 12
    orderable = [c for c in cards if c.orderable]
    too_far = [c for c in cards if c.reason == "too_far"]
    assert len(orderable) == 9
    assert {c.slug for c in too_far} == {"tapri-tales", "punjabi-rasoi", "pav-bhaji-corner"}
    # sorted by distance within each group, and distances agree with PostGIS
    assert [c.distance_m for c in orderable] == sorted(c.distance_m for c in orderable)
    assert all(5000 < c.distance_m <= 8000 for c in too_far)
    for c in cards:
        exact = (
            await world.execute(
                text(
                    "select ST_Distance(loc, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography)"
                    " from restaurants where slug = :s"
                ),
                {"lat": KORAMANGALA_5TH[0], "lng": KORAMANGALA_5TH[1], "s": c.slug},
            )
        ).scalar_one()
        assert abs(exact - c.distance_m) <= 1
        # and with a plain haversine, to 0.5 %
        assert abs(routing.haversine(KORAMANGALA_5TH, (c.lat, c.lng)) - exact) / exact < 0.005


async def test_radius_boundaries(world):
    r = await restaurant(world, "dosa-camp")
    lat, lng = 12.9345, 77.6182
    deg = 1 / 111_320  # metres → degrees of latitude
    for metres, shown, orderable in (
        (4950, True, True),
        (5050, True, False),
        (7950, True, False),
        (8050, False, False),
    ):
        cards = {c.slug: c for c in await geo.nearby(world, lat + metres * deg, lng)}
        assert ("dosa-camp" in cards) is shown, metres
        if shown:
            assert cards["dosa-camp"].orderable is orderable, metres
    assert r is not None


async def test_closed_restaurants_are_shown_with_their_hours(world):
    import datetime as dt

    from app.core import clock

    clock.set_fake(dt.datetime(2026, 11, 25, 12, 0, tzinfo=dt.UTC))  # 17:30 IST
    cards = {c.slug: c for c in await geo.nearby(world, *KORAMANGALA_5TH)}
    assert cards["thali-ghar"].orderable is False
    assert cards["thali-ghar"].reason == "closed"
    assert cards["thali-ghar"].opens == "Opens at 19:00"
    assert cards["bandstand-kitchen"].orderable is True


def nearest_sim(point: tuple[float, float]) -> str:
    from app.seed.seed import AREA

    return min(AREA["riders"], key=lambda r: routing.haversine(point, (r["lat"], r["lng"])))["name"]


async def test_nearest_available_rider_is_a_knn(world):
    for slug in ("dosa-camp", "momo-junction", "burger-barn"):
        r = await restaurant(world, slug)
        found = await dispatch.nearest_available_rider(
            world, Order(restaurant_id=r.id, is_demo=True)
        )
        lat, lng = await geo_point(world, r.id)
        # The demo rider is parked nearby too, but isn't sharing a location: never dispatched.
        assert found is not None and found.name == nearest_sim((lat, lng)), slug
        await world.rollback()


async def geo_point(db, restaurant_id):  # type: ignore[no-untyped-def]
    row = (
        await db.execute(
            text("select ST_Y(loc::geometry), ST_X(loc::geometry) from restaurants where id = :i"),
            {"i": restaurant_id},
        )
    ).one()
    return float(row[0]), float(row[1])


async def test_a_real_rider_sharing_location_is_dispatched(world):
    from app.services import sim

    divya = (await world.execute(select(Rider).where(Rider.name == "Divya S"))).scalar_one()
    await sim.upsert_position(world, divya.id, (12.9346, 77.6183), 0, 1.0)  # at Dosa Camp's door
    await world.commit()
    dosa = (await restaurant(world, "dosa-camp")).id
    found = await dispatch.nearest_available_rider(world, Order(restaurant_id=dosa, is_demo=True))
    assert found.name == "Divya S"
    # The demo phone is public: a real customer's order never goes to it (review H1).
    found = await dispatch.nearest_available_rider(world, Order(restaurant_id=dosa, is_demo=False))
    assert found.name != "Divya S" and found.is_sim


async def test_skip_locked_never_double_books(world, factory):
    # Only one sim rider free.
    await world.execute(text("update riders set status = 'busy' where name <> 'Kiran M'"))
    await world.commit()
    a = await place(world)
    b = await place(world, email="priya.sharma@customers.platter.demo")
    kitchen = Actor("restaurant", restaurant_id=a.restaurant_id)

    async def accept(order_id):  # type: ignore[no-untyped-def]
        async with factory() as db:
            await orders.transition(db, order_id, OrderStatus.accepted, kitchen)
            await db.commit()

    await asyncio.gather(accept(a.id), accept(b.id))
    async with factory() as db:
        offered = (
            (await db.execute(select(Offer.rider_id).where(Offer.order_id.in_([a.id, b.id]))))
            .scalars()
            .all()
        )
    assert len(offered) == 1  # Kiran was asked once, never for both at the same time
