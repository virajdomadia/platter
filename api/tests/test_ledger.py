"""v2 L5 money (TDD): a delivered order's ledger entries sum to what the customer paid, written
once; a paid order that won't arrive is refunded exactly once (even when two requests race), and
a refunded delivered order nets to zero; payouts never exceed a balance, even when two land at once.
And the walls: the demo admin / kitchen / phone never see or move real money."""

import asyncio
import uuid

import pytest
from sqlalchemy import func, select, text

from app.core import clock
from app.models import LedgerEntry, Order, OrderStatus, Refund
from app.services import ledger, orders, razorpay, refunds
from app.services.events import Actor
from tests.conftest import login, make_client, place, take_offer
from tests.conftest import test_settings as app_settings

pytestmark = pytest.mark.db
S = OrderStatus
ADMIN = "admin@platter.demo"


@pytest.fixture
def rzp(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, int]]:
    """Razorpay's refund API, mocked: records (payment_id, amount) and answers a refund id."""
    calls: list[tuple[str, int]] = []

    async def refund(settings, payment_id: str, amount_paise: int, *, receipt: str) -> str:  # type: ignore[no-untyped-def]
        calls.append((payment_id, amount_paise))
        await asyncio.sleep(0.01)  # let a racing request in
        return f"rfnd_{len(calls)}"

    monkeypatch.setattr(razorpay, "refund", refund)
    return calls


async def deliver(db, order: Order) -> Order:  # type: ignore[no-untyped-def]
    kitchen = Actor("restaurant", restaurant_id=order.restaurant_id)
    await orders.transition(db, order.id, S.accepted, kitchen)
    await db.commit()
    order = await take_offer(db, order.id)
    for to in (S.preparing, S.ready):
        await orders.transition(db, order.id, to, kitchen)
    await db.commit()
    order = await db.get(Order, order.id, populate_existing=True)
    if order.status == S.ready:  # a sim already waiting picks up at once; otherwise the rider
        await orders.transition(db, order.id, S.picked_up, Actor("rider", rider_id=order.rider_id))
    await orders.transition(db, order.id, S.delivered, Actor("rider", rider_id=order.rider_id))
    await db.commit()
    return await db.get(Order, order.id, populate_existing=True)


async def entries(db, order_id) -> dict[str, int]:  # type: ignore[no-untyped-def]
    rows = await db.execute(
        select(LedgerEntry.kind, LedgerEntry.amount_paise).where(LedgerEntry.order_id == order_id)
    )
    return dict(rows.all())


async def paid(db, **kw) -> Order:  # type: ignore[no-untyped-def]
    order = await place(db, payment="razorpay", **kw)
    order = await orders.mark_paid(db, order.id, f"pay_{uuid.uuid4().hex[:8]}")
    await db.commit()
    assert order is not None and order.status == S.placed
    return order


def test_the_split_sums_to_the_total_and_pays_the_rider_by_distance():
    o = Order(
        restaurant_id=uuid.uuid4(),
        rider_id=uuid.uuid4(),
        subtotal_paise=59999,
        delivery_fee_paise=3300,
        platform_fee_paise=500,
        total_paise=59999 + 3300 + 500,
        distance_m=3400,
    )
    rows = {kind: paise for _, kind, paise in ledger.split(o)}
    assert rows["sale"] == 47999  # 80% of the food, rounded down
    assert rows["fee"] == 12000
    assert rows["delivery"] == 3000 + 800 * 3  # ₹30 + ₹8 per km
    assert sum(rows.values()) == o.total_paise


async def test_a_delivered_order_writes_its_entries_once_and_they_balance(world):
    db = world
    order = await deliver(db, await place(db))
    rows = await entries(db, order.id)
    assert set(rows) == {"sale", "fee", "delivery", "delivery_margin"}
    assert sum(rows.values()) == order.total_paise
    await ledger.on_delivered(db, order)  # a replay writes nothing
    await db.commit()
    assert await entries(db, order.id) == rows
    accounts = (
        await db.execute(select(LedgerEntry.account).where(LedgerEntry.order_id == order.id))
    ).scalars()
    assert {a.split(":")[0] for a in accounts} == {"restaurant", "platform", "rider"}


