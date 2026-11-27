"""04 Â§12 test_transitions + R4: every allowed edge succeeds for its actor and 409s for every other
actor; illegal jumps 409; two concurrent accepts produce one `accepted` event."""

import asyncio

import pytest
from sqlalchemy import func, select

from app.core.errors import ApiError
from app.models import Order, OrderEvent, OrderStatus, Rider
from app.services import orders
from app.services.events import SYSTEM, Actor
from tests.conftest import place, restaurant, settle, user

pytestmark = pytest.mark.db
S = OrderStatus


async def actors(db, order: Order) -> dict[str, Actor]:
    own = await restaurant(db, "dosa-camp")
    other = await restaurant(db, "biryani-bhatti")
    stranger = await user(db, "ravi.kumar@customers.platter.demo")
    rider = await db.get(Rider, order.rider_id) if order.rider_id else None
    other_rider = (
        await db.execute(select(Rider).where(Rider.id != order.rider_id).limit(1))
    ).scalar_one()
    return {
        "owner": Actor("customer", user_id=order.user_id),
        "stranger": Actor("customer", user_id=stranger.id),
        "kitchen": Actor("restaurant", restaurant_id=own.id),
        "other_kitchen": Actor("restaurant", restaurant_id=other.id),
        "rider": Actor("rider", rider_id=rider.id)
        if rider
        else Actor("rider", rider_id=other_rider.id),
        "other_rider": Actor("rider", rider_id=other_rider.id),
        "admin": Actor("admin"),
    }


async def refused(db, order_id, to, actor) -> bool:
    try:
        await orders.transition(db, order_id, to, actor)
    except ApiError as exc:
        await db.rollback()
        assert exc.status == 409 and exc.code == "illegal_transition"
        assert exc.details == {"from": exc.details["from"], "to": str(to)}
        return True
    await db.rollback()
    return False


async def test_the_happy_path_each_step_by_its_own_actor(world):
    db = world
    order = await place(db)
    assert order.status == S.placed
    a = await actors(db, order)
    for to, who in (
        (S.accepted, "kitchen"),
        (S.preparing, "kitchen"),
        (S.ready, "kitchen"),
    ):
        order = await orders.transition(db, order.id, to, a[who])
        await db.commit()
        if to == S.accepted:
            await settle(db, [order.id])  # the offered sim takes it
            order = await db.get(Order, order.id, populate_existing=True)
        assert order.status == to
        assert getattr(order, f"{to}_at") is not None
    assert order.rider_id is not None  # dispatched on accept
    a = await actors(db, order)
    order = await orders.transition(db, order.id, S.picked_up, a["rider"])
    order = await orders.transition(db, order.id, S.delivered, a["rider"])
    await db.commit()
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
    statuses = [
        k for k in kinds if k not in ("rider_assigned", "route", "offer_sent", "offer_accepted")
    ]
    assert statuses == ["placed", "accepted", "preparing", "ready", "picked_up", "delivered"]
    rider = await db.get(Rider, order.rider_id, populate_existing=True)
    assert rider.status == "available"


async def test_every_other_actor_is_refused_on_every_edge(world):
    db = world
    order = await place(db)
    oid = order.id
    a = await actors(db, order)
    # placed â†’ accepted: only the restaurant that owns the order (or the kitchen autopilot)
    for who in ("owner", "stranger", "other_kitchen", "rider", "admin"):
        assert await refused(db, oid, S.accepted, a[who]), who
    # placed â†’ cancelled: only the customer who placed it
    for who in ("stranger", "kitchen", "rider", "admin"):
        assert await refused(db, oid, S.cancelled, a[who]), who
    # placed â†’ rejected: only the owning restaurant (the autopilot never rejects)
    for who in ("owner", "other_kitchen", "rider", "admin"):
        assert await refused(db, oid, S.rejected, a[who]), who
    assert await refused(db, oid, S.rejected, SYSTEM)

    await orders.transition(db, oid, S.accepted, a["kitchen"])
    await db.commit()
    await settle(db, [oid])
    await orders.transition(db, oid, S.preparing, a["kitchen"])
    order = await orders.transition(db, oid, S.ready, a["kitchen"])
    await db.commit()
    a = await actors(db, order)
    # ready â†’ picked_up: only the assigned rider â€” a customer, the restaurant, another rider: no
    for who in ("owner", "kitchen", "other_rider", "admin"):
        assert await refused(db, oid, S.picked_up, a[who]), who
    await orders.transition(db, oid, S.picked_up, a["rider"])
    await db.commit()
    # a restaurant cannot mark delivered
    for who in ("owner", "kitchen", "other_rider", "admin"):
        assert await refused(db, oid, S.delivered, a[who]), who


