"""Quotes, orders and the order state machine (04 §5, 04 §7).

Every status change goes through `transition()`: lock the order row, look the edge up in
`TRANSITIONS` (roles + a one-line guard), write the status and its `*_at`, append the event, and
run the edge's side effects — all in the caller's transaction. Anything not in the table is a
409 `illegal_transition { from, to }`. The `system` actor is the simulation: sim riders on the
rider edges, and the kitchen autopilot on the restaurant edges while nobody is on that board.
"""

import datetime as dt
import logging
import math
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.errors import ApiError
from app.models import (
    LegKind,
    MenuItem,
    Order,
    OrderItem,
    OrderStatus,
    PaymentKind,
    Restaurant,
    Rider,
    RiderLeg,
    RouteMethod,
    User,
)
from app.models.geo import latlng, make_point
from app.services import dispatch, events, hours, routing
from app.services.events import SYSTEM, Actor

S = OrderStatus
log = logging.getLogger(__name__)

RADIUS_M = 5000
SHOWN_RADIUS_M = 8000
PLATFORM_FEE_PAISE = 500
HANDOVER_S = 90
PAYMENT_WINDOW = dt.timedelta(minutes=15)
MAX_QTY = 20


def delivery_fee_paise(distance_m: int) -> int:
    """₹25 up to 2 km, then ₹8 per started km of the route distance (PRD decision 2)."""
    return 2500 + 800 * max(0, math.ceil((distance_m - 2000) / 1000))


# --- quote ------------------------------------------------------------------------------------


@dataclass
class QuoteLine:
    item: MenuItem
    qty: int


@dataclass
class Quote:
    restaurant: Restaurant
    lines: list[QuoteLine]
    subtotal_paise: int
    delivery_fee_paise: int
    platform_fee_paise: int
    total_paise: int
    distance_m: int
    straight_m: int
    eta_s: int
    method: str
    items_json: list[dict] = field(default_factory=list)


async def straight_distance(
    db: AsyncSession, restaurant_id: uuid.UUID, lat: float, lng: float
) -> int:
    return int(
        (
            await db.execute(
                text(
                    "select ST_Distance(loc, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography)"
                    " from restaurants where id = :id"
                ),
                {"lat": lat, "lng": lng, "id": restaurant_id},
            )
        ).scalar_one()
    )


def is_open(restaurant: Restaurant, at: dt.datetime | None = None) -> bool:
    return restaurant.is_open and hours.is_open_at(restaurant.hours, at or clock.now())


async def quote(
    db: AsyncSession,
    restaurant_id: uuid.UUID,
    items: list[tuple[uuid.UUID, int]],
    lat: float,
    lng: float,
) -> Quote:
    restaurant = await db.get(Restaurant, restaurant_id)
    if restaurant is None or restaurant.is_sandbox:  # the demo editor's copy takes no orders
        raise ApiError(404, "not_found", "No such restaurant")
    if not items:
        raise ApiError(422, "empty_cart", "Your cart is empty")
    wanted: dict[uuid.UUID, int] = {}
    for item_id, qty in items:
        wanted[item_id] = wanted.get(item_id, 0) + qty
    # After merging, so repeating a line can't get past the cap.
    if any(q < 1 for _, q in items) or any(q > MAX_QTY for q in wanted.values()):
        raise ApiError(422, "validation", f"Quantities run from 1 to {MAX_QTY}")
    if not is_open(restaurant):
        raise ApiError(
            422,
            "restaurant_closed",
            f"{restaurant.name} is closed right now",
            {"opens": hours.next_opening(restaurant.hours, clock.now())},
        )
    # The radius is always straight-line, so the list, the quote and the order agree (04 §4).
    straight = await straight_distance(db, restaurant.id, lat, lng)
    if straight > RADIUS_M:
        raise ApiError(
            422,
            "out_of_range",
            f"{restaurant.name} can't reach this address ({straight / 1000:.1f} km away)",
            {"distance_m": straight},
        )
    found = {
        m.id: m
        for m in (
            await db.execute(
                select(MenuItem).where(
                    MenuItem.id.in_(wanted.keys()), MenuItem.restaurant_id == restaurant.id
                )
            )
        ).scalars()
    }
    bad = [str(i) for i in wanted if i not in found or not found[i].is_available]
    if bad:
        raise ApiError(422, "item_unavailable", "Some items are no longer available", {"ids": bad})
    lines = [QuoteLine(found[i], q) for i, q in wanted.items()]
    return await price(restaurant, lines, lat, lng, straight)