async def test_rejecting_a_paid_order_refunds_it_once(world, app, rzp):
    db = world
    order = await paid(db, slug="bandstand-kitchen")
    async with await make_client(app) as board:
        await login(board, db, "owner.bandstand-kitchen@platter.demo")
        r = await board.post(f"/restaurant/orders/{order.id}/transition", json={"to": "rejected"})
        assert r.status_code == 200
        again = await board.post(
            f"/restaurant/orders/{order.id}/transition", json={"to": "rejected"}
        )
        assert again.status_code == 409
    assert rzp == [(order.razorpay_payment_id, order.total_paise)]
    refund = (await db.execute(select(Refund).where(Refund.order_id == order.id))).scalar_one()
    assert refund.status == "processed" and refund.razorpay_refund_id == "rfnd_1"
    # two more sends at once (a retry racing a retry): nothing more leaves
    settings = app_settings()

    async def resend() -> None:
        async with make_session(app)() as s:
            await refunds.send(s, settings, order.id)

    await asyncio.gather(resend(), resend())
    assert len(rzp) == 1
    assert await entries(db, order.id) == {}  # never delivered: no money moved in the ledger


def make_session(app):  # type: ignore[no-untyped-def]
    return app.state.session_factory


async def test_a_failed_refund_is_retried_once_by_the_admin(world, app, rzp, monkeypatch):
    db = world
    order = await paid(db)
    calls: list[int] = []

    async def down(settings, payment_id, amount_paise, *, receipt):  # type: ignore[no-untyped-def]
        calls.append(amount_paise)
        from app.core.errors import ApiError

        raise ApiError(502, "refund_failed", "down")

    monkeypatch.setattr(razorpay, "refund", down)
    async with await make_client(app) as c:
        await login(c, db, "ananya@platter.demo")
        assert (await c.post(f"/orders/{order.id}/cancel")).status_code == 200  # paid: allowed now
        o = (await c.get(f"/orders/{order.id}")).json()
        assert o["status"] == "cancelled" and o["refund"]["status"] == "failed"
    assert calls == [order.total_paise]

    async def up(settings, payment_id, amount_paise, *, receipt):  # type: ignore[no-untyped-def]
        calls.append(amount_paise)
        return "rfnd_ok"

    monkeypatch.setattr(razorpay, "refund", up)
    async with await make_client(app) as admin:
        await login(admin, db, ADMIN)
        r = await admin.post(f"/admin/orders/{order.id}/refund")
        assert r.status_code == 200 and r.json()["refund"]["status"] == "processed"
        r = await admin.post(f"/admin/orders/{order.id}/refund")  # processed: nothing more
        assert r.json()["refund"]["status"] == "processed"
    assert calls == [order.total_paise, order.total_paise]
    n = (await db.execute(select(func.count()).select_from(Refund))).scalar_one()
    assert n == 1


async def test_a_payment_after_expiry_goes_straight_back(world, rzp):
    db = world
    order = await place(db, payment="razorpay")
    clock.advance(16 * 60)
    await orders.expire_stale(db)
    await db.commit()
    await orders.mark_paid(db, order.id, "pay_late")
    await db.commit()
    await refunds.send(db, app_settings(), order.id)
    assert rzp == [("pay_late", order.total_paise)]


async def test_refunding_a_delivered_order_nets_it_to_zero(world, app, rzp):
    db = world
    order = await deliver(db, await paid(db))
    async with await make_client(app) as admin:
        await login(admin, db, ADMIN)
        r = await admin.post(f"/admin/orders/{order.id}/refund")
        assert r.status_code == 200
        await admin.post(f"/admin/orders/{order.id}/refund")
    rows = await entries(db, order.id)
    assert rows["refund"] == -order.total_paise
    assert sum(rows.values()) == 0  # what came in, less what went back
    assert len(rzp) == 1


async def test_cash_orders_have_nothing_to_refund(world, app, rzp):
    db = world
    order = await deliver(db, await place(db))
    async with await make_client(app) as admin:
        await login(admin, db, ADMIN)
        r = await admin.post(f"/admin/orders/{order.id}/refund")
        assert r.status_code == 409 and r.json()["error"]["code"] == "nothing_to_refund"
    assert rzp == []


