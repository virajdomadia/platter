# Platter — Database + API Design

**Lifecycle step:** 6 of 17 · **Locked:** 2026-09-17 · Behaviour in [04-technical-design.md](04-technical-design.md). Alembic `0001_v1` creates everything under **A** (after `create extension if not exists postgis`); v2 / v3 / v4 tables get their own migrations.

## A. Postgres schema (v1)

```sql
create extension if not exists postgis;

create type user_role     as enum ('customer','restaurant','rider','admin');
create type rider_status  as enum ('offline','available','busy');
create type order_status  as enum ('pending_payment','placed','accepted','preparing','ready','picked_up','delivered','rejected','cancelled','expired');
create type payment_kind  as enum ('cod','razorpay');
create type leg_kind      as enum ('to_restaurant','to_customer');
create type route_method  as enum ('osrm','line');

users            (id uuid pk, email citext unique, password_hash text, name text, phone text null, role user_role default 'customer', created_at)
sessions         (id text pk, user_id uuid fk, expires_at timestamptz, created_at)                         index (user_id)
addresses        (id uuid pk, user_id fk, label text, line text, loc geography(point,4326), created_at)   index (user_id)

restaurants      (id uuid pk, owner_user_id uuid fk unique, slug citext unique, name text, area text, cuisines text[],
                  is_veg bool default false, loc geography(point,4326), address text, prep_min int default 15,
                  hours jsonb,                       -- {mon: [["11:00","23:00"]], …}
                  is_open bool default true, cover_url text null, rating numeric(2,1) null, created_at)
                  index gist (loc) · index (slug)
menu_categories  (id uuid pk, restaurant_id fk, name text, sort int)                                       index (restaurant_id, sort)
menu_items       (id uuid pk, restaurant_id fk, category_id fk, name text, description text null,
                  price_paise int check (price_paise > 0), is_veg bool, photo_url text null,
                  is_available bool default true, sort int)                                                index (restaurant_id, category_id, sort)

riders           (id uuid pk, user_id uuid fk unique, name text, phone text, vehicle text,               -- 'scooter' | 'cycle'
                  is_sim bool default false, status rider_status default 'available', speed_kmh numeric(4,1) default 22.0, created_at)
                  index (status)
rider_positions  (rider_id uuid pk fk, loc geography(point,4326), heading smallint null, speed_mps numeric(5,2) null,
                  recorded_at timestamptz,                        -- server now(): the cursors and staleness checks use this
                  client_at timestamptz null)                     -- the phone's own clock, only to drop out-of-order fixes
                  index gist (loc)
rider_track      (id bigserial pk, order_id uuid fk, rider_id fk, at timestamptz, loc geography(point,4326))   index (order_id, at)

orders           (id uuid pk, number text unique,                     -- 'PL-1042', sequence-backed
                  user_id fk, restaurant_id fk, rider_id uuid fk null,
                  status order_status, payment payment_kind,
                  address_line text, drop_loc geography(point,4326),  -- snapshot
                  subtotal_paise int, delivery_fee_paise int, platform_fee_paise int, total_paise int,
                  distance_m int, route_method route_method, eta_s int null, note text null,
                  razorpay_order_id text unique null, razorpay_payment_id text null,
                  created_at, placed_at null, accepted_at null, preparing_at null, ready_at null,
                  picked_up_at null, delivered_at null, rejected_at null, cancelled_at null, expired_at null, reject_reason text null,
                  group_id uuid null (v4), stack_seq smallint null (v3))
                  index (user_id, created_at desc) · index (restaurant_id, status) · index (rider_id) where rider_id is not null ·
                  index (status, accepted_at) where rider_id is null
order_items      (id uuid pk, order_id fk, menu_item_id fk null, name text, price_paise int, qty int, is_veg bool, member_name text null (v4))  index (order_id)
order_events     (seq bigserial pk, order_id fk, kind text, actor_role text, actor_id uuid null, payload jsonb, at timestamptz default now())
                  index (order_id, seq) · index (seq)
rider_legs       (id uuid pk, order_id fk, rider_id fk, kind leg_kind, polyline text, distance_m int, duration_s int,
                  method route_method, started_at timestamptz, arrived_at null, ended_at null, stops jsonb null (v3))
                  index (rider_id) where ended_at is null · index (order_id)
webhook_events   (id text pk, event text, received_at)
```

