# Platter — Architecture

**Lifecycle step:** 5 of 17 · **Locked:** 2026-09-17

## 1. System diagram

```mermaid
flowchart LR
  subgraph Browsers
    CU[Customer · phone / laptop<br/>pin · menu · checkout · tracking (EventSource)]
    RB[Restaurant board · tablet<br/>tickets · accept / ready (EventSource)]
    RD[Rider · phone PWA<br/>watchPosition → POST · job · buttons (EventSource)]
    AD[Admin · desktop<br/>live map · reassign (EventSource)]
  end
  subgraph Vercel
    WEB[web · platter<br/>Next.js: pages · MapLibre · rewrites /api/* →]
    API[api · platter-api<br/>FastAPI bom1 · maxDuration 300<br/>REST · state machine · dispatch · sim · stream loop · webhooks]
  end
  PG[(Neon Postgres + PostGIS<br/>users · restaurants · menu · orders · order_events (bus)<br/>riders · rider_positions · rider_track · rider_legs)]
  BL[Vercel Blob<br/>dish photos · covers]
  OFM[OpenFreeMap tiles]
  OSRM[OSRM public router]
  PH[Photon geocoder]
  RZ[Razorpay]
  WP[Web Push · v2]

  CU & RB & RD & AD -->|same-origin /api/*| WEB --> API
  CU & RB & RD & AD -->|vector tiles| OFM
  API --> PG
  API -->|route per leg| OSRM
  API -->|search / reverse| PH
  API -->|create order · refund v2| RZ
  RZ -->|payment webhooks| API
  API -->|photos| BL --> CU
  API -->|revalidate tags| WEB
  API -->|notifications v2| WP
```

