"""04 §12 test_sim: a sim rider on a 600-m leg at 22 km/h (duration 98 s) is at the end after 98 s
(fake clock); arriving before `ready` waits; `ready` triggers pickup; delivery frees the rider
and hands it the oldest waiting order. Plus the kitchen autopilot and "no human action after
ready" (R10)."""

import datetime as dt
import uuid

import pytest
from sqlalchemy import select, text

from app.core import clock
from app.models import LegKind, Offer, Order, OrderStatus, Restaurant, Rider, RiderLeg, RouteMethod
from app.services import orders, routing, sim
from app.services.events import Actor
from tests.conftest import place, settle, take_offer

pytestmark = pytest.mark.db
S = OrderStatus


def leg_600m(order_id: uuid.UUID, rider_id: uuid.UUID) -> RiderLeg:
    start = (12.9345, 77.6182)
    end = (start[0] + 600 / 111_320, start[1])
    return RiderLeg(
        order_id=order_id,
        rider_id=rider_id,
        kind=LegKind.to_customer,
        polyline=routing.encode([start, end]),
        distance_m=600,
        duration_s=round(600 / (22 / 3.6)),
        method=RouteMethod.line,
        started_at=clock.now(),
    )


def test_position_on_a_600m_leg_at_22kmh():
    leg = leg_600m(uuid.uuid4(), uuid.uuid4())
    assert leg.duration_s == 98
    start = clock.now()
    p0, _, prog0 = sim.position_on_leg(leg, start)
    half, _, prog_half = sim.position_on_leg(leg, start + dt.timedelta(seconds=49))
    end, heading, prog_end = sim.position_on_leg(leg, start + dt.timedelta(seconds=98))
    assert prog0 == 0 and prog_half == pytest.approx(0.5) and prog_end == 1
    assert routing.haversine(p0, end) == pytest.approx(600, abs=2)
    assert routing.haversine(p0, half) == pytest.approx(300, abs=2)
    assert heading == 0  # due north
    after, _, _ = sim.position_on_leg(leg, start + dt.timedelta(seconds=500))
    assert after == end  # clamps at the drop


async def accepted_order(db, slug="dosa-camp"):  # type: ignore[no-untyped-def]
    order = await place(db, slug=slug)
    kitchen = Actor("restaurant", restaurant_id=order.restaurant_id)
    order = await orders.transition(db, order.id, S.accepted, kitchen)
    await db.commit()
    offered = select(Offer.id).where(Offer.order_id == order.id, Offer.state == "sent")
    if (await db.execute(offered)).first():
        order = await take_offer(db, order.id)
    return order, kitchen