`order_events` is append-only and is the bus; its `seq` is **commit-ordered** because every insert takes `pg_advisory_xact_lock(1)` first (04 §3), so a stream cursor `seq > $last` never skips an event. `kind ∈ placed | accepted | rejected | cancelled | preparing | ready | picked_up | delivered | expired | rider_assigned | rider_reassigned | route | note` (v2 adds `offer_sent | offer_declined | offer_expired | refunded`, v3 `stacked`); `payload` carries what the event needs (`route`: polyline + distance + duration + kind; `rider_assigned`: name + vehicle). `rider_positions` holds one row per rider (latest); `rider_track` is the trail for the order's map and the case study, pruned 7 days after `delivered`. `orders.drop_loc` and `address_line` are snapshots. Every `*_at` is set by its transition. Money is integer paise; `distance_m` is the OSRM (or straight × 1.3) restaurant → drop distance at quote time.

**transition recipe** (every actor, every edge):
```sql
begin;
  select * from orders where id = $1 for update;
  -- TRANSITIONS[(status, $to)] → roles + guard; not allowed → rollback, 409 illegal_transition {from, to}
  update orders set status = $to, <to>_at = now() where id = $1;
  select pg_advisory_xact_lock(1);                                          -- commit-ordered seq (taken after every row lock)
  insert into order_events (order_id, kind, actor_role, actor_id, payload) values ($1, $to, $role, $actor, $payload);
  -- side effects in the same transaction: accepted → assign_rider · ready → sim pickup if arrived ·
  -- picked_up → new leg · delivered → release_rider + on_rider_available (+ ledger v2)
commit;
```

**nearest available rider** (inside `assign_rider`):
```sql
select r.id from riders r join rider_positions p on p.rider_id = r.id
where r.status = 'available'
order by p.loc <-> (select loc from restaurants where id = $restaurant) limit 1
for update of r skip locked;
```

**nearby restaurants:**
```sql
select r.*, ST_Distance(r.loc, ST_MakePoint($lng, $lat)::geography)::int as distance_m
from restaurants r
where ST_DWithin(r.loc, ST_MakePoint($lng, $lat)::geography, 8000)
order by distance_m;   -- ≤ 5000 orderable, 5000–8000 "Too far"
```

**stream read per tick** (order scope):
```sql
select * from order_events where order_id = $o and seq > $seq order by seq;
select loc, heading, speed_mps, recorded_at from rider_positions where rider_id = $rider and recorded_at > to_timestamp($pos_ms / 1000.0);
-- sim riders: position computed from rider_legs (polyline, started_at, duration_s) — no read
```

**v2 additions:** `offers (id, order_id fk, rider_id fk, state text sent|accepted|declined|expired, expires_at, created_at)` unique (order_id, rider_id) · index (rider_id, state); `push_subscriptions (id, user_id fk, endpoint text unique, p256dh text, auth text, created_at)`; `ratings (id, order_id fk unique, restaurant_stars smallint, rider_stars smallint, line text null, created_at)`; `refunds (id, order_id fk unique, razorpay_refund_id text, amount_paise int, created_at)`; `ledger_entries (id, account text — 'platform' | 'restaurant:{id}' | 'rider:{id}', kind text sale|fee|delivery|delivery_margin|payout, amount_paise int signed, order_id fk null, payout_id uuid null, created_at)` index (account, created_at); `payouts (id, account text, amount_paise int, reference text, paid_by fk, paid_at)`; `restaurants.search tsvector` (name A, cuisines B, item names C via trigger) + GIN; `riders.online_since`.
**v3 additions:** `prep_stats (restaurant_id pk, median_s int, p80_s int, sample int, updated_at)`; `riders.median_speed_mps`; `eta_log (order_id fk, at, eta_s, actual_s null, method, phase text)`; `orders.stack_seq`; `rider_legs.stops`; trigger `notify_platter` on `order_events` and `rider_positions` → `pg_notify('platter', order_id / rider_id)`.
**v4 additions:** `groups (id, code text unique, host_user_id fk, restaurant_id fk, address_line, drop_loc, status text open|checked_out, order_id fk null, created_at, expires_at)`; `group_items (id, group_id fk, menu_item_id fk, member_name text, qty int, created_at)` index (group_id); `group_events (seq bigserial, group_id fk, kind text item_added|item_removed|checked_out, payload jsonb, at)` index (group_id, seq).