## 2. Boundaries
| Component | Owns | Never does |
|---|---|---|
| **web/** | Every screen; MapLibre maps, the gliding marker and route draw; `EventSource` reducers; the rider's GPS uplink (`watchPosition` → POST); the Razorpay modal; the PWA shell | Touch the DB, OSRM, Photon or Razorpay's server API; compute ETAs or distances that matter; decide who is nearest; trust a client total |
| **api/** | Auth and RBAC, the state machine (`transition()`), dispatch (`assign_rider`, offers v2, batching v3), the simulation clock, the stream loop, geo queries, routing + ETA, quotes / orders / `mark_paid` / webhooks, ledger (v2), seed | Hold WebSockets; run a background process; serve tiles; store lat/lng as floats outside PostGIS |
| **Postgres + PostGIS** | Everything durable and every spatial question (within radius, nearest, along-route); `order_events` as the bus; `LISTEN/NOTIFY` in v3 | Store photos |
| **Blob** | Bytes: dish photos, covers | Anything else |
| **OpenFreeMap / OSRM / Photon** | Tiles, one route per leg, address text | Anything the app depends on being up — every call has a fallback |
| **Razorpay** | Taking the money and telling us via webhook | Deciding when an order is `placed` — `mark_paid` is ours |

Contract: `api/openapi.json` → `web/src/lib/api-types.ts` via `pnpm gen:api`. Web client (`web/src/lib/api.ts`) = typed `fetch` forwarding cookies, trusting only the `{ error: { code, message, details } }` envelope. Stream payloads are typed in `web/src/lib/stream-types.ts`, hand-written from 06 §D.

## 3. api/ layout
```
api/app/
  main.py            app factory, request-id middleware, error envelope
  config.py          pydantic-settings
  db.py              async engine (pooled) · direct engine for LISTEN (v3)
  models/            user, session, restaurant, menu_category, menu_item, address, rider, rider_position, rider_track,
                     order, order_item, order_event, rider_leg, webhook_event,
                     offer · push_subscription · rating · refund · ledger_entry · payout (v2), prep_stat · eta_log (v3), group · group_item · group_event (v4)
  schemas/           pydantic request/response models (= the OpenAPI contract) · stream event payloads
  routers/           auth, geo (search, reverse), restaurants (list, page), orders (quote, create, verify, get, list, cancel, events),
                     rider (me, position, job, transition, events), restaurant (board, transition, menu availability, events),
                     admin (map, orders, reassign, riders, events), webhooks,
                     offers · push · menu · ratings · earnings · payouts (v2), heatmap (v3), groups (v4)
  services/
    orders.py        quote(), create(), TRANSITIONS, transition(), mark_paid(), expire_stale()
    dispatch.py      assign_rider(), release_rider(), on_rider_available(), reassign(); offer() (v2); try_stack() (v3)
    sim.py           advance_simulation(), position_on_leg(), sim_tick_positions()
    stream.py        stream(scope, since) — the SSE generator; scopes: order, restaurant, rider, admin, group (v4)
    routing.py       route(a, b, waypoints) → OSRM or straight line; decode / length / project helpers
    eta.py           eta(order, position) → { seconds, method, band (v3) }
    geo.py           nearby_restaurants(pin), nearest_available_rider(point), photon search / reverse
    razorpay.py      order create, signature verify, webhook verify, refund (v2)
    ledger.py        post_delivery(), balance() (v2)
    push.py          send(user, payload) (v2)
    prep_model.py    learned prep + rider speed (v3)
  seed/              area.json (restaurants, items, riders, junctions) · fetch_photos.py · photos/ (+ CREDITS.md) · seed.py (idempotent; two live orders)
scripts/             measure_latency.py (v3) · gen_vapid.py (v2)
tests/               the tests listed in 04 §12 only
.github/workflows/   ci.yml
```

## 4. web/ layout
```
web/src/
  app/(site)/            page.tsx (home) · r/[slug] · checkout · orders · orders/[id] · addresses · sign-in · sign-up · o/[code] (v4)
  app/(restaurant)/restaurant/   layout (404 non-restaurant) · page (board) · menu · earnings (v2)
  app/(rider)/rider/     layout (404 non-rider) · page (the app) · earnings (v2)
  app/(admin)/admin/     layout (404 non-admin) · page (map) · payouts (v2) · heatmap (v3)
  app/api/revalidate/    route.ts
  components/site/       PinHeader · AddressSearch · RestaurantCard · RestaurantList · Menu · MenuItem · CartSheet · CheckoutForm · RazorpayButton · OrderCard
  components/map/        Map (MapLibre) · RiderMarker · RouteLayer · TrailLayer · PinMarker · RestaurantMarker
  components/tracking/   StatusRail · EtaBadge · OrderSummary · RiderCard · GroupMembers (v4)
  components/board/      TicketColumn · Ticket · TodayStats · AvailabilityList
  components/rider/      JobCard · ShareLocationToggle · BigButtons · OfferCard (v2) · BusyAreaHint (v3)
  components/admin/      LiveMap · OrdersTable · ReassignPicker · Heatmap (v3)
  components/landing/    (exists)
  components/ui/
  lib/api.ts · api-types.ts (generated) · stream.ts (useOrderStream / useRestaurantStream / useRiderStream / useAdminStream / useGroupStream) · stream-types.ts · geo.ts (polyline decode, haversine, bearing) · geoUplink.ts · cart.ts · money.ts · session.ts
  public/manifest.webmanifest · sw.js · map-dark.json
```

## 5. Deployment topology
- Two Vercel projects per repo: `platter` (root `web/`) and `platter-api` (root `api/`, FastAPI preset, `bom1`, `maxDuration: 300` in `vercel.json`). `web/next.config.ts` rewrites `/api/:path*` → `API_URL`; cookies are first-party; `EventSource` is same-origin; no CORS.
- Neon: one project with PostGIS enabled; `main` = production, a `dev` branch for local; `DATABASE_DIRECT_URL` (unpooled) only for the v3 listener. CI uses `postgis/postgis:17-3.5`.
- Blob store on `platter-api`; `NEXT_PUBLIC_BLOB_HOST` in `remotePatterns`.
- Razorpay test mode; webhook → `https://platter.virajdomadia.com/api/webhooks/razorpay` (via the web rewrite).
- OpenFreeMap, OSRM public and Photon need no account; the API sends a `User-Agent: platter.virajdomadia.com` and rate-limits Photon at 10/min/IP.
- Previews: Vercel previews per PR for `web/` against the production API.
- CI: `web` = pnpm typecheck + build; `api` = ruff + pytest. That is all.

## 6. Request paths worth drawing
**Order:** pin at Koramangala 5th Block → `GET /api/restaurants?lat&lng` (PostGIS, 9 within 5 km) → `/r/dosa-camp` → cart → `POST /api/orders/quote` → `POST /api/orders { cod }` → `placed` + event → `/orders/PL-1042` opens `EventSource` → prime `status` → the board's stream ticks and prints the ticket.
**Accept → rider:** board `POST /api/orders/{id}/transition { to: accepted }` → `transition()` → `assign_rider()` KNN → sim rider 4 (`busy`), OSRM leg 1.3 km / 4 min → events `accepted`, `rider_assigned`, `route` → the customer stream draws the route and the marker starts gliding; the rider stream (a real rider) shows the job card.
**Ready → delivered (sim):** board marks `ready`; the sim is already waiting (`arrived_at`) → `picked_up` + leg *to_customer* (2.1 km / 7 min) → each tick computes the position, ETA falls → at progress 1 → `delivered` → rider `available` → `on_rider_available` finds nothing → idle at the drop.
**Real rider:** phone toggles *Share my location* → `watchPosition` → `POST /api/rider/position` every 3 s → upsert + track → the customer's next tick (≤ 1 s) emits `rider` → the marker interpolates to it over the next fixes' gap.
**Reconnect:** the stream closes at 280 s → the browser reconnects with `Last-Event-ID: 4312:1758112233000` → the loop replays events > 4312 and positions > that ms → nothing missed.
**Order together (v4):** host → `POST /api/groups` → `/o/K7Q2M9X4ZP` shared → friend adds a dosa → `group_events` → the host's stream shows it → host checks out → one order with `group_id` → both phones' `/o/{code}` become the tracking page.

## 7. Security notes (the short list)
Cookie session HttpOnly + SameSite=Lax; argon2 passwords; board / rider / admin 404 for the wrong role; every transition checks role + ownership + current status under a row lock; streams authorise the scope at open and on every reconnect; a customer stream never carries other orders' events; rider positions are accepted only from the rider's own session and only exposed on streams of orders they are assigned to (the admin sees all); prices and fees come from the DB and OSRM, never the client; Razorpay signatures verified on verify and webhooks, event ids deduped; Photon / OSRM calls go through the API with rate limits and a UA, never from the browser directly; group codes (v4) are 50-bit random capability URLs, expire 24 h after delivery, and checkout still needs the host's session; no PII in logs (positions are logged only as rows in `rider_track`, pruned 7 days after delivery).
