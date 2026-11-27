"""The rider app ðŸ›µ (06 Â§C): my job, GPS uplink, picked up / delivered, my stream."""

import datetime as dt
import uuid
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import schemas as s
from app.core import clock
from app.core.config import Settings, current_settings
from app.core.db import get_session
from app.core.errors import not_found
from app.models import (
    ACTIVE_STATUSES,
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
from app.routers import sse
from app.services import auth, dispatch, limits, orders, routing, sim, views
from app.services import stream as stream_service
from app.services.events import Actor

router = APIRouter(prefix="/rider", tags=["rider"])
S = OrderStatus
IST = ZoneInfo("Asia/Kolkata")
JUMP_M = 200
JUMP_WINDOW = dt.timedelta(seconds=3)
ARRIVED_M = 60
CLOCK_SKEW = dt.timedelta(seconds=30)


async def current_job(db: AsyncSession, rider: Rider) -> Order | None:
    return (
        await db.execute(
            select(Order)
            .where(Order.rider_id == rider.id, Order.status.in_(ACTIVE_STATUSES))
            .order_by(Order.accepted_at)
            .limit(1)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def rider_me(db: AsyncSession, rider: Rider) -> s.RiderMe:
    job = await current_job(db, rider)
    start = clock.now().astimezone(IST).replace(hour=0, minute=0, second=0, microsecond=0)
    done = (
        (
            await db.execute(
                select(Order.distance_m).where(
                    Order.rider_id == rider.id, Order.delivered_at >= start
                )
            )
        )
        .scalars()
        .all()
    )
    pos = await db.get(RiderPosition, rider.id, populate_existing=True)
    await db.refresh(rider)
    return s.RiderMe(
        rider=s.RiderSelf(
            id=str(rider.id), name=rider.name, vehicle=rider.vehicle, status=rider.status.value
        ),
        job=await views.job(db, job) if job else None,
        today=s.RiderToday(
            deliveries=len(done), pay_paise=sum(views.rider_pay_preview(d) for d in done)
        ),
        last_fix_s=views.seconds_since(pos.recorded_at) if pos else None,
        seq=await views.max_seq(db),
        offer=await views.rider_offer(db, rider),
    )


@router.get("/me", response_model=s.RiderMe)
async def me(
    who: auth.RiderUser = Depends(auth.require_rider), db: AsyncSession = Depends(get_session)
) -> s.RiderMe:
    job = await current_job(db, who.rider)
    offered = (
        await db.execute(
            select(Offer.order_id).where(Offer.rider_id == who.rider.id, Offer.state == "sent")
        )
    ).scalars()
    ids = [job.id] if job else []
    ids += [i for i in offered if i not in ids]
    if ids:
        await sim.advance(db, order_ids=ids)
        await db.commit()
    return await rider_me(db, who.rider)


async def _limit(request: Request, db: AsyncSession, settings: Settings) -> None:
    await limits.hit(db, f"rider:{limits.client_ip(request, settings)}", 60)


@router.post("/status", response_model=s.RiderMe)
async def set_status(
    body: s.RiderStatusIn,
    request: Request,
    who: auth.RiderUser = Depends(auth.require_rider),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(current_settings),
) -> s.RiderMe:
    """Online (`available`) / offline. Offline riders get no offers; finish the job first."""
    await _limit(request, db, settings)
    rider = (
        await db.execute(select(Rider).where(Rider.id == who.rider.id).with_for_update())
    ).scalar_one()
    await dispatch.set_status(db, rider, RiderStatus(body.status))
    await db.commit()
    return await rider_me(db, rider)


async def _answer(
    request: Request,
    offer_id: uuid.UUID,
    to: str,
    who: auth.RiderUser,
    db: AsyncSession,
    settings: Settings,
) -> s.Job | None:
    await _limit(request, db, settings)
    actor = Actor("rider", user_id=who.user.id, rider_id=who.rider.id)
    order = await dispatch.answer(db, offer_id, who.rider.id, to, actor)
    await db.commit()
    return await views.job(db, order) if to == "accepted" else None


@router.post("/offers/{offer_id}/accept", response_model=s.Job | None)
async def accept_offer(
    offer_id: uuid.UUID,
    request: Request,
    who: auth.RiderUser = Depends(auth.require_rider),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(current_settings),
) -> s.Job | None:
    """409 `offer_expired` after the 30 s, `offer_taken` if it was already answered."""
    return await _answer(request, offer_id, "accepted", who, db, settings)


@router.post("/offers/{offer_id}/decline", response_model=s.Job | None)
async def decline_offer(
    offer_id: uuid.UUID,
    request: Request,
    who: auth.RiderUser = Depends(auth.require_rider),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(current_settings),
) -> s.Job | None:
    return await _answer(request, offer_id, "declined", who, db, settings)


@router.post("/position", status_code=204)
async def position(
    body: s.PositionIn,
    who: auth.RiderUser = Depends(auth.require_rider),
    db: AsyncSession = Depends(get_session),
) -> Response:
    """`recorded_at` is server time; the phone's `at` only orders fixes from the same phone. A fix
    more than 200 m from the previous one within 3 s is a GPS jump and is dropped."""
    rider = who.rider
    now = clock.now()
    # A phone clock set in the future can't freeze the shared demo phone's later fixes out.
    at = min(body.at, now + CLOCK_SKEW)
    prev = await db.get(RiderPosition, rider.id)
    if prev is not None:
        if prev.client_at is not None and at <= prev.client_at:
            return Response(status_code=204, headers={"X-Ignored": "stale"})
        moved = routing.haversine(latlng(prev.loc), (body.lat, body.lng))
        if now - prev.recorded_at < JUMP_WINDOW and moved > JUMP_M:
            return Response(status_code=204, headers={"X-Ignored": "jump"})
    job = await current_job(db, rider)
    heading = round(body.heading) % 360 if body.heading is not None else None
    await sim.upsert_position(
        db,
        rider.id,
        (body.lat, body.lng),
        heading,
        body.speed_mps,
        order_id=job.id if job and job.status != S.placed else None,
        client_at=at,
    )
    if job is not None:
        # A real rider who reaches the kitchen is "at the door" on the board.
        leg = (
            await db.execute(
                select(RiderLeg).where(
                    RiderLeg.order_id == job.id,
                    RiderLeg.ended_at.is_(None),
                    RiderLeg.kind == LegKind.to_restaurant,
                    RiderLeg.arrived_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        restaurant = await db.get(Restaurant, job.restaurant_id)
        if leg is not None and restaurant is not None:
            if routing.haversine(latlng(restaurant.loc), (body.lat, body.lng)) <= ARRIVED_M:
                leg.arrived_at = now
    await db.commit()
    return Response(status_code=204)


@router.post("/orders/{order_id}/transition", response_model=s.Job | None)
async def transition(
    order_id: uuid.UUID,
    body: s.RiderTransitionIn,
    who: auth.RiderUser = Depends(auth.require_rider),
    db: AsyncSession = Depends(get_session),
) -> s.Job | None:
    """Picked up (only once the kitchen marked it ready) / Delivered. Returns the next job, if a
    waiting order was handed to this rider on delivery."""
    order = await db.get(Order, order_id)
    if order is None or order.rider_id != who.rider.id:
        raise not_found("No such job")
    await sim.advance(db, order_ids=[order_id])
    actor = Actor("rider", user_id=who.user.id, rider_id=who.rider.id)
    await orders.transition(db, order_id, OrderStatus(body.to), actor)
    await db.commit()
    nxt = await current_job(db, who.rider)
    return await views.job(db, nxt) if nxt else None


@router.get("/events", response_class=StreamingResponse)
async def events(
    request: Request,
    since: str | None = Query(default=None),
    who: auth.RiderUser = Depends(auth.require_rider),
    db: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    rider_id = who.rider.id
    return await sse.respond(request, db, stream_service.Scope("rider", rider_id), since)
