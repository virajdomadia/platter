"""The admin's live map: every active demo order and every rider, stuck flags, today's numbers (R9).
The only admin login is the public demo, so a real customer's order (and a sim rider's position
while it carries one, which would trace their door) never appears here.

Stuck rules: `placed` unaccepted for 5 min · accepted for 3 min with no rider · still cooking 5 min
past the kitchen's prep time · `ready` for 10 min and not picked up. A real rider with no fix for 2
minutes and no job shows as offline (they are not sharing their location, so dispatch skips them
too)."""

import datetime as dt
import uuid
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import schemas as s
from app.core import clock
from app.models import (
    ACTIVE_STATUSES,
    Order,
    OrderStatus,
    Restaurant,
    Rider,
    RiderLeg,
)
from app.models.geo import latlng
from app.services import dispatch, routing, views

S = OrderStatus
IST = ZoneInfo("Asia/Kolkata")
UNACCEPTED = dt.timedelta(minutes=5)
NO_RIDER = dt.timedelta(minutes=3)
NOT_PICKED_UP = dt.timedelta(minutes=10)
KITCHEN_LATE = dt.timedelta(minutes=5)


def stuck(order: Order, now: dt.datetime, prep_min: int | None = None) -> str | None:
    if order.status == S.placed and order.placed_at and now - order.placed_at >= UNACCEPTED:
        return "unaccepted"
    if (
        order.status in dispatch.WAITING
        and order.rider_id is None
        and order.accepted_at
        and now - order.accepted_at >= NO_RIDER
    ):
        return "no_rider"
    if (
        prep_min is not None
        and order.status in (S.accepted, S.preparing)
        and order.accepted_at
        and now - order.accepted_at >= dt.timedelta(minutes=prep_min) + KITCHEN_LATE
    ):
        return "kitchen_late"
    if order.status == S.ready and order.ready_at and now - order.ready_at >= NOT_PICKED_UP:
        return "not_picked_up"
    return None


def status_since(order: Order) -> dt.datetime:
    at = getattr(order, f"{order.status.value}_at", None)
    return at or order.created_at


async def riders(db: AsyncSession, near: tuple[float, float] | None = None) -> list[s.AdminRider]:
    rows = (await db.execute(select(Rider).order_by(Rider.name))).scalars().all()
    current = {
        rid: number
        for rid, number in (
            await db.execute(
                select(Order.rider_id, Order.number).where(
                    Order.rider_id.is_not(None),
                    Order.status.in_(ACTIVE_STATUSES),
                    Order.is_demo.is_(True),
                )
            )
        ).all()
    }
    legs: dict[uuid.UUID, RiderLeg] = {}
    on_real: set[uuid.UUID] = set()
    for leg, demo in await db.execute(
        select(RiderLeg, Order.is_demo)
        .join(Order, Order.id == RiderLeg.order_id)
        .where(RiderLeg.ended_at.is_(None))
    ):
        legs[leg.rider_id] = leg
        if not demo:
            on_real.add(leg.rider_id)
    out: list[s.AdminRider] = []
    for r in rows:
        fix = (
            None
            if r.id in on_real
            else await views.rider_fix(
                db, r, legs.get(r.id), legs[r.id].order_id if r.id in legs else None
            )
        )
        last = views.seconds_since(fix.at) if fix else None
        status = r.status.value
        if (
            not r.is_sim
            and status == "available"
            and (last is None or last > dispatch.LIVE_FIX.total_seconds())
        ):
            status = "offline"
        distance = (
            round(routing.haversine(near, (fix.lat, fix.lng))) if near and fix is not None else None
        )
        out.append(
            s.AdminRider(
                id=str(r.id),
                name=r.name,
                status=status,  # type: ignore[arg-type]
                is_sim=r.is_sim,
                vehicle=r.vehicle,
                lat=fix.lat if fix else None,
                lng=fix.lng if fix else None,
                heading=fix.heading if fix else None,
                current_order=current.get(r.id),
                last_fix_s=0 if (r.is_sim and r.id in legs) else last,
                distance_m=distance,
            )
        )
    if near is not None:
        out.sort(
            key=lambda x: (
                x.status != "available",
                x.distance_m if x.distance_m is not None else 1e9,
            )
        )
    return out


async def admin_order(
    db: AsyncSession, order: Order, restaurant: Restaurant, now: dt.datetime
) -> s.AdminOrder:
    legs = (
        (
            await db.execute(
                select(RiderLeg).where(RiderLeg.order_id == order.id, RiderLeg.ended_at.is_(None))
            )
        )
        .scalars()
        .all()
    )
    rider = await db.get(Rider, order.rider_id) if order.rider_id else None
    rlat, rlng = latlng(restaurant.loc)
    dlat, dlng = latlng(order.drop_loc)
    placed = order.placed_at or order.created_at
    return s.AdminOrder(
        id=str(order.id),
        number=order.number,
        status=order.status.value,  # type: ignore[arg-type]
        restaurant_name=restaurant.name,
        restaurant=s.Point(lat=rlat, lng=rlng),
        drop=s.Point(lat=dlat, lng=dlng),
        rider_id=str(rider.id) if rider else None,
        rider_name=rider.name if rider else None,
        age_s=int((now - placed).total_seconds()),
        status_age_s=int((now - status_since(order)).total_seconds()),
        stuck=stuck(order, now, restaurant.prep_min),  # type: ignore[arg-type]
        legs=[views.route_out(lg) for lg in legs],
        total_paise=order.total_paise,
    )


async def active_orders(
    db: AsyncSession, *, only_stuck: bool = False, status: str | None = None
) -> list[s.AdminOrder]:
    now = clock.now()
    q = (
        select(Order, Restaurant)
        .join(Restaurant, Restaurant.id == Order.restaurant_id)
        .where(Order.status.in_(ACTIVE_STATUSES), Order.is_demo.is_(True))
        .order_by(Order.placed_at.desc())
    )
    if status:
        q = q.where(Order.status == S(status))
    out = [await admin_order(db, o, r, now) for o, r in (await db.execute(q)).all()]
    return [o for o in out if o.stuck] if only_stuck else out


async def today(db: AsyncSession) -> s.AdminToday:
    now = clock.now()
    start = now.astimezone(IST).replace(hour=0, minute=0, second=0, microsecond=0)
    placed = (
        await db.execute(
            select(func.count(), func.coalesce(func.sum(Order.total_paise), 0)).where(
                Order.placed_at >= start, Order.status != S.pending_payment
            )
        )
    ).one()
    delivered = (
        await db.execute(
            select(
                func.count(),
                func.avg(func.extract("epoch", Order.delivered_at - Order.placed_at)),
            ).where(Order.delivered_at >= start)
        )
    ).one()
    return s.AdminToday(
        orders=int(placed[0]),
        delivered=int(delivered[0]),
        revenue_paise=int(placed[1]),
        avg_delivery_s=int(delivered[1]) if delivered[1] is not None else None,
    )


async def restaurants(db: AsyncSession) -> list[s.RestaurantCard]:
    rows = (await db.execute(select(Restaurant).order_by(Restaurant.name))).scalars().all()
    return [views.restaurant_card(r, distance_m=0) for r in rows]


async def live_map(db: AsyncSession) -> s.AdminMap:
    return s.AdminMap(
        orders=await active_orders(db),
        riders=await riders(db),
        restaurants=await restaurants(db),
        today=await today(db),
        seq=await views.max_seq(db),
    )


def parse_near(near: str | None) -> tuple[float, float] | None:
    if not near:
        return None
    try:
        lat, lng = (float(x) for x in near.split(","))
    except ValueError:
        return None
    return lat, lng
