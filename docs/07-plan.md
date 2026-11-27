# Platter — Development Plan

**Lifecycle step:** 7 of 17 · **Written:** 2026-09-17 · **Inputs:** [03-requirements.md](03-requirements.md), [04-technical-design.md](04-technical-design.md), [06-data-and-api.md](06-data-and-api.md).
**Tracker:** row status lives at https://claude.ai/artifact/HEHpyrigHuZpBMoECDs4qG (updated per milestone; rebuild the page with `python mockups/tracker-build.py`).
**Budget:** v1 ≈ 16 h · v2 ≈ 11 h · v3 ≈ 16 h · v4 ≈ 6 h = **≈ 49 h** (re-cut Viraj, 2026-11-19: native rider app into v3, heatmap to add-ons, v4 hardened). v1 runs the whole engine — PostGIS, the state machine, dispatch, the simulation and the SSE bus — from milestone 1.0, so v2 adds humans and money, v3 intelligence and the native rider app, v4 a surface; never a second engine. **Cadence:** evenings/weekends; each row = one branch + one PR, squash-merged, and **every PR shows something in the browser**. Milestones end deployed. **Build last** (order 1 → 2 → 3 → 4 → 5 → 6).

**Lean rules in force** (2026-09-15): setup is the minimum to deploy both apps with plain CI; no observability, contract gates, e2e workflows or tracker updates per PR; review findings fixed on the same branch; tests only from 04 §12. Hours saved go to the tracking page, the board's ticket moment and the seed. **Accounts and keys are created just-in-time** — in the row that first needs them, never in a setup batch: **Neon (+ PostGIS) and Vercel Blob in S2; Razorpay in F3; VAPID keys in L2; an Expo account (free; EAS build + push) in N1.** OpenFreeMap, OSRM and Photon need no account. Dish photos are CC from Wikimedia Commons, fetched by script in S2.

How the lifecycle maps: step 8 = milestone 1.0; steps 9–11 and 14–15 cycle inside every row; step 12 is one checklist row at the end of v1; step 13 is the CI file in 1.0; step 16 is skipped unless something breaks; step 17 is a short doc after v3.

Column key — **Who:** 🟢 customer · 🟠 restaurant · 🔵 rider · 🟣 admin · ⚪ platform / sim. Endpoints from 06 §C; screens from 03-user-flows.

---

## v1 — Kitchen (≈ 16 h)

### Milestone 1.0 — Skeleton + the engine live (≈ 6 h) — step 8
Goal: both apps deployed, PostGIS answering, a seeded order moving with a simulated rider over SSE, direction chosen.

| # | Part | Who | web/ | api/ | Est. | Done when |
|---|---|---|---|---|---|---|
| S1 | **Direction + tokens** | 🟢 | Direction already chosen (**L · Bento**, [04-ui-mockups.md](04-ui-mockups.md)) → tokens + Nunito in `globals.css`, tile + shadow primitives, themed browser surfaces; landing restyled to Bento | — | 1.5 h | Tokens live; the landing renders as bento tiles with the tile spring |
| S2 | **API skeleton + PostGIS + auth + seed** | ⚪ | `next.config.ts` rewrite `/api/*`; `lib/api.ts` typed fetch; `pnpm gen:api` | `pyproject` (uv), `main.py`, settings, error envelope, `/health`; models + Alembic `0001_v1` (06 §A, `create extension postgis`); `/auth/*` (argon2, sessions, `pl_session`, `/auth/demo`, four roles, `require_*`); `services/geo.py` (nearby, nearest rider), `/geo/*` (Photon proxy + limit), `GET /restaurants`, `/restaurants/{slug}`; `seed/area.json` — 12 restaurants at real Koramangala / HSR points, ~100 items, 8 sim riders at junctions + the demo rider, demo customer + addresses; `seed/fetch_photos.py` (Commons API, licence filter, backoff, `CREDITS.md`) → Blob; `seed.py` (idempotent); **accounts needed here and no others:** Vercel project `platter-api` (FastAPI preset, bom1, `maxDuration` 300) + Neon with PostGIS (`DATABASE_URL`) + Vercel Blob (`BLOB_READ_WRITE_TOKEN`); `ci.yml` (web typecheck + build · api ruff + pytest with `postgis/postgis`); **tests:** `geo`, `rbac` | 2 h | `api.platter…/docs` opens in prod; `GET /restaurants?lat&lng` for Koramangala 5th Block returns 9 orderable + 3 too far, sorted, in ≤ 150 ms; a customer hitting `/admin/*` gets 404; seed runs twice cleanly; CI green |
| S3 | **The engine: state machine + dispatch + sim + stream** | ⚪ | `lib/stream.ts` (`useOrderStream`), a bare `/orders/[id]` page that prints events and the rider's lat/lng as they arrive (the map comes in F2) | `services/orders.py` (`TRANSITIONS`, `transition()`, `quote()`, `create()` for COD), `dispatch.py` (`assign_rider`, `release_rider`, `on_rider_available`, `reassign`), `routing.py` (OSRM + fallback, polyline helpers), `sim.py` (`position_on_leg`, `advance_simulation`), `eta.py`, `stream.py` (the generator, `Last-Event-ID`, 280-s close, ping), routes `POST /orders/quote`, `POST /orders` (cod), `GET /orders/{id}`, `GET /orders/{id}/events`, `POST /restaurant/orders/{id}/transition`, `POST /rider/position`, `POST /rider/orders/{id}/transition`; seed adds two live orders in progress; **tests:** `transitions`, `quote_and_order`, `stream`, `sim`, `eta` | 2.5 h | In prod: place a COD order by curl → accept as the restaurant → a sim rider is assigned with an OSRM route → mark ready → the bare page prints a position every second moving along real streets → `delivered` with no human action; kill the connection, reconnect with `Last-Event-ID` → the missed events replay once; tests green |

