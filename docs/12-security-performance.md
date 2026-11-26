# Platter — Security & Performance (v1)

**Lifecycle step:** 12 of 17 · one page, as planned in [07-plan.md](07-plan.md) F6 · measured 2026-11-26 on a local production build (`next build` + `next start`) against the local API and PostGIS.

## Security — what v1 enforces, and where

| Concern | How | Where / proof |
|---|---|---|
| Sessions | Opaque 256-bit token in `pl_session` (HttpOnly, SameSite=Lax, Secure on https, 30 days); only its SHA-256 is stored, so a leaked `sessions` table holds no usable cookie. argon2id passwords; unknown emails still pay the full argon2 cost. | `api/app/services/auth.py` · `test_rbac.py::test_sign_up_in_me_out`, `test_sessions_expire_after_30_days` |
| Role gates | Board, rider app and admin answer **404** to everyone else (API and pages), so they don't admit they exist. A restaurant only ever sees and moves its own orders; a rider only its own job. | `require_restaurant / require_rider / require_admin`, `web/src/lib/guard.ts` · `test_the_wrong_role_gets_404_everywhere`, `test_a_restaurant_sees_and_moves_only_its_own_orders`, `test_a_rider_touches_only_its_own_job` |
| The state machine | Every status change is one `transition()`: row lock (`select … for update`), the `TRANSITIONS` table (roles + guard), else 409 `illegal_transition {from, to}`. Two concurrent accepts → one event. | `api/app/services/orders.py` · `test_transitions.py` (6 tests, incl. the race) |
| Streams | Authorised at open — and again on every reconnect, because a reconnect is a new request. A customer stream reads only its own order's rows; positions of a rider are only on the streams of orders that rider is carrying (the admin sees all). The customer is never told whether a rider is simulated. | `routers/orders.py::events` · `test_stream_routes_authorise` (403 / 401), `test_a_customer_stream_never_carries_other_orders` |
| Money | Prices, fees and totals are always the server's: items from the DB, fee from the road distance (OSRM, else straight line × 1.3); client totals are never read. Razorpay: HMAC-checked verify and webhook, webhook ids deduped, one idempotent `mark_paid`. | `test_order_total_equals_quote_and_ignores_client_prices`, `test_mark_paid.py` (4 tests) |
| GPS uplink | Only the signed-in rider's own position; `recorded_at` is server time; out-of-order fixes (`X-Ignored: stale`) and > 200 m jumps within 3 s (`X-Ignored: jump`) are dropped. | `routers/rider.py::position` · `test_position_rules` |
| Third parties | OSRM and Photon are called by the API only (User-Agent set, 3–4 s timeouts, fallbacks); Photon is limited to 10 searches / min / IP. The browser talks to its own origin, OpenFreeMap tiles and Razorpay only — a strict CSP allows exactly those. | `services/routing.py`, `services/geo.py`, `web/next.config.ts` |
| Data kept | Rider trails are pruned 7 days after an order closes: `PRUNE_DATABASE_URL=… uv run python -m scripts.prune_track`. No positions in logs. | `api/scripts/prune_track.py` |
| Operations | Migrations, the seed and the pruner never read `DATABASE_URL` — each names its target (`ALEMBIC_URL`, `SEED_DATABASE_URL`, `PRUNE_DATABASE_URL`), so a bare command can't touch production. | `alembic/env.py`, `app/seed/seed.py` |

## Performance

| Check | Result |
|---|---|
| Lighthouse (mobile) — home `/` | Accessibility **100** · Best practices **100** · SEO **100** |
| Lighthouse (mobile) — restaurant `/r/dosa-camp` | Accessibility **100** · Best practices **100** · SEO **100** |
| Lighthouse performance score | **Not measured yet** — the audit tool used here excludes the performance category. Re-run on the deployed site (PageSpeed Insights) and record it here. By construction: MapLibre (~800 kB) is dynamic-imported only on map pages; dish photos are pre-sized 480-px files with explicit dimensions (no CLS); Nunito via `next/font`. |
| First-load JS (from `next build`) | 130 kB shared; home 140 kB, restaurant 139 kB, tracking 140 kB (MapLibre loads after). |
| Nearby restaurants | One indexed PostGIS query (`ST_DWithin` + `ST_Distance`, GIST); the API test suite asserts results and order against `ST_Distance`. The ≤ 150 ms target is to be timed on Neon after deploy. |
| Nearest rider | One KNN (`loc <->` restaurant) with `for update … skip locked` — `test_skip_locked_never_double_books`. |
| Stream cost | One cheap indexed read per second per open stream (`order_events where seq > $cursor`), a session per tick, closed at 280 s. |

## Latency note (v1 = poll mode)

v1's stream loop **polls** the durable log once a second: a rider fix posted at time *t* reaches the customer at most ~1 s later, plus network. `order_events` is the durable log and the bus; a reconnect replays exactly what was missed by `seq` (`test_reconnect_replays_exactly_the_missed_events`). v3 adds `LISTEN/NOTIFY` **only as a wake-up** for the same read, and publishes measured p50 / p95 from `scripts/measure_latency.py`; until then no latency figure is claimed beyond the 1-s tick.
