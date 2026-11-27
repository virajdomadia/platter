"""Read models: rows → the shapes in `app.schemas` (06 §D). Each builder is the one place a shape
is assembled, so REST responses and stream payloads can't drift apart."""

import datetime as dt
import uuid

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app import schemas as s
from app.core import clock
from app.models import (
    LegKind,
    Offer,
    Order,
    OrderEvent,
    OrderItem,
    OrderStatus,
    Rating,
    Restaurant,
    Rider,
    RiderLeg,
    RiderPosition,
    User,
)
from app.models.geo import latlng
from app.services import dispatch, eta, hours, orders, routing, sim
from app.services.events import STATUS_KINDS

S = OrderStatus
PHOTO_W, PHOTO_H = 640, 480


def photo(url: str | None) -> s.Photo | None:
    return s.Photo(url=url, width=PHOTO_W, height=PHOTO_H) if url else None


def first_name(name: str) -> str:
    return name.split(" ")[0] if name else "Customer"


def rider_pay_preview(distance_m: int) -> int:
    """What the rider will earn: ₹30 + ₹8 per km of the drop (v2 writes it to the ledger)."""
    return 3000 + 800 * round(distance_m / 1000)


def route_out(leg: RiderLeg) -> s.RouteOut:
    return s.RouteOut(
        order_id=str(leg.order_id),
        leg_id=str(leg.id),
        kind=leg.kind.value,  # type: ignore[arg-type]
        polyline=leg.polyline,
        distance_m=leg.distance_m,
        duration_s=leg.duration_s,
        method=leg.method.value,  # type: ignore[arg-type]
        started_at=leg.started_at,
    )


