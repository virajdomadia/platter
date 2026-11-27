"""04 §12 test_stream: a reconnect with `Last-Event-ID` replays exactly the missed events (from the
durable log); a stranger gets 404; positions after the cursor only; the 280-s close (fake clock).
The generator is driven directly with a fake sleep that moves the fake clock."""

import datetime as dt
import json

import pytest
from sqlalchemy import select, text

from app.core import clock
from app.models import OrderStatus, Rider
from app.services import orders, sim
from app.services import stream as st
from app.services.events import Actor
from tests.conftest import login, make_client, place

pytestmark = pytest.mark.db
S = OrderStatus


def parse(frame: str) -> dict:
    out: dict = {}
    for line in frame.strip().splitlines():
        key, _, value = line.partition(": ")
        out[key] = value
    if "data" in out:
        out["data"] = json.loads(out["data"])
    return out


async def never() -> bool:
    return False


async def frames_until(  # type: ignore[no-untyped-def]
    factory, scope, cursor, seconds: int, lifetime_s: int = 280, step: float = 1.0
):
    """Frames until `seconds` of fake time have passed (each tick's sleep moves it `step` s)."""
    end = clock.now() + dt.timedelta(seconds=seconds)
    out: list[dict] = []

    async def sleep(_: float) -> None:
        clock.advance(step)

    async for raw in st.stream(
        factory, scope, cursor, is_disconnected=never, lifetime_s=lifetime_s, sleep=sleep
    ):
        if raw.startswith("retry"):
            continue
        out.append(parse(raw))
        if out[-1].get("event") == "reconnect" or clock.now() >= end:
            break
    return out


async def test_reconnect_replays_exactly_the_missed_events(world, factory):
    db = world
    order = await place(db)
    await db.execute(text("update restaurants set board_seen_at = :t"), {"t": clock.now()})
    await db.commit()
    first = await frames_until(factory, st.Scope("order", order.id), None, 2)
    snap = first[0]
    assert snap["event"] == "snapshot"
    assert snap["data"]["status"] == "placed" and snap["data"]["number"] == order.number
    last_id = snap["id"]

    # the connection drops; meanwhile the kitchen accepts and starts cooking
    kitchen = Actor("restaurant", restaurant_id=order.restaurant_id)
    await orders.transition(db, order.id, S.accepted, kitchen)
    await orders.transition(db, order.id, S.preparing, kitchen)
    await db.commit()

    again = await frames_until(factory, st.Scope("order", order.id), st.parse_cursor(last_id), 3)
    log = [
        (f["event"], f["data"].get("status"))
        for f in again
        if f["event"] in ("status", "rider_assigned", "route")
    ]
    assert log == [
        ("status", "accepted"),
        ("rider_assigned", None),
        ("route", None),
        ("status", "preparing"),
    ]
    # ids are monotonic and carry the seq
    seqs = [int(f["id"].split(":")[0]) for f in again if "id" in f]
    assert seqs == sorted(seqs)
    # a second reconnect from the newest id replays nothing more
    newest = [f for f in again if f["event"] == "status"][-1]["id"]
    once_more = await frames_until(factory, st.Scope("order", order.id), st.parse_cursor(newest), 2)
    assert not [f for f in once_more if f["event"] in ("status", "rider_assigned", "route")]


async def test_a_customer_stream_never_carries_other_orders(world, factory):
    db = world
    mine = await place(db)
    other = await place(db, email="ravi.kumar@customers.platter.demo", slug="thali-ghar")
    kitchen = Actor("restaurant", restaurant_id=other.restaurant_id)
    await orders.transition(db, other.id, S.accepted, kitchen)
    await db.commit()
    frames = await frames_until(factory, st.Scope("order", mine.id), st.Cursor(0, 0), 2)
    ids = {
        f["data"].get("order_id")
        for f in frames
        if isinstance(f.get("data"), dict) and "order_id" in f["data"]
    }
    assert ids == {str(mine.id)}


async def test_positions_after_the_cursor_only(world, factory):
    db = world
    divya = (await db.execute(select(Rider).where(Rider.name == "Divya S"))).scalar_one()
    await sim.upsert_position(db, divya.id, (12.9346, 77.6183), 0, 1.0)  # sharing, at the door
    await db.execute(text("update restaurants set board_seen_at = :t"), {"t": clock.now()})
    await db.commit()
    order = await place(db)
    kitchen = Actor("restaurant", restaurant_id=order.restaurant_id)
    order = await orders.transition(db, order.id, S.accepted, kitchen)
    await db.commit()
    assert order.rider_id == divya.id
    cursor_ms = clock.ms(clock.now())
    seq = int((await db.execute(text("select max(seq) from order_events"))).scalar_one())
    clock.advance(3)
    await sim.upsert_position(db, divya.id, (12.9350, 77.6190), 45, 4.0)
    await db.commit()
    frames = await frames_until(factory, st.Scope("order", order.id), st.Cursor(seq, cursor_ms), 2)
    fixes = [f for f in frames if f["event"] == "rider"]
    assert len(fixes) == 1
    assert fixes[0]["data"]["lat"] == pytest.approx(12.9350) and fixes[0]["data"]["heading"] == 45
    assert "is_sim" not in fixes[0]["data"]  # the customer never learns which kind of rider
    assert any(f["event"] == "eta" for f in frames)
    # from that fix's id onwards: nothing new
    later = await frames_until(
        factory, st.Scope("order", order.id), st.parse_cursor(fixes[0]["id"]), 2
    )
    assert not [f for f in later if f["event"] == "rider"]


async def test_the_stream_closes_itself_at_280_seconds(world, factory):
    order = await place(world)
    started = clock.now()
    frames = await frames_until(factory, st.Scope("order", order.id), None, 400, step=5)
    assert frames[-1]["event"] == "reconnect"
    assert 280 <= (clock.now() - started).total_seconds() <= 285
    pings = [f for f in frames if f["event"] == "ping"]
    assert len(pings) == 280 // 15  # one every 15 s


async def test_sim_positions_flow_while_on_a_leg(world, factory):
    db = world
    order = await place(db)
    kitchen = Actor("restaurant", restaurant_id=order.restaurant_id)
    await orders.transition(db, order.id, S.accepted, kitchen)
    await db.execute(text("update restaurants set board_seen_at = :t"), {"t": clock.now()})
    await db.commit()
    frames = await frames_until(factory, st.Scope("order", order.id), None, 5)
    fixes = [f["data"] for f in frames if f["event"] == "rider"]
    assert len(fixes) >= 4
    assert fixes[0]["lat"] != fixes[-1]["lat"] or fixes[0]["lng"] != fixes[-1]["lng"]  # moving


async def test_stream_routes_authorise(world, app):
    db = world
    order = await place(db)
    async with await make_client(app) as stranger:
        await login(stranger, db, "ravi.kumar@customers.platter.demo")
        r = await stranger.get(f"/orders/{order.id}/events")
        assert r.status_code == 404  # like every other order route: no existence oracle
    async with await make_client(app) as anon:
        assert (await anon.get(f"/orders/{order.id}/events")).status_code == 401
    app.state.settings.stream_lifetime_s = 0
    async with await make_client(app) as owner:
        await login(owner, db, "ananya@platter.demo")
        r = await owner.get(f"/orders/{order.id}/events")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        assert r.headers["cache-control"] == "no-cache, no-transform"
        assert r.headers["x-accel-buffering"] == "no"
        events = [line for line in r.text.splitlines() if line.startswith("event:")]
        assert events == ["event: snapshot", "event: reconnect"]
        assert "retry: 1000" in r.text
