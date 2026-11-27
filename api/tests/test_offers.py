"""v2 L1 (06 Â§C v2, 07 L1): rider offers. The nearest free rider gets 30 s to accept; decline or
timeout â†’ the next nearest, up to 5; sims accept on their own after 3â€“8 s. Every offer state change
is one conditional `update â€¦ where state = 'sent'`, so an accept racing the expiry of the same
offer â€” or two phones accepting it â€” has exactly one winner, and the loser does nothing at all."""

import asyncio
import datetime as dt

import pytest
from sqlalchemy import func, select, text

from app.core import clock
from app.core.errors import ApiError
from app.models import Offer, Order, OrderEvent, OrderStatus, Rider
from app.services import admin, dispatch, orders, sim
from app.services.events import Actor
from tests.conftest import login, make_client, place

pytestmark = pytest.mark.db
S = OrderStatus
DEMO_RIDER = "rider@platter.demo"
KITCHEN_DOOR = (12.9345, 77.6150)  # by Bandstand Kitchen


async def demo_rider(db) -> Rider:  # type: ignore[no-untyped-def]
    return (await db.execute(select(Rider).where(Rider.is_sim.is_(False)))).scalar_one()


async def offers_of(db, order_id) -> list[Offer]:  # type: ignore[no-untyped-def]
    rows = await db.execute(
        select(Offer)
        .where(Offer.order_id == order_id)
        .order_by(Offer.created_at, Offer.closed_at.nulls_last())
        .execution_options(populate_existing=True)
    )
    return list(rows.scalars())


async def kinds(db, order_id) -> list[str]:  # type: ignore[no-untyped-def]
    rows = await db.execute(
        select(OrderEvent.kind).where(OrderEvent.order_id == order_id).order_by(OrderEvent.seq)
    )
    return list(rows.scalars())


async def accept_at_kitchen(db, slug: str = "bandstand-kitchen") -> Order:  # type: ignore[no-untyped-def]
    order = await place(db, slug=slug)
    kitchen = Actor("restaurant", restaurant_id=order.restaurant_id)
    order = await orders.transition(db, order.id, S.accepted, kitchen)
    await db.commit()
    return order


async def only_the_demo_phone_is_free(db) -> Rider:  # type: ignore[no-untyped-def]
    await db.execute(text("update riders set status = 'busy' where is_sim"))
    await db.execute(text("update restaurants set board_seen_at = :t"), {"t": clock.now()})
    rider = await demo_rider(db)
    rider.status = "available"  # type: ignore[assignment]
    await sim.upsert_position(db, rider.id, KITCHEN_DOOR, 0, 1.0)
    await db.commit()
    return rider


async def test_accept_offers_the_nearest_sim_who_takes_it_within_8_s(world):
    db = world
    order = await accept_at_kitchen(db, "dosa-camp")
    assert order.rider_id is None  # offered, not yet taken
    [offer] = await offers_of(db, order.id)
    assert offer.state == "sent"
    assert offer.expires_at - offer.created_at == dt.timedelta(seconds=dispatch.OFFER_S)

    clock.advance(dispatch.SIM_ACCEPT_MAX_S)
    await sim.advance(db, order_ids=[order.id])
    await db.commit()
    order = await db.get(Order, order.id, populate_existing=True)
    assert order.rider_id == offer.rider_id
    assert (await offers_of(db, order.id))[0].state == "accepted"
    assert (await kinds(db, order.id))[-4:] == [
        "offer_sent",
        "offer_accepted",
        "rider_assigned",
        "route",
    ]


