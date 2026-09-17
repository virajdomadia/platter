# Platter — Requirements & Scope

**Lifecycle step:** 3 of 17 · **Locked:** 2026-09-17 · **Source:** [PRD.md](../PRD.md) locked decisions. Flows and screen index: [03-user-flows.md](03-user-flows.md).

Actors: **Customer** (signed in to order; browsing is public), **Restaurant** (one owner per restaurant, `/restaurant`), **Rider** (`/rider`, a phone), **Admin** (`/admin`), **Sim** (the lazy simulation, runs inside API requests). Each requirement ends with **Accept:** — the check that closes it. Ids: R = v1, R2 = v2, R3 = v3, R4 = v4. Money in ₹, integer paise in the DB; distances in metres; times in seconds.

---

## v1 — Kitchen (base, ≈ 16 h)

### R1. Auth & roles
- Email + password, cookie session (`pl_session`, HttpOnly, SameSite=Lax, 30 d); sign up / in / out. `users.role ∈ {customer, restaurant, rider, admin}`; a restaurant user owns exactly one `restaurants` row, a rider user exactly one `riders` row. Four demo logins on the landing (`POST /auth/demo`).
- `/restaurant/*` requires `restaurant`, `/rider/*` requires `rider`, `/admin/*` requires `admin` — 404 to anyone else. `/checkout`, `/orders/*` require any session; a customer sees only their own orders.
- **Accept:** a customer never sees the board, the rider app or the admin; a restaurant sees only its own orders; sessions expire after 30 days.

### R2. Location & discovery
- Home: the delivery pin (browser geolocation with permission, else the last saved address, else the seed default — Koramangala 5th Block) on a MapLibre map with a draggable marker; Photon search box for an address; saved addresses list (label, line, pin).
- `GET /restaurants?lat=&lng=` → restaurants within **5 km** (`ST_DWithin`), sorted by distance, each with distance, ETA (prep + travel), cuisines, veg flag, rating (v2), cover; restaurants 5–8 km appear greyed "Too far"; closed restaurants show hours.
- Restaurant page `/r/[slug]`: cover, name, area, cuisines, prep time, distance / delivery fee for the current pin, menu by category with photos, veg / non-veg marks, `is_available` (unavailable items greyed, not addable).
- **Accept:** for any pin in the seed area the list returns in ≤ 150 ms with correct order (SQL check against `ST_Distance`); moving the pin 3 km re-sorts and re-prices; an unavailable item cannot be added (422 on `POST /orders`).

### R3. Cart & checkout
- Cart per restaurant in `localStorage` (switching restaurant asks to clear). `/checkout`: items, address (saved or the current pin with a line typed), payment `cod | razorpay`, note to restaurant; totals from `POST /orders/quote` (subtotal, delivery fee, platform fee ₹5, total).
- `POST /orders` prices everything server-side: current item prices, availability, restaurant open, address within 5 km (route distance from OSRM else straight line × 1.3), fee ₹25 up to 2 km + ₹8 per started km. COD → `placed`; Razorpay → `pending_payment` + Razorpay order → modal → `POST /orders/{id}/verify` or webhook → **`mark_paid()`** → `placed`. Unpaid orders `expired` lazily after 15 min. Order number `PL-####`.
- **Accept (tests):** the total equals the quote for the same payload; a tampered client price is ignored; verify-then-webhook and webhook-then-verify → exactly one `placed` event; replay is a no-op; an address at 6 km → 422 `out_of_range`.

### R4. The order state machine
- `status ∈ {pending_payment, placed, accepted, preparing, ready, picked_up, delivered, rejected, cancelled, expired}`. Transitions and who may make them:

| From → To | Who | Side effects |
|---|---|---|
| `pending_payment → placed` | `mark_paid` (system) | event `placed`; board sees it |
| `placed → accepted` | restaurant | `assign_rider()` (R6); `accepted_at` |
| `placed → rejected` | restaurant (reason) | refund if Razorpay (v2); event |
| `placed → cancelled` | customer (only while `placed`) | refund (v2) |
| `accepted → preparing` | restaurant | — |
| `preparing → ready` | restaurant | `ready_at`; a waiting sim rider picks up |
| `ready → picked_up` | assigned rider (or sim) | leg *to_customer*; `picked_up_at` |
| `picked_up → delivered` | assigned rider (or sim) | rider `available` → takes the oldest waiting order; `delivered_at` |
| `pending_payment → expired` | lazy, 15 min | — |