async def test_payouts_never_exceed_the_balance_even_at_once(world, app):
    db = world
    order = await deliver(db, await place(db))
    account = ledger.restaurant_account(order.restaurant_id)
    held = await ledger.balance(db, account, True)
    assert held == order.subtotal_paise * 80 // 100
    async with await make_client(app) as a, await make_client(app) as b:
        await login(a, db, ADMIN)
        await login(b, db, ADMIN)
        over = await a.post(
            "/admin/payouts",
            json={"account": account, "amount_paise": held + 1, "reference": "UTR1"},
        )
        assert over.status_code == 422 and over.json()["error"]["code"] == "over_balance"
        # two admins pay the whole balance at the same moment: one wins
        ra, rb = await asyncio.gather(
            a.post(
                "/admin/payouts",
                json={"account": account, "amount_paise": held, "reference": "UTR2"},
            ),
            b.post(
                "/admin/payouts",
                json={"account": account, "amount_paise": held, "reference": "UTR3"},
            ),
        )
        assert sorted([ra.status_code, rb.status_code]) == [201, 422]
        dup = await a.post(
            "/admin/payouts", json={"account": account, "amount_paise": 1, "reference": "UTR2"}
        )
        assert dup.status_code in (409, 422)
        bad = await a.post(
            "/admin/payouts", json={"account": "platform", "amount_paise": 1, "reference": "x"}
        )
        assert bad.status_code == 422
        page = (await a.get("/admin/payouts")).json()
    assert await ledger.balance(db, account, True) == 0
    row = next(x for x in page["accounts"] if x["account"] == account)
    assert row["balance_paise"] == 0 and row["paid_paise"] == held


async def test_the_demo_never_sees_or_moves_real_money(world, app, rzp):
    from tests.test_demo_isolation import real_order

    db = world
    real = await real_order(app, db)  # a real customer at the demo restaurant
    await db.execute(
        text(
            "update orders set payment = 'razorpay', razorpay_payment_id = 'pay_real' where id = :o"
        ),
        {"o": real.id},
    )
    await db.commit()
    real = await deliver(db, await db.get(Order, real.id, populate_existing=True))
    assert await entries(db, real.id)  # real money moved, on the real side
    account = ledger.restaurant_account(real.restaurant_id)
    async with await make_client(app) as admin:
        await login(admin, db, ADMIN)
        assert (await admin.post(f"/admin/orders/{real.id}/refund")).status_code == 404
        page = (await admin.get("/admin/payouts")).json()
        assert all(o["id"] != str(real.id) for o in page["refundable"])
        assert all(a["account"] != account for a in page["accounts"])
        r = await admin.post(
            "/admin/payouts", json={"account": account, "amount_paise": 100, "reference": "x"}
        )
        assert r.status_code == 422  # the demo side of this account holds nothing
    async with await make_client(app) as board:
        await login(board, db, "owner.bandstand-kitchen@platter.demo")
        earned = (await board.get("/restaurant/earnings")).json()
        assert earned["earned_paise"] == 0 and earned["entries"] == []
    assert rzp == []
    assert await ledger.balance(db, account, False) > 0


async def test_earnings_for_the_kitchen_and_the_rider(world, app):
    db = world
    order = await deliver(db, await place(db, slug="bandstand-kitchen"))
    async with await make_client(app) as board:
        await login(board, db, "owner.bandstand-kitchen@platter.demo")
        e = (await board.get("/restaurant/earnings")).json()
    assert e["balance_paise"] == order.subtotal_paise * 80 // 100
    assert e["entries"][0]["order_number"] == order.number
    rider_email = (
        await db.execute(
            text("select u.email from users u join riders r on r.user_id = u.id where r.id = :r"),
            {"r": order.rider_id},
        )
    ).scalar_one()
    async with await make_client(app) as phone:
        await login(phone, db, rider_email)
        e = (await phone.get("/rider/earnings")).json()
    assert e["balance_paise"] == ledger.rider_pay(order.distance_m)
