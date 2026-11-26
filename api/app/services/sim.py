"""The lazy simulation (PRD decision 3, 04 §6). There is no process: the world advances whenever
someone looks — every stream tick, every order read, every board / rider / admin read — and is
idempotent under row locks, so whoever looks first moves it and everyone else reads the result.

* **Sim riders** have no GPS: a sim's position is the point along its open leg's polyline at
  `min(1, (now − started_at) / duration_s)`. Arriving at the restaurant before `ready` waits
  there (`arrived_at`); at the drop the order is `delivered` and the rider takes the next one.
* **Kitchen autopilot**: while nobody has the restaurant's board open (`board_seen_at` older than
  30 s), its tickets run themselves — accepted after 45 s, preparing 20 s later, ready when the
  restaurant's prep time has passed since accepting. Open the board and the kitchen is yours.
* **Unpaid orders** expire after 15 minutes; **waiting orders** get any rider that became free.

Lock order is always order → leg → rider (the same as a transition's), so a stream advancing the
world can never deadlock with a restaurant tapping Ready.
"""

import datetime as dt
import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.models import LegKind, Order, OrderStatus, Restaurant, Rider, RiderLeg
from app.services import dispatch, orders, routing
from app.services.events import SYSTEM, Actor

S = OrderStatus

AUTO_ACCEPT_S = 45
AUTO_PREPARING_S = 20
BOARD_WATCHED = dt.timedelta(seconds=30)
POSITION_EVERY = dt.timedelta(seconds=3)


def position_on_leg(leg: RiderLeg, now: dt.datetime) -> tuple[tuple[float, float], int, float]:
    """((lat, lng), heading, progress 0..1) of a sim rider on `leg` at `now`."""
    points = routing.decode(leg.polyline)
    cum = routing.cumulative(points)
    elapsed = (now - leg.started_at).total_seconds()
    progress = 1.0 if leg.duration_s <= 0 else max(0.0, min(1.0, elapsed / leg.duration_s))
    p, heading = routing.point_at(points, cum, progress * cum[-1])
    return p, heading, progress


async def upsert_position(
    db: AsyncSession,
    rider_id: uuid.UUID,
    p: tuple[float, float],
    heading: int | None,
    speed_mps: float | None,
    *,
    order_id: uuid.UUID | None = None,
    client_at: dt.datetime | None = None,
) -> None:
    now = clock.now()
    params = {
        "rider": rider_id,
        "lat": p[0],
        "lng": p[1],
        "heading": heading,
        "speed": speed_mps,
        "now": now,
        "client_at": client_at,
    }
    await db.execute(
        text(
            """
            insert into rider_positions (rider_id, loc, heading, speed_mps, recorded_at, client_at)
            values (:rider, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography, :heading,
                    :speed, :now, :client_at)
            on conflict (rider_id) do update set loc = excluded.loc, heading = excluded.heading,
              speed_mps = excluded.speed_mps, recorded_at = excluded.recorded_at,
              client_at = excluded.client_at
            """
        ),
        params,
    )
    if order_id is not None:
        await db.execute(
            text(
                "insert into rider_track (order_id, rider_id, at, loc) values (:order, :rider,"
                " :now, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography)"
            ),
            {**params, "order": order_id},
        )


def _scoped(q, order_ids: list[uuid.UUID] | None, restaurant_id: uuid.UUID | None):  # type: ignore[no-untyped-def]
    if order_ids is not None:
        q = q.where(Order.id.in_(order_ids))
    if restaurant_id is not None:
        q = q.where(Order.restaurant_id == restaurant_id)
    return q