- Every transition runs in one transaction under `select … for update`, checks the role and the current status, writes `orders.status` and appends `order_events(kind = status, payload)`; anything else → 409 `illegal_transition` with `{ from, to }`.
- **Accept (tests):** every row of the table succeeds for its actor and 409s for every other actor; `preparing → delivered` is refused; two concurrent `accept`s produce one `accepted` event.

### R5. Live tracking (customer)
- `/orders/[id]`: MapLibre map with the restaurant, the drop pin, the route polyline, the rider marker and its trail; a status rail `Placed · Accepted · Cooking · Ready · Picked up · Delivered` lit from `order_events`; ETA; the order summary; "Cancel" while `placed`; the rider's name and a mock call button once assigned.
- `GET /orders/{id}/events` (SSE, owner only): `route` once per leg (polyline, distance, duration), `status` per event, `rider` for every new position (≤ 1 s after it lands), `eta` whenever status or position changes, `ping` every 15 s; `id: {seq}:{pos_ms}`; the server closes at 280 s and `EventSource` reconnects with `Last-Event-ID`.
- The marker **glides** between fixes (interpolated over the 3-s interval, heading-rotated); reduced motion: jumps.
- **Accept:** a position posted by the rider phone is on the customer map ≤ 2 s later (measured with `performance.now()` on both ends in the case study); killing the connection for 20 s and reconnecting replays every missed event exactly once (test with a fake clock); a stranger's `GET /orders/{id}/events` → 403.

### R6. Dispatch
- `assign_rider(order)` on `accepted`: `select riders … where status = 'available' order by loc <-> restaurant.loc limit 1 for update skip locked` → rider `busy`, `orders.rider_id`, `rider_legs(to_restaurant)` with OSRM polyline (fallback straight line), events `rider_assigned` + `route`. None available → `rider_id null` and the tracking page shows "Finding a rider"; `on_rider_available(rider)` assigns the oldest `accepted | preparing | ready` order without a rider.
- Admin `POST /admin/orders/{id}/reassign { rider_id }`: the current rider (if any) is released to `available`, the new one assigned, a new leg drawn, event `rider_reassigned`.
- **Accept (tests):** with three riders at known points the nearest is chosen; `skip locked` under two concurrent accepts never double-books a rider; reassigning releases the old rider; an order waiting for a rider is taken the moment one becomes available.

### R7. Rider app
- `/rider` (phone, installable PWA): status toggle (online / offline in v2; v1 only *Share my location*), current job card (restaurant → customer, items count, distance, pay preview), a dark MapLibre map with the leg's route and the rider's own position, two big buttons **Picked up** (enabled at `ready`) and **Delivered**, next job when free, today's deliveries count.
- *Share my location* → `navigator.geolocation.watchPosition` (high accuracy) → `POST /rider/position` every 3 s or ≥ 5 m; a screen wake lock while on; the toggle state survives reloads. `GET /rider/events` pushes assignment and order status to the phone.
- **Accept:** on a phone, switching the toggle on posts positions (network tab) and the customer map moves; *Picked up* before `ready` → 409; *Delivered* ends the job and the next waiting order (if any) is offered within one tick.

### R8. Restaurant board
- `/restaurant` (tablet / desktop, landscape): columns **New · Cooking · Ready · Out for delivery**, each order as a ticket (number, items, note, customer first name, payment, age); **Accept / Reject** on new, **Preparing** and **Ready** buttons, the rider's name + distance once assigned; a chime + a printed-ticket entrance on new orders (`GET /restaurant/events`); today's totals (orders, revenue, avg accept time). `/restaurant/menu` (v1: availability toggles only).
- **Accept:** a new order appears on the board ≤ 2 s after `placed` without a refresh; toggling an item off removes it from the customer menu on the next request and blocks it in `POST /orders`.

