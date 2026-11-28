"""Money to three parties (PRD decision 4, v2 L5). Integer paise, signed, per account.

A delivered order writes, once (unique per order + kind), in the delivery's own transaction:
  restaurant `sale`  = 80% of the food subtotal (rounded down)
  platform   `fee`   = the rest of the subtotal
  rider      `delivery` = ₹30 + ₹8 per km of the order's road distance
  platform   `delivery_margin` = delivery fee + platform fee − the rider's pay (may be negative)
so an order's entries always sum to exactly what the customer paid. A refund of a delivered order
adds one platform `refund` entry for the whole total (the platform carries it), so the sum is then
zero. A payout is a negative entry on the paid account, never above its balance.

Every entry carries the order's `is_demo`: the public demo's money and real money never mix (the
demo admin, board and rider phone only ever see demo entries).
"""

import uuid

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app import schemas as s
from app.core import clock
from app.core.errors import ApiError
from app.models import LedgerEntry, Order, Payout, Restaurant, Rider

PLATFORM = "platform"
SALE_PERCENT = 80


def restaurant_account(restaurant_id: uuid.UUID) -> str:
    return f"restaurant:{restaurant_id}"


def rider_account(rider_id: uuid.UUID) -> str:
    return f"rider:{rider_id}"


def rider_pay(distance_m: int) -> int:
    """What the rider earns for a drop: ₹30 + ₹8 per km (shown on the job, written on delivery)."""
    return 3000 + 800 * round(distance_m / 1000)


def split(order: Order) -> list[tuple[str, str, int]]:
    """(account, kind, paise) for a delivered order; sums to `order.total_paise`."""
    assert order.rider_id is not None  # noqa: S101 - only delivered orders, which had a rider
    sale = order.subtotal_paise * SALE_PERCENT // 100
    pay = rider_pay(order.distance_m)
    return [
        (restaurant_account(order.restaurant_id), "sale", sale),
        (PLATFORM, "fee", order.subtotal_paise - sale),
        (rider_account(order.rider_id), "delivery", pay),
        (PLATFORM, "delivery_margin", order.delivery_fee_paise + order.platform_fee_paise - pay),
    ]


async def _write(db: AsyncSession, order: Order, rows: list[tuple[str, str, int]]) -> None:
    at = clock.now()
    await db.execute(
        pg_insert(LedgerEntry)
        .values(
            [
                {
                    "account": account,
                    "kind": kind,
                    "amount_paise": paise,
                    "order_id": order.id,
                    "is_demo": order.is_demo,
                    "created_at": at,
                }
                for account, kind, paise in rows
            ]
        )
        .on_conflict_do_nothing(
            index_elements=["order_id", "kind"], index_where=text("order_id is not null")
        )
    )


async def on_delivered(db: AsyncSession, order: Order) -> None:
    """In the delivery's transaction. A second call writes nothing (unique per order + kind)."""
    await _write(db, order, split(order))


async def on_refunded(db: AsyncSession, order: Order, amount_paise: int) -> None:
    """A delivered order refunded: the platform carries it, so the order nets to zero."""
    await _write(db, order, [(PLATFORM, "refund", -amount_paise)])


async def balance(db: AsyncSession, account: str, is_demo: bool) -> int:
    q = select(func.coalesce(func.sum(LedgerEntry.amount_paise), 0)).where(
        LedgerEntry.account == account, LedgerEntry.is_demo.is_(is_demo)
    )
    return int((await db.execute(q)).scalar_one())


async def pay(
    db: AsyncSession,
    *,
    account: str,
    amount_paise: int,
    reference: str,
    paid_by: uuid.UUID,
    is_demo: bool,
) -> Payout:
    """Mark money paid out of `account`. One payout per account at a time (advisory lock), so two
    clicks can't both pass the balance check; 422 above the balance, 409 on a reused reference."""
    if account == PLATFORM or not account.startswith(("restaurant:", "rider:")):
        raise ApiError(422, "validation", "Payouts go to a restaurant or a rider")
    await db.execute(text("select pg_advisory_xact_lock(hashtext(:k))"), {"k": f"pay:{account}"})
    held = await balance(db, account, is_demo)
    if amount_paise > held:
        raise ApiError(
            422, "over_balance", "That's more than this account holds", {"balance_paise": held}
        )
    dup = select(Payout.id).where(Payout.account == account, Payout.reference == reference)
    if (await db.execute(dup)).first():
        raise ApiError(409, "duplicate_reference", "This reference was already used for a payout")
    p = Payout(
        id=uuid.uuid4(),
        account=account,
        amount_paise=amount_paise,
        reference=reference,
        paid_by=paid_by,
        is_demo=is_demo,
        paid_at=clock.now(),
    )
    db.add(p)
    await db.flush()
    db.add(
        LedgerEntry(
            account=account,
            kind="payout",
            amount_paise=-amount_paise,
            payout_id=p.id,
            is_demo=is_demo,
            created_at=p.paid_at,
        )
    )
    await db.flush()
    return p


async def earnings(db: AsyncSession, account: str, is_demo: bool) -> s.Earnings:
    """One account's balance and latest entries, on one side of the demo partition."""
    mine = (LedgerEntry.account == account) & LedgerEntry.is_demo.is_(is_demo)
    earned, paid = (
        await db.execute(
            select(
                func.coalesce(
                    func.sum(LedgerEntry.amount_paise).filter(LedgerEntry.kind != "payout"), 0
                ),
                func.coalesce(
                    -func.sum(LedgerEntry.amount_paise).filter(LedgerEntry.kind == "payout"), 0
                ),
            ).where(mine)
        )
    ).one()
    rows = (
        await db.execute(
            select(LedgerEntry, Order.number)
            .outerjoin(Order, Order.id == LedgerEntry.order_id)
            .where(mine)
            .order_by(LedgerEntry.created_at.desc(), LedgerEntry.id.desc())
            .limit(50)
        )
    ).all()
    return s.Earnings(
        balance_paise=int(earned) - int(paid),
        earned_paise=int(earned),
        paid_paise=int(paid),
        entries=[
            s.LedgerLine(kind=e.kind, amount_paise=e.amount_paise, order_number=n, at=e.created_at)  # type: ignore[arg-type]
            for e, n in rows
        ],
    )


async def accounts(db: AsyncSession, is_demo: bool) -> list[s.AccountBalance]:
    """Every restaurant and rider account with money on it, highest balance first."""
    rows = (
        await db.execute(
            select(
                LedgerEntry.account,
                func.sum(LedgerEntry.amount_paise),
                func.coalesce(
                    -func.sum(LedgerEntry.amount_paise).filter(LedgerEntry.kind == "payout"), 0
                ),
            )
            .where(LedgerEntry.is_demo.is_(is_demo), LedgerEntry.account != PLATFORM)
            .group_by(LedgerEntry.account)
        )
    ).all()
    out = []
    for account, bal, paid in rows:
        kind, _, raw = account.partition(":")
        model = Restaurant if kind == "restaurant" else Rider
        found = await db.get(model, uuid.UUID(raw))
        name = found.name if found else account
        out.append(
            s.AccountBalance(
                account=account,
                name=name,
                kind="restaurant" if kind == "restaurant" else "rider",
                balance_paise=int(bal),
                paid_paise=int(paid),
            )
        )
    return sorted(out, key=lambda a: (-a.balance_paise, a.name))