async def test_illegal_jumps(world):
    db = world
    order = await place(db)
    oid = order.id
    a = await actors(db, order)
    assert await refused(db, oid, S.ready, a["kitchen"])  # placed â†’ ready
    assert await refused(db, oid, S.delivered, a["kitchen"])
    await orders.transition(db, oid, S.accepted, a["kitchen"])
    order = await orders.transition(db, oid, S.preparing, a["kitchen"])
    await db.commit()
    assert await refused(db, oid, S.delivered, a["kitchen"])  # preparing â†’ delivered
    a = await actors(db, await db.get(Order, oid))
    assert await refused(db, oid, S.picked_up, a["rider"])  # picked up before ready
    assert await refused(db, oid, S.cancelled, a["owner"])  # cancel only while placed
    assert await refused(db, oid, S.accepted, a["kitchen"])  # no going back


async def test_a_customer_cancels_only_while_placed(world):
    db = world
    order = await place(db)
    order = await orders.transition(
        db, order.id, S.cancelled, Actor("customer", user_id=order.user_id)
    )
    await db.commit()
    assert order.status == S.cancelled and order.cancelled_at is not None


async def test_rejecting_keeps_the_reason(world):
    db = world
    order = await place(db)
    kitchen = Actor("restaurant", restaurant_id=order.restaurant_id)
    order = await orders.transition(db, order.id, S.rejected, kitchen, reason="Out of dosa batter")
    await db.commit()
    assert order.reject_reason == "Out of dosa batter"
    ev = (await db.execute(select(OrderEvent).where(OrderEvent.kind == "rejected"))).scalar_one()
    assert ev.payload["reason"] == "Out of dosa batter"


async def test_concurrent_accepts_produce_one_event(world, factory):
    order = await place(world)
    kitchen = Actor("restaurant", restaurant_id=order.restaurant_id)

    async def accept() -> str:
        async with factory() as db:
            try:
                await orders.transition(db, order.id, S.accepted, kitchen)
                await db.commit()
                return "ok"
            except ApiError as exc:
                await db.rollback()
                return exc.code

    results = await asyncio.gather(accept(), accept(), accept())
    assert sorted(results) == ["illegal_transition", "illegal_transition", "ok"]
    async with factory() as db:
        await settle(db, [order.id])
        accepted = (
            await db.execute(
                select(func.count()).where(
                    OrderEvent.order_id == order.id, OrderEvent.kind == "accepted"
                )
            )
        ).scalar_one()
        assigned = (
            await db.execute(
                select(func.count()).where(
                    OrderEvent.order_id == order.id, OrderEvent.kind == "rider_assigned"
                )
            )
        ).scalar_one()
    assert accepted == 1
    assert assigned == 1


async def test_event_seq_is_commit_ordered(world):
    db = world
    first = await place(db)
    second = await place(db, slug="thali-ghar")
    seqs = (
        await db.execute(select(OrderEvent.seq, OrderEvent.order_id).order_by(OrderEvent.seq))
    ).all()
    assert [s[1] for s in seqs] == [first.id, second.id]
