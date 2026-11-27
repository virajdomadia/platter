"""The stream loop (04 §3): one async generator behind `/orders/{id}/events`, `/restaurant/events`,
`/rider/events` and `/admin/events`.

Postgres is the bus. Every tick (1 s) the loop advances the lazy simulation for its scope, then
reads `order_events where seq > $cursor` — the durable log — and rider positions newer than its
position cursor, and yields them as SSE frames with `id: {seq}:{pos_ms}`. A reconnect sends that
id back as `Last-Event-ID`, so the loop replays exactly what was missed, from the log. (v3 adds
`LISTEN/NOTIFY` only as a wake-up for this same read; the log stays the source of truth.)
The loop closes itself at 280 s with `event: reconnect` (Vercel's function limit is 300 s).
"""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import Text, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.db import SessionFactory
from app.models import (
    ACTIVE_STATUSES,
    LegKind,
    Offer,
    Order,
    OrderEvent,
    Restaurant,
    Rider,
    RiderLeg,
)
from app.models.geo import latlng
from app.services import admin as admin_service
from app.services import eta as eta_service
from app.services import routing, sim, views
from app.services.dispatch import OFFER_KINDS
from app.services.events import STATUS_KINDS

TICK_S = 1.0
PING_EVERY_S = 15
RESTAURANT_RIDERS_EVERY = 3  # ticks
ADMIN_RIDERS_EVERY = 2  # ticks

ScopeKind = Literal["order", "restaurant", "rider", "admin"]


@dataclass
class Scope:
    kind: ScopeKind
    id: uuid.UUID | None = None


@dataclass
class Cursor:
    seq: int
    pos_ms: int

    @property
    def id(self) -> str:
        return f"{self.seq}:{self.pos_ms}"


def parse_cursor(value: str | None) -> Cursor | None:
    """`Last-Event-ID` (or `?since=`) = "{seq}:{pos_ms}"; a bare seq is accepted too."""
    if not value:
        return None
    seq, _, pos = value.strip().partition(":")
    try:
        return Cursor(max(0, int(seq)), max(0, int(pos or 0)))
    except ValueError:
        return None


def frame(event: str, data: Any, event_id: str | None = None) -> str:
    body = json.dumps(data, separators=(",", ":"), default=str)
    head = f"id: {event_id}\n" if event_id else ""
    return f"{head}event: {event}\ndata: {body}\n\n"


def event_frame(ev: OrderEvent, cursor: Cursor, scope: ScopeKind = "admin") -> str | None:
    oid = str(ev.order_id)
    if ev.kind in OFFER_KINDS:
        p = ev.payload
        data = {"order_id": oid, "state": p.get("state"), "attempt": p.get("attempt")}
        if scope != "order":  # the customer learns how many riders were asked, never who
            data |= {k: p.get(k) for k in ("offer_id", "rider_id", "expires_at")}
        return frame("offer", data, cursor.id)
    if ev.kind in STATUS_KINDS:
        data: dict[str, Any] = {"order_id": oid, "status": ev.kind, "at": ev.at.isoformat()}
        if ev.payload.get("reason"):
            data["reason"] = ev.payload["reason"]
        return frame("status", data, cursor.id)
    if ev.kind in ("rider_assigned", "rider_reassigned"):
        p = ev.payload
        rider = {
            "id": p.get("rider_id"),
            "name": p.get("name"),
            "vehicle": p.get("vehicle"),
            "phone_masked": p.get("phone_masked"),
        }
        data = {"order_id": oid, "rider": rider, "from_rider_id": p.get("from_rider_id")}
        return frame(ev.kind, data, cursor.id)
    if ev.kind == "route":
        p = ev.payload
        data = {
            "order_id": oid,
            "leg_id": p.get("leg_id"),
            "kind": p.get("kind"),
            "polyline": p.get("polyline"),
            "distance_m": p.get("distance_m"),
            "duration_s": p.get("duration_s"),
            "method": p.get("method"),
            "started_at": p.get("started_at"),
        }
        return frame("route", data, cursor.id)
    return None