### R9. Admin
- `/admin`: a live MapLibre map of every active order (restaurant → rider → drop) and every rider (available / busy / offline; sims with a dotted ring), an orders list with status, age and **stuck** flags (`placed` > 5 min unaccepted, `accepted` > 3 min without a rider, `ready` > 10 min not picked up), **Reassign** with a rider picker, today's numbers. `GET /admin/events` streams every order event and all rider positions every 2 s.
- **Accept:** reassigning an order moves its marker to the new rider within one tick; a stuck order is flagged at the right age (test with a fake clock).

### R10. Simulation & seed
- `advance_simulation()` (decision 3) runs at the top of every stream tick and inside every order read / transition: for each sim rider on a leg, compute progress; leg complete → the transition of R4 as the rider, or wait for `ready`. Sim speed 22 km/h ± 10 % per rider; a sim rider "posts" a position each tick (the stream computes it; `rider_positions` is upserted every 3 s so admin / restaurant views agree).
- Idempotent seed: admin; demo customer (three saved addresses, ~10 past orders); 12 restaurants with owner logins, categories, ~100 items with CC photos in Blob (`api/app/seed/fetch_photos.py` — Commons API, licence filter, backoff, `CREDITS.md`); 8 sim riders at real junctions + the demo rider; ~60 delivered orders over 30 days with events, legs and tracks; two live orders in progress so the demo has something moving from the first second.
- **Accept:** `seed` runs twice without duplicates; an order placed with COD reaches `delivered` with no human action after the restaurant marks `ready` (test with a fake clock: the sim arrives, picks up, delivers); ETA on sims is within ±3 min of the actual delivery.

---

## v2 — Rush (mid, ≈ 11 h)

### R2-1. Offers
- `riders.status ∈ {offline, available, busy}` with an online toggle on the rider app. On `accepted`: `offers(order, rider, expires_at = now + 30 s)` to the nearest available rider not already offered this order; `GET /rider/events` pushes `offer` with a countdown; **Accept** → assigned (as v1); **Decline** or expiry → the next nearest, up to 5 riders; then the order waits and the admin sees it flagged. Expiry is lazy (checked in the tick).
- **Accept (tests):** decline → the next rider is offered within one tick; an expired offer cannot be accepted (409); accepting from two phones at once yields one assignment.

### R2-2. Web Push
- VAPID keys (generated once, free); `push_subscriptions(user, endpoint, keys)` from `pushManager.subscribe` in the customer, board and rider PWAs; `pywebpush` sends: customer → accepted / picked up / delivered / rejected; restaurant → new order; rider → new offer / assignment. Stale endpoints (410) deleted.
- **Accept:** with the tab closed on a phone, `picked_up` produces a notification within 5 s; a 410 endpoint is removed.

### R2-3. Menu management
- `/restaurant/menu`: categories (add, rename, reorder), items (name, description, ₹, veg, photo upload via Blob client token ≤ 5 MB, availability), restaurant details (cover, hours per weekday, `is_open` override, prep time).
- **Accept:** a new item with a photo shows on `/r/[slug]` within the cache window; a restaurant marked closed disappears from the "open now" list and `POST /orders` → 422 `restaurant_closed`.

### R2-4. Search, filters, history, ratings
- Home search (`q` over restaurant names, cuisines, item names — `tsvector`), cuisine chips, veg-only toggle, sort by distance / ETA / rating. `/orders`: past orders with **Reorder** (rebuilds the cart if items still exist). After `delivered`: rate the restaurant and the rider (1–5 + a line) once; averages on cards and the admin.
- **Accept:** "dosa" finds a restaurant by item name only; reorder with one discontinued item explains what was dropped; a second rating → 409.