async def price(
    restaurant: Restaurant, lines: list[QuoteLine], lat: float, lng: float, straight: int
) -> Quote:
    """Totals from DB prices; the fee on the road distance (OSRM, else straight × 1.3)."""
    subtotal = sum(line.item.price_paise * line.qty for line in lines)
    leg = await routing.route(latlng(restaurant.loc), (lat, lng))
    fee = delivery_fee_paise(leg.distance_m)
    return Quote(
        restaurant=restaurant,
        lines=lines,
        subtotal_paise=subtotal,
        delivery_fee_paise=fee,
        platform_fee_paise=PLATFORM_FEE_PAISE,
        total_paise=subtotal + fee + PLATFORM_FEE_PAISE,
        distance_m=leg.distance_m,
        straight_m=straight,
        eta_s=restaurant.prep_min * 60 + leg.duration_s + HANDOVER_S,
        method=leg.method,
        items_json=[
            {
                "id": str(line.item.id),
                "name": line.item.name,
                "price_paise": line.item.price_paise,
                "qty": line.qty,
                "is_veg": line.item.is_veg,
            }
            for line in lines
        ],
    )


async def create(
    db: AsyncSession,
    user_id: uuid.UUID,
    q: Quote,
    *,
    lat: float,
    lng: float,
    address_line: str,
    payment: PaymentKind,
    note: str | None,
    actor: Actor,
) -> Order:
    """Insert the order from a server-side quote (client totals are never read). COD is `placed`
    at once; Razorpay waits in `pending_payment` for `mark_paid`. The caller commits."""
    number = (await db.execute(text("select nextval('order_number_seq')"))).scalar_one()
    now = clock.now()
    customer = await db.get(User, user_id)
    order = Order(
        id=uuid.uuid4(),
        number=f"PL-{number}",
        user_id=user_id,
        is_demo=bool(customer and customer.is_demo),
        restaurant_id=q.restaurant.id,
        status=S.placed if payment == PaymentKind.cod else S.pending_payment,
        payment=payment,
        address_line=address_line.strip()[:200],
        drop_loc=make_point(lat, lng),
        subtotal_paise=q.subtotal_paise,
        delivery_fee_paise=q.delivery_fee_paise,
        platform_fee_paise=q.platform_fee_paise,
        total_paise=q.total_paise,
        distance_m=q.distance_m,
        route_method=RouteMethod(q.method),
        eta_s=q.eta_s,
        note=(note or "").strip()[:280] or None,
        created_at=now,
        placed_at=now if payment == PaymentKind.cod else None,
    )
    db.add(order)
    await db.flush()
    for line in q.lines:
        db.add(
            OrderItem(
                order_id=order.id,
                menu_item_id=line.item.id,
                name=line.item.name,
                price_paise=line.item.price_paise,
                qty=line.qty,
                is_veg=line.item.is_veg,
            )
        )
    if order.status == S.placed:
        await events.append(db, order.id, "placed", actor, {"status": "placed"})
    await db.flush()
    return order


# --- the state machine ------------------------------------------------------------------------

Guard = Callable[[Order, Actor], bool]


def _own_restaurant(o: Order, a: Actor) -> bool:
    return a.role == "system" or a.restaurant_id == o.restaurant_id


def _own_order(o: Order, a: Actor) -> bool:
    return a.user_id == o.user_id


def _own_unpaid_order(o: Order, a: Actor) -> bool:
    # shortcut: no refunds until v2, so an order paid online can't be cancelled by the customer.
    return _own_order(o, a) and o.payment == PaymentKind.cod


def _assigned_rider(o: Order, a: Actor) -> bool:
    return o.rider_id is not None and a.rider_id == o.rider_id


def _always(o: Order, a: Actor) -> bool:
    return True


@dataclass(frozen=True)
class Rule:
    roles: frozenset[str]
    guard: Guard = _always


def _rule(*roles: str, guard: Guard = _always) -> Rule:
    return Rule(frozenset(roles), guard)


TRANSITIONS: dict[tuple[OrderStatus, OrderStatus], Rule] = {
    (S.pending_payment, S.placed): _rule("system"),
    (S.pending_payment, S.expired): _rule("system"),
    (S.placed, S.accepted): _rule("restaurant", "system", guard=_own_restaurant),
    (S.placed, S.rejected): _rule("restaurant", guard=_own_restaurant),
    (S.placed, S.cancelled): _rule("customer", guard=_own_unpaid_order),
    (S.accepted, S.preparing): _rule("restaurant", "system", guard=_own_restaurant),
    (S.preparing, S.ready): _rule("restaurant", "system", guard=_own_restaurant),
    (S.ready, S.picked_up): _rule("rider", "system", guard=_assigned_rider),
    (S.picked_up, S.delivered): _rule("rider", "system", guard=_assigned_rider),
}


def illegal(order: Order, to: OrderStatus) -> ApiError:
    return ApiError(
        409,
        "illegal_transition",
        f"An order that is {order.status.replace('_', ' ')} can't become {to.replace('_', ' ')}",
        {"from": str(order.status), "to": str(to)},
    )