async def test_decline_offers_the_next_rider_at_once(world, app):
    db = world
    phone_rider = await only_the_demo_phone_is_free(db)
    order = await accept_at_kitchen(db)
    [offer] = await offers_of(db, order.id)
    assert offer.rider_id == phone_rider.id
    await db.execute(text("update riders set status = 'available' where is_sim"))
    await db.commit()

    async with await make_client(app) as phone:
        await login(phone, db, DEMO_RIDER)
        me = (await phone.get("/rider/me")).json()
        assert me["offer"]["id"] == str(offer.id) and me["offer"]["expires_in_s"] == 30
        assert me["offer"]["job"]["order_id"] == str(order.id)
        r = await phone.post(f"/rider/offers/{offer.id}/decline")
        assert r.status_code == 200, r.text
        assert (await phone.get("/rider/me")).json()["offer"] is None
    first, second = await offers_of(db, order.id)
    assert (first.state, second.state) == ("declined", "sent")
    assert second.rider_id != phone_rider.id


async def test_an_expired_offer_cannot_be_accepted_and_the_next_rider_gets_it(world, app):
    db = world
    await only_the_demo_phone_is_free(db)
    order = await accept_at_kitchen(db)
    [offer] = await offers_of(db, order.id)
    await db.execute(text("update riders set status = 'available' where is_sim"))
    await db.commit()

    clock.advance(dispatch.OFFER_S)
    async with await make_client(app) as phone:
        await login(phone, db, DEMO_RIDER)
        r = await phone.post(f"/rider/offers/{offer.id}/accept")
        assert r.status_code == 409 and r.json()["error"]["code"] == "offer_expired"
    await sim.advance(db, order_ids=[order.id])
    await db.commit()
    first, second = await offers_of(db, order.id)
    assert first.state == "expired" and second.state == "sent"
    assert (await db.get(Order, order.id, populate_existing=True)).rider_id is None


async def test_the_demo_phone_accepts_and_rides(world, app):
    db = world
    rider = await only_the_demo_phone_is_free(db)
    order = await accept_at_kitchen(db)
    [offer] = await offers_of(db, order.id)
    async with await make_client(app) as phone:
        await login(phone, db, DEMO_RIDER)
        r = await phone.post(f"/rider/offers/{offer.id}/accept")
        assert r.status_code == 200, r.text
        assert r.json()["order_id"] == str(order.id)
        assert (await phone.get("/rider/me")).json()["job"]["order_id"] == str(order.id)
    order = await db.get(Order, order.id, populate_existing=True)
    assert order.rider_id == rider.id
    assert (await db.get(Rider, rider.id, populate_existing=True)).status == "busy"


async def test_two_phones_accepting_the_same_offer_make_one_assignment(world, app):
    db = world
    await only_the_demo_phone_is_free(db)
    order = await accept_at_kitchen(db)
    [offer] = await offers_of(db, order.id)
    async with await make_client(app) as a, await make_client(app) as b:
        await login(a, db, DEMO_RIDER)
        await login(b, db, DEMO_RIDER)
        ra, rb = await asyncio.gather(
            a.post(f"/rider/offers/{offer.id}/accept"), b.post(f"/rider/offers/{offer.id}/accept")
        )
    assert sorted([ra.status_code, rb.status_code]) == [200, 409]
    loser = ra if ra.status_code == 409 else rb
    assert loser.json()["error"]["code"] == "offer_taken"
    assert (await kinds(db, order.id)).count("rider_assigned") == 1


