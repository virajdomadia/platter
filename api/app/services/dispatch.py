"""Dispatch (04 §6): offers to the nearest available rider the moment a restaurant accepts (v2).

`offer` runs inside the accept transaction: one KNN (`loc <-> restaurant`) over the GIST index,
`for update of r skip locked`, so two concurrent accepts never offer the same rider. The rider has
30 s to accept; decline or timeout → the next nearest, up to 5 riders, then the order waits and
the admin sees it flagged. Sims accept on their own 3–8 s after the offer (lazily, in the tick).
Every offer state change is one conditional `update … where state = 'sent'` taken after the order
row lock, so an accept racing the expiry has one winner and only the winner runs side effects.
No rider free → the order waits with `rider_id null` ("Finding a rider"); the tick offers it again.
A real (non-sim) rider is only offered work while online and sharing their location (a fix in the
last 2 minutes). The only real rider is the public demo phone, so it only ever carries demo orders
(`is_demo`): a real customer's address never reaches a stranger's screen.
"""

import datetime as dt
import uuid

from sqlalchemy import func, select, text, true, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.errors import ApiError
from app.models import (
    LegKind,
    Offer,
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
OFFER_S = 30
MAX_OFFERS = 5
SIM_ACCEPT_MIN_S, SIM_ACCEPT_MAX_S = 3, 8
OFFER_KINDS = ("offer_sent", "offer_accepted", "offer_declined", "offer_expired")


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
                  and not exists (select 1 from offers f where f.rider_id = r.id
                                  and (f.order_id = :order or f.state = 'sent'))
                order by p.loc <-> (select loc from restaurants where id = :restaurant)
                limit 1
                for update of r skip locked
                """
            ),
            {
                "restaurant": order.restaurant_id,
                "order": order.id,
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
    # Staging or an admin reassign can beat a pending offer: it closes, its rider's card goes.
    await _close_offers(db, order, "expired", started_at)
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


# --- offers (v2) ------------------------------------------------------------------------------


def _offer_payload(f: Offer, attempt: int | None = None) -> dict:
    out = {
        "offer_id": str(f.id),
        "rider_id": str(f.rider_id),
        "state": f.state,
        "expires_at": f.expires_at.isoformat(),
    }
    return out if attempt is None else {**out, "attempt": attempt}


def sim_accepts_at(f: Offer) -> dt.datetime:
    """A sim makes up its mind 3–8 s after the offer (fixed per offer, so every tick agrees)."""
    spread = SIM_ACCEPT_MAX_S - SIM_ACCEPT_MIN_S + 1
    return f.created_at + dt.timedelta(seconds=SIM_ACCEPT_MIN_S + f.id.int % spread)


async def offer(db: AsyncSession, order: Order, at: dt.datetime | None = None) -> Offer | None:
    """Inside the caller's transaction with `order` locked: offer it to the nearest free rider who
    hasn't been asked yet, unless an offer is already out or five riders have said no."""
    if order.rider_id is not None or order.status not in WAITING:
        return None
    sent, tried = (
        await db.execute(
            select(func.count().filter(Offer.state == "sent"), func.count()).where(
                Offer.order_id == order.id
            )
        )
    ).one()
    if sent or tried >= MAX_OFFERS:
        return None
    rider = await nearest_available_rider(db, order)
    if rider is None:
        return None
    now = at or clock.now()
    f = Offer(
        id=uuid.uuid4(),
        order_id=order.id,
        rider_id=rider.id,
        state="sent",
        created_at=now,
        expires_at=now + dt.timedelta(seconds=OFFER_S),
    )
    db.add(f)
    await db.flush()
    await events.append(
        db, order.id, "offer_sent", events.SYSTEM, _offer_payload(f, tried + 1), at=now
    )
    return f


async def _lock_order(db: AsyncSession, order_id: uuid.UUID, skip: bool = False) -> Order | None:
    return (
        await db.execute(
            select(Order)
            .where(Order.id == order_id)
            .with_for_update(skip_locked=skip)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def _close(db: AsyncSession, offer_id: uuid.UUID, to: str, at: dt.datetime) -> Offer | None:
    """The one conditional write every outcome goes through: only a `sent` offer can close, and
    accept / decline only before the deadline, expire only after it. None = someone else won."""
    deadline = Offer.expires_at > at if to != "expired" else Offer.expires_at <= at
    row = (
        await db.execute(
            update(Offer)
            .where(Offer.id == offer_id, Offer.state == "sent", deadline)
            .values(state=to, closed_at=at)
            .returning(Offer)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    return row


async def _close_offers(
    db: AsyncSession, order: Order, to: str, at: dt.datetime | None = None
) -> None:
    now = at or clock.now()
    closed = (
        await db.execute(
            update(Offer)
            .where(Offer.order_id == order.id, Offer.state == "sent")
            .values(state=to, closed_at=now)
            .returning(Offer)
        )
    ).scalars()
    for f in list(closed):
        await events.append(db, order.id, f"offer_{to}", events.SYSTEM, _offer_payload(f), at=now)


async def answer(
    db: AsyncSession,
    offer_id: uuid.UUID,
    rider_id: uuid.UUID,
    to: str,
    actor: Actor,
    at: dt.datetime | None = None,
) -> Order:
    """A rider (or a sim, `at` its decision time) accepts or declines. 404 if it isn't theirs,
    409 `offer_expired` / `offer_taken` if it already closed. Accept → assigned; decline → the
    next rider is offered at once. The caller commits."""
    f = await db.get(Offer, offer_id)
    if f is None or f.rider_id != rider_id:
        raise ApiError(404, "not_found", "No such offer")
    order = await _lock_order(db, f.order_id)  # order first: the same lock order as a transition
    assert order is not None  # noqa: S101 - FK
    now = at or clock.now()
    rider = (
        await db.execute(select(Rider).where(Rider.id == rider_id).with_for_update())
    ).scalar_one()
    won = await _close(db, offer_id, to, now)
    if won is None:
        await db.refresh(f)
        late = f.state == "expired" or (f.state == "sent" and f.expires_at <= now)
        raise ApiError(
            409,
            "offer_expired" if late else "offer_taken",
            "This offer has expired" if late else "This offer was already answered",
        )
    if to == "accepted" and rider.status != RiderStatus.available:
        # Raised before any commit: the caller rolls back, so the offer is still out.
        raise ApiError(409, "rider_busy", "Finish your current job first")
    await events.append(db, order.id, f"offer_{to}", actor, _offer_payload(won), at=now)
    if to == "accepted":
        await assign_rider(db, order, rider, started_at=now)
    else:
        await offer(db, order, at=now)
    return order


async def expire(db: AsyncSession, offer_id: uuid.UUID, at: dt.datetime | None = None) -> bool:
    """The timeout: if the offer is still out past its deadline, close it and ask the next rider.
    False if an accept or decline got there first (then nothing at all happens here)."""
    f = await db.get(Offer, offer_id)
    if f is None:
        return False
    order = await _lock_order(db, f.order_id)
    assert order is not None  # noqa: S101 - FK
    now = at or clock.now()
    won = await _close(db, offer_id, "expired", now)
    if won is None:
        return False
    await events.append(db, order.id, "offer_expired", events.SYSTEM, _offer_payload(won), at=now)
    await offer(db, order, at=won.expires_at)
    return True


async def run_offers(
    db: AsyncSession,
    order_ids: list[uuid.UUID] | None = None,
    restaurant_id: uuid.UUID | None = None,
) -> None:
    """The lazy tick: sims answer their offers, unanswered ones time out."""
    q = (
        select(Offer, Rider.is_sim)
        .join(Rider, Rider.id == Offer.rider_id)
        .where(Offer.state == "sent")
    )
    if order_ids is not None:
        q = q.where(Offer.order_id.in_(order_ids))
    if restaurant_id is not None:
        mine = select(Order.id).where(Order.restaurant_id == restaurant_id)
        q = q.where(Offer.order_id.in_(mine))
    now = clock.now()
    for f, is_sim in (await db.execute(q)).all():
        if is_sim and sim_accepts_at(f) <= now:
            # A sim decides before its deadline, so even a catch-up accepts rather than expires.
            if await _lock_order(db, f.order_id, skip=True) is None:
                continue
            rider = await db.get(Rider, f.rider_id)
            to = "accepted" if rider and rider.status == RiderStatus.available else "declined"
            sim_actor = Actor("system", rider_id=f.rider_id)
            try:
                await answer(db, f.id, f.rider_id, to, sim_actor, at=sim_accepts_at(f))
            except ApiError:
                continue  # it closed meanwhile
        elif f.expires_at <= now:
            if await _lock_order(db, f.order_id, skip=True) is not None:
                await expire(db, f.id)


async def set_status(db: AsyncSession, rider: Rider, status: RiderStatus) -> None:
    """The rider's online / offline switch. Going offline declines an offer on screen."""
    if rider.status == RiderStatus.busy:
        raise ApiError(409, "rider_busy", "Finish your current job before going offline")
    rider.status = status
    await db.flush()
    if status == RiderStatus.offline:
        live = (
            await db.execute(
                select(Offer.id).where(Offer.rider_id == rider.id, Offer.state == "sent")
            )
        ).scalars()
        for offer_id in list(live):
            actor = Actor("rider", user_id=rider.user_id, rider_id=rider.id)
            try:
                await answer(db, offer_id, rider.id, "declined", actor)
            except ApiError:
                continue


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


def waiting_for_offer():  # type: ignore[no-untyped-def]
    """Orders with no rider, no offer out, and fewer than five riders asked."""
    asked = select(func.count()).where(Offer.order_id == Order.id).scalar_subquery()
    out = select(Offer.id).where(Offer.order_id == Order.id, Offer.state == "sent").exists()
    return (
        select(Order)
        .where(Order.rider_id.is_(None), Order.status.in_(WAITING), ~out, asked < MAX_OFFERS)
        .order_by(Order.accepted_at)
    )


async def on_rider_available(db: AsyncSession, rider: Rider) -> Order | None:
    """A freed rider: the oldest order still waiting is offered out again (a real phone only
    ever hears about a demo order). Returns the order if an offer went out."""
    q = waiting_for_offer().where(Order.is_demo.is_(True) if not rider.is_sim else true())
    order = (await db.execute(q.limit(1).with_for_update(skip_locked=True))).scalar_one_or_none()
    if order is None or await offer(db, order) is None:
        return None
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
