# Platter

**Hot food, tracked to your door.** A three-sided food-delivery app: customers order, restaurants accept, riders deliver — and the rider moves on the customer's map in real time.

> Status: in progress — planning and design stage. One of six portfolio projects by [Viraj Domadia](https://virajdomadia.vercel.app). Will go live at `platter.virajdomadia.com`.

## What it proves
Geospatial (PostGIS) · live location streaming · order state machine across roles

## Stack
Next.js (App Router) · TypeScript · Tailwind CSS 4 · PostgreSQL (Neon) + Drizzle · Better Auth · Razorpay · Vitest + Playwright · Sentry · Vercel

## In this repo
```
web/        Next.js 15 (App Router, TypeScript, Tailwind 4) — the landing page lives here
  src/app/            layout.tsx, page.tsx, globals.css
  src/components/     landing/ (one component per section), ui/
  src/lib/
api/        FastAPI backend — folder structure only until the build starts
  app/core · routers · models · schemas · services
  tests/
PRD.md      product requirements (v0, being refined)
mockups/    landing.html — the design source the web/ page was ported from
brand/      logo, mark and favicon
```

### Run the landing page
```
cd web
pnpm install
pnpm dev
```

## Roadmap
1. Finalise the PRD
2. Scaffold the Next.js app
3. Build the thin vertical slice described in the PRD
4. Tests, CI, Lighthouse, deploy
5. Case study on the portfolio