async def open_leg(db, order_id):  # type: ignore[no-untyped-def]
    return (
        await db.execute(
            select(RiderLeg)
            .where(RiderLeg.order_id == order_id, RiderLeg.ended_at.is_(None))
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def test_sim_waits_at_the_kitchen_then_picks_up_on_ready_and_delivers(world):
    db = world
    order, kitchen = await accepted_order(db)
    # The board is open, so the autopilot leaves this kitchen alone.
    await db.execute(text("update restaurants set board_seen_at = :t"), {"t": clock.now()})
    await db.commit()
    leg = await open_leg(db, order.id)
    assert leg.kind == LegKind.to_restaurant
    rider = await db.get(Rider, order.rider_id)
    assert rider.is_sim and rider.status == "busy"
    # a sim's duration is its own speed over the distance
    assert leg.duration_s == round(leg.distance_m / (float(rider.speed_kmh) / 3.6))

    clock.advance(leg.duration_s + 1)
    await db.execute(text("update restaurants set board_seen_at = :t"), {"t": clock.now()})
    await sim.advance(db, order_ids=[order.id])
    await db.commit()
    leg = await open_leg(db, order.id)
    assert leg.kind == LegKind.to_restaurant and leg.arrived_at is not None  # waiting
    order = await db.get(Order, order.id, populate_existing=True)
    assert order.status == S.accepted

    await orders.transition(db, order.id, S.preparing, kitchen)
    order = await orders.transition(db, order.id, S.ready, kitchen)
    await db.commit()
    order = await db.get(Order, order.id, populate_existing=True)
    assert order.status == S.picked_up  # the waiting sim picked up at once
    leg = await open_leg(db, order.id)
    assert leg.kind == LegKind.to_customer

    clock.advance(leg.duration_s + 1)
    await sim.advance(db, order_ids=[order.id])
    await db.commit()
    order = await db.get(Order, order.id, populate_existing=True)
    assert order.status == S.delivered
    rider = await db.get(Rider, order.rider_id, populate_existing=True)
    assert rider.status == "available"
    assert await open_leg(db, order.id) is None


async def test_a_cod_order_is_delivered_with_no_human_action_after_ready(world):
    """The kitchen autopilot (nobody on the board) and a sim rider carry it all the way."""
    db = world
    order = await place(db)
    for _ in range(80):  # 80 × 30 s = 40 minutes of fake time
        clock.advance(30)
        await sim.advance(db, order_ids=[order.id])
        await db.commit()
        order = await db.get(Order, order.id, populate_existing=True)
        if order.status == S.delivered:
            break
    assert order.status == S.delivered
    assert order.accepted_at and order.ready_at and order.picked_up_at and order.delivered_at
    r = await db.get(Restaurant, order.restaurant_id)
    cooked = (order.ready_at - order.accepted_at).total_seconds()
    assert r.prep_min * 60 <= cooked <= r.prep_min * 60 + 30


async def test_delivery_frees_the_rider_for_the_oldest_waiting_order(world):
    db = world
    await db.execute(text("update riders set status = 'busy' where name <> 'Kiran M'"))
    await db.execute(text("update restaurants set board_seen_at = :t"), {"t": clock.now()})
    await db.commit()
    first, kitchen = await accepted_order(db)
    kiran = await db.get(Rider, first.rider_id)
    assert kiran.name == "Kiran M"
    clock.advance(5)
    second, _ = await accepted_order(db, slug="dosa-camp")
    assert second.rider_id is None  # nobody free: "Finding a rider"

    await orders.transition(db, first.id, S.preparing, kitchen)
    await orders.transition(db, first.id, S.ready, kitchen)
    await db.commit()
    for _ in range(60):
        clock.advance(20)
        await db.execute(text("update restaurants set board_seen_at = :t"), {"t": clock.now()})
        await sim.advance(db, order_ids=[first.id])
        await db.commit()
        if (await db.get(Order, first.id, populate_existing=True)).status == S.delivered:
            break
    await settle(db)  # the freed rider is offered the waiting order and takes it
    second = await db.get(Order, second.id, populate_existing=True)
    assert second.rider_id == kiran.id  # taken the moment Kiran was free
    leg = await open_leg(db, second.id)
    assert leg is not None and leg.kind == LegKind.to_restaurant


async def test_two_streams_advancing_at_once_move_a_sim_once(world, factory):
    import asyncio

    db = world
    order = await place(db)
    for _ in range(90):
        clock.advance(30)

        async def tick() -> None:
            async with factory() as s2:
                await sim.advance(s2, order_ids=[order.id])
                await s2.commit()

        await asyncio.gather(tick(), tick())
        if (await db.get(Order, order.id, populate_existing=True)).status == S.delivered:
            break
    kinds = (
        (
            await db.execute(
                text("select kind from order_events where order_id = :o order by seq"),
                {"o": order.id},
            )
        )
        .scalars()
        .all()
    )
    statuses = [k for k in kinds if k not in ("route", "rider_assigned") and "offer" not in k]
    assert statuses == ["placed", "accepted", "preparing", "ready", "picked_up", "delivered"]
    assert kinds.count("route") == 2


async def test_catching_up_stamps_each_step_when_it_really_happened(world):
    """Nobody looked for two hours: one advance replays the whole order with its true times."""
    db = world
    order = await place(db)
    placed = order.placed_at
    clock.advance(2 * 3600)
    for _ in range(6):  # each look moves it at least one step
        await sim.advance(db, order_ids=[order.id])
        await db.commit()
    order = await db.get(Order, order.id, populate_existing=True)
    assert order.status == S.delivered
    r = await db.get(Restaurant, order.restaurant_id)
    assert (order.accepted_at - placed).total_seconds() == sim.AUTO_ACCEPT_S
    assert (order.ready_at - order.accepted_at).total_seconds() == r.prep_min * 60
    assert order.picked_up_at >= order.ready_at
    # delivered when the rider reached the door — not two hours later when someone looked
    assert (order.delivered_at - placed).total_seconds() < 60 * 60
    assert order.delivered_at < clock.now()