### Milestone 1.1 — Order and watch (≈ 5 h) 🟢
| # | Part | Who | web/ | api/ | Est. | Done when |
|---|---|---|---|---|---|---|
| F1 | **Home + restaurant + cart** | 🟢 | S1 home: `PinHeader` (MapLibre mini-map, draggable pin, geolocation), `AddressSearch` (Photon), `RestaurantList` with `RestaurantCard` (cover via `next/image`, distance / ETA / fee, too far / closed states); S2 restaurant page with `Menu`, `MenuItem` (veg mark, availability), `CartSheet` (`lib/cart.ts`, per-restaurant, switch prompt); S11 addresses; **Plate slide** into the cart bar; tile spring on the list | cache headers; `app/api/revalidate` contract; `/addresses*` | 1.5 h | Moving the pin 3 km re-sorts and re-prices the list without a reload; Lighthouse mobile ≥ 90 / 100 / 100 on home and restaurant with no CLS; an unavailable item cannot be added |
| F2 | **Tracking page — the hero** | 🟢 | S5 `/orders/[id]`: `Map` (MapLibre dynamic import, liberty style), `RouteLayer` (**Route draw**), `RiderMarker` (**Rider glide**: rAF interpolation between fixes, heading), `TrailLayer`, the tile grid with **Tile spring** and colour swaps per state, ETA roll, Steam while cooking, Handover at delivered, `PinMarker` + `RestaurantMarker`, `StatusRail` lit from events, `EtaBadge`, `OrderSummary`, `RiderCard`, cancel while placed, "Finding a rider" / "signal weak" states; S16 states | `GET /orders`, `POST /orders/{id}/cancel`; `rider_track` in the stream prime; ETA recompute rules | 2 h | Watching a seeded live order: the route draws, the marker glides along Koramangala's streets, the ETA falls, the rail lights step by step, delivered lands without a refresh; reduced motion: jumps and no draw; closing the laptop lid for a minute and reopening replays and catches up |
| F3 | **Checkout + Razorpay + orders** | 🟢 | S4 `/checkout` (`CheckoutForm`: address pick / pin, payment COD / Razorpay, quote, note), `RazorpayButton` (lazy `checkout.js`, modal, verify, dismissed message); S6 `/orders` history; S10 sign in / up with the four demo cards | **Razorpay test account + webhook created here** (`RAZORPAY_*`); `services/razorpay.py`, `mark_paid`, `expire_stale`, `POST /orders` (razorpay), `/orders/{id}/verify`, `/webhooks/razorpay`; order numbers `PL-####`; **test:** `mark_paid` | 1.5 h | A customer orders on a phone with the test card in under 2 minutes and lands on the tracking page as `placed`; the webhook replay is a no-op; an unpaid order never reaches the board and expires at 15 min |

