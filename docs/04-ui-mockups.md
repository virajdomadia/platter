# Platter — UI Mockups

**Lifecycle step:** 4 of 17 (UX companion to the technical design) · **Brief locked:** 2026-09-17 · **Variants:** `mockups/direction-variants.html` (twelve directions × six screens, twelve live motion candidates), published at https://claude.ai/artifact/JAekpL7HjR4oU5c39ak7dg · **Chosen: L · Bento** (Viraj, 2026-09-17, from twelve after a second round)
**Pairs with:** [03-user-flows.md](03-user-flows.md) — one mockup per v1 screen (S1–S12, S16) after the direction is chosen.
**Files:** `mockups/landing.html` (exists, already ported to `web/`) → `mockups/direction-variants.html` (S1 home + S2 menu on a 390 px phone, **S5 tracking on a phone — the hero**, S7 restaurant board on a tablet, S8 rider on a phone, S9 admin map at desktop, six directions) → `mockups/screens.html` (every v1 screen in the chosen direction) → `mockups/tracker.html` (built by `mockups/tracker-build.py`). Photos: CC from Wikimedia Commons in `mockups/img/`, credits in `mockups/img/CREDITS.md`. Maps: real raster tiles of Koramangala / HSR stitched into `mockups/img/map-light.jpg` and `map-dark.jpg` (artifacts block external tile hosts), with a real OSRM route drawn over them as SVG.
**Published:** [Direction variants](https://claude.ai/artifact/JAekpL7HjR4oU5c39ak7dg) · [Screens](https://claude.ai/artifact/GGchE2CjZ7DN5t83pzs9Cu) · [Tracker](https://claude.ai/artifact/HEHpyrigHuZpBMoECDs4qG).

## Brief
**Style:** the landing set a first identity — **Bricolage Grotesque**, cream `#FFF6E9`, green `#2F7D4A`, tomato `#E4402E`, butter `#FFD166`, 16 px radius — warm and appetising. It is one candidate (A), not the answer. Delivery apps live or die on **the tracking page** (does the rider feel real? does the ETA feel honest?) and **the menu** (does the food look worth ordering at 9 pm?) — plus two screens only this project has: **the restaurant board** on a tablet in a hot kitchen (big, loud, one-tap) and **the rider app** on a phone in a handlebar mount (dark, huge buttons, glanceable). The variants must be genuinely different UI styles (layout DNA, type, surface, density), not chrome swaps of one system; the admin is the same system at a denser, calmer setting.

**The product is the map and the food.** On the tracking page the map is the biggest thing; on the menu the photos are. Chrome is type and rules. The rider phone is dark in every direction (a screen in sunlight and at night); everything else is free. Board is a tablet in landscape; admin is desktop.

**Real content:** the seed — 12 restaurants around Koramangala / HSR (Dosa Camp, Biryani Bhatti, Koramangala Social, Momo Junction, Thali Ghar, Chai Point…), ~100 dishes with CC photos, prices in ₹ (₹40 filter coffee to ₹420 biryani), a live order `PL-1042` with a sim rider (Suresh · scooter) 6 minutes away, a board with four tickets, an admin map with 9 riders.

## Motion candidates — live in the variant page
| Candidate | What happens | Reduced-motion fallback |
|---|---|---|
| **1 · Rider glide** | The rider marker (a scooter) eases between GPS fixes over their 3-s gap with a heading rotation; a thin trail draws behind it; the ETA badge nudges when it changes | Marker jumps; no trail animation |
| **2 · Route draw** | When a route arrives, the polyline draws itself from the restaurant to the pin (dashoffset, 900 ms) and the pin drops with a bounce | Route appears |
| **3 · Status rail** | The order steps Placed → Accepted → Cooking → Ready → Picked up → Delivered light along a rail as events arrive; the current step breathes; Cooking has a steam wisp | Steps set to their state |
| **4 · ETA flip** | Minutes flip like a split-flap board when the ETA changes (top half falls, bottom half rises); "≈" appears when the method is a straight line | Number changes |
| **5 · Ticket print** | On the board, a new order feeds out of a slot at the top of the New column as a KOT ticket with a perforated edge (translateY, 700 ms) and a chime; a tear-off when accepted | Ticket appears |
| **6 · Plate slide** | Add to cart: the dish photo scales down and slides onto the cart bar at the bottom, which bumps and counts up | Count changes |
| **7 · Radar ping** | On accept, a ring sweeps out from the restaurant on the customer map until it touches the nearest rider, then locks with a click | "Finding a rider" text only |
| **8 · Bell** | The board's bell icon swings and the ticket count pops when a new order lands; the tablet title shows "(1) New order" | Count changes |

Recommendation: **1 · Rider glide + 2 · Route draw** as the signature (the wow moment is the marker moving on real streets) + **5 · Ticket print** on the board + one catalogue touch (**6**) per direction.

## Variant page (`mockups/direction-variants.html`) — six directions, six screens each
Each tab: **S5 tracking** on a 390 px phone (the hero, with the live marker) beside **S1 home** and **S2 menu** on phones; **S7 restaurant board** on a 1024 px tablet; **S8 rider** on a phone (dark map); **S9 admin map** at desktop 1280 (scaled); then a strip with the eight motion candidates live in that direction's idiom. Keys 1–6 switch tabs; every direction carries the same photos, the same map and the same copy.

| Direction | Style (layout DNA · surface · type) | Demonstrates |
|---|---|---|
| **A · Menu card** | The landing's diner system: cream, green, tomato, butter; Bricolage Grotesque; 16 px radius; soft cards; bottom cart bar; map with a rounded sheet over it | Rider glide + Plate slide |
| **B · Night kitchen** | Near-black with warm amber and chilli red; Sora headings; the dark map is the page on every screen; full-bleed dish photos with gradients; horizontal rails; the tracking sheet is a glass panel | Route draw + ETA flip |
| **C · Dabba** | Tiffin steel and kraft paper: warm grey-brown, brass, a stamped label red; Fraunces headings + IBM Plex Sans; stacked-tin sections with rivets, kraft tags for prices, rubber stamps for status; the board is a kitchen slip rail | Ticket print + Status rail |
| **D · Dispatch** | Control-room: graphite and signal green, Space Grotesk + JetBrains Mono, telemetry chips (speed, heading, fixes), the map with a grid and range rings; dense; the rail is a timeline with timestamps | Radar ping + Rider glide |
| **E · Newsprint** | Editorial menu: off-white, ink, one tomato accent; Instrument Serif at 64 px, numbered dishes with dotted leaders, thin rules, a two-column menu like a printed card; the map in a bordered plate | Status rail + Plate slide |
| **F · Poster** | Swiss bold: saffron, leaf, chilli, off-white; Archivo Black / Archivo; giant type, flat colour blocks, no radius, black hairlines; the ETA is the poster headline; the board is a departures board | ETA flip + Bell |

`prefers-reduced-motion` respected in all.

## Round two (2026-09-17)
Viraj asked for "something else" after A–F; six more directions were added on the same page (**G · Glass** frosted panels over a full-bleed map · **H · Zine** hand-drawn street-food comic · **I · Receipt** thermal-printer monochrome · **J · Neon** night market · **K · Atlas** folded paper map · **L · Bento** pastel tiles) plus four more motion candidates (**9 · Steam** wisps over the dish while cooking · **10 · Handover** the bag hops from the scooter to the door and a tick lands · **11 · Accuracy ring** the drop pin's GPS ring tightens as fixes improve · **12 · Counter roll** totals roll digit by digit). He picked **L**.

## Chosen direction — L · Bento (locked 2026-09-17)
**Idea:** every screen is a bento box — a grid of chunky rounded tiles in five pastels, each tile one thing (the map, the ETA, the rider, the steps, the bill). Nunito at weight 900 for anything that matters, 700 for everything else; emoji-scale icons instead of an icon set where a glyph is enough; nothing has a border — surfaces are separated by colour and a soft two-layer shadow. The map is simply the biggest tile. Tiles pop in with a spring and reflow when the order's state changes, so the page itself is the status: the ETA tile grows when the rider is close, the steps tile turns mint at delivered. The board is four pastel columns of white tickets; the rider app is the same tiles on ink; the admin is three stat tiles, a big map tile and a ledger tile.

### Tokens (→ `web/src/app/globals.css`)
| Token | Value | Use |
|---|---|---|
| `--bg` | `#F3F0FF` | page ground (lavender-white) |
| `--tile` | `#FFFFFF` | default tile |
| `--lav` / `--mint` / `--peach` / `--lemon` / `--sky` | `#E6DEFF` / `#D9F5E3` / `#FFE1D1` / `#FFF1B8` / `#D8EDFF` | the five pastels: lav = info / steps done, mint = good / delivered / ETA, peach = attention / stuck / new order, lemon = rider / money, sky = restaurant / cooking |
| `--ink` / `--ink2` / `--muted` | `#1F1B2E` / `#3B3552` / `#8D87A3` | text / secondary / labels (≥ 4.5:1 on every pastel) |
| `--violet` | `#7B5CFF` | primary action, the route, current chip |
| `--coral` | `#FF7A59` | the rider marker, alerts, reject, the current step |
| `--green` | `#2ECC71` | live dot, share-location toggle, available riders |
| `--ink-tile` | `#1F1B2E` · text `#F3F0FF` | dark tiles (rider app ground, cart bar, nav on dark) |
| radii | tile 24 px · inner card 18 px · chip 14 px · pill 999 · phone 44 | nothing square; images always inside a tile radius |
| shadow | `0 2px 0 rgba(31,27,46,.05), 0 10px 24px rgba(31,27,46,.06)` | every tile; `0 0 0 3px var(--coral)` for a fresh ticket |
| type | **Nunito** 900 (titles, numbers, buttons) · 800 (labels) · 700 (body 13–14 px) · tabular numerals for ₹, km, min | `next/font/google`, `display: swap`; no second family |
| grid | phone: 2 columns, 10 px gap, 12 px gutter; tablet board: 4 columns; admin: `1fr 1fr 1fr 460px` with the map spanning three | tiles are `grid-template-rows` sized, never fixed heights inside |
| map | MapLibre `liberty` inside a tile; dark tile uses `map-dark.json`; route `--violet` 7 px with a white casing, trail `--coral`, restaurant pin ink, drop pin violet, rider marker coral scooter | |

### Motion (all with `prefers-reduced-motion` fallbacks)
| Moment | Spec | Reduced |
|---|---|---|
| **Rider glide + Route draw (signature, S5 / S8 / S9)** | the marker interpolates between fixes over their gap with rAF and rotates to heading; a coral trail follows; when a `route` event lands the violet polyline draws itself (dashoffset, 900 ms, `cubic-bezier(.2,.8,.2,1)`) and the drop pin drops with a spring (`.34,1.56,.64,1`) | marker jumps; route appears; pin static |
| **Tile spring (every screen)** | tiles enter with a 60 ms stagger: `scale(.92) translateY(8px)` → identity, 420 ms spring; on a status change the affected tile re-springs and swaps colour (ETA tile → mint at ≤ 3 min, steps tile → mint at delivered, rider tile → lemon when assigned) | tiles appear; colours swap instantly |
| Ticket print (S7) | a new order feeds out of the top of the New column as a white ticket (translateY, 700 ms), the column tile pulses peach once, a chime plays (user-gesture-unlocked); Accept slides the ticket to Cooking with a `view-transition` | ticket appears; column colour swaps |
| Plate slide (S2 / S3) | Add: the dish photo shrinks and slides into the cart bar, which bumps (`translateY(-8px) scale(1.03)`, 500 ms spring) and rolls its count | count changes |
| ETA roll (S5) | minutes change with the Counter roll (digits slide vertically, 500 ms) | number changes |
| Steam (S5 while cooking, S7 Cooking column) | three blurred wisps rise from the dish / the ticket header on a 2.2-s loop | none |
| Handover (S5 at delivered) | the coral bag hops from the scooter to the door tile and a mint tick lands; the steps tile turns mint | tick appears |
| Accuracy ring (S1 / S4 pin) | the pin's GPS ring breathes and tightens as `accuracy` improves | static ring |
| Radar ping (S5 on accept) | two rings sweep from the restaurant tile's map until the nearest rider locks | "Finding a rider" chip only |
| Bell (S7) | the bell swings and the New count pops on a new order; the tab title shows "(1) New order" | count changes |

### Browser surfaces
`::selection` lavender with ink · scrollbar: bg track, lavender thumb 10 px rounded · focus ring 3 px `--violet`, offset 2 px · `caret-color` violet · `theme-color` `#F3F0FF` (light) / `#1F1B2E` (rider app) · favicon = the mark on a lavender rounded tile.

## Screens (`mockups/screens.html`)
Every v1 screen from the screen index in Bento plus S16 states: S1 home (desktop + phone), S2 restaurant, S3 cart sheet, S4 checkout (+ Razorpay modal dismissed), S5 tracking (phone, the resume of the wow moment; desktop), S6 orders, S7 restaurant board (tablet), S8 rider app (phone, before and after *Share my location*), S9 admin map (desktop), S10 sign in with the four demo cards, S11 addresses, S12 restaurant menu availability, S16 states (finding a rider, restaurant closed, too far, cart from another restaurant, payment dismissed, empty orders, rider offline / weak signal). Published at https://claude.ai/artifact/GGchE2CjZ7DN5t83pzs9Cu. **Step 4 complete.**