def _scope_filter(q, scope: Scope):  # type: ignore[no-untyped-def]
    if scope.kind == "order":
        return q.where(OrderEvent.order_id == scope.id)
    if scope.kind == "restaurant":
        mine = select(Order.id).where(Order.restaurant_id == scope.id, Order.is_demo.is_(True))
        return q.where(OrderEvent.order_id.in_(mine))
    if scope.kind == "rider":
        mine = select(RiderLeg.order_id).where(RiderLeg.rider_id == scope.id)
        legs = select(func.cast(RiderLeg.id, Text)).where(RiderLeg.rider_id == scope.id)
        # After a reassign, the old rider still hears the status, never the new rider's route; a
        # rider hears only their own offers.
        offered = OrderEvent.kind.in_(OFFER_KINDS)
        return q.where(
            (
                OrderEvent.order_id.in_(mine)
                & ~offered
                & ((OrderEvent.kind != "route") | OrderEvent.payload["leg_id"].astext.in_(legs))
            )
            | (offered & (OrderEvent.payload["rider_id"].astext == str(scope.id)))
        )
    # admin: the public demo console hears demo orders only
    return q.where(OrderEvent.order_id.in_(select(Order.id).where(Order.is_demo.is_(True))))


async def _advance(db: AsyncSession, scope: Scope) -> None:
    if scope.kind == "order":
        await sim.advance(db, order_ids=[scope.id])  # type: ignore[list-item]
    elif scope.kind == "restaurant":
        await db.execute(
            update(Restaurant).where(Restaurant.id == scope.id).values(board_seen_at=clock.now())
        )
        await sim.advance(db, restaurant_id=scope.id)
    elif scope.kind == "rider":
        ids = list(
            (
                await db.execute(
                    select(Order.id).where(
                        Order.rider_id == scope.id, Order.status.in_(ACTIVE_STATUSES)
                    )
                )
            ).scalars()
        ) + list(
            (
                await db.execute(
                    select(Offer.order_id).where(Offer.rider_id == scope.id, Offer.state == "sent")
                )
            ).scalars()
        )
        if ids:
            await sim.advance(db, order_ids=ids)
    elif (await db.execute(text("select pg_try_advisory_xact_lock(2)"))).scalar():
        # Admin: one global advance at a time across every open console; the others just read.
        await sim.advance(db)
    await db.commit()


async def _order_positions(
    db: AsyncSession, order_id: uuid.UUID, cursor: Cursor, status_changed: bool, last_eta: list
) -> list[str]:
    order = await db.get(Order, order_id, populate_existing=True)
    if order is None or order.status not in ACTIVE_STATUSES:
        return []
    out: list[str] = []
    fix = None
    leg = await views.open_leg(db, order.id)
    moved = False
    if order.rider_id is not None:
        rider = await db.get(Rider, order.rider_id)
        assert rider is not None  # noqa: S101
        fix = await views.rider_fix(db, rider, leg, order.id)
        if fix is not None:
            fix_ms = clock.ms(fix.at)
            if rider.is_sim and leg is not None:
                moved = True
                cursor.pos_ms = max(cursor.pos_ms, fix_ms)
            elif fix_ms > cursor.pos_ms:
                moved = True
                cursor.pos_ms = fix_ms
            if moved:
                out.append(frame("rider", fix.model_dump(mode="json"), cursor.id))
    if moved or status_changed:
        restaurant = await db.get(Restaurant, order.restaurant_id)
        assert restaurant is not None  # noqa: S101
        found = await views.eta_for(db, order, restaurant, leg, fix)
        if found is not None and (not last_eta or last_eta[0] != (found.eta_s, found.phase)):
            last_eta[:] = [(found.eta_s, found.phase)]
            out.append(frame("eta", found.model_dump(mode="json"), cursor.id))
    return out