### Milestone 1.2 — The other three sides + close (≈ 5 h) 🟠🔵🟣
| # | Part | Who | web/ | api/ | Est. | Done when |
|---|---|---|---|---|---|---|
| F4 | **Restaurant board** | 🟠 | `(restaurant)` layout (404 otherwise); S7 board: `TicketColumn` × 4, `Ticket` (**Ticket print** entrance + chime on new, column pulse, Bell), Accept / Reject (reason) / Preparing / Ready, rider name + distance, age colouring; `TodayStats`; S12 `AvailabilityList` | `GET /restaurant/board`, `GET /restaurant/events` (scope: restaurant, rider distance while *to_restaurant*), `PATCH /restaurant/items/{id}` | 2 h | On a tablet the ticket prints ≤ 2 s after a customer places an order; Accept dispatches a rider whose distance ticks down on the ticket; an item toggled off vanishes from the customer menu and is refused at order time |
| F5 | **Rider app + admin map** | 🔵🟣 | `(rider)` layout; S8 `/rider`: PWA manifest + `sw.js` shell, `JobCard`, dark `Map` (`map-dark.json`), `ShareLocationToggle` (`lib/geoUplink.ts`: `watchPosition`, 3 s / 5 m throttle, wake lock, persisted), `BigButtons` (Picked up enabled at ready, Delivered), next job, today's count; `(admin)` layout; S9 `/admin`: `LiveMap` (all riders + active orders, sims dotted), `OrdersTable` with stuck flags, `ReassignPicker` | `GET /rider/me`, `GET /rider/events`; `GET /admin/map`, `/admin/orders`, `/admin/riders?near=`, `POST /admin/orders/{id}/reassign`, `GET /admin/events` (riders every 2 s); stuck rules | 1.5 h | **The two-phone demo:** rider login on a phone, toggle on, walk — the marker on the laptop's tracking page walks too, ≤ 2 s behind; Picked up before ready → 409 shown as a disabled button; admin reassigns a stuck order and the customer's route redraws within a tick |
| F6 | **Home-screen polish + v1 close** | 🟢⚪ | S16 remaining states; empty / error states; themed surfaces; landing → real home; README "how the bus works" with the sequence diagram | `docs/12-security-performance.md` (one page + Lighthouse numbers); `rider_track` pruning script; latency note (poll mode) | 1.5 h | Lighthouse budgets hold; v1 tagged; case-study entry drafted with the two-phone recording |

**v1 total ≈ 16 h**

**v1 as built (2026-11-26, branch `feat/v1`) — where it departs from the rows above, and why:**
- **Dish photos** are 87 CC Commons thumbnails committed under `web/public/dishes/` (served from the web origin, credited in `CREDITS.md`) instead of Vercel Blob — no Blob account needed in v1; `fetch_photos.py` can still upload to Blob later.
- **Dark rider map** uses OpenFreeMap's own `dark` style instead of a generated `map-dark.json`.
- **Kitchen autopilot** (new, `services/sim.py`): while nobody has a restaurant's board open (`restaurants.board_seen_at`, the one v1 column beyond 06 §A), its orders are accepted after 45 s and cooked for its prep time, so an order from any kitchen completes with no human action. Opening the board hands the kitchen back to the human.
- **Demo scenes** (`services/demo.py`): each demo login stages live orders through the real state machine (an order on the way for the customer, tickets on the board, a job for the demo rider, orders on the admin map); sim customers place an occasional order while the board or admin map is open. A catch-up after a quiet period stamps each step with when it really happened.
- **Dispatch** only considers a real (non-sim) rider who sent a fix in the last 2 minutes; the rider PWA's **relay mode** replays the phone's steps in Koramangala when the phone is far from Bengaluru, so the two-phone demo works anywhere.
- **Razorpay** is implemented against the REST API (no SDK) and switches itself off without keys (checkout offers COD only).


---

## v2 — Rush (≈ 11 h)

### Milestone 2.0 — Humans in the loop (≈ 4 h) 🔵🟢🟠
| # | Part | web/ | api/ | Est. | Done when |
|---|---|---|---|---|---|
| L1 | **Rider offers + online toggle** | S8 `OfferCard` (30-s countdown ring, Accept / Decline), online / offline toggle; S9 `no_rider` flag; S5 "Finding a rider" now shows attempts | `offers`; `POST /rider/status`; `dispatch.offer()` chain (≤ 5, lazy expiry in the tick, sims auto-accept 3–8 s; every offer state change is one conditional `update … where state = 'sent'` and only the winner runs side effects); `/rider/offers/{id}/accept` · `/decline`; stream `offer`; **test:** `offers` | 2.5 h | Decline on the phone → the next rider is offered within a tick; an expired offer cannot be accepted; two phones accepting → one assignment; **race test** (Viraj, 2026-11-19): an accept and the timeout expiry of the same offer run concurrently at the boundary → exactly one transition wins; the loser makes no assignment, no push, no next offer, no `order_event` |
| L2 | **Web Push** | `pushManager.subscribe` in customer, board and rider PWAs (`sw.js` `push` + `notificationclick` → the right page); opt-in prompts at the right moment (after first order / on the board / on going online) | **VAPID keys generated here** (`scripts/gen_vapid.py`); `push_subscriptions`; `services/push.py` (`pywebpush`, 410 cleanup); sends after commit on accepted / picked_up / delivered / rejected (customer), placed (restaurant), offer / assigned (rider); `GET /push/key`, `POST/DELETE /push/subscribe` | 1.5 h | With the tab closed on a phone, `picked_up` notifies within 5 s and the tap opens the tracking page; a dead endpoint is removed |

