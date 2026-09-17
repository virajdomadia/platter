# Platter — Technical Design

**Lifecycle step:** 4 of 17 · **Locked:** 2026-09-17 · UI companion: [04-ui-mockups.md](04-ui-mockups.md). Schema and routes: [06-data-and-api.md](06-data-and-api.md).

## 1. Stack (shared stack, two additions: PostGIS and the stream loop)
| Layer | Choice | Notes |
|---|---|---|
| web/ | Next.js 15 App Router · TypeScript strict · Tailwind 4 · pnpm | UI only; `/api/*` rewritten to the API so cookies are same-origin and `EventSource` is first-party. New: **`maplibre-gl`** (dynamic import, only on map pages), `polyline` decode in `lib/geo.ts` |
| api/ | FastAPI (Python 3.12, uv) · SQLAlchemy 2.0 async (asyncpg) + **GeoAlchemy2** + Alembic · pydantic · pytest | Vercel FastAPI preset, `bom1`, `maxDuration` 300. New: `httpx` (OSRM, Photon, Razorpay), `razorpay`, `polyline`, `pywebpush` (v2) |
| Data | **Neon Postgres + PostGIS** | `create extension postgis` in `0001_v1`; geography columns + GIST; `order_events` is the bus |
| Realtime | **SSE from FastAPI** (`StreamingResponse`, `text/event-stream`) | One loop in `services/stream.py`; 1-s tick (v3: `LISTEN/NOTIFY`), 280-s lifetime, `Last-Event-ID` replay |
| Maps | MapLibre GL JS + **OpenFreeMap** (`tiles.openfreemap.org/styles/liberty`) | No key, no quota; a dark style for the rider app derived from `positron` by a script into `web/public/map-dark.json` |
| Routing | **OSRM public** (`router.project-osrm.org`, `driving`, `overview=full`, `geometries=polyline`) | Once per leg, cached on `rider_legs`; straight line × 1.3 fallback |
| Geocoding | **Photon** (`photon.komoot.io/api`, `/reverse`, `lang=en`, bbox = Bengaluru) | Called from the browser through `/api/geo/*` (API adds the UA and a 10/min/IP limit) |
| Files | Vercel Blob | Dish photos, restaurant covers (seed + v2 uploads) |
| Payments | Razorpay Standard Checkout, test mode | Orders, verify, webhooks; refunds (v2) |
| Push (v2) | Web Push, VAPID, `pywebpush` | Free; keys generated locally once |
| Contract | `api/openapi.json` → `openapi-typescript` → `web/src/lib/api-types.ts` | `pnpm gen:api`; committed; not CI-gated |
| CI | GitHub Actions: `web` (typecheck + build), `api` (ruff + pytest with a `postgis/postgis:17-3.5` service) | That is all |

## 2. Domain model
- `users(role customer|restaurant|rider|admin)` → `restaurants(owner_user_id unique, slug, name, area, cuisines text[], is_veg, loc geography, address, prep_min, hours jsonb, is_open, cover_url, rating)` → `menu_categories(sort)` → `menu_items(price_paise, is_veg, photo_url, is_available)`; `riders(user_id unique, name, phone, vehicle, is_sim, status offline|available|busy, speed_kmh)`; `rider_positions(rider_id pk, loc, heading, speed_mps, recorded_at)`; `rider_track(order_id, at, loc)`.
- `addresses(user_id, label, line, loc)`; `orders(number 'PL-####', user, restaurant, address snapshot, rider_id null, status, payment cod|razorpay, subtotal / delivery_fee / platform_fee / total paise, distance_m, eta_s, note, razorpay ids, timestamps per status, group_id (v4))` → `order_items(name, price_paise snapshot, qty, member_name (v4))`; **`order_events(seq bigserial, order_id, kind, actor_role, actor_id, payload jsonb, at)`**; `rider_legs(order_id, rider_id, kind to_restaurant|to_customer, polyline, distance_m, duration_s, started_at, ended_at null, stops jsonb (v3))`.
- v2: `offers`, `push_subscriptions`, `ratings`, `refunds`, `ledger_entries`, `payouts`; v3: `prep_stats`, `eta_log`; v4: `groups`, `group_items`, `group_events`.
- Money is integer paise; distances integer metres; every geography column is `SRID 4326` and the web only ever sees `{ lat, lng }`.