## B. Blob keys
| Prefix | Written by | Deleted when |
|---|---|---|
| `dishes/{restaurant_slug}/{item_id}.jpg` | Seed (`fetch_photos.py`) · v2 menu editor (client token, ≤ 5 MB) | Item deleted / photo replaced |
| `covers/{restaurant_slug}.jpg` | Seed · v2 restaurant details | Replaced |

## C. REST API (`/api/*` from the browser; FastAPI serves `/docs`)

Error envelope everywhere: `{ "error": { "code": "illegal_transition", "message": "…", "details": {…} } }`. Auth via cookie; `🔒` = signed in, `🍽` = restaurant owner (404 otherwise, own restaurant only), `🛵` = rider (404), `👑` = admin (404), `📡` = SSE stream (`text/event-stream`). Money fields are paise integers; points are `{ lat, lng }`.

### Auth
| Method | Path | Body → Returns |
|---|---|---|
| POST | `/auth/sign-up` | `{ email, password, name, phone? }` → `Me` |
| POST | `/auth/sign-in` | `{ email, password }` → `Me` |
| POST | `/auth/sign-out` | → 204 |
| GET | `/auth/me` | `Me { id, name, email, role, restaurant?: { id, slug, name }, rider?: { id, name, status } }` · 401 |
| POST | `/auth/demo` | `{ as: 'customer' \| 'restaurant' \| 'rider' \| 'admin' }` → `Me` |

### Geo & discovery (public)
| Method | Path | Returns |
|---|---|---|
| GET | `/geo/search?q=&lat=&lng=` | `Place[] { label, line, lat, lng }` (Photon, bbox Bengaluru, 10/min/IP) |
| GET | `/geo/reverse?lat=&lng=` | `Place` |
| GET | `/restaurants?lat=&lng=&q= (v2)&cuisine= (v2)&veg= (v2)&sort= (v2)` | `RestaurantCard[]` — within 8 km, `orderable` = ≤ 5 km and open; `distance_m`, `eta_s`, `delivery_fee_paise` for the pin · `private, max-age=30` |
| GET | `/restaurants/{slug}?lat=&lng=` | `Restaurant` (info + `categories → items` with `is_available`; distance / fee for the pin when given) · 404 |

### Customer 🔒
| Method | Path | Body → Returns |
|---|---|---|
| GET/POST/DELETE | `/addresses` · `/addresses/{id}` | `{ label, line, lat, lng }` → `Address` |
| POST | `/orders/quote` | `{ restaurant_id, items: [{ id, qty }], address: { lat, lng } }` → `Quote { items: QuoteItem[], subtotal_paise, delivery_fee_paise, platform_fee_paise, total_paise, distance_m, eta_s }` · 422 `item_unavailable { ids }` / `out_of_range` / `restaurant_closed` |
| POST | `/orders` | `Quote request + { address_line, address_id?, payment: 'cod' \| 'razorpay', note? }` → `OrderStart { order: Order, razorpay?: { order_id, key_id, amount_paise } }` |
| POST | `/orders/{id}/verify` | `{ razorpay_payment_id, razorpay_signature }` → `Order` · 400 `bad_signature` |
| GET | `/orders` | `OrderCard[]` (own) |
| GET | `/orders/{id}` | `Order` (items, status, timestamps, rider `{ name, vehicle }?`, legs, eta, events) — own only · 404 |
| POST | `/orders/{id}/cancel` | → `Order` · 409 unless `placed` |
| GET 📡 | `/orders/{id}/events` | SSE — see **D** · 403 not owner |