async def lock(db: AsyncSession, order_id: uuid.UUID) -> Order | None:
    return (
        await db.execute(
            select(Order)
            .where(Order.id == order_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def transition(
    db: AsyncSession,
    order_id: uuid.UUID,
    to: OrderStatus,
    actor: Actor,
    *,
    reason: str | None = None,
    rider: Rider | None = None,
    at: dt.datetime | None = None,
) -> Order:
    """`rider`: on `accepted`, dispatch to this rider instead of the nearest (demo staging).
    `at`: when it happened, if earlier than now — the lazy simulation catching up stamps each
    step with the moment it really happened (a sim's arrival = leg start + duration)."""
    order = await lock(db, order_id)
    if order is None:
        raise ApiError(404, "not_found", "No such order")
    rule = TRANSITIONS.get((order.status, to))
    if rule is None or actor.role not in rule.roles or not rule.guard(order, actor):
        raise illegal(order, to)
    now = min(at, clock.now()) if at else clock.now()
    order.status = to
    setattr(order, f"{to}_at", now)
    payload: dict = {"status": str(to)}
    if to == S.rejected:
        order.reject_reason = (reason or "The kitchen couldn't take this order").strip()[:200]
        payload["reason"] = order.reject_reason
    await db.flush()
    await events.append(db, order.id, str(to), actor, payload, at=now)
    await _side_effects(db, order, to, rider)
    return order


async def _open_leg_of(db: AsyncSession, order: Order) -> RiderLeg | None:
    return (
        await db.execute(
            select(RiderLeg)
            .where(RiderLeg.order_id == order.id, RiderLeg.ended_at.is_(None))
            .with_for_update()
        )
    ).scalar_one_or_none()


async def _side_effects(
    db: AsyncSession, order: Order, to: OrderStatus, chosen: Rider | None = None
) -> None:
    if to == S.accepted:
        if chosen is not None:  # demo staging hands the order straight to its rider
            await dispatch.assign_rider(db, order, chosen, started_at=order.accepted_at)
        else:
            await dispatch.offer(db, order, at=order.accepted_at)
    elif to == S.ready and order.rider_id is not None:
        # A sim rider already waiting at the counter picks up at once.
        rider = await db.get(Rider, order.rider_id)
        leg = await _open_leg_of(db, order)
        if rider and rider.is_sim and leg and leg.kind == LegKind.to_restaurant and leg.arrived_at:
            await transition(
                db, order.id, S.picked_up, Actor("system", rider_id=rider.id), at=order.ready_at
            )
    elif to == S.picked_up:
        rider = await db.get(Rider, order.rider_id)
        assert rider is not None  # noqa: S101 - guarded
        leg = await _open_leg_of(db, order)
        if leg is not None:
            leg.ended_at = clock.now()
        restaurant = latlng((await db.get(Restaurant, order.restaurant_id)).loc)  # type: ignore[union-attr]
        start = (
            restaurant if rider.is_sim else (await dispatch.position_of(db, rider.id) or restaurant)
        )
        await dispatch.open_leg(
            db,
            order,
            rider,
            LegKind.to_customer,
            start,
            latlng(order.drop_loc),
            order.picked_up_at,
        )
    elif to == S.delivered:
        rider = await db.get(Rider, order.rider_id)
        assert rider is not None  # noqa: S101 - guarded
        await dispatch.release_rider(db, rider)
        await dispatch.on_rider_available(db, rider)


# --- payments ---------------------------------------------------------------------------------


async def mark_paid(db: AsyncSession, order_id: uuid.UUID, payment_id: str) -> Order | None:
    """Idempotent: whichever of verify / webhook arrives first places the order; the other (and any
    replay) finds it no longer `pending_payment` and does nothing. The caller commits."""
    order = await lock(db, order_id)
    if order is None:
        return None
    if order.status == S.expired and not order.razorpay_payment_id:
        # Captured after the 15-minute window: keep the payment id so it can be refunded.
        order.razorpay_payment_id = payment_id
        log.warning("payment %s captured for expired order %s: refund it", payment_id, order.number)
    if order.status != S.pending_payment:
        return order
    order.razorpay_payment_id = payment_id
    order = await transition(db, order.id, S.placed, SYSTEM)
    return order


async def expire_stale(db: AsyncSession, order_ids: list[uuid.UUID] | None = None) -> int:
    """Lazy: an unpaid order older than 15 minutes becomes `expired` (nothing to release)."""
    q = (
        select(Order.id)
        .where(Order.status == S.pending_payment, Order.created_at <= clock.now() - PAYMENT_WINDOW)
        .with_for_update(skip_locked=True)
    )
    if order_ids is not None:
        q = q.where(Order.id.in_(order_ids))
    ids = list((await db.execute(q)).scalars())
    for oid in ids:
        await transition(db, oid, S.expired, SYSTEM)
    return len(ids)