async def open_leg(db: AsyncSession, order_id: uuid.UUID) -> RiderLeg | None:
    return (
        await db.execute(
            select(RiderLeg)
            .where(RiderLeg.order_id == order_id, RiderLeg.ended_at.is_(None))
            .order_by(RiderLeg.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def rider_fix(
    db: AsyncSession, rider: Rider, leg: RiderLeg | None, order_id: uuid.UUID | None
) -> s.RiderFix | None:
    """A rider's position now: computed along the leg for a sim on a job, else the last fix."""
    now = clock.now()
    if rider.is_sim and leg is not None:
        p, heading, _ = sim.position_on_leg(leg, now)
        return s.RiderFix(
            order_id=str(order_id) if order_id else None,
            rider_id=str(rider.id),
            lat=p[0],
            lng=p[1],
            heading=heading,
            speed_mps=round(float(rider.speed_kmh) / 3.6, 2),
            at=now,
        )
    pos = await db.get(RiderPosition, rider.id)
    # A real phone's fix is shown only while it is live: never where someone *was*.
    if pos is None or (not rider.is_sim and pos.recorded_at <= now - dispatch.LIVE_FIX):
        return None
    lat, lng = latlng(pos.loc)
    return s.RiderFix(
        order_id=str(order_id) if order_id else None,
        rider_id=str(rider.id),
        lat=lat,
        lng=lng,
        heading=pos.heading,
        speed_mps=float(pos.speed_mps) if pos.speed_mps is not None else None,
        at=pos.recorded_at,
    )


async def eta_for(
    db: AsyncSession,
    order: Order,
    restaurant: Restaurant,
    leg: RiderLeg | None,
    fix: s.RiderFix | None,
) -> s.EtaOut | None:
    rider = await db.get(Rider, order.rider_id) if order.rider_id else None
    speed = eta.speed_mps(
        bool(rider and rider.is_sim),
        float(rider.speed_kmh) if rider else eta.DEFAULT_KMH,
        fix.speed_mps if fix else None,
    )
    found = eta.compute(
        order,
        prep_min=restaurant.prep_min,
        leg=leg,
        position=(fix.lat, fix.lng) if fix else None,
        speed=speed,
        now=clock.now(),
    )
    if found is None:
        return None
    return s.EtaOut(**found.as_event(str(order.id)))  # type: ignore[arg-type]


RATING_PRIOR = 10  # the seeded score counts as ten ratings, so one review can't swing it


def public_rating(r: Restaurant) -> float | None:
    """The seeded score blended with real customers' ratings (demo ratings are never counted)."""
    if r.rating is None and not r.rating_count:
        return None
    prior = RATING_PRIOR if r.rating is not None else 0
    base = float(r.rating or 0) * prior
    return round((base + (r.rating_sum or 0)) / (prior + (r.rating_count or 0)), 1)


def restaurant_card(
    r: Restaurant, *, distance_m: int, drop: tuple[float, float] | None = None
) -> s.RestaurantCard:
    now = clock.now()
    open_now = orders.is_open(r, now)
    too_far = distance_m > orders.RADIUS_M
    road = round(distance_m * routing.LINE_FACTOR)
    ride_s = round(road / (routing.LINE_SPEED_KMH / 3.6))
    lat, lng = latlng(r.loc)
    return s.RestaurantCard(
        id=str(r.id),
        slug=r.slug,
        name=r.name,
        area=r.area,
        cuisines=list(r.cuisines),
        is_veg=r.is_veg,
        cover=photo(r.cover_url),
        rating=public_rating(r),
        prep_min=r.prep_min,
        lat=lat,
        lng=lng,
        distance_m=distance_m,
        eta_s=r.prep_min * 60 + ride_s + orders.HANDOVER_S,
        # The list estimates the fee from straight × 1.3; checkout prices the road (OSRM).
        delivery_fee_paise=orders.delivery_fee_paise(road),
        orderable=open_now and not too_far,
        reason="too_far" if too_far else (None if open_now else "closed"),
        hours_label=hours.label(r.hours, now),
        opens=None if open_now else hours.next_opening(r.hours, now),
    )


async def order_out(db: AsyncSession, order: Order) -> s.OrderOut:
    restaurant = await db.get(Restaurant, order.restaurant_id)
    assert restaurant is not None  # noqa: S101 - FK
    items = (
        (await db.execute(select(OrderItem).where(OrderItem.order_id == order.id))).scalars().all()
    )
    legs = (
        (
            await db.execute(
                select(RiderLeg).where(RiderLeg.order_id == order.id).order_by(RiderLeg.started_at)
            )
        )
        .scalars()
        .all()
    )
    leg = next((lg for lg in reversed(legs) if lg.ended_at is None), None)
    status_events = (
        (
            await db.execute(
                select(OrderEvent)
                .where(OrderEvent.order_id == order.id, OrderEvent.kind.in_(STATUS_KINDS))
                .order_by(OrderEvent.seq)
            )
        )
        .scalars()
        .all()
    )
    seq = (
        await db.execute(
            select(func.coalesce(func.max(OrderEvent.seq), 0)).where(
                OrderEvent.order_id == order.id
            )
        )
    ).scalar_one()
    rider = await db.get(Rider, order.rider_id) if order.rider_id else None
    fix = None
    if rider is not None and order.status in (S.accepted, S.preparing, S.ready, S.picked_up):
        fix = await rider_fix(db, rider, leg, order.id)
    trail_rows = (
        (
            await db.execute(
                text(
                    "select ST_Y(loc::geometry), ST_X(loc::geometry) from rider_track"
                    " where order_id = :o and rider_id = :r order by at desc limit 400"
                ),
                {"o": order.id, "r": order.rider_id},
            )
        ).all()
        if rider
        else []
    )
    rlat, rlng = latlng(restaurant.loc)
    dlat, dlng = latlng(order.drop_loc)
    timestamps = {
        st.value: getattr(order, f"{st.value}_at")
        for st in S
        if st != S.pending_payment and getattr(order, f"{st.value}_at") is not None
    }
    return s.OrderOut(
        id=str(order.id),
        number=order.number,
        status=order.status.value,  # type: ignore[arg-type]
        payment=order.payment.value,  # type: ignore[arg-type]
        restaurant=s.OrderRestaurant(
            id=str(restaurant.id),
            slug=restaurant.slug,
            name=restaurant.name,
            area=restaurant.area,
            address=restaurant.address,
            lat=rlat,
            lng=rlng,
            cover=photo(restaurant.cover_url),
        ),
        drop=s.Drop(line=order.address_line, lat=dlat, lng=dlng),
        items=[
            s.OrderItemOut(name=i.name, price_paise=i.price_paise, qty=i.qty, is_veg=i.is_veg)
            for i in items
        ],
        totals=s.Totals(
            subtotal_paise=order.subtotal_paise,
            delivery_fee_paise=order.delivery_fee_paise,
            platform_fee_paise=order.platform_fee_paise,
            total_paise=order.total_paise,
            distance_m=order.distance_m,
        ),
        note=order.note,
        reject_reason=order.reject_reason,
        rider=s.RiderPublic(
            id=str(rider.id),
            name=rider.name,
            vehicle=rider.vehicle,
            phone_masked=dispatch.mask_phone(rider.phone),
        )
        if rider
        else None,
        rider_position=fix,
        legs=[
            route_out(lg) for lg in legs if lg.ended_at is None or lg.kind == LegKind.to_customer
        ],
        trail=[[float(a), float(b)] for a, b in reversed(trail_rows)],
        eta=await eta_for(db, order, restaurant, leg, fix),
        events=[
            s.StatusEventOut(
                order_id=str(order.id),
                status=e.kind,  # type: ignore[arg-type]
                at=e.at,
                reason=e.payload.get("reason"),
            )
            for e in status_events
        ],
        timestamps=timestamps,
        created_at=order.created_at,
        seq=int(seq),
        offer_attempts=await offer_attempts(db, order.id),
        rating=await rating_of(db, order.id),
    )


async def rating_of(db: AsyncSession, order_id: uuid.UUID) -> s.RatingOut | None:
    r = (await db.execute(select(Rating).where(Rating.order_id == order_id))).scalar_one_or_none()
    if r is None:
        return None
    return s.RatingOut(restaurant_stars=r.restaurant_stars, rider_stars=r.rider_stars, line=r.line)


async def order_card(db: AsyncSession, order: Order) -> s.OrderCard:
    restaurant = await db.get(Restaurant, order.restaurant_id)
    assert restaurant is not None  # noqa: S101
    items = (
        (await db.execute(select(OrderItem).where(OrderItem.order_id == order.id))).scalars().all()
    )
    return s.OrderCard(
        id=str(order.id),
        number=order.number,
        status=order.status.value,  # type: ignore[arg-type]
        restaurant_name=restaurant.name,
        restaurant_slug=restaurant.slug,
        cover=photo(restaurant.cover_url),
        items_summary=", ".join(f"{i.qty} × {i.name}" for i in items),
        total_paise=order.total_paise,
        created_at=order.created_at,
    )


def leg_phase(order: Order, leg: RiderLeg | None) -> str:
    if order.status == S.picked_up:
        return "to_customer"
    if leg is not None and leg.arrived_at is None and leg.kind == LegKind.to_restaurant:
        return "to_restaurant"
    return "waiting"


async def ticket(db: AsyncSession, order: Order) -> s.Ticket:
    customer = await db.get(User, order.user_id)
    items = (
        (await db.execute(select(OrderItem).where(OrderItem.order_id == order.id))).scalars().all()
    )
    rider_info = None
    if order.rider_id:
        rider = await db.get(Rider, order.rider_id)
        assert rider is not None  # noqa: S101
        leg = await open_leg(db, order.id)
        fix = await rider_fix(db, rider, leg, order.id)
        restaurant = await db.get(Restaurant, order.restaurant_id)
        assert restaurant is not None  # noqa: S101
        distance = None
        eta_s = None
        phase = leg_phase(order, leg)
        if fix is not None:
            distance = round(routing.haversine((fix.lat, fix.lng), latlng(restaurant.loc)))
        if leg is not None and phase == "to_restaurant":
            remaining = eta.remaining_on_leg(leg, (fix.lat, fix.lng) if fix else None)
            spd = eta.speed_mps(
                rider.is_sim, float(rider.speed_kmh), fix.speed_mps if fix else None
            )
            eta_s = round(remaining / spd)
        rider_info = s.TicketRider(name=rider.name, distance_m=distance, eta_s=eta_s, phase=phase)  # type: ignore[arg-type]
    placed = order.placed_at or order.created_at
    return s.Ticket(
        id=str(order.id),
        number=order.number,
        status=order.status.value,  # type: ignore[arg-type]
        placed_at=placed,
        age_s=max(0, int((clock.now() - placed).total_seconds())),
        customer_first_name=first_name(customer.name if customer else ""),
        payment=order.payment.value,  # type: ignore[arg-type]
        note=order.note,
        items=[s.TicketItem(name=i.name, qty=i.qty, is_veg=i.is_veg) for i in items],
        total_paise=order.total_paise,
        rider=rider_info,
    )


async def job(db: AsyncSession, order: Order) -> s.Job:
    restaurant = await db.get(Restaurant, order.restaurant_id)
    customer = await db.get(User, order.user_id)
    assert restaurant is not None and customer is not None  # noqa: S101
    items = (
        (await db.execute(select(OrderItem).where(OrderItem.order_id == order.id))).scalars().all()
    )
    leg = await open_leg(db, order.id)
    rlat, rlng = latlng(restaurant.loc)
    dlat, dlng = latlng(order.drop_loc)
    return s.Job(
        order_id=str(order.id),
        number=order.number,
        status=order.status.value,  # type: ignore[arg-type]
        phase=leg_phase(order, leg),  # type: ignore[arg-type]
        restaurant=s.JobPlace(name=restaurant.name, line=restaurant.address, lat=rlat, lng=rlng),
        drop=s.JobPlace(
            name=first_name(customer.name), line=order.address_line, lat=dlat, lng=dlng
        ),
        customer_first_name=first_name(customer.name),
        items=[s.TicketItem(name=i.name, qty=i.qty, is_veg=i.is_veg) for i in items],
        items_count=sum(i.qty for i in items),
        payment=order.payment.value,  # type: ignore[arg-type]
        total_paise=order.total_paise,
        note=order.note,
        leg=route_out(leg) if leg else None,
        pay_preview_paise=rider_pay_preview(order.distance_m),
    )


async def offer_attempts(db: AsyncSession, order_id: uuid.UUID) -> int:
    return int(
        (
            await db.execute(
                select(func.count()).select_from(Offer).where(Offer.order_id == order_id)
            )
        ).scalar_one()
    )


async def rider_offer(db: AsyncSession, rider: Rider) -> s.RiderOffer | None:
    """The offer on this rider's screen, if one is still out (an expired one is never shown)."""
    now = clock.now()
    f = (
        await db.execute(
            select(Offer)
            .where(Offer.rider_id == rider.id, Offer.state == "sent", Offer.expires_at > now)
            .limit(1)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if f is None:
        return None
    order = await db.get(Order, f.order_id)
    assert order is not None  # noqa: S101 - FK
    left = max(0, round((f.expires_at - now).total_seconds()))
    return s.RiderOffer(
        id=str(f.id), expires_at=f.expires_at, expires_in_s=left, job=await job(db, order)
    )


def seconds_since(at: dt.datetime | None) -> int | None:
    return None if at is None else max(0, int((clock.now() - at).total_seconds()))


async def max_seq(db: AsyncSession) -> int:
    return int((await db.execute(select(func.coalesce(func.max(OrderEvent.seq), 0)))).scalar_one())
