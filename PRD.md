# PRD — Platter: Food delivery with live rider tracking

**Status:** v1 · lifecycle steps 1–7 complete (2026-09-17) — see [docs/](docs/) · next: step 8 Project Setup (= milestone 1.0), **last in the build order** (1 → 2 → 4 → 5 → 3 → 6)
**Name:** Platter · *hot food, tracked to your door*
**URL:** https://platter.virajdomadia.com (landing live at https://platter-viraj.vercel.app until DNS)
**Slot:** #6 · Budget ~38 h (v1 16 · v2 11 · v3 8 · v4 3) · Build last
**Live artifacts:** [Tracker](https://claude.ai/artifact/HEHpyrigHuZpBMoECDs4qG) (plan rows with status, all docs, mockups, project facts) · [Screens](https://claude.ai/artifact/GGchE2CjZ7DN5t83pzs9Cu) (every v1 screen in the chosen direction) · [Direction variants](https://claude.ai/artifact/JAekpL7HjR4oU5c39ak7dg) (A–L, L chosen) · Landing: https://platter-viraj.vercel.app

## One-liner
A four-sided food-delivery platform for one Bengaluru neighbourhood — **customers** pin a location, order from restaurants nearby and **watch the rider move on a real map**; **restaurants** run a live order board on a tablet; **riders** get dispatched, share their GPS from a phone and mark pickup / drop; an **admin** sees every active order and rider on one map and can reassign — built on PostGIS, an order state machine guarded by role, and **live location over SSE with Postgres as the bus**. No paid map, routing, realtime or AI service: ₹0 per order.

## Who it's for
- **Customer:** ordering dinner on a phone; wants the restaurants that can actually reach them, a fair ETA, and to see the rider coming.
- **Restaurant:** one owner per restaurant with a tablet in the kitchen; wants new orders to be loud and one-tap to accept, cook, and hand over.
- **Rider:** a phone in a handlebar mount; wants the next job, the route, and two big buttons (picked up / delivered).
- **Admin (platform):** one operator; wants the live map, stuck orders, and a reassign button. A small real UI, not code.

## Why this project
- **Geo + realtime + a multi-role state machine** is the closest a portfolio gets to Swiggy-scale problems: restaurants within radius and nearest-rider dispatch in PostGIS, a role-guarded `placed → … → delivered` machine, and rider GPS streamed to exactly the people who should see it.
- **The realtime is ours, and it is honest.** Riders post GPS every 3 s; `order_events` is an append-only log that doubles as the message bus; the API streams SSE from FastAPI on Vercel; v3 replaces the 1-s poll with `LISTEN/NOTIFY` and measures the latency. No Pusher, no Firebase, no WebSockets to host.
- **₹0 infrastructure for a map product:** MapLibre + OpenFreeMap tiles, OSRM's public router with a straight-line fallback, Photon geocoding — every "expensive" part of a delivery app is done with open data.
- **Four roles you can demo from the landing** — customer · restaurant · rider · admin — and the wow moment works with two phones: the rider walks, the marker moves.
- **The unique feature (v4, ₹0 per use): Order together.** One link, many phones: friends add to the cart from their own phones, one pays, and the same link becomes everyone's live tracking page.

## Locked decisions (2026-09-17) — follow these until the project ends

### 1. Live location: SSE from FastAPI, Postgres as the bus (the hard part)
- **Producers:** a rider's phone `POST /rider/position { lat, lng, heading, speed, at }` every 3 s while "Share my location" is on (`watchPosition`, sent only if moved ≥ 5 m or 3 s passed). One row per rider in `rider_positions` (PostGIS `geography(Point)`, heading, speed, `recorded_at`); every position while on a job is also appended to `rider_track(order_id, at, loc)` for the trail and the case study. Every status transition appends a row to **`order_events(seq bigserial, order_id, kind, payload, at)`** — that log is the bus.
- **Consumers:** `GET /orders/{id}/events` (customer, v4 group members), `GET /restaurant/events` (the board), `GET /rider/events` (assignment, status), `GET /admin/events` (everything + every rider every 2 s). One loop in `services/stream.py`: every 1 s read `order_events` newer than the last seq and positions newer than the last timestamp, `yield` them as SSE (`id: {seq}:{pos_ms}`, `event: status | rider | eta | route | offer | ping`), `retry: 1000`, a `ping` every 15 s, and close cleanly at **280 s** (Vercel's 300-s function limit); `EventSource` reconnects with `Last-Event-ID` and misses nothing because the log is durable. Simulated riders are advanced inside the same tick (decision 3).
- **Why not polling / a hosted service:** polling the tracking page every 3 s is a 3-s lag with nothing to show; Pusher / Ably add a key, a free-tier cap and hide the thing the project proves. SSE over Postgres costs nothing, degrades to "reconnect and catch up", and v3 makes it push-based with `LISTEN/NOTIFY` on a direct Neon connection.
- **Proof:** a position posted from the rider phone appears on the customer's map in ≤ 2 s (measured in the case study); killing the stream mid-order and reconnecting replays every missed event; a customer can only open the stream for their own order (403 otherwise).

### 2. Geo, maps and routing at ₹0
- **PostGIS on Neon** (`create extension postgis`): `restaurants.loc`, `addresses.loc`, `rider_positions.loc` are `geography(Point, 4326)` with GIST. Restaurants for a pin = `ST_DWithin(loc, pin, 8000)` ordered by `ST_Distance` — ≤ 5 km orderable, 5–8 km shown greyed as "Too far"; nearest available rider = KNN `loc <-> restaurant.loc`.
- **Map:** MapLibre GL JS with **OpenFreeMap** vector tiles (`https://tiles.openfreemap.org/styles/liberty`, no key, no quota) — light style for customer / restaurant / admin, a dark variant on the rider phone.
- **Routes and ETA:** **OSRM public server** (`router.project-osrm.org/route/v1/driving/…?overview=full&geometries=polyline`) called **once per leg** (rider → restaurant, restaurant → customer) and cached on `rider_legs` (polyline, distance, duration). ETA = remaining prep time (until `ready`) + travel time of the remaining polyline at the rider's recent speed (min 12, max 30 km/h). Fallback when OSRM fails: straight line × 1.3 at 22 km/h, `eta.method = "line"` shown as "≈".
- **Addresses:** a draggable pin on MapLibre + **Photon** (`photon.komoot.io/api`, `/reverse`) for search and the label; saved addresses per customer; the seed's default pin is Koramangala 5th Block. Delivery radius 5 km; a restaurant outside it is shown greyed with "Too far".
- **Delivery fee:** ₹25 up to 2 km, then ₹8 per started km of the route distance (or straight line × 1.3); the 5 km radius itself is always straight-line so the list and checkout agree; platform fee ₹5; integer paise everywhere; no minimum order.

### 3. Riders: simulated and real
- **Simulated riders (8)** have no process. A sim rider's position at any moment = the point along its current leg's polyline at `min(1, (now − leg.started_at) / leg.duration_s)`, where the sim's `duration_s` = the leg's distance ÷ its own `speed_kmh` (22 ± 10 %); the SSE tick computes it and pushes it like a real fix. Arrival advances the world lazily and idempotently (`select … for update skip locked`): leg *to_restaurant* complete → wait at the restaurant until the order is `ready` → `picked_up` + leg *to_customer*; that leg complete → `delivered` → rider `available` → takes the oldest order waiting for a rider. `advance_simulation()` runs inside every stream tick and every order read or transition, so the world is always consistent whoever looks first.
- **The demo rider** is real: the landing's rider login lands on `/rider` on a phone with a job already assigned and "Share my location" off; switching it on streams the phone's GPS (`watchPosition`, wake lock, foreground only — a PWA on the home screen). Two phones = the wow moment.
- The customer never learns which kind of rider they got; the admin map marks sims with a dotted ring.

### 4. Payments: COD default + Razorpay in v1
- `POST /orders` prices server-side (items from the DB, availability checked, fee from decision 2) → `payment = cod` → `placed` immediately; `payment = razorpay` → `pending_payment` → Standard Checkout modal → verify (HMAC) or webhook `payment.captured` → the same idempotent **`mark_paid()`** → `placed` + `order_events`. Unpaid orders expire lazily after 15 min. The restaurant board never sees `pending_payment`.
- Refund on rejection (v2): a rejected Razorpay order is refunded automatically; COD needs nothing.
- **Money to three parties (v2):** `ledger_entries` — restaurant `sale` +80 % / platform `fee` +20 % of the food subtotal, rider `delivery` ₹30 + ₹8/km of the leg, platform keeps the delivery + platform fee minus the rider's pay; admin marks payouts paid. Razorpay Route stays out.

### 5. Dispatch: nearest now, offers in v2, batching in v3
- **v1:** the moment a restaurant **accepts**, `assign_rider(order)` locks the nearest `available` rider (KNN) → rider `busy`, `orders.rider_id`, leg *to_restaurant* via OSRM, event `rider_assigned` — the rider rides while the food cooks. No rider free → the order waits (`rider_id null`, the customer sees "Finding a rider"); a rider becoming free takes the oldest waiting order. Admin can **reassign** to any available rider (the old leg is closed, a new one drawn).
- **v2:** `offers(order, rider, expires_at)` — the nearest rider gets 30 s to **accept / decline** on the phone (a countdown ring); decline or timeout → the next nearest, up to 5; after that the order waits and the admin is flagged. Riders go `offline / available / busy`.
- **v3 batching:** when a rider is assigned or picking up at restaurant R, a second `accepted` order from R whose drop is ≤ 1.5 km off the first drop's route is stacked onto the same rider → a multi-stop leg (OSRM with three waypoints); both customers' ETAs update; max 2 orders per rider.

### 6. Seed: one neighbourhood, 12 restaurants, ~100 dishes, 9 riders
Koramangala + HSR Layout (~4 × 4 km). 12 fictional restaurants (each with an owner login), 6–10 items each with real **CC-BY / CC0 photos from Wikimedia Commons** (biryani, masala dosa, thali, momos, paneer, chole bhature, pav bhaji, filter coffee, rasmalai …; credits in `api/app/seed/CREDITS.md`), realistic prep times (12–25 min) and hours; 8 simulated riders parked at real junctions + 1 demo rider; the demo customer with three saved addresses and ~10 past orders; ~60 historical orders over 30 days so dashboards, ratings (v2) and the ETA model (v3) have data. Four demo logins on the landing: **customer**, **restaurant** (Koramangala Social — the busiest), **rider**, **admin**.

### 7. Versions — base → mid → advanced
Every project is cut base → mid → advanced (rule set 2026-09-15), plus one unique free feature as v4 (rule set 2026-09-17). v1 alone is a complete delivery platform with live tracking; each later version adds humans, money or intelligence to dispatch, never a second engine.

| Version | Ships | Proves | ~Hours |
|---|---|---|---|
| **v1 Kitchen** (base) | Auth (email + password, `pl_session`, roles customer / restaurant / rider / admin; four demo logins) · **home**: location pin + Photon search → restaurants within 5 km by distance / ETA · restaurant page + menu + cart · **checkout** COD + Razorpay (idempotent `mark_paid`) · **order state machine** `placed → accepted → preparing → ready → picked_up → delivered` (+ `rejected`, `cancelled`), every transition role-guarded and logged · **live tracking page** (MapLibre, route drawn, rider marker gliding over SSE, ETA, status rail, trail) · **restaurant board** (tablet, live over SSE: new-order ticket, accept / reject, preparing, ready; item availability toggle; today's numbers) · **rider app** (phone PWA: current job, route, Share my location, picked up / delivered, next job) · **auto-dispatch** nearest available rider · **admin live map** (every order + rider, stuck orders, reassign) · sim riders · seed (decision 6) | PostGIS, the SSE bus, the state machine across four roles, ₹0 maps | 16 |
| **v2 Rush** (mid) | Rider **offers** (accept / decline / 30-s timeout chain, online / offline) · **Web Push** (VAPID, `pywebpush`, free) for customer status, new-order on the board, new job on the rider · restaurant **menu management** (categories, items, photos, hours, open / closed) · search + cuisine + veg filters + sort · order history + reorder · ratings (restaurant + rider) · refund on rejection · **ledgers + payouts** (restaurant 80/20, rider ₹30 + ₹8/km, admin marks paid) | Humans in the dispatch loop; push; money to three parties | 11 |
| **v3 Fleet** (advanced) | **Batching** (stacked orders, multi-stop legs) · **smart ETA** (per-restaurant prep learned from the last 20 `accepted → ready`, rider's own speed, a confidence band on the tracking page) · **`LISTEN/NOTIFY`** replaces the 1-s poll in the stream loop, end-to-end latency measured and published · admin **demand heatmap** (PostGIS hex bins over 7 days) + "where to wait" hint on the rider app | Real dispatch logic; true push; geo analytics from own data | 8 |
| **v4 Order together** (unique, free) | **One link, many phones** — `/o/{code}`: before checkout it is a **group cart** (anyone with the link adds items under their name from their own phone, live over the same SSE core; the host sees who added what and pays once); after checkout the **same link is the shared live tracking page** for everyone in the group, each phone marking "your items" | Reach: the order leaves one phone, and the core doesn't change (Viraj, 2026-09-17) | 3 |

### 8. Stack and setup — lean
Shared stack from [`projects/README.md`](../README.md): `web/` Next.js App Router + Tailwind 4, `api/` FastAPI on Vercel (FastAPI preset, `bom1`), Neon Postgres **with PostGIS**, own cookie-session auth (`pl_session`), Razorpay (test mode). New deps: `maplibre-gl` in web; `geoalchemy2`, `polyline` (decode; the polyline maths are pure Python), `httpx` (OSRM, Photon, Razorpay), `razorpay`, `pywebpush` (v2) in api. Setup is the minimum to deploy both apps with plain CI (web typecheck + build, api ruff + pytest with a `postgis/postgis` service). OpenAPI → TS types by script, committed, not CI-gated; no Sentry, no uptime monitor. **Accounts and keys are created just-in-time** in the plan row that first needs them: Neon (+ PostGIS) in S2, Vercel Blob (dish photos) in S2's seed, Razorpay in F3, VAPID keys (generated locally, free) in L2.

## The wow moment (v1)
Open the landing on your laptop as the **customer**, pin your location, order a masala dosa; the restaurant tablet (second tab) rings and prints a ticket — Accept. A rider is found in a radar ping and starts moving along the real streets of Koramangala toward the kitchen. Mark it Ready; the rider picks up and the ETA drops as the marker glides toward your pin. Now open the **rider** login on your phone, switch on *Share my location* and walk down the corridor — the marker on the laptop walks with you.

## Add-ons (after v4, only from time saved)
Nice-to-have, not priority (Viraj, 2026-09-17): listed in [docs/07-plan.md](docs/07-plan.md) — restaurant white-label storefront + embed · scheduled orders · rider tips · promo codes · customer ↔ rider chat · proof-of-delivery photo · Telegram status bot · restaurant analytics. Skipping all of them is fine.

## Out of scope (all versions)
Multi-city · real turn-by-turn navigation · paid maps, routing, realtime or AI services · restaurant onboarding / KYC · GST invoices · native apps (the rider app is a PWA) · multi-restaurant carts · real-money billing · surge pricing · scheduled shifts · customer support tooling · multiple admins.

## Success criteria
- **A position posted by the rider phone appears on the customer's map within 2 s** (SSE, measured); the stream survives the 280-s cut and a network drop with no missed event (`Last-Event-ID` replay covered by a test).
- **Every state transition is validated server-side by role** (tests: a customer cannot accept, a restaurant cannot mark delivered, a rider cannot touch an order not assigned to them; illegal transitions → 409).
- Restaurants within 5 km of any pin in the seed area are returned sorted by distance in ≤ 150 ms (PostGIS GIST); the nearest-rider query is a single KNN.
- An order placed with COD reaches `delivered` by a simulated rider without any human action after the restaurant marks `ready`; ETA on the tracking page is within ±3 min of the actual delivery for sim riders.
- Razorpay: verify-then-webhook and webhook-then-verify → exactly one `placed`; replayed webhooks are no-ops; an unpaid order expires at 15 min and never reaches the board.
- Lighthouse mobile ≥ 90 perf / 100 a11y / 100 SEO on home and restaurant pages (map pages excluded from the perf budget; MapLibre loaded on demand; dish photos via `next/image`, no CLS).
- v4: a friend with the link adds an item from a second phone and it appears on the host's cart within 2 s; after payment both phones show the same rider.
- A visible frontend signature (chosen in step 4, direction **L · Bento**, [docs/04-ui-mockups.md](docs/04-ui-mockups.md)): **Rider glide + Route draw** on the tracking page, **Tile spring** on every screen, the **ticket print** on the restaurant board, Plate slide in the cart, themed browser surfaces, reduced-motion fallbacks.

## Resolved questions
- *Polling, SSE, or a hosted realtime service?* SSE from FastAPI with Postgres (`order_events` + `rider_positions`) as the bus; `LISTEN/NOTIFY` in v3 (Viraj, 2026-09-17, fork 1: "choose what is best").
- *Which map, routing and geocoder at ₹0?* MapLibre + OpenFreeMap, OSRM public with a straight-line fallback, Photon (fork 2).
- *Simulated riders or real GPS?* Both — lazy sims for the public demo, a real demo rider for two-phone demos (fork 3).
- *Razorpay only or COD?* COD default + Razorpay, same `mark_paid` recipe as Skillroom / Offcut (fork 4).
- *How is a rider chosen?* v1 nearest-available at accept, v2 offers with timeout, v3 batching (fork 5).
- *How big is the seed?* One neighbourhood, 12 / ~100 / 9, 60 past orders (fork 6).
- *v4?* Order together (one link, many phones) over a public tracking link and a restaurant storefront, which became add-ons (Viraj, 2026-09-17).
- *WebSockets?* No — Vercel functions don't hold them; SSE is one-way and that is all tracking needs; the rider's uplink is plain POSTs.
- *Auth: Better Auth / Drizzle?* No — those were the old TS-stack notes; own cookie session in FastAPI like every other project.
