"""Demo scenes and the ambient world, so every demo login lands on something alive.

* `stage()` places a real order through the real state machine (`create` + `transition`) and then
  shifts its timeline into the past, so it is mid-flight: cooking with a rider on the way to the
  kitchen, or picked up with the rider part-way to the door. Every row is what the engine would
  have written — the events, legs and track just carry earlier timestamps.
* `ensure_*_scene` run on `POST /auth/demo`: the customer gets an order on the way, the board gets
  a fresh ticket and one cooking, the demo rider gets a job, the admin sees orders moving.
* `keep_alive` runs from the board and admin streams: sim customers (seeded) place an order now
  and then while someone is watching, and the kitchen autopilot and sim riders carry it through.
"""

import datetime as dt
import random

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.models import (
    ACTIVE_STATUSES,
    LegKind,
    MenuItem,
    Order,
    OrderStatus,
    PaymentKind,
    Restaurant,
    Rider,
    RiderLeg,
    RiderStatus,
    User,
)
from app.services import events, orders, sim
from app.services.events import SYSTEM, Actor

S = OrderStatus
SIM_CUSTOMER_DOMAIN = "@customers.platter.demo"
DEMO_CUSTOMER_EMAIL = "ananya@platter.demo"
DEMO_RIDER_EMAIL = "rider@platter.demo"
DEMO_RESTAURANT_SLUG = "bandstand-kitchen"
AMBIENT_TARGET = 3
AMBIENT_GAP = dt.timedelta(seconds=90)

NOTES = [
    None,
    None,
    None,
    "Extra chutney please",
    "Less spicy",
    "Ring the bell, the dog is friendly",
    "No cutlery needed",
    "Call when you're downstairs",
]


# --- picking things ---------------------------------------------------------------------------


async def sim_customers(db: AsyncSession) -> list[User]:
    return list(
        (
            await db.execute(
                select(User).where(User.is_demo, User.email.like(f"%{SIM_CUSTOMER_DOMAIN}"))
            )
        )
        .scalars()
        .all()
    )


async def home_of(db: AsyncSession, user: User) -> tuple[str, float, float] | None:
    row = (
        await db.execute(
            text(
                "select line, ST_Y(loc::geometry), ST_X(loc::geometry) from addresses"
                " where user_id = :u order by created_at limit 1"
            ),
            {"u": user.id},
        )
    ).first()
    return (row[0], float(row[1]), float(row[2])) if row else None


async def open_restaurants_near(
    db: AsyncSession, lat: float, lng: float, prefer: list[str] | None = None
) -> list[Restaurant]:
    rows = (
        (
            await db.execute(
                text(
                    "select id from restaurants where ST_DWithin(loc,"
                    " ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography, :r)"
                    " order by loc <-> ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography"
                ),
                {"lat": lat, "lng": lng, "r": orders.RADIUS_M - 200},
            )
        )
        .scalars()
        .all()
    )
    found = [r for r in [await db.get(Restaurant, rid) for rid in rows] if r and orders.is_open(r)]
    if prefer:
        found.sort(key=lambda r: prefer.index(r.slug) if r.slug in prefer else len(prefer))
    return found


async def pick_items(db: AsyncSession, restaurant: Restaurant, n: int) -> list[orders.QuoteLine]:
    items = (
        (
            await db.execute(
                select(MenuItem).where(
                    MenuItem.restaurant_id == restaurant.id, MenuItem.is_available.is_(True)
                )
            )
        )
        .scalars()
        .all()
    )
    chosen = random.sample(list(items), k=min(n, len(items)))
    return [orders.QuoteLine(item, random.choice((1, 1, 1, 2))) for item in chosen]


async def nearest_free_sim(db: AsyncSession, restaurant: Restaurant) -> Rider | None:
    rider_id = (
        await db.execute(
            text(
                "select r.id from riders r join rider_positions p on p.rider_id = r.id"
                " where r.status = 'available' and r.is_sim and not exists"
                " (select 1 from offers f where f.rider_id = r.id and f.state = 'sent')"
                " order by p.loc <-> (select loc from restaurants where id = :rest) limit 1"
                " for update of r skip locked"
            ),
            {"rest": restaurant.id},
        )
    ).scalar_one_or_none()
    return await db.get(Rider, rider_id) if rider_id else None


# --- staging ----------------------------------------------------------------------------------


async def _shift(db: AsyncSession, order: Order, times: dict[str, dt.datetime]) -> None:
    """Move an order's timeline into the past: status columns and their events."""
    for status, at in times.items():
        setattr(order, f"{status}_at", at)
        for ev in events.pending(db):
            if ev.order_id == order.id and ev.kind == status:
                ev.at = at
    order.created_at = times.get("placed", order.created_at)
    await db.flush()


async def _leg(db: AsyncSession, order: Order, kind: LegKind) -> RiderLeg | None:
    return (
        await db.execute(
            select(RiderLeg).where(RiderLeg.order_id == order.id, RiderLeg.kind == kind)
        )
    ).scalar_one_or_none()


