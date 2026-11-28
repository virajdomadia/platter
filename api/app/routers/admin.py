"""The admin 👑 (06 §C): live map, orders with stuck flags, riders by distance, reassign, stream."""

import uuid

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import schemas as s
from app.core import clock
from app.core.config import Settings, current_settings
from app.core.db import get_session
from app.core.errors import ApiError
from app.models import ACTIVE_STATUSES, Order, OrderStatus, PaymentKind, Restaurant, User
from app.routers import sse
from app.services import admin, auth, demo, dispatch, ledger, limits, refunds, sim, views
from app.services import stream as stream_service
from app.services.events import Actor

router = APIRouter(prefix="/admin", tags=["admin"])
AMBIENT_EVERY = 20  # stream ticks


@router.get("/map", response_model=s.AdminMap)
async def live_map(
    _: User = Depends(auth.require_admin), db: AsyncSession = Depends(get_session)
) -> s.AdminMap:
    await sim.advance(db)
    await db.commit()
    return await admin.live_map(db)


@router.get("/orders", response_model=list[s.AdminOrder])
async def list_orders(
    status: str | None = Query(default=None),
    stuck: bool = Query(default=False),
    _: User = Depends(auth.require_admin),
    db: AsyncSession = Depends(get_session),
) -> list[s.AdminOrder]:
    await sim.advance(db)
    await db.commit()
    try:
        return await admin.active_orders(db, only_stuck=stuck, status=status)
    except ValueError as exc:
        raise ApiError(422, "validation", "Unknown status") from exc


@router.get("/riders", response_model=list[s.AdminRider])
async def riders(
    near: str | None = Query(default=None, description="lat,lng"),
    _: User = Depends(auth.require_admin),
    db: AsyncSession = Depends(get_session),
) -> list[s.AdminRider]:
    return await admin.riders(db, admin.parse_near(near))


@router.post("/orders/{order_id}/reassign", response_model=s.AdminOrder)
async def reassign(
    order_id: uuid.UUID,
    body: s.ReassignIn,
    user: User = Depends(auth.require_admin),
    db: AsyncSession = Depends(get_session),
) -> s.AdminOrder:
    try:
        rider_id = uuid.UUID(body.rider_id)
    except ValueError as exc:
        raise ApiError(404, "not_found", "No such rider") from exc
    order = await dispatch.reassign(db, order_id, rider_id, Actor("admin", user_id=user.id))
    await db.commit()
    restaurant = await db.get(Restaurant, order.restaurant_id)
    assert restaurant is not None  # noqa: S101
    fresh = await db.get(Order, order.id, populate_existing=True)
    assert fresh is not None  # noqa: S101
    return await admin.admin_order(db, fresh, restaurant, clock.now())


@router.get("/payouts", response_model=s.PayoutsOut)
async def payouts(
    user: User = Depends(auth.require_admin), db: AsyncSession = Depends(get_session)
) -> s.PayoutsOut:
    """Balances by account, the platform's take, and paid-online orders that can be refunded.
    The admin login is the public demo: it sees the demo's money only."""
    closed = (
        OrderStatus.delivered,
        OrderStatus.rejected,
        OrderStatus.cancelled,
        OrderStatus.expired,
    )
    rows = (
        (
            await db.execute(
                select(Order)
                .where(
                    Order.is_demo.is_(user.is_demo),
                    Order.payment == PaymentKind.razorpay,
                    Order.razorpay_payment_id.is_not(None),
                    Order.status.in_(closed),
                )
                .order_by(Order.created_at.desc())
                .limit(30)
            )
        )
        .scalars()
        .all()
    )
    return s.PayoutsOut(
        accounts=await ledger.accounts(db, user.is_demo),
        platform_paise=await ledger.balance(db, ledger.PLATFORM, user.is_demo),
        refundable=[
            s.RefundableOrder(
                id=str(o.id),
                number=o.number,
                status=o.status.value,  # type: ignore[arg-type]
                total_paise=o.total_paise,
                refund=await views.refund_of(db, o.id),
            )
            for o in rows
        ],
    )


@router.post("/payouts", response_model=s.PayoutsOut, status_code=201)
async def pay(
    body: s.PayoutIn,
    request: Request,
    user: User = Depends(auth.require_admin),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(current_settings),
) -> s.PayoutsOut:
    """Mark money paid to a restaurant or rider. 422 above the balance; 409 on a reused ref."""
    await limits.hit(db, f"money:{limits.client_ip(request, settings)}", 30)
    await ledger.pay(
        db,
        account=body.account,
        amount_paise=body.amount_paise,
        reference=body.reference,
        paid_by=user.id,
        is_demo=user.is_demo,
    )
    await db.commit()
    return await payouts(user, db)


@router.post("/orders/{order_id}/refund", response_model=s.RefundableOrder)
async def refund(
    order_id: uuid.UUID,
    request: Request,
    user: User = Depends(auth.require_admin),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(current_settings),
) -> s.RefundableOrder:
    """Refund a closed, paid-online order in full (once; a repeat re-sends a failed refund)."""
    await limits.hit(db, f"money:{limits.client_ip(request, settings)}", 30)
    order = await db.get(Order, order_id)
    if order is None or order.is_demo != user.is_demo:  # the demo admin never touches real money
        raise ApiError(404, "not_found", "No such order")
    if not refunds.refundable(order):
        raise ApiError(409, "nothing_to_refund", "Only an order paid online can be refunded")
    if order.status in ACTIVE_STATUSES or order.status == OrderStatus.pending_payment:
        raise ApiError(409, "order_active", "Refund it once it's delivered, rejected or cancelled")
    await refunds.request(db, order, "admin")
    await db.commit()
    await refunds.send(db, settings, order.id)
    return s.RefundableOrder(
        id=str(order.id),
        number=order.number,
        status=order.status.value,  # type: ignore[arg-type]
        total_paise=order.total_paise,
        refund=await views.refund_of(db, order.id),
    )


@router.get("/events", response_class=StreamingResponse)
async def events(
    request: Request,
    since: str | None = Query(default=None),
    _: User = Depends(auth.require_admin),
    db: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    settings: Settings = request.app.state.settings

    async def ambient(tick_db: AsyncSession, tick: int) -> None:
        if settings.ambient_orders and tick % AMBIENT_EVERY == 10:
            await demo.keep_alive(tick_db)

    return await sse.respond(request, db, stream_service.Scope("admin"), since, ambient)