### Milestone 2.1 — Menus, money, memory (≈ 7 h) 🟠🟢🟣
| # | Part | web/ | api/ | Est. | Done when |
|---|---|---|---|---|---|
| L3 | **Menu management + restaurant details** | S12 full editor: categories (add / rename / reorder), items (form, ₹, veg, photo drop via Blob client token, availability), restaurant details (cover, hours per weekday, open override, prep time) | `/restaurant/categories*`, `/restaurant/items*`, `/restaurant/items/{id}/photo/token` (client-upload protocol, ≤ 5 MB), `PATCH /restaurant`; revalidate on change; `restaurant_closed` in quote | 2.5 h | A new item with a photo shows on the restaurant page within the cache window; marking closed removes the restaurant from "open now" and refuses orders |
| L4 | **Search, filters, history, ratings** | S1 search box (URL `q`), cuisine chips, veg toggle, sort; S6 **Reorder** with the dropped-items note; S5 rating card after delivered; stars on cards and tickets | `restaurants.search` tsvector + trigger; `/restaurants?q&cuisine&veg&sort`; `POST /orders/{id}/reorder`, `/orders/{id}/rating`; averages | 2 h | "dosa" finds a restaurant by item name only; reorder with one discontinued item explains what was dropped; a second rating → 409 |
| L5 | **Refunds + ledgers + payouts + v2 close** | S13 `/restaurant/earnings`, `/rider/earnings` (balance, entries), `/admin/payouts` (balances by account, pay with reference), admin refund button | `refunds` (auto on rejected / cancelled Razorpay), `ledger_entries` on delivered (sale 80 / fee 20 / delivery ₹30 + ₹8/km / delivery_margin), `payouts`; `services/ledger.py`; `POST /admin/orders/{id}/refund`; **test:** `ledger` | 2.5 h | A delivered ₹640 order writes entries summing to ₹640 + fees; rejecting a paid order refunds once; a payout above balance → 422; v2 tagged; case study updated |

**v2 total ≈ 11 h**

---

## v3 — Fleet (≈ 16 h)

Re-cut (Viraj, 2026-11-19): the **native rider app** moves in — the v1 PWA stops sending GPS when the screen locks, and background location needs a native app; the demand heatmap + "where to wait" hint move to add-on I. Hours from the rows: 3.0 = 3 + 2 + 1.5 = 6.5 h; 3.1 = 2.5 + 3 + 1 + 1.5 + 1.5 = 9.5 h; **v3 = 16 h**.

### Milestone 3.0 — Smarter dispatch, true push (≈ 6.5 h) ⚪🟣🟢
| # | Part | web/ | api/ | Est. | Done when |
|---|---|---|---|---|---|
| A1 | **Batching** | S5 "one more drop before yours" + stop order; S8 job card with two drops; S9 stacked orders drawn as one leg | `dispatch.try_stack()` (same restaurant, drop ≤ 1.5 km off the route via `ST_DWithin` on the line, not yet picked up, max 2), multi-stop OSRM leg, `rider_legs.stops`, `orders.stack_seq`, event `stacked`; pickup marks both; per-order delivered; **test:** `batching` | 3 h | Two eligible orders → one rider, one 3-waypoint route, two correct ETAs; a far drop is not stacked; a third is not stacked |
| A2 | **Measured ETA** | S5 `EtaBadge` with the band ("18–24 min"); S9 ETA error column | `prep_stats` (average ± SD of the restaurant's last 20 `accepted → ready` — measured from our own history, no model), `riders.median_speed_mps` (the rider's own last 10 legs), `eta_log` per phase with `actual_s` on delivery; `eta` events gain `band`; seed history feeds it; **test:** `measured_eta` | 2 h | Mean absolute ETA error at `accepted` on the seeded history ≤ 4 min; the band never inverts |
| A3 | **LISTEN / NOTIFY** | — | `notify_platter` trigger on `order_events` + `rider_positions`; `db.py` direct engine (`DATABASE_DIRECT_URL`); `stream.py` waits on the notification with a 5-s safety poll, automatic fallback to polling — `NOTIFY` only wakes the loop, which still reads `order_events where seq > $last` (the durable log; reconnects replay by seq); `scripts/measure_latency.py` (50 fixes, p50 / p95) → README | 1.5 h | Measured p50 ≤ 300 ms, p95 ≤ 1 s rider POST → customer event; unplugging the direct URL falls back to polling with one log line; a dropped notification loses no event |

