# Platter

**Hot food, tracked to your door.** A four-sided food-delivery platform for one Bengaluru neighbourhood (Koramangala + HSR Layout): customers order from kitchens that can actually reach them, restaurants run a live order board, riders get dispatched and share their GPS from a phone, and an admin sees every order and rider on one map — and the rider moves on the customer's map in real time.

> Status: **v1 Kitchen and v2 Rush built** (milestones 1.0–1.2, 2.0–2.1). One of six portfolio projects by [Viraj Domadia](https://virajdomadia.com). Live: https://platter.virajdomadia.com (Web Push needs the VAPID keys set on the API; without them it stays off).

## Try it
Every side has a one-tap demo login on the home page and `/sign-in`:

| Demo | What you land on |
|---|---|
| 🙂 **Customer** (Ananya) | Three saved addresses and an order already on the way — the route draws itself and the rider glides along real streets. Search by dish ("dosa"), filter by cuisine or pure veg, reorder a past order, rate a delivered one, and turn on notifications for when the tab is closed |
| 🍳 **Restaurant** (Bandstand Kitchen) | The kitchen board on a tablet: tickets print with a chime; Accept offers the order to the nearest rider. The **menu editor** (dishes, categories, hours, open/closed, cover) works on a private copy that resets at the next demo sign-in, so customers keep seeing the live menu. **Earnings**: 80% of each delivered order's food |
| 🛵 **Rider** (Divya) | A phone PWA. Jobs arrive as **offers** with a 30-second ring (accept or decline); a *Taking jobs* switch takes you offline. Switch on *Share my location* and walk — the customer's map walks with you (outside Bengaluru, *relay mode* replays your steps in Koramangala). **Earnings**: ₹30 + ₹8/km per drop |
| 🗺️ **Admin** | Every active order and rider on one map, stuck flags (including "no rider, 5 asked"), reassign; **Payouts**: balances by kitchen and rider, mark paid, refund an order paid online |

Eight riders are simulated (no process: a sim's position is computed from its route and the clock whenever anyone looks; a sim accepts an offer 3 to 8 seconds after it arrives), and while nobody is on a restaurant's board a *kitchen autopilot* accepts and cooks its orders, so an order placed from any kitchen is delivered with no human action. The demo rider is real.

The one-tap demo logins are public, so they are a **partition**, not just accounts: they only ever see and act on demo orders, demo money and the demo kitchen's private menu copy. A real customer's order never reaches the demo board, rider or admin; a demo visitor can't notify, refund or publicly rate anything real.

## What it proves
- **PostGIS**: restaurants within 5 km of a pin (`ST_DWithin`, GIST), nearest available rider by KNN with `skip locked`.
- **A role-guarded state machine**: `placed → accepted → preparing → ready → picked_up → delivered` (+ rejected, cancelled, expired), one `transition()` under a row lock, 409 for anything else.
- **Live location over SSE with Postgres as the bus** — no WebSockets, no Pusher, ₹0 per order: MapLibre + OpenFreeMap, OSRM routes, Photon geocoding.
- **Humans in the dispatch loop (v2)**: a 30-second offer per rider, up to five riders; every outcome (accept, decline, timeout) is one conditional `update … where state = 'sent'` after the order's row lock, so an accept racing its own timeout, or two phones accepting, has exactly one winner (tested concurrently).
- **Money to three parties (v2)**: a delivered order writes ledger entries (kitchen 80% of the food, platform the rest, rider ₹30 + ₹8/km, platform the delivery margin) that always sum to what the customer paid; a paid order that won't arrive is refunded once (a unique row before Razorpay is called); payouts can't exceed a balance, even when two land at once.
- **Web Push (v2)** from the same event log, sent after commit with fixed templates (no visitor-typed text on a lock screen), each subscription tied to its browser session.

## How the bus works
Every status change appends a row to `order_events` (commit-ordered `seq`: events are buffered in the transaction and inserted at commit under `pg_advisory_xact_lock(1)`, after its row locks, so a slow OSRM call never holds the lock). Riders POST GPS fixes into `rider_positions`. One stream loop in `api/app/services/stream.py` serves four scopes (order, restaurant, rider, admin): every second it advances the lazy simulation for its scope, reads `order_events where seq > $cursor` and positions newer than its position cursor, and yields SSE frames with `id: {seq}:{pos_ms}`. It closes itself at 280 s; the browser reconnects with `Last-Event-ID` and the loop replays exactly what was missed — `order_events` is the durable log, so a dropped connection loses nothing.

```mermaid
sequenceDiagram
  participant RP as Rider phone (/rider)
  participant API as FastAPI (stream loop)
  participant PG as Postgres + PostGIS
  participant CU as Customer (/orders/id)
  RP->>API: POST /rider/position {lat, lng, heading, at} (every 3 s / 5 m)
  API->>PG: upsert rider_positions · insert rider_track
  CU->>API: GET /orders/{id}/events (EventSource)
  API-->>CU: snapshot (the whole order)
  loop every 1 s, until 280 s
    API->>PG: advance_simulation() · events where seq > cursor · position newer than cursor
    API-->>CU: status / route / rider / eta frames (id: seq:pos_ms) · ping every 15 s
  end
  API-->>CU: reconnect
  CU->>API: GET /orders/{id}/events + Last-Event-ID: 4312:1758112233000
  API-->>CU: replays events > 4312, positions after that ms — nothing missed
```

v1 polls the log once a second. v3 adds `LISTEN/NOTIFY` purely as a wake-up for the same read (the log stays the source of truth) and publishes measured latency. ETAs are remaining prep + the remaining route at the rider's own speed; v3's ETA range is *measured from our own history* (average ± 1 SD of the restaurant's last 20 orders) — never "learned".

## Stack
Next.js 15 (App Router) · TypeScript · Tailwind 4 · MapLibre GL + OpenFreeMap · FastAPI (Python 3.12, uv) · SQLAlchemy 2 async + GeoAlchemy2 + Alembic · Neon Postgres + PostGIS · SSE · OSRM · Photon · Razorpay (test mode) · Vercel (built on GitHub Actions)

## Repo
```
api/   FastAPI — app/{core,models,schemas,routers,services,seed}, alembic/, tests/ (134 tests, PostGIS), scripts/
web/   Next.js — app/(site) customer · (restaurant) board · (rider) PWA · (admin) map; components/; lib/; tests/
docs/  03 requirements + flows · 04 technical design + UI · 05 architecture · 06 data + API · 07 plan · 12 security + performance
```

## Run locally
Needs Postgres with PostGIS (e.g. `docker run -p 5432:5432 -e POSTGRES_HOST_AUTH_METHOD=trust postgis/postgis:17-3.5`), [uv](https://docs.astral.sh/uv/) and pnpm.
```bash
# api
cd api
uv sync
export DB=postgresql+asyncpg://postgres@localhost:5432/platter
ALEMBIC_URL=$DB uv run alembic upgrade head
SEED_DATABASE_URL=$DB uv run python -m app.seed.seed      # add --offline to skip OSRM
DATABASE_URL=$DB uv run uvicorn app.main:app --port 8000  # /docs for the API
TEST_DATABASE_URL=postgresql+asyncpg://postgres@localhost:5432/platter_test uv run pytest

# web (another terminal)
cd web
pnpm install
API_URL=http://localhost:8000 pnpm dev                    # http://localhost:3000
pnpm lint && pnpm exec tsc --noEmit && pnpm test
```
`pnpm gen:api` regenerates `web/src/lib/api-types.ts` from the API's OpenAPI schema.

## Deploy
Both apps deploy from GitHub Actions only (`.github/workflows/vercel.yml`, after CI passes on `main`): the api (`platter-api`) first, then the web. Vercel's own Git builds are off. Migrations are a deliberate manual step before merging a schema change: `ALEMBIC_URL=<neon direct url> uv run alembic upgrade head`.

## Planning
[PRD](PRD.md) · [Plan](docs/07-plan.md) · [Tracker](https://claude.ai/artifact/HEHpyrigHuZpBMoECDs4qG) · [Screens](https://claude.ai/artifact/GGchE2CjZ7DN5t83pzs9Cu) · Dish photos: Wikimedia Commons, credited in `web/public/dishes/CREDITS.md`.

Roadmap: v1 Kitchen ✓ → v2 Rush ✓ (rider offers, Web Push, menu editor, search + ratings, refunds + ledgers + payouts) → v3 Fleet (batching, measured ETA, LISTEN/NOTIFY, native Expo rider app) → v4 Order together.

Web Push keys: `cd api && uv run python -m scripts.gen_vapid` writes a VAPID pair to `api/.env.local` (gitignored); set `VAPID_PUBLIC_KEY` and `VAPID_PRIVATE_KEY` on the API.