## 3. The stream loop (SSE)
`services/stream.py::stream(scope, since)` is one async generator behind four routes (`/orders/{id}/events`, `/restaurant/events`, `/rider/events`, `/admin/events`, and `/groups/{code}/events` in v4). Per request:
1. Parse `Last-Event-ID` = `"{seq}:{pos_ms}"` (or the query `?since=`); authorise the scope (owner / restaurant / rider / admin / group member).
2. **Prime:** send `route` events for open legs in scope and, for an order stream, a `status` snapshot — so a fresh page needs no second request.
3. **Tick** every 1 s (v3: on `NOTIFY`, with a 5-s safety poll): `advance_simulation(scope)`; `select … from order_events where seq > $seq and <scope> order by seq`. **Seq is commit-ordered:** every `order_events` insert first takes `pg_advisory_xact_lock(1)` (always after the row locks a transition already holds, so no lock cycle), which serialises event commits at this scale and guarantees that no event with a lower seq becomes visible after a higher one was read — the cursor never skips; positions `where recorded_at > $pos_ms and rider in <scope>` (sim riders: computed, not read); `eta` recomputed when a status or a position changed; `yield` each as `id: {seq}:{pos_ms}\nevent: {kind}\ndata: {json}\n\n`. A `: ping` comment every 15 s keeps proxies open.
4. **Close** at 280 s with a final `event: reconnect`; the browser's `EventSource` reconnects (`retry: 1000`) with the last id. Because every event is a durable row, a reconnect after any outage replays exactly what was missed. Client disconnect (`await request.is_disconnected()`) ends the loop immediately.

Response headers: `Content-Type: text/event-stream`, `Cache-Control: no-cache, no-transform`, `X-Accel-Buffering: no`. The web `rewrites` `/api/*` → the API host, so the stream is same-origin; Vercel's Python runtime streams `StreamingResponse` bodies as chunks (Fluid compute) — the same design Frontrow locked. Function `maxDuration = 300`.

**Rider positions:** `POST /rider/position { lat, lng, heading, speed_mps, at }` → `rider_positions` upsert with `recorded_at = now()` (server time — the stream cursors and the "signal weak" check never trust a phone clock) and `client_at = at` kept only to drop out-of-order fixes from the same phone (`at` older than the stored `client_at` → 204, `X-Ignored: stale`); `rider_track` insert when the rider is on a job; a fix > 200 m from the previous within 3 s is **dropped** as a GPS jump (204, `X-Ignored: jump`, logged) — one rule, used everywhere. Positions are pushed to the order stream of the rider's current order(s), the restaurant stream (distance to the restaurant while *to_restaurant*), and the admin stream (all riders every 2 s).

**Fan-out cost:** each open stream = one function invocation for ≤ 280 s doing one cheap indexed read per second; the tracking page, the board and the admin map are the only long-lived consumers, and the seed runs two live orders — well inside Hobby limits. v3 removes the per-second query.

## 4. Geo
- **Nearby restaurants:** `select …, ST_Distance(loc, :pin) as dist from restaurants where ST_DWithin(loc, :pin, 8000) order by dist` — those ≤ 5000 m are orderable, 5–8 km are "Too far" (shown, greyed). GIST index on `loc`.
- **Nearest rider:** `select id from riders r join rider_positions p using (rider_id) where r.status = 'available' order by p.loc <-> :restaurant limit 1 for update of r skip locked` — a KNN on the GIST index.
- **Legs:** `services/routing.py::route(a, b, waypoints=[])` → OSRM `GET /route/v1/driving/{lng,lat;…}?overview=full&geometries=polyline&steps=false` with a 3-s timeout → `{ polyline, distance_m, duration_s }`; on any error → `{ polyline: encode([a, b]), distance_m: haversine × 1.3, duration_s: distance / 22 km/h, method: "line" }`. `rider_legs.polyline` is Google-encoded (precision 5); the web decodes with `lib/geo.ts`.
- **Position along a leg** (`services/sim.py`): decode once, cumulative haversine lengths, `progress = clamp((now − started_at) / duration_s)` where a **sim rider's `duration_s` is `distance_m ÷ (speed_kmh / 3.6)`** (its own speed, set when its leg is created; OSRM's duration is kept only for ETA estimates before assignment), target distance = `progress × total`, interpolate on the segment; heading = bearing of that segment. Pure Python, no shapely.
- **ETA** (`services/eta.py`): `remaining_prep = max(0, prep_min × 60 − (now − accepted_at))` until `ready`; `travel = remaining_polyline_length / speed` where the remaining length is measured from the projection of the current position onto the leg polyline (nearest vertex + segment projection) and speed = the rider's median speed over the last 60 s, clamped to 12–30 km/h (sims: their fixed speed); before assignment, travel = restaurant → drop leg estimate. `eta_s = remaining_prep + travel (+ 90 s handover)`; `method = osrm | line`. v3 replaces `prep_min` with the learned median and adds the p80 band.
- **Delivery fee and radius:** the **radius is always straight-line** (`ST_DWithin(restaurant.loc, drop, 5000)`) so the list, the quote and `POST /orders` agree — a restaurant shown as orderable can never 422 `out_of_range` at checkout; `distance_m` for the **fee** = the restaurant → drop OSRM distance at quote time (fallback straight × 1.3), fee = 2500 + 800 × max(0, ceil((distance_m − 2000) / 1000)) paise.