async def _set_leg(
    db: AsyncSession, order: Order, leg: RiderLeg, started: dt.datetime, **extra: dt.datetime | None
) -> None:
    leg.started_at = started
    for k, v in extra.items():
        setattr(leg, k, v)
    for ev in events.pending(db):
        if ev.order_id != order.id:
            continue
        if ev.kind == "route" and ev.payload.get("leg_id") == str(leg.id):
            ev.at = started
            ev.payload = {**ev.payload, "started_at": started.isoformat()}
        elif ev.kind == "rider_assigned":
            ev.at = started
    await db.flush()


async def _track(db: AsyncSession, order: Order, leg: RiderLeg, until: dt.datetime) -> None:
    """The trail a sim would have left: a point every 3 s along the leg up to `until`."""
    t = leg.started_at
    while t <= until:
        p, _, _ = sim.position_on_leg(leg, t)
        await db.execute(
            text(
                "insert into rider_track (order_id, rider_id, at, loc) values (:o, :r, :at,"
                " ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography)"
            ),
            {"o": order.id, "r": leg.rider_id, "at": t, "lat": p[0], "lng": p[1]},
        )
        t += dt.timedelta(seconds=3)


async def stage(
    db: AsyncSession,
    *,
    customer: User,
    restaurant: Restaurant,
    drop: tuple[str, float, float],
    phase: str,
    rider: Rider | None = None,
    progress: float = 0.3,
    ready_in_s: int = 120,
    items: int = 2,
) -> Order | None:
    """phase: `placed` (a fresh ticket) · `cooking` (accepted, preparing, rider heading to the
    kitchen `progress` of the way, ready in `ready_in_s`) · `on_the_way` (picked up, the rider
    `progress` of the way to the door)."""
    line, lat, lng = drop
    lines = await pick_items(db, restaurant, items)
    if not lines:
        return None
    straight = await orders.straight_distance(db, restaurant.id, lat, lng)
    quote = await orders.price(restaurant, lines, lat, lng, straight)
    actor = Actor("customer", user_id=customer.id)
    order = await orders.create(
        db,
        customer.id,
        quote,
        lat=lat,
        lng=lng,
        address_line=line,
        payment=PaymentKind.cod,
        note=random.choice(NOTES),
        actor=actor,
    )
    now = clock.now()
    if phase == "placed":
        return order
    if rider is None:
        rider = await nearest_free_sim(db, restaurant)
        if rider is None:
            return order  # nobody free: it stays a fresh ticket
    await orders.transition(db, order.id, S.accepted, SYSTEM, rider=rider)
    await orders.transition(db, order.id, S.preparing, SYSTEM)
    to_rest = await _leg(db, order, LegKind.to_restaurant)
    assert to_rest is not None  # noqa: S101
    prep = restaurant.prep_min * 60
    if phase == "cooking":
        accepted = now - dt.timedelta(seconds=max(60, prep - ready_in_s))
        await _shift(
            db,
            order,
            {
                "placed": accepted - dt.timedelta(seconds=40),
                "accepted": accepted,
                "preparing": accepted + dt.timedelta(seconds=20),
            },
        )
        started = now - dt.timedelta(seconds=to_rest.duration_s * progress)
        await _set_leg(db, order, to_rest, started)
        if rider.is_sim:
            await _track(db, order, to_rest, now)
        return order
    # on_the_way: ready and picked up, then part-way to the door.
    to_rest.arrived_at = now
    await db.flush()
    await orders.transition(db, order.id, S.ready, SYSTEM)  # the waiting sim picks up at once
    await db.refresh(order)
    to_cust = await _leg(db, order, LegKind.to_customer)
    if to_cust is None:
        return order
    picked = now - dt.timedelta(seconds=to_cust.duration_s * progress)
    ready = picked - dt.timedelta(seconds=75)
    accepted = ready - dt.timedelta(seconds=prep)
    await _shift(
        db,
        order,
        {
            "placed": accepted - dt.timedelta(seconds=45),
            "accepted": accepted,
            "preparing": accepted + dt.timedelta(seconds=20),
            "ready": ready,
            "picked_up": picked,
        },
    )
    rest_started = accepted + dt.timedelta(seconds=5)
    await _set_leg(
        db,
        order,
        to_rest,
        rest_started,
        arrived_at=min(ready, rest_started + dt.timedelta(seconds=to_rest.duration_s)),
        ended_at=picked,
    )
    await _set_leg(db, order, to_cust, picked)
    await _track(db, order, to_cust, now)
    return order


# --- scenes -----------------------------------------------------------------------------------


async def _active(db: AsyncSession, *where) -> list[Order]:  # type: ignore[no-untyped-def]
    return list(
        (await db.execute(select(Order).where(Order.status.in_(ACTIVE_STATUSES), *where)))
        .scalars()
        .all()
    )


