"""Customer orders (06 §C): quote, place (COD / Razorpay), verify, list, read, cancel, stream."""

import uuid

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import schemas as s
from app.core.config import Settings, current_settings
from app.core.db import get_session
from app.core.errors import ApiError, not_found
from app.models import ACTIVE_STATUSES, Order, OrderStatus, PaymentKind, User
from app.routers import sse
from app.services import auth, limits, orders, razorpay, sim, views
from app.services import stream as stream_service
from app.services.events import Actor

router = APIRouter(prefix="/orders", tags=["orders"])


def _uuid(value: str, what: str = "item") -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise ApiError(422, "item_unavailable", f"Unknown {what}", {"ids": [value]}) from exc


async def _quote(db: AsyncSession, body: s.QuoteIn) -> orders.Quote:
    try:
        restaurant_id = uuid.UUID(body.restaurant_id)
    except ValueError as exc:
        raise not_found("No such restaurant") from exc
    items = [(_uuid(line.id), line.qty) for line in body.items]
    return await orders.quote(db, restaurant_id, items, body.address.lat, body.address.lng)


def quote_out(q: orders.Quote) -> s.QuoteOut:
    return s.QuoteOut(
        items=[s.QuoteItem(**i) for i in q.items_json],
        subtotal_paise=q.subtotal_paise,
        delivery_fee_paise=q.delivery_fee_paise,
        platform_fee_paise=q.platform_fee_paise,
        total_paise=q.total_paise,
        distance_m=q.distance_m,
        eta_s=q.eta_s,
        method=q.method,  # type: ignore[arg-type]
    )


async def own_order(db: AsyncSession, order_id: uuid.UUID, user: User) -> Order:
    order = await db.get(Order, order_id, populate_existing=True)
    if order is None or order.user_id != user.id:
        raise not_found("No such order")
    return order


@router.post("/quote", response_model=s.QuoteOut)
async def quote(
    body: s.QuoteIn,
    user: User = Depends(auth.require_user),
    db: AsyncSession = Depends(get_session),
) -> s.QuoteOut:
    # Each quote is an OSRM call under Platter's User-Agent (public server: ~1 req/s).
    await limits.hit(db, f"quote:{user.id}", 30)
    return quote_out(await _quote(db, body))


@router.get("/config", response_model=s.PaymentsConfig)
async def payments_config(settings: Settings = Depends(current_settings)) -> s.PaymentsConfig:
    return s.PaymentsConfig(
        razorpay_key_id=settings.razorpay_key_id if settings.razorpay_enabled else None
    )


@router.post("", response_model=s.OrderStart, status_code=201)
async def place(
    body: s.OrderIn,
    user: User = Depends(auth.require_user),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(current_settings),
) -> s.OrderStart:
    """Prices everything again server-side; the client's total is only compared, never charged."""
    await limits.hit(db, f"place:{user.id}", 10)
    payment = PaymentKind(body.payment)
    if payment == PaymentKind.razorpay and not settings.razorpay_enabled:
        raise ApiError(
            503, "payments_off", "Online payment is switched off — choose cash on delivery"
        )
    q = await _quote(db, body)
    if body.expected_total_paise is not None and body.expected_total_paise != q.total_paise:
        # The road distance (OSRM vs the straight-line fallback) moved the fee since checkout.
        raise ApiError(
            409,
            "price_changed",
            "The delivery fee changed since you opened checkout. Check the new total.",
            {"quote": quote_out(q).model_dump()},
        )
    order = await orders.create(
        db,
        user.id,
        q,
        lat=body.address.lat,
        lng=body.address.lng,
        address_line=body.address_line,
        payment=payment,
        note=body.note,
        actor=Actor("customer", user_id=user.id),
    )
    start = None
    if payment == PaymentKind.razorpay:
        rp_order = await razorpay.create_order(
            settings, amount_paise=order.total_paise, receipt=order.number
        )
        order.razorpay_order_id = rp_order
        start = s.RazorpayStart(
            order_id=rp_order,
            key_id=settings.razorpay_key_id or "",
            amount_paise=order.total_paise,
            name="Platter",
            description=f"{order.number} · {q.restaurant.name}",
            prefill={"name": user.name, "email": user.email, "contact": user.phone or ""},
        )
    await db.commit()
    return s.OrderStart(order=await views.order_out(db, order), razorpay=start)


@router.post("/{order_id}/verify", response_model=s.OrderOut)
async def verify(
    order_id: uuid.UUID,
    body: s.VerifyIn,
    user: User = Depends(auth.require_user),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(current_settings),
) -> s.OrderOut:
    order = await own_order(db, order_id, user)
    if not order.razorpay_order_id or not razorpay.verify_payment(
        settings, order.razorpay_order_id, body.razorpay_payment_id, body.razorpay_signature
    ):
        raise ApiError(400, "bad_signature", "We couldn't confirm that payment")
    order = await orders.mark_paid(db, order.id, body.razorpay_payment_id) or order
    await db.commit()
    if order.status == OrderStatus.expired:
        raise ApiError(
            409,
            "payment_late",
            "Your payment came after this order expired. It will be refunded; please order again.",
        )
    return await views.order_out(db, order)


@router.get("", response_model=list[s.OrderCard])
async def list_orders(
    user: User = Depends(auth.require_user), db: AsyncSession = Depends(get_session)
) -> list[s.OrderCard]:
    mine = select(Order.id).where(Order.user_id == user.id, Order.status.in_(ACTIVE_STATUSES))
    active = list((await db.execute(mine)).scalars())
    if active:
        await sim.advance(db, order_ids=active)
        await db.commit()
    rows = (
        await db.execute(
            select(Order)
            .where(Order.user_id == user.id, Order.status != OrderStatus.pending_payment)
            .order_by(Order.created_at.desc())
            .limit(50)
        )
    ).scalars()
    return [await views.order_card(db, o) for o in rows]


@router.get("/{order_id}", response_model=s.OrderOut)
async def read(
    order_id: uuid.UUID,
    user: User = Depends(auth.require_user),
    db: AsyncSession = Depends(get_session),
) -> s.OrderOut:
    await own_order(db, order_id, user)
    await sim.advance(db, order_ids=[order_id])
    await db.commit()
    return await views.order_out(db, await own_order(db, order_id, user))


@router.post("/{order_id}/cancel", response_model=s.OrderOut)
async def cancel(
    order_id: uuid.UUID,
    user: User = Depends(auth.require_user),
    db: AsyncSession = Depends(get_session),
) -> s.OrderOut:
    await own_order(db, order_id, user)
    order = await orders.transition(
        db, order_id, OrderStatus.cancelled, Actor("customer", user_id=user.id)
    )
    await db.commit()
    return await views.order_out(db, order)


@router.get("/{order_id}/events", response_class=StreamingResponse)
async def events(
    order_id: uuid.UUID,
    request: Request,
    since: str | None = Query(default=None),
    user: User = Depends(auth.require_user),
    db: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """SSE for one order — its owner only (authorised again on every reconnect)."""
    await own_order(db, order_id, user)
    return await sse.respond(request, db, stream_service.Scope("order", order_id), since)
