# Platter

**Hot food, tracked to your door.** A four-sided food-delivery platform: customers order, restaurants accept, riders deliver, an admin dispatches — and the rider moves on the customer's map in real time.

> Status: **lifecycle steps 1–7 complete (2026-09-17)** — PRD v1, docs 03–07, direction L · Bento, every v1 screen mocked. Next: step 8 Project Setup (milestone 1.0), last in the build order. One of six portfolio projects by [Viraj Domadia](https://virajdomadia.vercel.app). **Live (landing page):** https://platter-viraj.vercel.app — will move to `platter.virajdomadia.com` later.

## What it proves
Geospatial (PostGIS) · live location streaming · order state machine across roles

## Stack
Next.js 15 (App Router) · TypeScript · Tailwind 4 · MapLibre GL + OpenFreeMap · FastAPI (Python) · Neon Postgres + PostGIS · SSE (Postgres as the bus) · OSRM · Photon · Razorpay · Vercel

## In this repo
```
web/        Next.js 15 (App Router, TypeScript, Tailwind 4) — the landing page lives here
  src/app/            layout.tsx, page.tsx, globals.css
  src/components/     landing/ (one component per section), ui/
  src/lib/
api/        FastAPI backend — folder structure only until the build starts
  app/core · routers · models · schemas · services
  tests/
PRD.md      product requirements v1 — locked decisions, versions v1–v4, success criteria
docs/       03 requirements + user flows · 04 technical design + UI mockups · 05 architecture · 06 data + API · 07 plan
mockups/    landing.html · direction-variants.html (A–L) · screens.html (every v1 screen, L · Bento) · tracker.html (+ tracker-build.py) · img/ (CC photos + OSM rasters, CREDITS.md)
brand/      logo, mark and favicon
```

### Run the landing page
```
cd web
pnpm install
pnpm dev
```

## Live planning artifacts
- [Tracker](https://claude.ai/artifact/HEHpyrigHuZpBMoECDs4qG) — plan rows with status, all docs, mockups, project facts
- [Screens](https://claude.ai/artifact/GGchE2CjZ7DN5t83pzs9Cu) — every v1 screen in L · Bento with the live tracking map
- [Direction variants](https://claude.ai/artifact/JAekpL7HjR4oU5c39ak7dg) — twelve directions, L chosen

## Roadmap
v1 Kitchen (16 h) → v2 Rush (11 h) → v3 Fleet (8 h) → v4 Order together (3 h) — see [docs/07-plan.md](docs/07-plan.md). Build starts at milestone 1.0 after the other five projects.