async def test_accept_racing_the_expiry_at_the_boundary_has_exactly_one_winner(world, factory):
    """Viraj, 2026-11-19: the accept and the timeout of the same offer run at once, at the moment
    it expires. One wins; the loser makes no assignment, no next offer and no `order_event`."""
    db = world
    rider = await only_the_demo_phone_is_free(db)
    order = await accept_at_kitchen(db)
    [offer] = await offers_of(db, order.id)
    await db.execute(text("update riders set status = 'available' where is_sim"))
    await db.commit()
    events_before = len(await kinds(db, order.id))
    actor = Actor("rider", user_id=rider.user_id, rider_id=rider.id)

    async def accept() -> str:
        async with factory() as s:
            try:
                # The phone's tap landed a hair before the deadline.
                await dispatch.answer(
                    s,
                    offer.id,
                    rider.id,
                    "accepted",
                    actor,
                    at=offer.expires_at - dt.timedelta(milliseconds=1),
                )
                await s.commit()
                return "accepted"
            except ApiError as err:
                await s.rollback()
                return err.code

    async def expire() -> str:
        async with factory() as s:
            won = await dispatch.expire(s, offer.id, at=offer.expires_at)
            await s.commit()
            return "expired" if won else "lost"

    for _ in range(10):
        results = await asyncio.gather(accept(), expire())
        winners = [r for r in results if r in ("accepted", "expired")]
        assert len(winners) == 1, results
        offs = await offers_of(db, order.id)
        evs = await kinds(db, order.id)
        o = await db.get(Order, order.id, populate_existing=True)
        if winners == ["accepted"]:
            assert o.rider_id == rider.id and len(offs) == 1
            assert evs[events_before:] == ["offer_accepted", "rider_assigned", "route"]
        else:
            assert o.rider_id is None
            assert [f.state for f in offs] == ["expired", "sent"]  # the winner's next offer
            assert evs[events_before:] == ["offer_expired", "offer_sent"]
        # Reset the same offer for another round.
        await db.execute(text("delete from rider_legs where order_id = :o"), {"o": order.id})
        await db.execute(text("delete from offers where id <> :f"), {"f": offer.id})
        first_offer = (
            await db.execute(text("select min(seq) from order_events where kind = 'offer_sent'"))
        ).scalar_one()
        await db.execute(
            text("delete from order_events where order_id = :o and seq > :s"),
            {"o": order.id, "s": first_offer},
        )
        await db.execute(
            text("update offers set state = 'sent', closed_at = null where id = :f"),
            {"f": offer.id},
        )
        await db.execute(text("update orders set rider_id = null where id = :o"), {"o": order.id})
        await db.execute(text("update riders set status = 'available'"))
        await db.commit()


async def test_after_five_unanswered_offers_the_order_waits_and_admin_is_flagged(world):
    db = world
    order = await accept_at_kitchen(db, "dosa-camp")
    # Nobody answers: the sims are all hesitating, so each offer times out.
    for _ in range(dispatch.MAX_OFFERS + 2):
        await db.execute(text("update offers set created_at = created_at + interval '1 hour'"))
        await db.commit()
        clock.advance(dispatch.OFFER_S)
        await sim.advance(db, order_ids=[order.id])
        await db.commit()
    offs = await offers_of(db, order.id)
    assert len(offs) == dispatch.MAX_OFFERS
    assert all(f.state == "expired" for f in offs)
    assert len({f.rider_id for f in offs}) == dispatch.MAX_OFFERS  # never the same rider twice
    order = await db.get(Order, order.id, populate_existing=True)
    assert order.rider_id is None
    listed = await admin.active_orders(db)
    flagged = next(o for o in listed if o.id == str(order.id))
    assert flagged.stuck == "no_rider" and flagged.offer_attempts == dispatch.MAX_OFFERS


async def test_an_offline_rider_gets_no_offers_and_cannot_go_offline_mid_job(world, app):
    db = world
    rider = await only_the_demo_phone_is_free(db)
    async with await make_client(app) as phone:
        await login(phone, db, DEMO_RIDER)
        r = await phone.post("/rider/status", json={"status": "offline"})
        assert r.status_code == 200 and r.json()["rider"]["status"] == "offline"
        order = await accept_at_kitchen(db)
        assert await offers_of(db, order.id) == []  # the only free phone is off duty

        r = await phone.post("/rider/status", json={"status": "available"})
        assert r.json()["rider"]["status"] == "available"
        await sim.advance(db, order_ids=[order.id])
        await db.commit()
        [offer] = await offers_of(db, order.id)
        assert offer.rider_id == rider.id
        # Going offline with an offer on screen declines it.
        await phone.post("/rider/status", json={"status": "offline"})
        assert (await offers_of(db, order.id))[0].state == "declined"
        await phone.post("/rider/status", json={"status": "available"})

        await db.execute(text("update riders set status = 'busy' where id = :r"), {"r": rider.id})
        await db.commit()
        r = await phone.post("/rider/status", json={"status": "offline"})
        assert r.status_code == 409


