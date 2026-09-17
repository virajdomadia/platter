# Platter — User Flows & Screen Index

**Lifecycle step:** 3 of 17 · **Locked:** 2026-09-17 · Pairs with [03-requirements.md](03-requirements.md); every screen below gets a mockup in [04-ui-mockups.md](04-ui-mockups.md).

## Flow 1 — Pin to delivered (v1, the main path)

```mermaid
flowchart LR
  H[S1 Home · pin + restaurants] --> R[S2 Restaurant · menu]
  R -->|add items| C[S3 Cart sheet]
  C --> K[S4 Checkout · address · COD / Razorpay]
  K -->|COD → placed| T[S5 Tracking · Placed]
  K -->|Razorpay modal → verify → mark_paid| T
  T -->|restaurant accepts · rider assigned| T2[S5 Tracking · rider on the map]
  T2 -->|ready · picked up| T3[S5 Tracking · rider gliding · ETA]
  T3 -->|delivered| D[S5 Tracking · Delivered → rate in v2]
  D --> O[S6 Orders · history]
```

## Flow 2 — The order state machine (v1)

```mermaid
stateDiagram-v2
  [*] --> pending_payment: POST /orders (razorpay)
  [*] --> placed: POST /orders (cod)
  pending_payment --> placed: verify / webhook → mark_paid()
  pending_payment --> expired: 15 min, lazy
  placed --> accepted: restaurant · assign_rider()
  placed --> rejected: restaurant (reason) · refund v2
  placed --> cancelled: customer · refund v2
  accepted --> preparing: restaurant
  preparing --> ready: restaurant · waiting sim picks up
  ready --> picked_up: assigned rider / sim · leg to_customer
  picked_up --> delivered: assigned rider / sim · rider available → next waiting order
  delivered --> [*]
  note right of accepted
    every transition: select … for update ·
    role check · status check · orders.status ·
    order_events append (the bus) · else 409
  end note
```

## Flow 3 — Live location: rider → bus → customer (v1, the hard part)

```mermaid
sequenceDiagram
  participant RP as Rider phone (/rider)
  participant API as FastAPI
  participant PG as Postgres (PostGIS)
  participant CU as Customer (/orders/id)
  RP->>API: POST /rider/position {lat, lng, heading, speed, at} (every 3 s / ≥ 5 m)
  API->>PG: upsert rider_positions · insert rider_track
  CU->>API: GET /orders/{id}/events (EventSource, Last-Event-ID?)
  API->>PG: order + legs + events since seq · position since pos_ms
  API-->>CU: event: route {polyline} · event: status · event: rider {lat,lng,heading} · event: eta
  loop every 1 s until 280 s (v3: on NOTIFY)
    API->>PG: advance_simulation() · events > seq · position > pos_ms
    API-->>CU: rider / status / eta events (id: seq:pos_ms) · ping every 15 s
  end
  API-->>CU: stream closes at 280 s
  CU->>API: reconnect with Last-Event-ID (nothing missed — the log is durable)
```

## Flow 4 — Dispatch (v1 nearest · v2 offers · v3 batching)

```mermaid
flowchart TD
  A[restaurant accepts] --> Q{available rider<br/>KNN loc <-> restaurant}
  Q -->|v1: nearest| AS[assign: rider busy · orders.rider_id · leg to_restaurant via OSRM · event rider_assigned]
  Q -->|none| W[order waits · rider_id null<br/>tracking shows Finding a rider]
  W -->|a rider becomes available| AS
  AS --> ADM[admin reassign → release old · assign new · new leg]
  subgraph v2 offers
    Q -->|nearest not yet offered| OF[offer · 30 s countdown on the phone]
    OF -->|accept| AS
    OF -->|decline / expiry| Q
    OF -->|5 riders tried| W
  end
  subgraph v3 batching
    AS -->|second accepted order from the same restaurant<br/>drop ≤ 1.5 km off the route · not yet picked up| ST[stack on the same rider · multi-stop leg]
  end
```

## Flow 5 — Simulated rider clock (v1)

```mermaid
stateDiagram-v2
  [*] --> available: seed at a junction
  available --> to_restaurant: assign_rider · leg with OSRM polyline · started_at
  to_restaurant --> waiting: progress = 1 and order not ready
  to_restaurant --> to_customer: progress = 1 and order ready → picked_up
  waiting --> to_customer: restaurant marks ready → picked_up
  to_customer --> available: progress = 1 → delivered → takes the oldest waiting order
  note right of to_restaurant
    position(now) = point along the polyline at
    min(1, (now − started_at) / duration_s), where a sim's duration_s = distance_m ÷ its speed_kmh;
    computed in every stream tick and every order read —
    no process, idempotent under row locks
  end note
```