### Restaurant 🍽
| Method | Path | Body → Returns |
|---|---|---|
| GET | `/restaurant/board` | `Board { new: Ticket[], cooking: Ticket[], ready: Ticket[], out: Ticket[], today: { orders, revenue_paise, avg_accept_s } }` |
| POST | `/restaurant/orders/{id}/transition` | `{ to: 'accepted' \| 'rejected' \| 'preparing' \| 'ready', reason? }` → `Ticket` · 409 `illegal_transition` |
| GET/PATCH | `/restaurant/menu` · `/restaurant/items/{id}` | v1: `{ is_available }` only → `MenuItem` |
| GET 📡 | `/restaurant/events` | SSE — order events for this restaurant + rider distance while *to_restaurant* |

### Rider 🛵
| Method | Path | Body → Returns |
|---|---|---|
| GET | `/rider/me` | `RiderMe { rider, job?: Job { order, leg, restaurant, drop, items_count, pay_preview_paise }, today: { deliveries, pay_paise } }` |
| POST | `/rider/position` | `{ lat, lng, heading?, speed_mps?, at }` → 204; `recorded_at` is server time, `at` only orders fixes from the same phone (older `at` → 204 `X-Ignored: stale`; > 200 m within 3 s → 204 `X-Ignored: jump`, dropped) |
| POST | `/rider/orders/{id}/transition` | `{ to: 'picked_up' \| 'delivered' }` → `Job \| null` · 409 |
| GET 📡 | `/rider/events` | SSE — `assigned`, `status`, `route`, `offer` (v2) |

### Admin 👑
| Method | Path | Body → Returns |
|---|---|---|
| GET | `/admin/map` | `{ orders: AdminOrder[] (active, with rider, legs, stuck?: string), riders: AdminRider[] (position, status, is_sim, current_order?), today: { orders, delivered, revenue_paise, avg_delivery_s } }` |
| GET | `/admin/orders?status=&stuck=` | `AdminOrder[]` |
| GET | `/admin/riders?near=lat,lng` | `AdminRider[]` sorted by distance (for the reassign picker) |
| POST | `/admin/orders/{id}/reassign` | `{ rider_id }` → `AdminOrder` · 409 if the rider is busy / the order is not assignable |
| GET 📡 | `/admin/events` | SSE — every order event + `riders` snapshot every 2 s |

### Server-to-server
| Method | Path | Notes |
|---|---|---|
| POST | `/webhooks/razorpay` | `X-Razorpay-Signature` HMAC over the raw body; `webhook_events.id` unique; `payment.captured → mark_paid`, `payment.failed → no-op (stays pending until expiry)` |
| POST (web) | `{WEB_URL}/api/revalidate` | `{ tags: [], secret }` — on menu / restaurant changes |

### v2
| Method | Path | Notes |
|---|---|---|
| 🛵 | `POST /rider/status { status: 'available' \| 'offline' }` · `POST /rider/offers/{id}/accept` · `/decline` | offers; 409 `offer_expired` / `offer_taken` |
| 🔒 | `POST /push/subscribe { endpoint, keys }` · `DELETE /push/subscribe` | VAPID public key at `GET /push/key` |
| 🍽 | `POST/PATCH/DELETE /restaurant/categories*` · `/restaurant/items*` · `POST /restaurant/items/{id}/photo/token` · `PATCH /restaurant` (hours, is_open, prep_min, cover) | menu editor; Blob client-upload protocol |
| 🔒 | `POST /orders/{id}/rating { restaurant_stars, rider_stars, line? }` · `POST /orders/{id}/reorder` → `{ cart, dropped: string[] }` | once per order |
| 🍽 🛵 | `GET /restaurant/earnings` · `GET /rider/earnings` → `Earnings { balance_paise, paid_paise, entries[] }` | |
| 👑 | `GET /admin/payouts` (balances by account) · `POST /admin/payouts { account, amount_paise, reference }` · `POST /admin/orders/{id}/refund` | |

### v3
`GET 👑 /admin/heatmap?hour=` → `{ hexes: [{ geojson, count }] }` · `GET 🛵 /rider/hint` → `{ area, centre, count }` · order `eta` events gain `band: [lo, hi]` and `stack: { seq, of }` · `scripts/measure_latency.py` (rider POST → customer event, 50 fixes).

