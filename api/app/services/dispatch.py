"""Dispatch (04 §6, v1): the nearest available rider the moment a restaurant accepts.

`assign_rider` runs inside the accept transaction: one KNN (`loc <-> restaurant`) over the GIST
index, `for update of r skip locked`, so two concurrent accepts never take the same rider. No
rider free → the order waits with `rider_id null` ("Finding a rider"); `on_rider_available` gives
a freed rider the oldest waiting order. A real (non-sim) rider is only dispatched while they are
sharing their location (a fix in the last 2 minutes) — a phone that isn't sending GPS can't ride.
The only real rider is the public demo phone, so it only ever carries demo orders (`is_demo`): a
real customer's address never reaches a stranger's screen.
"""

import datetime as dt
import uuid

from sqlalchemy import select, text, true, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.errors import ApiError
from app.models import (
    LegKind,
    Order,
    OrderStatus,
    Restaurant,
    Rider,
    RiderLeg,
    RiderPosition,
    RiderStatus,
)
from app.models.geo import latlng
from app.services import events, routing
from app.services.events import Actor

LIVE_FIX = dt.timedelta(minutes=2)
TRAIL_DAYS = 7
WAITING = (OrderStatus.accepted, OrderStatus.preparing, OrderStatus.ready)


def mask_phone(phone: str) -> str:
    digits = phone.replace(" ", "")
    return f"{digits[:3]} ••••• {digits[-3:]}" if len(digits) >= 6 else "•••"


def rider_payload(rider: Rider) -> dict:
    return {
        "rider_id": str(rider.id),
        "name": rider.name,
        "vehicle": rider.vehicle,
        "phone_masked": mask_phone(rider.phone),
    }


async def position_of(db: AsyncSession, rider_id: uuid.UUID) -> tuple[float, float] | None:
    pos = await db.get(RiderPosition, rider_id)
    return latlng(pos.loc) if pos else None


async def restaurant_point(db: AsyncSession, restaurant_id: uuid.UUID) -> tuple[float, float]:
    r = await db.get(Restaurant, restaurant_id)
    assert r is not None  # noqa: S101 - FK
    return latlng(r.loc)


async def nearest_available_rider(db: AsyncSession, order: Order) -> Rider | None:
    rider_id = (
        await db.execute(
            text(
                """
                select r.id from riders r join rider_positions p on p.rider_id = r.id
                where r.status = 'available'
                  and (r.is_sim or (:demo and p.recorded_at > :fresh))
                order by p.loc <-> (select loc from restaurants where id = :restaurant)
                limit 1
                for update of r skip locked
                """
            ),
            {
                "restaurant": order.restaurant_id,
                "demo": order.is_demo,
                "fresh": clock.now() - LIVE_FIX,
            },
        )
    ).scalar_one_or_none()
    return await db.get(Rider, rider_id) if rider_id else None


async def open_leg(
    db: AsyncSession,
    order: Order,
    rider: Rider,
    kind: LegKind,
    start: tuple[float, float],
    end: tuple[float, float],
    started_at: dt.datetime | None = None,
) -> RiderLeg:
    """One OSRM route per leg (straight line × 1.3 if OSRM fails), cached on the row. A sim
    rider's duration is its own speed over the route distance (04 §4)."""
    found = await routing.route(start, end)
    duration = found.duration_s
    if rider.is_sim:
        duration = max(1, round(found.distance_m / (float(rider.speed_kmh) / 3.6)))
    leg = RiderLeg(
        order_id=order.id,
        rider_id=rider.id,
        kind=kind,
        polyline=found.polyline,
        distance_m=found.distance_m,
        duration_s=duration,
        method=found.method,
        started_at=started_at or clock.now(),
    )
    db.add(leg)
    await db.flush()
    await events.append(db, order.id, "route", events.SYSTEM, route_payload(leg), at=leg.started_at)
    return leg


def route_payload(leg: RiderLeg) -> dict:
    return {
        "leg_id": str(leg.id),
        "kind": str(leg.kind),
        "polyline": leg.polyline,
        "distance_m": leg.distance_m,
        "duration_s": leg.duration_s,
        "method": str(leg.method),
        "started_at": leg.started_at.isoformat(),
    }


async def _attach(
    db: AsyncSession,
    order: Order,
    rider: Rider,
    kind: str,
    extra: dict | None = None,
    started_at: dt.datetime | None = None,
) -> RiderLeg:
    rider.status = RiderStatus.busy
    order.rider_id = rider.id
    await db.flush()
    await events.append(
        db, order.id, kind, events.SYSTEM, {**rider_payload(rider), **(extra or {})}
    )
    start = await position_of(db, rider.id) or await restaurant_point(db, order.restaurant_id)
    end = await restaurant_point(db, order.restaurant_id)
    return await open_leg(db, order, rider, LegKind.to_restaurant, start, end, started_at)