async def test_a_real_order_is_never_offered_to_the_demo_phone(world, app):
    from tests.test_demo_isolation import real_order

    db = world
    await only_the_demo_phone_is_free(db)
    order = await real_order(app, db)
    await orders.transition(
        db, order.id, S.accepted, Actor("restaurant", restaurant_id=order.restaurant_id)
    )
    await db.commit()
    for _ in range(3):
        clock.advance(dispatch.OFFER_S)
        await sim.advance(db)
        await db.commit()
    assert await offers_of(db, order.id) == []
    count = select(func.count()).select_from(Offer)
    assert (await db.execute(count)).scalar_one() == 0


async def test_the_offer_reaches_the_rider_stream_and_the_customer_sees_attempts(world, factory):
    from app.services import stream as st
    from tests.test_stream import frames_until

    db = world
    rider = await only_the_demo_phone_is_free(db)
    order = await accept_at_kitchen(db)
    frames = await frames_until(factory, st.Scope("rider", rider.id), st.Cursor(0, 0), 1)
    offer = next(f for f in frames if f["event"] == "offer")
    assert offer["data"]["state"] == "sent" and offer["data"]["rider_id"] == str(rider.id)
    # Another rider's stream never hears this offer.
    other = (await db.execute(select(Rider).where(Rider.is_sim).limit(1))).scalar_one()
    frames = await frames_until(factory, st.Scope("rider", other.id), st.Cursor(0, 0), 1)
    assert not [f for f in frames if f["event"] == "offer"]
    frames = await frames_until(factory, st.Scope("order", order.id), None, 1)
    assert frames[0]["data"]["offer_attempts"] == 1
    assert "rider_id" not in str([f for f in frames if f["event"] == "offer"])


async def test_going_offline_while_the_offer_is_accepted_never_deadlocks(world, app):
    """Review: the status switch used to lock the rider before the order (the reverse of every
    other path). Both requests racing now finish: one wins, nothing 500s."""
    db = world
    for _ in range(5):
        await db.execute(text("update offers set state = 'expired' where state = 'sent'"))
        await db.commit()
        await only_the_demo_phone_is_free(db)
        order = await accept_at_kitchen(db)
        [offer] = [f for f in await offers_of(db, order.id) if f.state == "sent"]
        async with await make_client(app) as a, await make_client(app) as b:
            await login(a, db, DEMO_RIDER)
            await login(b, db, DEMO_RIDER)
            ra, rb = await asyncio.gather(
                a.post(f"/rider/offers/{offer.id}/accept"),
                b.post("/rider/status", json={"status": "offline"}),
            )
        assert ra.status_code in (200, 409) and rb.status_code in (200, 409), (ra.text, rb.text)
        await db.execute(text("update riders set status = 'available'"))
        await db.execute(text("update orders set rider_id = null"))
        await db.commit()


async def test_a_rider_never_holds_two_open_offers(world, factory):
    """Review: two orders offering at once can both read the rider as free; the partial unique
    index makes the second insert lose cleanly (no rider), never a second open offer."""
    db = world
    await only_the_demo_phone_is_free(db)
    a = await place(db, slug="bandstand-kitchen")
    b = await place(db, slug="bandstand-kitchen", email="priya.sharma@customers.platter.demo")
    kitchen = Actor("restaurant", restaurant_id=a.restaurant_id)

    async def accept(order_id):  # type: ignore[no-untyped-def]
        async with factory() as s:
            await orders.transition(s, order_id, S.accepted, kitchen)
            await s.commit()

    await asyncio.gather(accept(a.id), accept(b.id))
    sent = select(func.count()).select_from(Offer).where(Offer.state == "sent")
    assert (await db.execute(sent)).scalar_one() == 1
