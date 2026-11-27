"""Idempotent seed (R10): one neighbourhood, 12 restaurants, ~100 dishes, 8 sim riders + the demo
rider, the demo customer (3 addresses, ~10 past orders), sim customers, ~60 past orders over the
last 30 days (with events, legs and tracks), and two live orders in progress.

    SEED_DATABASE_URL=postgresql+asyncpg://… uv run python -m app.seed.seed [--offline]

The target is SEED_DATABASE_URL (or --database-url) only — never DATABASE_URL — so a bare run
can't touch production by accident. Every row has a deterministic id (uuid5), so a second run
updates in place and inserts nothing twice; menu availability toggled on the board is kept.
`--offline` draws straight-line legs instead of asking OSRM (CI, no network).
"""

import argparse
import asyncio
import datetime as dt
import json
import os
import random
import re
import sys
import uuid
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import clock
from app.core.config import get_settings
from app.core.db import make_engine
from app.models import ACTIVE_STATUSES, Order
from app.services import demo, hours, routing

AREA = json.loads(Path(__file__).with_name("area.json").read_text(encoding="utf-8"))
NS = uuid.UUID("6b1d5f6e-2b7c-4c55-9c1a-0d6a2f1e7a01")
ALL_DAY = ["00:00", "24:00"]
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
HISTORY_ORDERS = 60
DEMO_HISTORY = 10


def uid(*parts: object) -> uuid.UUID:
    return uuid.uuid5(NS, "/".join(str(p) for p in parts))


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def hours_of(spec: str | list) -> dict[str, list[list[str]]]:
    ranges = [ALL_DAY] if spec == "24h" else spec
    return {d: [list(r) for r in ranges] for d in DAYS}


def point_sql(name: str) -> str:
    return f"ST_SetSRID(ST_MakePoint(:{name}_lng, :{name}_lat), 4326)::geography"


async def upsert_user(
    db: AsyncSession, email: str, name: str, role: str, phone: str | None = None
) -> uuid.UUID:
    user_id = uid("user", email)
    await db.execute(
        text(
            "insert into users (id, email, name, phone, role, is_demo, created_at)"
            " values (:id, :email, :name, :phone, :role, true, :now)"
            " on conflict (email) do update set name = excluded.name, role = excluded.role,"
            # Someone who signed up with a seeded email first can't keep a password on that role.
            " phone = excluded.phone, is_demo = true, password_hash = null"
        ),
        {
            "id": user_id,
            "email": email,
            "name": name,
            "phone": phone,
            "role": role,
            "now": clock.now(),
        },
    )
    return (
        await db.execute(text("select id from users where email = :e"), {"e": email})
    ).scalar_one()


async def upsert_address(db: AsyncSession, user_id: uuid.UUID, a: dict) -> None:
    await db.execute(
        text(
            "insert into addresses (id, user_id, label, line, loc, created_at)"
            f" values (:id, :user, :label, :line, {point_sql('p')}, :at)"
            " on conflict (id) do update set label = excluded.label, line = excluded.line,"
            " loc = excluded.loc"
        ),
        {
            "id": uid("address", user_id, a["label"]),
            "user": user_id,
            "label": a["label"],
            "line": a["line"],
            "p_lat": a["lat"],
            "p_lng": a["lng"],
            "at": clock.now() - dt.timedelta(days=40) + dt.timedelta(minutes=len(a["label"])),
        },
    )


async def seed_people(db: AsyncSession) -> None:
    await upsert_user(db, "admin@platter.demo", "Platform Admin", "admin")
    c = AREA["demo_customer"]
    customer = await upsert_user(db, c["email"], c["name"], "customer", c["phone"])
    for i, a in enumerate(c["addresses"]):
        await upsert_address(db, customer, {**a, "label": a["label"]})
        await db.execute(
            text("update addresses set created_at = :at where id = :id"),
            {
                "at": clock.now() - dt.timedelta(days=60 - i),
                "id": uid("address", customer, a["label"]),
            },
        )
    for p in AREA["customers"]:
        email = f"{slugify(p['name']).replace('-', '.')}{demo.SIM_CUSTOMER_DOMAIN}"
        user = await upsert_user(db, email, p["name"], "customer")
        await upsert_address(db, user, {"label": "Home", **p})