## 5. The order state machine
`services/orders.py::transition(order_id, to, actor)`:
```
begin; select * from orders where id = $1 for update;
allowed = TRANSITIONS[(order.status, to)]          -- {roles, guard}
if actor.role not in allowed.roles or not guard(order, actor): raise 409 illegal_transition {from, to}
update orders set status = to, {to}_at = now();            -- every status has its *_at column (06 §A)
select pg_advisory_xact_lock(1); insert order_events (order_id, kind = to, actor_role, actor_id, payload);   -- commit-ordered seq
side effects in the same transaction: accepted → assign_rider(); ready → sim pickup if waiting; picked_up → new leg;
delivered → release_rider() → on_rider_available(); rejected / cancelled → refund (v2) · ledger on delivered (v2)
commit
```
The table lives in one dict (`TRANSITIONS`), the guards are one-liners (`restaurant.id == order.restaurant_id`, `rider.id == order.rider_id`, `order.status == 'placed'` for cancel). Sim riders act with `actor = system`. Every transition also emits the push (v2) after commit.

## 6. Dispatch and simulation
- `assign_rider(order)` (inside the accept transaction): nearest available (§4) → `riders.status = busy`, `orders.rider_id`, `rider_legs(to_restaurant)` from the rider's current position to the restaurant, events `rider_assigned { rider: { name, vehicle } }` and `route { kind, polyline, distance_m, duration_s }`. None → nothing; `on_rider_available(rider)` later picks `select … from orders where rider_id is null and status in ('accepted','preparing','ready') order by accepted_at limit 1 for update skip locked`.
- **Reassign:** release the old rider (`available`, its leg `ended_at`), assign the chosen one, event `rider_reassigned`; the stream pushes a fresh `route`.
- **`advance_simulation(scope)`** (`services/sim.py`): for each `is_sim` rider with an open leg in scope: `progress ≥ 1` → *to_restaurant*: if the order is `ready` → `transition(picked_up, system)` (which opens *to_customer*); else mark the leg `arrived_at` and wait (the `ready` transition checks `arrived_at` and picks up immediately); *to_customer* → `transition(delivered, system)`. Every 3 s of wall time the sim's computed position is also upserted into `rider_positions` so admin / board reads agree. Runs under `for update skip locked` so two concurrent streams never double-advance. Speed per sim rider: 22 km/h ± 10 % (`riders.speed_kmh`).
- **v2 offers:** on accept, `offer(order)` → nearest available rider without an offer for this order → `offers(expires_at = now + 30 s)`, push + stream `offer`; `POST /rider/offers/{id}/accept` (409 if expired / taken) → assign; `/decline` or the tick noticing expiry → the next rider (≤ 5) → else waits, admin flag `no_rider`. Sim riders always accept after 3–8 s (in the tick).
- **v3 batching:** on accept, before offering, look for a rider assigned to the same restaurant whose first order is not `picked_up` and whose *to_customer* estimate line is `ST_DWithin(new_drop, 1500)` → stack: `orders.rider_id`, `stack_seq = 2`, the *to_customer* leg is (re)routed with two drops (nearest first), `stops jsonb = [{ order_id, eta_s }]`, event `stacked`. Pickup marks both `picked_up`; each drop is its own `delivered`.