### Milestone 3.1 — Native rider app (≈ 9.5 h) 🔵🟣
| # | Part | rider-app/ · web/ | api/ | Est. | Done when |
|---|---|---|---|---|---|
| N1 | **Expo shell + job + native map** | `rider-app/` (Expo SDK, TypeScript, expo-router): sign-in (demo rider), `JobCard`, `react-native-maps` with the route from `route` events, Picked up / Delivered, online toggle, offer card; `/rider/events` via `react-native-sse`; **Expo account created here** | Bearer session beside the cookie (`Authorization: Bearer`, token in `expo-secure-store`) — same routes, no fork | 2.5 h | On an Android phone in Expo Go: sign in as the demo rider, see the job and route, accept an offer, mark picked up — same API |
| N2 | **Background location + source** | `expo-task-manager` task + `Location.startLocationUpdatesAsync` with an Android foreground service; battery-aware sampler (≥ 5 m or 3 s moving, 15 s stationary); permission flow (foreground → background); S9 admin map badges sim / PWA / native | `position_source` (`sim \| pwa \| native`) on `rider_positions` + `rider_track`; server writes `sim`, clients may send only `pwa` / `native` (else 422); `rider` / `riders` events carry `source` | 3 h | Phone locked 5 min on a job → the customer's marker keeps moving (`source = native`); stationary 1 min → ≤ 1 fix / 15 s; the admin map shows the three kinds distinctly |
| N3 | **Expo push for offers** | `expo-notifications` token → `POST /push/expo`; tapping opens the offer | `expo_push_tokens`; `services/push.py` sends offer / assignment via Expo's push API (no key) beside Web Push; `DeviceNotRegistered` → token deleted | 1 h | With the app closed an offer notifies within 5 s; accepting from it assigns; a dead token is removed |
| N4 | **Offline status queue** | queued taps in AsyncStorage `{ idempotency_key, order_id, to, tapped_at }`, flushed in order on reconnect (NetInfo); "2 waiting to sync" chip | `Idempotency-Key` on `POST /rider/orders/{id}/transition` → `rider_ops` row in the transition's transaction; same key → stored response, no second transition / event; **test:** `rider_ops` | 1.5 h | Picked up + Delivered tapped in airplane mode sync once on reconnect, in order; flushing twice adds no `order_events`; a tap made stale by a reassign → 409 shown once and dropped |
| N5 | **APK + v3 close** | EAS build → Android APK (sideloaded, no store listing) + an Expo Go link; README "PWA in v1 → native in v3"; `docs/17-post-launch.md` (½ page); case study with the locked-screen recording | — | 1.5 h | The APK runs the locked-screen demo; the PWA still completes a delivery as the fallback; v3 tagged; case study live |

**v3 total ≈ 16 h**

---

## v4 — Order together (≈ 6 h) — the unique free feature 🟢

### Milestone 4.0 — One link, many phones (≈ 6 h)
Same core, a new place: the order leaves one phone. ₹0 per use (Viraj, 2026-09-17). Re-estimated 3 → 6 h for many phones editing at once — the R4-2 rules (Viraj, 2026-11-19).

