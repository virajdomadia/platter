# Platter — UI Mockups

**Lifecycle step:** 4 of 17 (UX companion to the technical design) · **Brief locked:** 2026-09-17 · **Variants:** `mockups/direction-variants.html` (six directions × six screens, eight live motion candidates), published at https://claude.ai/artifact/VARIANTS_URL · **Chosen: TBD**
**Pairs with:** [03-user-flows.md](03-user-flows.md) — one mockup per v1 screen (S1–S12, S16) after the direction is chosen.
**Files:** `mockups/landing.html` (exists, already ported to `web/`) → `mockups/direction-variants.html` (S1 home + S2 menu on a 390 px phone, **S5 tracking on a phone — the hero**, S7 restaurant board on a tablet, S8 rider on a phone, S9 admin map at desktop, six directions) → `mockups/screens.html` (every v1 screen in the chosen direction) → `mockups/tracker.html` (built by `mockups/tracker-build.py`). Photos: CC from Wikimedia Commons in `mockups/img/`, credits in `mockups/img/CREDITS.md`. Maps: real raster tiles of Koramangala / HSR stitched into `mockups/img/map-light.jpg` and `map-dark.jpg` (artifacts block external tile hosts), with a real OSRM route drawn over them as SVG.
**Published:** [Direction variants](https://claude.ai/artifact/VARIANTS_URL) · [Screens](https://claude.ai/artifact/SCREENS_URL) · [Tracker](https://claude.ai/artifact/TRACKER_URL).

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

## Chosen direction — TBD (after Viraj's letter)
Tokens, motion table and browser surfaces are written here once the direction is chosen; then `mockups/screens.html` renders every v1 screen in it.