## 7. Money
- **Quote:** `POST /orders/quote { restaurant_id, items: [{ id, qty }], address: { lat, lng } }` → items priced from the DB (unavailable → 422 `item_unavailable { ids }`), `distance_m`, `delivery_fee_paise`, `platform_fee_paise = 500`, `total`. `POST /orders` repeats the quote server-side and never trusts client totals.
- **Razorpay:** the Skillroom recipe — `orders(pending_payment)` → `order.create` → modal → `POST /orders/{id}/verify` (HMAC) or webhook `payment.captured` → `mark_paid()` under `for update`: `pending_payment → placed`, event `placed`; else no-op; `webhook_events.id` unique. Expiry lazy at 15 min (nothing to release). COD → `placed` directly.
- **Refund (v2):** `rejected` / `cancelled` on a Razorpay order → `razorpay.payment.refund` once (`refunds` row unique per order) → event `refunded`.
- **Ledger (v2):** on `delivered` in the same transaction: `sale` +80 % of `subtotal` → `restaurant:{id}`, `fee` +20 % → `platform`, `delivery` 3000 + 800 × km(leg) → `rider:{id}`, `delivery_margin` = `delivery_fee + platform_fee − rider pay` → `platform` (signed). Balances are sums; payouts as Skillroom (request-less: admin pays any positive balance with a reference).

## 8. Web
- **Rendering:** home and restaurant pages are dynamic with tag caching (`restaurants`, `restaurant:{slug}`), `revalidate: 300`, invalidated on menu changes; the restaurant list itself is fetched client-side for the current pin (`/api/restaurants?lat&lng`). Tracking, board, rider, admin: dynamic `no-store` + `EventSource`.
- **Map component** (`components/map/Map.tsx`): MapLibre via dynamic import, style from `NEXT_PUBLIC_MAP_STYLE` (liberty) or `/map-dark.json`, a `useRiderMarker` hook that **interpolates** between the last two fixes over their time gap (max 3 s) with `requestAnimationFrame` and rotates a scooter SVG by heading; `useRoute` draws the polyline as a line layer with a **draw-on** animation (line-gradient / `line-dasharray` progress) when a `route` event arrives; trail = a second, thinner line from `rider_track` points received. Reduced motion: marker jumps, route appears.
- **`useOrderStream(orderId)`** (`lib/stream.ts`): `new EventSource('/api/orders/{id}/events')`, reducers per event kind into `{ status, events[], rider, route, eta }`, `lastEventId` handled by the browser; on `reconnect` nothing to do; on `error` exponential backoff is the browser's; a stale banner if no `ping` for 45 s.
- **Board** (`app/(restaurant)/restaurant/page.tsx`): columns driven by `useRestaurantStream`; a new `placed` event **prints a ticket** (the signature on this screen) and plays a chime (user-gesture-unlocked once); actions call `POST /restaurant/orders/{id}/transition { to }`.
- **Rider app** (`app/(rider)/rider/page.tsx`): PWA manifest + minimal SW (app shell), `useGeoUplink` (`watchPosition` → throttle 3 s / 5 m → `POST /rider/position`, `navigator.wakeLock`), the dark map, the job card, two buttons; `useRiderStream` for assignment and status.
- **Admin map:** all riders + active orders from `useAdminStream`; click an order → the reassign picker (available riders sorted by distance to the restaurant, from `/admin/riders?near=`).
- **Order together (v4):** `/o/[code]` = the restaurant menu + shared cart from `useGroupStream`; member name in `localStorage`; after checkout the same route renders the tracking view with `member_name` matched to `order_items.member_name`.
- **Motion signature and visual direction:** decided in [04-ui-mockups.md](04-ui-mockups.md) from the variant page. On the table: *Rider glide*, *Route draw*, *Status rail*, *ETA flip*, *Ticket print*, *Plate slide*, *Radar ping*, *Bell*.

## 9. Auth & access
Own session auth as every other project: `users(email citext, password_hash argon2, name, phone, role)`, `sessions`, cookie `pl_session` HttpOnly SameSite=Lax 30 d. `POST /auth/demo { as: customer|restaurant|rider|admin }`. Dependencies `require_user`, `require_restaurant` (loads the owned restaurant; 404 otherwise), `require_rider` (404), `require_admin` (404). Streams authorise once at open; an order stream also re-checks ownership on every reconnect. Group links (v4) are capability URLs (`code` = 10 random base32 chars) — no account needed to add items, the host's session needed to check out.

