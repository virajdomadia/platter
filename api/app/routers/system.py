"""Health checks and the Razorpay webhook."""

import json
import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.config import Settings, current_settings
from app.core.db import get_session
from app.core.errors import ApiError
from app.models import Order, OrderStatus, WebhookEvent
from app.services import orders, razorpay, refunds

router = APIRouter(tags=["system"])
log = logging.getLogger(__name__)


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
async def ready(db: AsyncSession = Depends(get_session)) -> dict[str, str]:
    await db.execute(text("select postgis_lib_version()"))
    return {"status": "ok"}


@router.post("/webhooks/razorpay")
async def razorpay_webhook(
    request: Request,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(current_settings),
) -> dict[str, str]:
    """`payment.captured` → the same idempotent `mark_paid` as verify; event ids are deduped, so
    a replay is a no-op. `payment.failed` changes nothing (the order expires at 15 min)."""
    if settings.razorpay_webhook_secret is None:
        raise ApiError(503, "payments_off", "Webhook not configured")
    body = await request.body()
    if not razorpay.verify_webhook(settings, body, request.headers.get("x-razorpay-signature", "")):
        raise ApiError(400, "bad_signature", "Signature mismatch")
    event_id = request.headers.get("x-razorpay-event-id") or ""
    try:
        data = json.loads(body)
    except ValueError as exc:
        raise ApiError(400, "bad_payload", "Not JSON") from exc
    kind = data.get("event", "")
    if event_id:
        db.add(WebhookEvent(id=event_id, event=kind, received_at=clock.now()))
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            return {"status": "duplicate"}
    if kind == "payment.captured":
        payment = data.get("payload", {}).get("payment", {}).get("entity", {})
        rp_order = payment.get("order_id")
        order = (
            await db.execute(select(Order).where(Order.razorpay_order_id == rp_order))
        ).scalar_one_or_none()
        if order is None or payment.get("amount") not in (None, order.total_paise):
            log.warning("captured payment %s matches no order total", payment.get("id"))
        else:
            paid = await orders.mark_paid(db, order.id, payment.get("id", ""))
            await db.commit()
            if paid is not None and paid.status == OrderStatus.expired:
                await refunds.send(db, settings, paid.id)
    await db.commit()
    return {"status": "ok"}