| # | Part | web/ | api/ | Est. | Done when |
|---|---|---|---|---|---|
| U1 | **Group cart + secure link** | S3 **Order together** → share sheet (`navigator.share` / copy); S15 `/o/[code]`: the restaurant menu + shared cart with member names, join once with a name, remove own, host controls; `useGroupStream` | `groups` (`code` = 128-bit `token_urlsafe(16)`), `group_members` (signed `pl_grp` cookie), `group_items` unique (group, member, item), `group_events`; `POST /groups`, `POST /groups/{code}/join`, `GET /groups/{code}`, `POST/DELETE /groups/{code}/items`, `GET /groups/{code}/events` (stream scope: group); per-IP lookup limit; **test:** `group` | 2 h | An item added on phone B appears on phone A ≤ 2 s with B's name; 1 000 random codes → 404 and the limiter trips; B cannot remove A's line (403); only the host sees Checkout |
| U2 | **Concurrency, availability, expiry** | Struck-through unavailable lines with Remove; "This group cart expired"; host **Stop sharing** | atomic `insert … on conflict do update set qty = qty + $d`; board toggle / restaurant close → `item_unavailable` / `restaurant_closed` to open groups; lazy expiry (1 h idle / 3 h) → 410; revoke → 404 | 2 h | Two phones adding the same dish 10× at once → qty 20, identical carts; an item toggled off mid-session is struck on both ≤ 2 s and checkout → 409 until removed; 61 min idle (fake clock) → 410 |
| U3 | **Host checkout + shared tracking + v4 close** | S15 after checkout = the S5 tracking view for every member with "your items" highlighted; `GroupMembers` on the host's `/orders/[id]`; README "one link, many phones"; `docs/17-post-launch.md` (½ page); case study | `POST /groups/{code}/checkout` (host only; group row `for update`, `open → checked_out` conditional; adds hold it `for share`) → one order with `group_id`, `order_items.member_name`; member-scoped view (no payment, contact or cancel); the group stream hands over to the order's events; links expire 24 h after delivered | 2 h | Member checkout → 403; two host taps → one order; an add racing checkout is in the order or 409, never orphaned; both phones show the same rider gliding; member payloads carry no payment / contact fields; delivered + 24 h → "expired"; v4 tagged; case study live |

**v4 total ≈ 6 h** · **Project total ≈ 49 h**

---

## Whole-product summary
| Version | Milestones | Hours | Cumulative |
|---|---|---|---|
| v1 Kitchen | 1.0 – 1.2 | 16 | 16 |
| v2 Rush | 2.0 – 2.1 | 11 | 27 |
| v3 Fleet | 3.0 – 3.1 | 16 | 43 |
| v4 Order together | 4.0 | 6 | 49 |
| Add-ons (in priority order) | A storefront + embed (3) · B scheduled orders (2) · C tips (1) · D promo codes (2) · E chat (3) · F proof of delivery (2) · G Telegram bot (2) · H restaurant analytics (2) · I demand heatmap + where to wait (1.5) | up to 18.5 | up to 67.5 |

## Add-ons (only from time saved)
**Nice-to-have, not priority** (Viraj, 2026-09-17): considered only after v4 is fully done (docs and case study included), in this order, from time saved — and skipping all of them is a fine outcome. None is a version; none changes the engine. All free to run.

| # | Add-on | What | Version it extends | ~h |
|---|---|---|---|---|
| A | **Restaurant storefront + embed** | `/r/[slug]/order` as a white-label page (the restaurant's name and colours, Platter in the footer) plus a one-line `<script>` embed that opens it in a drawer on the restaurant's own site; orders and tracking are the same core | v1 | 3 |
| B | **Scheduled orders** | "Deliver at 8 pm" on checkout; the order sits as `scheduled` and becomes `placed` at `prep_min + travel` before the slot (lazy, in the tick) | v1 | 2 |
| C | **Rider tips** | ₹10 / ₹20 / ₹50 on the tracking page after delivered (Razorpay); a `tip` ledger entry to the rider | v2 | 1 |
| D | **Promo codes** | `promos(code, percent \| flat, min_subtotal, max_uses, expires_at)` applied in the quote; the ledger keeps the discount on the platform side | v2 | 2 |
| E | **Customer ↔ rider chat** | Canned + free-text messages over the same stream loop (`order_messages` rows → `message` events), both apps; closes at delivered | v1 | 3 |
| F | **Proof of delivery** | The rider takes a photo at the drop (Blob client token, ≤ 2 MB); shown on the tracking page and the admin | v1 | 2 |
| G | **Telegram status bot** | Link a chat once; status changes arrive as Telegram messages with the tracking link (Bot API, free) | v2 | 2 |
| H | **Restaurant analytics** | Orders per hour, top items, accept time, rating trend for the last 30 days on the board | v2 | 2 |
| I | **Demand heatmap + where to wait** | `/admin/heatmap`: PostGIS `ST_HexagonGrid(250 m)` over 7 days of pickups + drops, hour slider; an idle rider sees a "busy area" hint (the top hex for this hour) — moved from v3 (Viraj, 2026-11-19) | v3 | 1.5 |