async def seed_restaurants(db: AsyncSession) -> None:
    for r in AREA["restaurants"]:
        owner = await upsert_user(db, f"owner.{r['slug']}@platter.demo", r["owner"], "restaurant")
        rid = uid("restaurant", r["slug"])
        await db.execute(
            text(
                "insert into restaurants (id, owner_user_id, slug, name, area, cuisines, is_veg,"
                " loc, address, prep_min, hours, is_open, cover_url, rating, created_at)"
                f" values (:id, :owner, :slug, :name, :area, :cuisines, :veg, {point_sql('p')},"
                " :address, :prep, cast(:hours as jsonb), true, :cover, :rating, :now)"
                " on conflict (slug) do update set name = excluded.name, area = excluded.area,"
                " cuisines = excluded.cuisines, is_veg = excluded.is_veg, loc = excluded.loc,"
                " address = excluded.address, prep_min = excluded.prep_min,"
                " hours = excluded.hours, cover_url = excluded.cover_url,"
                " rating = excluded.rating"
            ),
            {
                "id": rid,
                "owner": owner,
                "slug": r["slug"],
                "name": r["name"],
                "area": r["area"],
                "cuisines": r["cuisines"],
                "veg": r["is_veg"],
                "p_lat": r["lat"],
                "p_lng": r["lng"],
                "address": r["address"],
                "prep": r["prep_min"],
                "hours": json.dumps(hours_of(r["hours"])),
                "cover": f"/dishes/{r['cover']}.jpg",
                "rating": r["rating"],
                "now": clock.now() - dt.timedelta(days=90),
            },
        )
        for ci, (category, items) in enumerate(r["menu"].items()):
            cid = uid("category", r["slug"], category)
            await db.execute(
                text(
                    "insert into menu_categories (id, restaurant_id, name, sort)"
                    " values (:id, :r, :name, :sort) on conflict (id) do update"
                    " set name = excluded.name, sort = excluded.sort"
                ),
                {"id": cid, "r": rid, "name": category, "sort": ci},
            )
            for ii, (name, rupees, veg, photo, desc) in enumerate(items):
                await db.execute(
                    text(
                        "insert into menu_items (id, restaurant_id, category_id, name, description,"
                        " price_paise, is_veg, photo_url, is_available, sort) values (:id, :r, :c,"
                        " :name, :desc, :price, :veg, :photo, true, :sort) on conflict (id) do"
                        " update set name = excluded.name, description = excluded.description,"
                        " price_paise = excluded.price_paise, is_veg = excluded.is_veg,"
                        " photo_url = excluded.photo_url, sort = excluded.sort"
                    ),
                    {
                        "id": uid("item", r["slug"], name),
                        "r": rid,
                        "c": cid,
                        "name": name,
                        "desc": desc,
                        "price": rupees * 100,
                        "veg": veg,
                        "photo": f"/dishes/{photo}.jpg",
                        "sort": ii,
                    },
                )


async def seed_riders(db: AsyncSession) -> None:
    people = [(r, True) for r in AREA["riders"]] + [(AREA["demo_rider"], False)]
    for i, (r, is_sim) in enumerate(people):
        email = f"rider.{i + 1}@riders.platter.demo" if is_sim else demo.DEMO_RIDER_EMAIL
        user = await upsert_user(db, email, r["name"], "rider", r["phone"])
        rider_id = uid("rider", email)
        await db.execute(
            text(
                "insert into riders (id, user_id, name, phone, vehicle, is_sim, status, speed_kmh,"
                " created_at) values (:id, :u, :name, :phone, :vehicle, :sim, 'available', :speed,"
                " :now) on conflict (user_id) do update set name = excluded.name,"
                " phone = excluded.phone, vehicle = excluded.vehicle, is_sim = excluded.is_sim,"
                " speed_kmh = excluded.speed_kmh"
            ),
            {
                "id": rider_id,
                "u": user,
                "name": r["name"],
                "phone": r["phone"],
                "vehicle": r["vehicle"],
                "sim": is_sim,
                "speed": r.get("speed_kmh", 22.0),
                "now": clock.now() - dt.timedelta(days=120),
            },
        )
        # Parked at its junction. The demo rider's fix is old: it isn't dispatched until the phone
        # shares its location.
        recorded = clock.now() - (dt.timedelta(seconds=0) if is_sim else dt.timedelta(days=1))
        await db.execute(
            text(
                "insert into rider_positions (rider_id, loc, heading, speed_mps, recorded_at)"
                f" values (:r, {point_sql('p')}, 0, 0, :at) on conflict (rider_id) do nothing"
            ),
            {"r": rider_id, "p_lat": r["lat"], "p_lng": r["lng"], "at": recorded},
        )


# --- history ----------------------------------------------------------------------------------


async def _route(a: tuple[float, float], b: tuple[float, float], offline: bool) -> routing.Route:
    if offline:
        return routing.line_route(a, b)
    found = await routing.route(a, b)
    await asyncio.sleep(0.4)  # polite to the public OSRM server
    return found