### R2-5. Refunds, ledgers, payouts
- Rejection / cancellation of a Razorpay order → automatic refund (`refunds`), event `refunded`. On `delivered`: ledger entries — restaurant `sale` +80 % of the food subtotal, platform `fee` +20 %, rider `delivery` ₹30 + ₹8 per km of the *to_customer* leg, platform `delivery_margin` = delivery fee + platform fee − rider pay (signed, may be negative). `/restaurant/earnings` and `/rider/earnings` show balances and entries; `/admin/payouts` lists balances by account and marks payouts paid with a reference.
- **Accept (tests):** entries per delivered order sum to the order total; a rejected Razorpay order refunds once; balances are sums; a payout above balance → 422.

---

## v3 — Fleet (advanced, ≈ 8 h)

### R3-1. Batching
- When a rider is assigned to or heading for restaurant R and another order from R becomes `accepted` whose drop is ≤ 1.5 km from any point of the first order's *to_customer* route (`ST_DWithin` on the route line) and the first is not yet `picked_up`, the second is **stacked** on the same rider (max 2). Pickup covers both; the *to_customer* leg becomes a multi-stop OSRM route (nearest drop first); each order's ETA is its own stop; `delivered` per order. The customer sees "Your rider has one more drop before yours" when second.
- **Accept (tests):** two eligible orders → one rider, one 3-waypoint leg, two correct ETAs; a drop 3 km off the route is not stacked; a third order is not stacked.

### R3-2. Smart ETA
- `prep_model`: per restaurant, the median and p80 of `accepted → ready` over the last 20 orders (fallback: the restaurant's declared prep time); rider speed = the median of the rider's last 10 legs (fallback 22 km/h). ETA = remaining prep (median) + travel at the rider's speed; the band = [median, p80] shown as "18–24 min". Accuracy logged per delivered order (`eta_error_s`) and shown on the admin.
- **Accept:** on the seeded history the mean absolute ETA error at `accepted` is ≤ 4 min; the band never inverts.

### R3-3. LISTEN / NOTIFY
- `order_events` and `rider_positions` writes `NOTIFY platter, '{order_id}'` via a trigger; the stream loop holds a direct (non-pooled) asyncpg connection with `LISTEN platter` and wakes on notification instead of sleeping 1 s (a 5-s safety poll stays). Latency (`rider POST → customer event`) is measured by a script on 50 fixes and published in the README.
- **Accept:** p50 ≤ 300 ms, p95 ≤ 1 s on the measured run; falling back to polling if `LISTEN` fails is automatic and logged.

### R3-4. Heatmap & where to wait
- `/admin/heatmap`: PostGIS hex grid (`ST_HexagonGrid`, 250 m) over the last 7 days of order drops and pickups, coloured by count, with an hour-of-day slider. The rider app shows a "busy area" hint (the top hex for this hour) when idle.
- **Accept:** hex counts match a SQL check; the hint changes with the hour.

---

## v4 — Order together (unique, free, ≈ 3 h)

### R4-1. The link
- On the cart, **Order together** → `POST /groups { restaurant_id, address }` → `groups(code, host_user, restaurant, status open|checked_out)` and `/o/{code}`. Anyone opening the link (no account needed; a display name asked once, kept in `localStorage`) sees the same menu and the shared cart; `POST /groups/{code}/items` adds under their name; `DELETE` their own; the host may remove anything. Live over `GET /groups/{code}/events` (the same stream loop over `group_events`). The host checks out (COD or Razorpay) → one `orders` row with `group_id`, items tagged by member; the group becomes `checked_out`.
- After checkout `/o/{code}` shows the **tracking page** (R5) to every member — the map, the status rail, the rider — with "your items" highlighted for the phone that added them; the host's `/orders/[id]` is the same page. The link expires 24 h after delivery.
- **Accept:** an item added on phone B appears on phone A ≤ 2 s; only the host can check out (403); after checkout both phones stream the same rider; a fresh phone with the link after checkout sees the tracking page read-only.

---

## Out of scope (all versions)
Multi-city · turn-by-turn navigation · paid maps / routing / realtime / AI · KYC · GST invoices · native apps · multi-restaurant carts · real money · surge pricing · shifts · support tooling · multiple admins · scheduled deliveries (add-on) · tips (add-on) · chat (add-on).
