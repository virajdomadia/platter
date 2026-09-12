# PRD — Platter: Food delivery with live rider tracking

**Status:** draft v0 (basic) · to be detailed together
**Name:** Platter · *hot food, tracked to your door*
**URL:** https://platter.virajdomadia.com
**Slot:** #6 · Budget ~40 h · Build last

## One-liner
A three-sided food-delivery app for one city: customers order from nearby restaurants, restaurants accept and prepare, riders deliver — and the customer watches the rider move on the map in real time.

## Who it's for
- **Customer:** ordering dinner on a phone.
- **Restaurant:** a tablet view of incoming orders.
- **Rider:** a phone view with the next delivery and a "share my location" toggle.
- **Admin:** dispatch overview.

## Why this project
- Geospatial queries + live location streaming + a multi-step order state machine across three roles — the closest thing to "Swiggy-scale problems" a portfolio can show.
- Cloud kitchens and local restaurant groups are real clients.

## Core features (thin vertical slice)
**Customer**
- Set delivery location (map pin / search) → restaurants within radius, sorted by distance/ETA
- Restaurant menu, cart, Razorpay / COD checkout
- Order tracking page: status steps + rider marker moving live + ETA

**Restaurant**
- Live incoming orders board; accept / reject / mark ready; toggle menu item availability

**Rider**
- Assigned order, pickup & drop on map, "start sharing location", mark picked up / delivered

**Admin**
- Map of active orders and riders; manual reassign

## The wow moment
Place an order on one phone, open the rider view on another, walk around — the marker moves on the customer's screen.

## Out of scope (v1)
Automatic rider dispatch optimisation, promo codes, ratings, chat, real routing/turn-by-turn.

## Tech notes (to discuss)
- Geo: PostGIS (Neon supports it) — restaurants within radius, distance sort; MapLibre + free tiles
- Live location: rider posts GPS every few seconds → WebSocket/SSE fan-out to that order's customer only
- Order state machine: placed → accepted → preparing → ready → picked_up → delivered / rejected, with role-guarded transitions
- Notifications: web push for status changes (nice-to-have)

## Success criteria
- Rider location appears on the customer map within ~2 s of an update
- Every state transition is validated server-side by role (covered by tests)

## Open questions
- Simulated riders (scripted routes) for the public demo, plus real GPS for live demos?
- Payments: Razorpay only, or COD as the default for simplicity?