### v4
`POST 🔒 /groups { restaurant_id, address_line, lat, lng }` → `Group { code, url }` · `GET /groups/{code}` → `GroupView { restaurant, items: GroupItem[] (member_name), totals, status, order_id? }` · `POST /groups/{code}/items { menu_item_id, qty, member_name }` · `DELETE /groups/{code}/items/{id}` (own or host) · `POST 🔒 /groups/{code}/checkout { payment, note? }` (host only → `OrderStart`) · `GET 📡 /groups/{code}/events` (group events, then the order's events after checkout).

## D. Stream events and payload shapes
```ts
// SSE frames: id: "{seq}:{pos_ms}" · event: <kind> · data: <json>. retry: 1000. ": ping" every 15 s. "event: reconnect" at 280 s.
type StatusEvent   = { order_id: string; status: OrderStatus; at: string; reason?: string; rider?: { name: string; vehicle: string } };
type RouteEvent    = { order_id: string; kind: 'to_restaurant' | 'to_customer'; polyline: string; distance_m: number; duration_s: number; method: 'osrm' | 'line'; stops?: { order_id: string; eta_s: number }[] };
type RiderEvent    = { order_id?: string; rider_id: string; lat: number; lng: number; heading: number | null; speed_mps: number | null; at: string; is_sim?: boolean };
type EtaEvent      = { order_id: string; eta_s: number; method: 'osrm' | 'line'; band?: [number, number]; phase: 'cooking' | 'to_restaurant' | 'to_customer' };
type OfferEvent    = { offer_id: string; order: Job; expires_at: string };                    // v2, rider stream
type RidersEvent   = { riders: AdminRider[] };                                                // admin stream, every 2 s
type GroupEvent    = { kind: 'item_added' | 'item_removed' | 'checked_out'; item?: GroupItem; order_id?: string }; // v4

type RestaurantCard = { id: string; slug: string; name: string; area: string; cuisines: string[]; is_veg: boolean; cover: { url: string; width: number; height: number } | null;
                        rating: number | null; prep_min: number; distance_m: number; eta_s: number; delivery_fee_paise: number; orderable: boolean; reason?: 'too_far' | 'closed' };
type Restaurant  = RestaurantCard & { address: string; hours: Record<string, [string, string][]>; categories: { id: string; name: string; items: MenuItem[] }[] };
type MenuItem    = { id: string; name: string; description: string | null; price_paise: number; is_veg: boolean; photo: { url: string; width: number; height: number } | null; is_available: boolean };
type Quote       = { items: { id: string; name: string; price_paise: number; qty: number }[]; subtotal_paise: number; delivery_fee_paise: number; platform_fee_paise: number; total_paise: number; distance_m: number; eta_s: number };
type Order       = { id: string; number: string; status: OrderStatus; payment: 'cod' | 'razorpay'; restaurant: { slug: string; name: string; lat: number; lng: number }; drop: { line: string; lat: number; lng: number };
                     items: { name: string; price_paise: number; qty: number; is_veg: boolean; member_name?: string }[]; totals: Omit<Quote, 'items'>;
                     rider?: { name: string; vehicle: string; phone_masked: string }; legs: RouteEvent[]; eta?: EtaEvent; events: StatusEvent[]; timestamps: Partial<Record<OrderStatus, string>>; group?: { code: string; members: string[] } };
type Ticket      = { id: string; number: string; status: OrderStatus; placed_at: string; age_s: number; customer_first_name: string; payment: 'cod' | 'razorpay'; note: string | null;
                     items: { name: string; qty: number; is_veg: boolean }[]; total_paise: number; rider?: { name: string; distance_m: number; eta_s: number } };
type Job         = { order: Order; leg: RouteEvent; phase: 'to_restaurant' | 'waiting' | 'to_customer'; pay_preview_paise: number };
type AdminOrder  = Order & { stuck?: 'unaccepted' | 'no_rider' | 'not_picked_up'; rider_id?: string };
type AdminRider  = { id: string; name: string; status: 'offline' | 'available' | 'busy'; is_sim: boolean; lat: number; lng: number; heading: number | null; current_order?: string; last_fix_s: number };
type Me          = { id: string; name: string; email: string; role: 'customer' | 'restaurant' | 'rider' | 'admin'; restaurant?: { id: string; slug: string; name: string }; rider?: { id: string; name: string; status: string } };
```