async def assign_rider(
    db: AsyncSession,
    order: Order,
    rider: Rider | None = None,
    started_at: dt.datetime | None = None,
) -> Rider | None:
    """Inside the caller's transaction, with `order` already locked. `started_at`: the moment the
    accept happened when the simulation is catching up (the rider set off then)."""
    if order.rider_id is not None:
        return None
    rider = rider or await nearest_available_rider(db, order)
    if rider is None:
        return None
    await _attach(db, order, rider, "rider_assigned", started_at=started_at)
    return rider


async def release_rider(db: AsyncSession, rider: Rider) -> None:
    await db.execute(
        update(RiderLeg)
        .where(RiderLeg.rider_id == rider.id, RiderLeg.ended_at.is_(None))
        .values(ended_at=clock.now())
    )
    rider.status = RiderStatus.available
    await forget_rider(db, rider.user_id)
    await db.flush()


async def forget_rider(db: AsyncSession, user_id: uuid.UUID) -> None:
    """A real phone's last fix and its trail go when its job or its session ends (05 §7). Sims
    have no GPS, so theirs stay."""
    for table in ("rider_positions", "rider_track"):
        await db.execute(
            text(
                f"delete from {table} where rider_id in"  # noqa: S608 - fixed table names
                " (select id from riders where user_id = :u and not is_sim)"
            ),
            {"u": user_id},
        )


async def prune(db: AsyncSession, days: int = TRAIL_DAYS) -> int:
    """Lazy retention, run on every demo login (nothing can read these rows without one) and by
    `scripts/prune_track`: a real rider's fix once it is no longer live, trails of orders closed
    more than `days` ago, spent rate-limit windows. Returns the trail points deleted."""
    now = clock.now()
    await db.execute(
        text(
            "delete from rider_positions p using riders r where r.id = p.rider_id"
            " and not r.is_sim and p.recorded_at < :stale"
        ),
        {"stale": now - LIVE_FIX},
    )
    await db.execute(
        text("delete from rate_limits where window_start < :old"),
        {"old": now - dt.timedelta(hours=1)},
    )
    trail = await db.execute(
        text(
            "delete from rider_track t using orders o where o.id = t.order_id"
            " and o.status in ('delivered', 'rejected', 'cancelled', 'expired')"
            " and coalesce(o.delivered_at, o.rejected_at, o.cancelled_at, o.expired_at) < :cutoff"
        ),
        {"cutoff": now - dt.timedelta(days=days)},
    )
    return int(trail.rowcount or 0)  # type: ignore[attr-defined]


async def on_rider_available(db: AsyncSession, rider: Rider) -> Order | None:
    """A freed rider takes the oldest order still waiting for one (a real phone: a demo order)."""
    order = (
        await db.execute(
            select(Order)
            .where(
                Order.rider_id.is_(None),
                Order.status.in_(WAITING),
                Order.is_demo.is_(True) if not rider.is_sim else true(),
            )
            .order_by(Order.accepted_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
    ).scalar_one_or_none()
    if order is None:
        return None
    await assign_rider(db, order, rider)
    return order


async def reassign(
    db: AsyncSession, order_id: uuid.UUID, rider_id: uuid.UUID, actor: Actor
) -> Order:
    """Admin: release the current rider (if any), give the order to `rider_id`, draw a new leg."""
    order = (
        await db.execute(select(Order).where(Order.id == order_id).with_for_update())
    ).scalar_one_or_none()
    if order is None or not order.is_demo:  # every admin login is the public demo
        raise ApiError(404, "not_found", "No such order")
    if order.status not in WAITING:
        raise ApiError(
            409,
            "not_assignable",
            "Only an order that hasn't been picked up yet can be reassigned",
            {"status": str(order.status)},
        )
    rider = (
        await db.execute(select(Rider).where(Rider.id == rider_id).with_for_update())
    ).scalar_one_or_none()
    if rider is None:
        raise ApiError(404, "not_found", "No such rider")
    if rider.status != RiderStatus.available or rider.id == order.rider_id:
        raise ApiError(409, "rider_busy", f"{rider.name} isn't free right now")
    pos = await db.get(RiderPosition, rider.id)
    live = pos is not None and (rider.is_sim or pos.recorded_at > clock.now() - LIVE_FIX)
    # Demo staging (system) may hand the demo phone a job before its first fix arrives.
    if not live and actor.role != "system":
        raise ApiError(409, "rider_busy", f"{rider.name} isn't sharing a location right now")

    old: Rider | None = None
    if order.rider_id is not None:
        old = (
            await db.execute(select(Rider).where(Rider.id == order.rider_id).with_for_update())
        ).scalar_one()
        await release_rider(db, old)
        order.rider_id = None
    await _attach(
        db,
        order,
        rider,
        "rider_reassigned",
        {"from_rider_id": str(old.id) if old else None, "by": str(actor.user_id)},
    )
    if old is not None:
        await on_rider_available(db, old)
    return order