async def _restaurant_riders(
    db: AsyncSession, restaurant_id: uuid.UUID, cursor: Cursor
) -> list[str]:
    restaurant = await db.get(Restaurant, restaurant_id)
    assert restaurant is not None  # noqa: S101
    home = latlng(restaurant.loc)
    rows = (
        await db.execute(
            select(RiderLeg, Rider)
            .join(Rider, Rider.id == RiderLeg.rider_id)
            .join(Order, Order.id == RiderLeg.order_id)
            .where(
                Order.restaurant_id == restaurant_id,
                Order.is_demo.is_(True),
                RiderLeg.ended_at.is_(None),
                RiderLeg.kind == LegKind.to_restaurant,
            )
        )
    ).all()
    out = []
    for leg, rider in rows:
        fix = await views.rider_fix(db, rider, leg, leg.order_id)
        if fix is None:
            continue
        fix.distance_m = round(routing.haversine((fix.lat, fix.lng), home))
        data = fix.model_dump(mode="json")
        remaining = eta_service.remaining_on_leg(leg, (fix.lat, fix.lng))
        speed = eta_service.speed_mps(rider.is_sim, float(rider.speed_kmh), fix.speed_mps)
        data["eta_s"] = 0 if leg.arrived_at else round(remaining / speed)
        out.append(frame("rider", data, cursor.id))
    return out


async def stream(
    factory: SessionFactory,
    scope: Scope,
    cursor: Cursor | None,
    *,
    is_disconnected: Callable[[], Awaitable[bool]],
    lifetime_s: int = 280,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    on_tick: Callable[[AsyncSession, int], Awaitable[Any]] | None = None,
) -> AsyncIterator[str]:
    started = clock.now()
    last_ping = started
    tick = 0
    last_eta: list = []
    yield "retry: 1000\n\n"

    # Prime: a fresh page needs no second request. An order stream opens with the whole order;
    # the others with the current log position. A reconnect (cursor given) replays instead.
    async with factory() as db:
        await _advance(db, scope)
        if cursor is None:
            if scope.kind == "order":
                order = await db.get(Order, scope.id)
                if order is None:
                    return
                snap = await views.order_out(db, order)
                cursor = Cursor(snap.seq, clock.ms(clock.now()))
                if snap.eta:
                    last_eta[:] = [(snap.eta.eta_s, snap.eta.phase)]
                yield frame("snapshot", snap.model_dump(mode="json"), cursor.id)
            else:
                cursor = Cursor(await views.max_seq(db), clock.ms(clock.now()))
                yield frame("ready", {"seq": cursor.seq}, cursor.id)

    while True:
        if await is_disconnected():
            return
        if (clock.now() - started).total_seconds() >= lifetime_s:
            yield frame("reconnect", {"after_ms": 1000}, cursor.id)
            return
        status_changed = False
        async with factory() as db:
            if tick > 0 and (scope.kind != "admin" or tick % ADMIN_RIDERS_EVERY == 0):
                await _advance(db, scope)
            if on_tick is not None:
                await on_tick(db, tick)
                await db.commit()
            q = _scope_filter(select(OrderEvent), scope).where(OrderEvent.seq > cursor.seq)
            for ev in (await db.execute(q.order_by(OrderEvent.seq).limit(500))).scalars():
                cursor.seq = ev.seq
                if ev.kind in STATUS_KINDS or ev.kind == "route":
                    status_changed = True
                out = event_frame(ev, cursor, scope.kind)
                if out:
                    yield out
            if scope.kind == "order":
                for out in await _order_positions(db, scope.id, cursor, status_changed, last_eta):  # type: ignore[arg-type]
                    yield out
            elif scope.kind == "restaurant" and tick % RESTAURANT_RIDERS_EVERY == 0:
                for out in await _restaurant_riders(db, scope.id, cursor):  # type: ignore[arg-type]
                    yield out
            elif scope.kind == "admin" and tick % ADMIN_RIDERS_EVERY == 0:
                riders = await admin_service.riders(db)
                cursor.pos_ms = clock.ms(clock.now())
                yield frame(
                    "riders", {"riders": [r.model_dump(mode="json") for r in riders]}, cursor.id
                )
        now = clock.now()
        if (now - last_ping).total_seconds() >= PING_EVERY_S:
            last_ping = now
            yield frame("ping", {"at": now.isoformat()})
        tick += 1
        await sleep(TICK_S)