async def _try_lock_order(db: AsyncSession, order_id: uuid.UUID) -> Order | None:
    return (
        await db.execute(
            select(Order)
            .where(Order.id == order_id)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def run_kitchens(
    db: AsyncSession, order_ids: list[uuid.UUID] | None, restaurant_id: uuid.UUID | None
) -> None:
    now = clock.now()
    q = (
        select(Order.id, Order.status, Order.placed_at, Order.accepted_at, Restaurant.prep_min)
        .join(Restaurant, Restaurant.id == Order.restaurant_id)
        .where(
            Order.status.in_((S.placed, S.accepted, S.preparing)),
            (Restaurant.board_seen_at.is_(None)) | (Restaurant.board_seen_at < now - BOARD_WATCHED),
        )
    )
    for oid, status, placed_at, accepted_at, prep_min in (
        await db.execute(_scoped(q, order_ids, restaurant_id))
    ).all():
        to: OrderStatus | None = None
        when: dt.datetime | None = None
        if status == S.placed and placed_at:
            to, when = S.accepted, placed_at + dt.timedelta(seconds=AUTO_ACCEPT_S)
        elif status == S.accepted and accepted_at:
            to, when = S.preparing, accepted_at + dt.timedelta(seconds=AUTO_PREPARING_S)
        elif status == S.preparing and accepted_at:
            to, when = S.ready, accepted_at + dt.timedelta(minutes=prep_min)
        if when is not None and when > now:
            to = None
        if to is None:
            continue
        locked = await _try_lock_order(db, oid)
        # Another stream may have moved it between the read and the lock: act only on what we read.
        if locked is not None and locked.status == status:
            await orders.transition(db, oid, to, SYSTEM, at=when)


async def run_riders(
    db: AsyncSession, order_ids: list[uuid.UUID] | None, restaurant_id: uuid.UUID | None
) -> None:
    q = (
        select(RiderLeg.id, RiderLeg.order_id)
        .join(Rider, Rider.id == RiderLeg.rider_id)
        .join(Order, Order.id == RiderLeg.order_id)
        .where(RiderLeg.ended_at.is_(None), Rider.is_sim.is_(True))
    )
    for leg_id, order_id in (await db.execute(_scoped(q, order_ids, restaurant_id))).all():
        order = await _try_lock_order(db, order_id)
        if order is None:
            continue
        leg = (
            await db.execute(
                select(RiderLeg)
                .where(RiderLeg.id == leg_id, RiderLeg.ended_at.is_(None))
                .with_for_update(skip_locked=True)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if leg is None:
            continue
        rider = await db.get(Rider, leg.rider_id)
        assert rider is not None  # noqa: S101 - FK
        await _advance_leg(db, order, leg, rider)


async def _advance_leg(db: AsyncSession, order: Order, leg: RiderLeg, rider: Rider) -> None:
    now = clock.now()
    p, heading, progress = position_on_leg(leg, now)
    actor = Actor("system", rider_id=rider.id)
    speed = float(rider.speed_kmh) / 3.6
    if progress < 1:
        last = (
            await db.execute(
                text("select recorded_at from rider_positions where rider_id = :r"),
                {"r": rider.id},
            )
        ).scalar_one_or_none()
        if last is None or now - last >= POSITION_EVERY:
            await upsert_position(db, rider.id, p, heading, speed, order_id=order.id)
        return
    if leg.kind == LegKind.to_restaurant:
        if leg.arrived_at is None:
            leg.arrived_at = leg.started_at + dt.timedelta(seconds=leg.duration_s)
            await upsert_position(db, rider.id, p, heading, 0.0, order_id=order.id)
            await db.flush()
        if order.status == S.ready:
            arrived = leg.arrived_at or now
            picked = max(arrived, order.ready_at or arrived)
            await orders.transition(db, order.id, S.picked_up, actor, at=picked)
    else:
        await upsert_position(db, rider.id, p, heading, 0.0, order_id=order.id)
        arrived = leg.started_at + dt.timedelta(seconds=leg.duration_s)
        await orders.transition(db, order.id, S.delivered, actor, at=arrived)


async def run_waiting(
    db: AsyncSession, order_ids: list[uuid.UUID] | None, restaurant_id: uuid.UUID | None
) -> None:
    q = (
        select(Order)
        .where(Order.rider_id.is_(None), Order.status.in_(dispatch.WAITING))
        .order_by(Order.accepted_at)
        .with_for_update(skip_locked=True)
    )
    for order in (await db.execute(_scoped(q, order_ids, restaurant_id))).scalars().all():
        if await dispatch.assign_rider(db, order) is None:
            break  # nobody free: the rest wait too


async def advance(
    db: AsyncSession,
    *,
    order_ids: list[uuid.UUID] | None = None,
    restaurant_id: uuid.UUID | None = None,
) -> None:
    """Move the world forward for a scope (everything when both are None). The caller commits."""
    await orders.expire_stale(db, order_ids)
    await run_kitchens(db, order_ids, restaurant_id)
    await run_riders(db, order_ids, restaurant_id)
    await run_waiting(db, order_ids, restaurant_id)