## Flow 6 — Checkout money (v1) and refund (v2)

```mermaid
sequenceDiagram
  participant C as Customer
  participant API as FastAPI
  participant RZ as Razorpay
  C->>API: POST /orders/quote {items, address} → totals
  C->>API: POST /orders {items, address, payment}
  alt cod
    API-->>C: order PL-1042 placed
  else razorpay
    API->>RZ: order.create(amount)
    API-->>C: {order_id, razorpay_order_id, key_id}
    C->>RZ: Standard Checkout modal
    C->>API: POST /orders/{id}/verify {payment_id, signature}
    API->>API: mark_paid() → placed (idempotent)
    RZ->>API: webhook payment.captured → mark_paid() → no-op
  end
  Note over API: v2 · rejected / cancelled razorpay → refund once · event refunded
```

## Flow 7 — Restaurant board and rider app (v1)

```mermaid
flowchart LR
  subgraph Board["Board · S7"]
    N[New · ticket prints + chime] -->|Accept| CK[Cooking]
    N -->|Reject + reason| X[gone]
    CK -->|Ready| RD[Ready · rider name + distance]
    RD -->|rider picked up| OD[Out for delivery]
  end
  subgraph Rider["Rider · S8"]
    J[Job card · to restaurant] -->|arrive| WT[Waiting for ready]
    WT -->|Picked up| TC[To customer · dark map · route]
    TC -->|Delivered| NX[Next job / idle]
  end
  CK -.->|assign_rider| J
```

## Flow 8 — Order together (v4)

```mermaid
flowchart LR
  A[S3 Cart · Order together] -->|POST /groups| L["/o/CODE · shared cart"]
  L -->|friend opens on phone B · name once| L2[adds items under their name]
  L2 -->|group_events over SSE| L
  L -->|host checks out · one order with group_id| T["/o/CODE = S5 Tracking for everyone"]
  T -->|your items highlighted per phone| T
  T -->|24 h after delivered| E[link expired]
```

## Screen index

| # | Screen | Route | Who | Version | Notes |
|---|---|---|---|---|---|
| S1 | Home | `/` | all | v1 · search / filters in v2 | Exists as landing; becomes the pin + restaurants list (map header, address search, cards with distance / ETA / fee) |
| S2 | Restaurant | `/r/[slug]` | all | v1 | Cover, info strip, menu by category with photos, veg marks, availability, add-to-cart |
| S3 | Cart | `/r/[slug]` (sheet) | customer | v1 · Order together in v4 | Items, quantities, note, totals preview, Checkout |
| S4 | Checkout | `/checkout` | customer | v1 | Address (saved / pin), payment COD / Razorpay, quote, Place order; Razorpay modal + dismissed state |
| S5 | **Tracking** | `/orders/[id]` | customer | v1 · rating in v2 · ETA band in v3 · group view in v4 | **The hero:** map with route, rider marker gliding, trail, ETA, status rail, order summary, cancel while placed |
| S6 | Orders | `/orders` | customer | v1 · reorder in v2 | History with status chips |
| S7 | **Restaurant board** | `/restaurant` | restaurant | v1 | Tablet columns New · Cooking · Ready · Out; ticket entrance; accept / reject / preparing / ready; today's totals |
| S8 | **Rider app** | `/rider` | rider | v1 · offers + online toggle in v2 · busy-area hint in v3 | Phone PWA: job card, dark map with route, Share my location, Picked up / Delivered |
| S9 | **Admin map** | `/admin` | admin | v1 · heatmap in v3 | Live map of orders + riders, stuck flags, reassign picker, today's numbers |
| S10 | Sign in / up + demo | `/sign-in`, `/sign-up` | all | v1 | Four demo cards: customer · restaurant · rider · admin |
| S11 | Addresses | `/addresses` | customer | v1 | Saved addresses with pins; add via search / drag |
| S12 | Restaurant menu | `/restaurant/menu` | restaurant | v1 (availability) · full editor in v2 | Availability toggles; v2 categories, items, photos, hours |
| S13 | Earnings + payouts | `/restaurant/earnings`, `/rider/earnings`, `/admin/payouts` | restaurant / rider / admin | v2 | Balances, entries, mark paid |
| S14 | Heatmap | `/admin/heatmap` | admin | v3 | Hex grid, hour slider |
| S15 | Order together | `/o/[code]` | anyone with the link | v4 | Shared cart with names → the tracking page after checkout |
| S16 | States | various | all | v1 | Finding a rider, restaurant closed, too far, cart from another restaurant, payment dismissed, empty history, offline rider |