## 10. Caching & rendering
Restaurant pages: `s-maxage=300, stale-while-revalidate=600` + web tags. `/restaurants?lat&lng`: `private, max-age=30`. Streams, orders, rider, admin: `no-store`. Blob photos immutable by name. Map tiles cached by the browser (OpenFreeMap sends long max-age). OSRM results cached per leg in the DB (never re-requested for the same leg).

## 11. Failure modes worth handling
| Failure | Behaviour |
|---|---|
| OSRM down / slow (> 3 s) | Straight-line leg, `method = line`, ETA shown as "≈ 22 min"; the leg is not retried (a reassign draws a new one) |
| Photon down | Search shows "Drop the pin instead"; the pin still works; reverse label falls back to `lat, lng` |
| Rider phone loses GPS / goes to background | No fixes → the customer marker stops; after 30 s without a fix (server `recorded_at`) the tracking page shows "Rider's signal is weak"; the ETA freezes; the admin flags the rider after 2 min |
| GPS jump | A fix > 200 m from the previous within 3 s is dropped (204 `X-Ignored: jump`, logged) — the same rule as §3 |
| Stream hits 280 s / network drop | `EventSource` reconnects with `Last-Event-ID`; the loop replays from the log; no duplicate events (ids are monotonic) |
| No rider available | Order waits with `rider_id null`; tracking shows "Finding a rider"; admin flag after 3 min; the next freed rider takes it |
| Restaurant never accepts | Admin flag at 5 min; customer can cancel while `placed`; the board's ticket turns red at 3 min |
| Razorpay modal dismissed | Order stays `pending_payment` 15 min; checkout can re-open the same order; never on the board |
| Webhook before verify / replayed | `mark_paid` idempotent; `webhook_events.id` unique |
| Two sims advanced by two streams | `for update skip locked` — one wins, the other reads the result next tick |
| Vercel cold start on the stream | First event within ~1 s of connect (prime step); the page shows the last known state from the initial `GET /orders/{id}` meanwhile |
| Push endpoint dead (v2) | 404 / 410 → subscription deleted |
| `LISTEN` connection refused (v3, pooled URL) | Falls back to the 1-s poll automatically and logs once; the direct Neon URL is a separate env var |
| Group link after checkout (v4) | Read-only tracking; adding → 409 `checked_out` |

## 12. Testing (only these)
- `test_transitions`: every allowed row of the table for its actor; every other actor → 409; illegal jumps → 409; concurrent accepts → one event.
- `test_geo`: three restaurants at known points → correct order and distances; 5 km / 8 km boundaries; nearest-rider KNN picks the right one; `skip locked` under two concurrent assigns never double-books.
- `test_quote_and_order`: quote == order totals; tampered prices ignored; unavailable item 422; out of range 422 at 5.1 km straight-line while a 4.9 km straight / 6.2 km route address is accepted with the route-based fee; fee at 1.9 / 2.1 / 4.0 km.
- `test_mark_paid`: verify-then-webhook and webhook-then-verify → one `placed`; replay no-op; expiry at 15 min (fake clock).
- `test_stream`: an order stream with `Last-Event-ID` replays exactly the missed events; a stranger → 403; positions after `since` only; the 280-s close (fake clock).
- `test_sim`: a sim rider on a 600-m leg at its `speed_kmh` = 22 (leg `duration_s` = 98) is at the end after 98 s (fake clock); arrival before `ready` waits; `ready` triggers pickup; delivery frees the rider and assigns the waiting order.
- `test_eta`: projection onto the polyline and remaining length; `method` fallback when OSRM is mocked to fail.
- v2: `test_offers` (decline → next; expiry; double accept → one), `test_ledger` (entries sum; refund once). v3: `test_batching` (stack / not stack / max 2), `test_prep_model`. v4: `test_group` (host-only checkout; add after checkout 409).

## 13. Environment
`api/`: `DATABASE_URL` (pooled), `DATABASE_DIRECT_URL` (v3, `LISTEN`), `SESSION_SECRET`, `WEB_URL`, `API_URL`, `REVALIDATE_SECRET`, `BLOB_READ_WRITE_TOKEN`, `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET`, `OSRM_URL` (default the public server), `PHOTON_URL`; v2: `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT`. `web/`: `API_URL`, `REVALIDATE_SECRET`, `NEXT_PUBLIC_RAZORPAY_KEY_ID`, `NEXT_PUBLIC_MAP_STYLE`, `NEXT_PUBLIC_BLOB_HOST`; v2: `NEXT_PUBLIC_VAPID_PUBLIC_KEY`.
