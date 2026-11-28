"""Refunds (v2 L5): a paid online order that won't be eaten gets its money back, exactly once.

`request()` runs inside the transaction that rejects / cancels the order (or finds a payment that
arrived after it expired, or an admin's refund): it inserts the one `refunds` row per order
(unique), so a retry or a race can't create a second. Razorpay is called only after that commit,
by `send()`, which first claims the row with a conditional update; a claim that loses does
nothing. Razorpay itself refuses a second full refund of the same payment, a last backstop if a
process dies between Razorpay's answer and our write (the row then stays `sending` and an admin
retry re-sends it once it is 5 minutes old).
"""

import datetime as dt
import logging
import uuid

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.config import Settings
from app.core.errors import ApiError
from app.models import Order, OrderStatus, PaymentKind, Refund
from app.services import ledger, razorpay

log = logging.getLogger(__name__)
STUCK = dt.timedelta(minutes=5)


def refundable(order: Order) -> bool:
    return order.payment == PaymentKind.razorpay and bool(order.razorpay_payment_id)


async def request(db: AsyncSession, order: Order, reason: str) -> Refund | None:
    """In the caller's transaction. None if there's nothing to refund (cash, or never paid);
    the existing row if one was already requested."""
    if not refundable(order):
        return None
    now = clock.now()
    await db.execute(
        pg_insert(Refund)
        .values(
            id=uuid.uuid4(),
            order_id=order.id,
            amount_paise=order.total_paise,
            reason=reason,
            status="pending",
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(index_elements=["order_id"])
    )
    if order.status == OrderStatus.delivered:
        await ledger.on_refunded(db, order, order.total_paise)
    return (
        await db.execute(
            select(Refund)
            .where(Refund.order_id == order.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def send(db: AsyncSession, settings: Settings, order_id: uuid.UUID) -> Refund | None:
    """After the request's commit: claim the row, call Razorpay, record the answer. Never raises
    (the order action has already happened); a failure stays `failed` for an admin retry."""
    now = clock.now()
    claimed = (
        await db.execute(
            update(Refund)
            .where(
                Refund.order_id == order_id,
                or_(
                    Refund.status.in_(("pending", "failed")),
                    (Refund.status == "sending") & (Refund.updated_at < now - STUCK),
                ),
            )
            .values(status="sending", updated_at=now)
            .returning(Refund)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    await db.commit()
    if claimed is None:
        return None
    order = await db.get(Order, order_id)
    assert order is not None and order.razorpay_payment_id  # noqa: S101 - refundable
    try:
        refund_id = await razorpay.refund(
            settings, order.razorpay_payment_id, claimed.amount_paise, receipt=order.number
        )
        status, rid = "processed", refund_id
    except ApiError as exc:
        log.warning("refund for %s failed: %s", order.number, exc.code)
        status, rid = "failed", None
    await db.execute(
        update(Refund)
        .where(Refund.id == claimed.id)
        .values(status=status, razorpay_refund_id=rid, updated_at=clock.now())
    )
    await db.commit()
    return await db.get(Refund, claimed.id, populate_existing=True)