async def ensure_customer_scene(db: AsyncSession, user: User) -> None:
    await sim.advance(db)
    if await _active(db, Order.user_id == user.id):
        return
    home = await home_of(db, user)
    if home is None:
        return
    prefer = ["dosa-camp", "momo-junction", "biryani-bhatti", "burger-barn", "bandstand-kitchen"]
    for restaurant in await open_restaurants_near(db, home[1], home[2], prefer):
        if await nearest_free_sim(db, restaurant) is None:
            break
        if await stage(
            db, customer=user, restaurant=restaurant, drop=home, phase="on_the_way", progress=0.25
        ):
            return


async def ensure_restaurant_scene(db: AsyncSession, restaurant: Restaurant) -> None:
    await sim.advance(db, restaurant_id=restaurant.id)
    restaurant.board_seen_at = clock.now()
    # A visitor may have switched every dish off; the next visitor gets a working kitchen.
    await db.execute(
        update(MenuItem).where(MenuItem.restaurant_id == restaurant.id).values(is_available=True)
    )
    active = await _active(db, Order.restaurant_id == restaurant.id)
    customers = await sim_customers(db)
    random.shuffle(customers)
    wants = []
    if not any(o.status == S.placed for o in active):
        wants.append("placed")
    if not any(o.status in (S.accepted, S.preparing, S.ready) for o in active):
        wants.append("cooking")
    for phase, customer in zip(wants, customers, strict=False):
        home = await home_of(db, customer)
        if home is None:
            continue
        if await orders.straight_distance(db, restaurant.id, home[1], home[2]) > orders.RADIUS_M:
            continue
        await stage(
            db,
            customer=customer,
            restaurant=restaurant,
            drop=home,
            phase=phase,
            progress=0.35,
            ready_in_s=240,
        )


async def ensure_rider_scene(db: AsyncSession, rider: Rider) -> None:
    await sim.advance(db)
    if await _active(db, Order.rider_id == rider.id):
        return
    # The two-phone demo: the demo customer's order (not yet picked up) moves to this phone.
    customer = (
        await db.execute(select(User).where(User.email == DEMO_CUSTOMER_EMAIL))
    ).scalar_one_or_none()
    if customer is not None:
        theirs = await _active(
            db,
            Order.user_id == customer.id,
            Order.status.in_((S.accepted, S.preparing, S.ready)),
        )
        if theirs and rider.status == RiderStatus.available:
            from app.services import dispatch

            await dispatch.reassign(db, theirs[0].id, rider.id, SYSTEM)
            return
    pos = (
        await db.execute(
            text(
                "select ST_Y(loc::geometry), ST_X(loc::geometry) from rider_positions"
                " where rider_id = :r"
            ),
            {"r": rider.id},
        )
    ).first()
    if pos is None:  # the phone hasn't shared a live fix: start the job at the demo kitchen
        pos = (
            await db.execute(
                text(
                    "select ST_Y(loc::geometry), ST_X(loc::geometry) from restaurants"
                    " where slug = :s"
                ),
                {"s": DEMO_RESTAURANT_SLUG},
            )
        ).first()
        if pos is None:
            return
    customers = await sim_customers(db)
    random.shuffle(customers)
    for restaurant in await open_restaurants_near(db, float(pos[0]), float(pos[1])):
        for c in customers:
            home = await home_of(db, c)
            if home and await orders.straight_distance(db, restaurant.id, home[1], home[2]) <= 4000:
                rider.status = RiderStatus.available
                await stage(
                    db,
                    customer=c,
                    restaurant=restaurant,
                    drop=home,
                    phase="cooking",
                    rider=rider,
                    progress=0.0,
                    ready_in_s=90,
                )
                return


async def ensure_admin_scene(db: AsyncSession) -> None:
    await sim.advance(db)
    active = await _active(db)
    for phase in ("on_the_way", "cooking")[: max(0, 2 - len(active))]:
        await spawn(db, phase=phase)


async def spawn(
    db: AsyncSession, *, phase: str = "placed", prefer: Restaurant | None = None
) -> Order | None:
    customers = await sim_customers(db)
    random.shuffle(customers)
    for c in customers[:4]:
        home = await home_of(db, c)
        if home is None:
            continue
        options = await open_restaurants_near(db, home[1], home[2])
        if prefer is not None and prefer in options and random.random() < 0.5:
            options = [prefer]
        if not options:
            continue
        return await stage(
            db,
            customer=c,
            restaurant=random.choice(options[:6]),
            drop=home,
            phase=phase,
            progress=random.uniform(0.1, 0.5),
            ready_in_s=random.randint(120, 300),
        )
    return None


async def keep_alive(db: AsyncSession, prefer: Restaurant | None = None) -> Order | None:
    """While someone watches the board or the admin map, sim customers keep ~3 orders in the air."""
    now = clock.now()
    active = (
        await db.execute(
            select(func.count()).select_from(Order).where(Order.status.in_(ACTIVE_STATUSES))
        )
    ).scalar_one()
    if active >= AMBIENT_TARGET:
        return None
    newest = (await db.execute(select(func.max(Order.created_at)))).scalar_one()
    if newest is not None and now - newest < AMBIENT_GAP:
        return None
    return await spawn(db, phase="placed", prefer=prefer)