async def seed_history(db: AsyncSession, offline: bool) -> int:
    rng = random.Random(20260917)
    existing = (await db.execute(select(func.count()).select_from(Order))).scalar_one()
    if existing >= HISTORY_ORDERS:
        return 0
    customers = (
        await db.execute(
            text(
                "select u.id, u.name, a.line, ST_Y(a.loc::geometry), ST_X(a.loc::geometry)"
                " from users u join addresses a on a.user_id = u.id"
                " where u.role = 'customer' and (a.label = 'Home') order by u.email"
            )
        )
    ).all()
    demo_customer = next(c for c in customers if c[1] == AREA["demo_customer"]["name"])
    restaurants = (
        await db.execute(
            text(
                "select id, slug, prep_min, ST_Y(loc::geometry), ST_X(loc::geometry), hours"
                " from restaurants order by slug"
            )
        )
    ).all()
    riders = (
        await db.execute(
            text(
                "select r.id, ST_Y(p.loc::geometry), ST_X(p.loc::geometry) from riders r"
                " join rider_positions p on p.rider_id = r.id where r.is_sim order by r.name"
            )
        )
    ).all()
    now = clock.now()
    made = 0
    for i in range(HISTORY_ORDERS):
        oid = uid("history", i)
        if await db.get(Order, oid):
            continue
        cust = demo_customer if i < DEMO_HISTORY else customers[rng.randrange(len(customers))]
        drop = (float(cust[3]), float(cust[4]))
        rider = riders[rng.randrange(len(riders))]
        day = now - dt.timedelta(days=rng.randint(1, 30))
        hour = rng.choice((12, 13, 13, 14, 19, 20, 20, 21, 21, 22))
        placed = day.replace(hour=hour - 5, minute=rng.randint(0, 29), second=rng.randint(0, 59))
        placed = placed - dt.timedelta(minutes=30)  # an IST lunch / dinner hour, in UTC
        near = [
            r
            for r in restaurants
            if routing.haversine((float(r[3]), float(r[4])), drop) <= 4800
            and hours.is_open_at(r[5], placed)
        ]
        if not near:
            continue
        rest = near[rng.randrange(len(near))]
        status = "delivered"
        if i % 20 == 7:
            status = "rejected"
        elif i % 20 == 13:
            status = "cancelled"
        items = (
            await db.execute(
                text(
                    "select id, name, price_paise, is_veg from menu_items where restaurant_id = :r"
                ),
                {"r": rest[0]},
            )
        ).all()
        picks = rng.sample(list(items), k=min(len(items), rng.randint(1, 3)))
        lines = [(it, rng.choice((1, 1, 2))) for it in picks]
        subtotal = sum(it[2] * q for it, q in lines)
        rest_pt = (float(rest[3]), float(rest[4]))
        to_cust = await _route(rest_pt, drop, offline or i >= DEMO_HISTORY)
        fee = 2500 + 800 * max(0, -(-(to_cust.distance_m - 2000) // 1000))
        number = (await db.execute(text("select nextval('order_number_seq')"))).scalar_one()
        accepted = placed + dt.timedelta(seconds=rng.randint(35, 140))
        t = {
            "placed": placed,
            "accepted": accepted,
            "preparing": accepted + dt.timedelta(seconds=20),
            "ready": accepted + dt.timedelta(seconds=rest[2] * 60 + rng.randint(-150, 200)),
        }
        t["picked_up"] = t["ready"] + dt.timedelta(seconds=rng.randint(30, 160))
        t["delivered"] = t["picked_up"] + dt.timedelta(
            seconds=to_cust.duration_s + rng.randint(-60, 120)
        )
        if status != "delivered":
            t = {"placed": placed, status: placed + dt.timedelta(seconds=rng.randint(60, 200))}
        await db.execute(
            text(
                "insert into orders (id, number, user_id, restaurant_id, rider_id, status, payment,"
                " address_line, drop_loc, subtotal_paise, delivery_fee_paise, platform_fee_paise,"
                " total_paise, distance_m, route_method, eta_s, note, reject_reason, created_at,"
                " placed_at, accepted_at, preparing_at, ready_at, picked_up_at, delivered_at,"
                f" rejected_at, cancelled_at) values (:id, :number, :user, :rest, :rider, :status,"
                f" 'cod', :line, {point_sql('d')}, :sub, :fee, 500, :total, :dist, :method, :eta,"
                " null, :reason, :placed, :placed, :accepted, :preparing, :ready, :picked_up,"
                " :delivered, :rejected, :cancelled)"
            ),
            {
                "id": oid,
                "number": f"PL-{number}",
                "user": cust[0],
                "rest": rest[0],
                "rider": rider[0] if status == "delivered" else None,
                "status": status,
                "line": cust[2],
                "d_lat": drop[0],
                "d_lng": drop[1],
                "sub": subtotal,
                "fee": fee,
                "total": subtotal + fee + 500,
                "dist": to_cust.distance_m,
                "method": to_cust.method,
                "eta": rest[2] * 60 + to_cust.duration_s + 90,
                "reason": "Kitchen is closing early tonight" if status == "rejected" else None,
                "placed": placed,
                **{
                    k: t.get(k)
                    for k in ("accepted", "preparing", "ready", "picked_up", "delivered")
                },
                "rejected": t.get("rejected"),
                "cancelled": t.get("cancelled"),
            },
        )
        for it, q in lines:
            await db.execute(
                text(
                    "insert into order_items (id, order_id, menu_item_id, name, price_paise, qty,"
                    " is_veg) values (:id, :o, :m, :n, :p, :q, :v)"
                ),
                {
                    "id": uid("item-line", oid, it[0]),
                    "o": oid,
                    "m": it[0],
                    "n": it[1],
                    "p": it[2],
                    "q": q,
                    "v": it[3],
                },
            )
        actor = {
            "placed": "customer",
            "cancelled": "customer",
            "picked_up": "system",
            "delivered": "system",
        }
        for kind, at in sorted(t.items(), key=lambda kv: kv[1]):
            payload: dict = {"status": kind}
            if kind == "rejected":
                payload["reason"] = "Kitchen is closing early tonight"
            await db.execute(
                text(
                    "insert into order_events (order_id, kind, actor_role, payload, at)"
                    " values (:o, :k, :r, cast(:p as jsonb), :at)"
                ),
                {
                    "o": oid,
                    "k": kind,
                    "r": actor.get(kind, "restaurant"),
                    "p": json.dumps(payload),
                    "at": at,
                },
            )
        if status == "delivered":
            to_rest = routing.line_route((float(rider[1]), float(rider[2])), rest_pt)
            for kind, leg, start, end in (
                ("to_restaurant", to_rest, accepted, t["picked_up"]),
                ("to_customer", to_cust, t["picked_up"], t["delivered"]),
            ):
                await db.execute(
                    text(
                        "insert into rider_legs (id, order_id, rider_id, kind, polyline,"
                        " distance_m, duration_s, method, started_at, arrived_at, ended_at)"
                        " values (:id, :o, :r, :k, :pl, :d, :s, :m, :start, :end, :end)"
                    ),
                    {
                        "id": uid("leg", oid, kind),
                        "o": oid,
                        "r": rider[0],
                        "k": kind,
                        "pl": leg.polyline,
                        "d": leg.distance_m,
                        "s": leg.duration_s,
                        "m": leg.method,
                        "start": start,
                        "end": end,
                    },
                )
            points = routing.decode(to_cust.polyline)
            cum = routing.cumulative(points)
            span = (t["delivered"] - t["picked_up"]).total_seconds()
            for k in range(0, int(span), 15):
                p, _ = routing.point_at(points, cum, cum[-1] * k / max(1, span))
                await db.execute(
                    text(
                        "insert into rider_track (order_id, rider_id, at, loc) values (:o, :r, :at,"
                        f" {point_sql('p')})"
                    ),
                    {
                        "o": oid,
                        "r": rider[0],
                        "at": t["picked_up"] + dt.timedelta(seconds=k),
                        "p_lat": p[0],
                        "p_lng": p[1],
                    },
                )
        made += 1
    return made


async def seed_live(db: AsyncSession) -> int:
    active = (
        await db.execute(
            select(func.count()).select_from(Order).where(Order.status.in_(ACTIVE_STATUSES))
        )
    ).scalar_one()
    made = 0
    for phase in ("on_the_way", "cooking")[: max(0, 2 - active)]:
        if await demo.spawn(db, phase=phase):
            made += 1
    return made


async def run(url: str, offline: bool) -> None:
    if offline:
        os.environ["OSRM_URL"] = "off"
        get_settings.cache_clear()
    engine = make_engine(url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        await seed_people(db)
        await seed_restaurants(db)
        await seed_riders(db)
        await db.commit()
        history = await seed_history(db, offline)
        await db.commit()
        live = await seed_live(db)
        await db.commit()
        counts = (
            await db.execute(
                text(
                    "select (select count(*) from restaurants), (select count(*) from menu_items),"
                    " (select count(*) from riders), (select count(*) from orders),"
                    " (select count(*) from order_events)"
                )
            )
        ).one()
    await engine.dispose()
    print(
        f"seeded: {counts[0]} restaurants · {counts[1]} dishes · {counts[2]} riders ·"
        f" {counts[3]} orders ({history} new past, {live} new live) · {counts[4]} events"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--database-url", default=os.environ.get("SEED_DATABASE_URL"))
    parser.add_argument("--offline", action="store_true", help="straight-line legs, no OSRM")
    args = parser.parse_args()
    if not args.database_url:
        print(
            "Set SEED_DATABASE_URL or pass --database-url (DATABASE_URL is never used).",
            file=sys.stderr,
        )
        return 2
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore[attr-defined]
    asyncio.run(run(args.database_url, args.offline))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
