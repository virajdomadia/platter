"use client";

// S1: the delivery pin on a MapLibre map (drag it, search, or use your location), and every
// restaurant that can reach it — PostGIS within 5 km by straight line, 5–8 km greyed "Too far".
// Moving the pin re-sorts and re-prices the list without a reload.
import Link from "next/link";
import { Fragment, useEffect, useMemo, useState } from "react";
import { Map } from "@/components/map/Map";
import { api, type Address, type Place, type RestaurantCard as Card } from "@/lib/api";
import { DEFAULT_PIN, haversine, AREA_CENTRE } from "@/lib/geo";
import { minutes } from "@/lib/format";
import { hasSavedPin, setPin, usePin, type Pin } from "@/lib/pin";
import { useMe } from "@/lib/session";
import { AddressSearch } from "./AddressSearch";
import { DemoCards } from "./DemoCards";
import { RestaurantCard } from "./RestaurantCard";

async function labelFor(lat: number, lng: number): Promise<Pin> {
  try {
    const p = await api<Place>(`/geo/reverse?lat=${lat}&lng=${lng}`);
    return { lat, lng, label: p.label, line: p.line };
  } catch {
    return { lat, lng, label: "Pinned location", line: `${lat.toFixed(5)}, ${lng.toFixed(5)}` };
  }
}

export function HomeScreen() {
  const pin = usePin();
  const me = useMe();
  const [cards, setCards] = useState<Card[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [addresses, setAddresses] = useState<Address[]>([]);
  const [locating, setLocating] = useState(false);
  const [geoNote, setGeoNote] = useState<string | null>(null);
  const [editing, setEditing] = useState(false); // phone: the location card is one line until "Change"
  const [filters, setFilters] = useState<Filters>(EMPTY);
  const [cuisines, setCuisines] = useState<{ pin: string; list: string[] }>({ pin: "", list: [] });

  // Filters live in the URL (?q=&cuisine=&veg=1&sort=), so a search can be shared or reloaded.
  useEffect(() => setFilters(fromUrl()), []);
  useEffect(() => toUrl(filters), [filters]);
  const query = useDebounced(filters.q.trim(), 250);

  useEffect(() => {
    const ctrl = new AbortController();
    setFailed(false);
    const params = new URLSearchParams({ lat: String(pin.lat), lng: String(pin.lng) });
    if (query) params.set("q", query);
    if (filters.cuisine) params.set("cuisine", filters.cuisine);
    if (filters.veg) params.set("veg", "true");
    if (filters.sort !== "distance") params.set("sort", filters.sort);
    const narrowed = !!(query || filters.cuisine || filters.veg);
    const here = `${pin.lat},${pin.lng}`;
    api<Card[]>(`/restaurants?${params}`, { signal: ctrl.signal })
      .then((list) => {
        setCards(list);
        if (!narrowed) setCuisines({ pin: here, list: cuisinesOf(list) });
      })
      .catch((e) => (e as Error).name !== "AbortError" && setFailed(true));
    // The chips offer every cuisine near the pin, so a filtered view never hides the way across.
    if (narrowed && cuisines.pin !== here) {
      api<Card[]>(`/restaurants?lat=${pin.lat}&lng=${pin.lng}`, { signal: ctrl.signal })
        .then((list) => setCuisines({ pin: here, list: cuisinesOf(list) }))
        .catch(() => undefined);
    }
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `cuisines.pin` only gates a one-off fetch
  }, [pin.lat, pin.lng, query, filters.cuisine, filters.veg, filters.sort]);
  const filtered = !!(query || filters.cuisine || filters.veg);

  useEffect(() => {
    if (!me) return;
    api<Address[]>("/addresses")
      .then((list) => {
        setAddresses(list);
        // First visit while signed in: start from the first saved address.
        if (!hasSavedPin() && list[0]) setPin({ lat: list[0].lat, lng: list[0].lng, label: list[0].label, line: list[0].line, addressId: list[0].id });
      })
      .catch(() => undefined);
  }, [me]);

  const orderable = useMemo(() => cards?.filter((c) => c.orderable) ?? [], [cards]);
  const fastest = useMemo(() => [...orderable].sort((a, b) => a.eta_s - b.eta_s)[0], [orderable]);
  const far = haversine([pin.lat, pin.lng], AREA_CENTRE) > 12_000;

  const locate = () => {
    if (!navigator.geolocation) return setGeoNote("This browser can't share a location. Drag the pin instead.");
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        setPin(await labelFor(pos.coords.latitude, pos.coords.longitude));
        setLocating(false);
        setGeoNote(null);
      },
      () => {
        setLocating(false);
        setGeoNote("Location permission was refused. Search or drag the pin instead.");
      },
      { enableHighAccuracy: true, timeout: 10_000 },
    );
  };

  return (
    <main id="main" className="page home">
      <section className="home-grid">
        <div className={`tile home-side spring ${editing ? "open" : ""}`}>
          <div className="home-where">
            <div style={{ minWidth: 0 }}>
              <p className="label">Deliver to</p>
              <h1 style={{ fontSize: 22 }}>
                <span aria-hidden="true">📍 </span>
                {pin.label}
              </h1>
              <p className="muted" style={{ fontSize: 13 }}>{pin.line}</p>
            </div>
            <button className="btn small ghost home-change" aria-expanded={editing} onClick={() => setEditing(!editing)}>
              {editing ? "Done" : "Change"}
            </button>
          </div>
          <div className="home-map">
            <Map
              label="Delivery pin, drag to move"
              center={[pin.lat, pin.lng]}
              zoom={14}
              draggable={{ lat: pin.lat, lng: pin.lng, onDragEnd: async (lat, lng) => setPin(await labelFor(lat, lng)) }}
              markers={(cards ?? []).map((c) => ({ id: c.id, kind: "restaurant" as const, lat: c.lat, lng: c.lng, title: c.name }))}
            >
              <span className="map-pill">Drag the pin</span>
            </Map>
          </div>
          <AddressSearch near={pin} onPick={(p) => setPin({ lat: p.lat, lng: p.lng, label: p.label, line: p.line })} />
          <div className="row" style={{ flexWrap: "wrap", gap: 6 }}>
            <button className="chip lav" onClick={locate} disabled={locating}>
              {locating ? "Locating…" : <><span aria-hidden="true">🎯</span> Use my location</>}
            </button>
            {addresses.map((a) => (
              <button
                key={a.id}
                className={`chip ${pin.addressId === a.id ? "dark" : ""}`}
                onClick={() => setPin({ lat: a.lat, lng: a.lng, label: a.label, line: a.line, addressId: a.id })}
              >
                {a.label}
              </button>
            ))}
            {pin.lat !== DEFAULT_PIN.lat && (
              <button className="chip" onClick={() => setPin(DEFAULT_PIN)}>
                Koramangala 5th Block
              </button>
            )}
          </div>
          {geoNote && <p className="error-text">{geoNote}</p>}
        </div>

        <div className="home-list">
          <div className="tile ink spring home-hero">
            <p className="label">Bengaluru · Koramangala & HSR</p>
            <h2 style={{ fontSize: 26, color: "#fff" }}>Hot food, tracked to your door.</h2>
            <p className="home-blurb" style={{ color: "#d9d3f0", fontSize: 14, maxWidth: "52ch" }}>
              Order from kitchens that can actually reach your pin, then watch the rider move on a real map. The ETA is
              measured along the route, not guessed.
            </p>
            {me === null && (
              <div style={{ marginTop: 6 }}>
                <p className="label" style={{ color: "#d9d3f0", marginBottom: 6 }}>Try the demo, no sign-up</p>
                <DemoCards strip />
              </div>
            )}
          </div>
          <div className="tile peach spring stat">
            <b className="num">{cards ? orderable.length : "–"}</b>
            <small>{cards ? (orderable.length === 1 ? "kitchen can reach you now" : "kitchens can reach you now") : "finding kitchens…"}</small>
          </div>
          <div className="tile mint spring stat">
            <b className="num">{fastest ? `${minutes(fastest.eta_s)}′` : "–"}</b>
            <small>{fastest ? `fastest right now: ${fastest.name}` : "fastest kitchen"}</small>
          </div>

          <SearchBar filters={filters} setFilters={setFilters} cuisines={cuisines.list} count={cards?.length ?? null} />

          {failed && (
            <div className="tile span2">
              <h3>Couldn&apos;t load restaurants</h3>
              <p className="muted">Check your connection and try again.</p>
              <button className="btn small" style={{ marginTop: 8 }} onClick={() => setPin({ ...pin })}>
                Retry
              </button>
            </div>
          )}
          {!cards && !failed && [0, 1, 2, 3, 4, 5].map((i) => <div key={i} className="skeleton" style={{ aspectRatio: "4 / 3.4" }} />)}
          {cards && cards.length === 0 && filtered && (
            <div className="tile lemon span2" role="status">
              <h3>No kitchens near you match {query ? `"${query}"` : "these filters"}</h3>
              <p className="muted" style={{ marginTop: 4 }}>Try a dish (dosa, momos, biryani) or a cuisine instead.</p>
              <button className="btn small" style={{ marginTop: 10 }} onClick={() => setFilters(EMPTY)}>
                Clear search and filters
              </button>
            </div>
          )}
          {cards && cards.length === 0 && !filtered && (
            <div className="tile lemon span2">
              <h3>{far ? "We only deliver in Koramangala & HSR Layout for now" : "No kitchens near this pin"}</h3>
              <p className="muted" style={{ marginTop: 4 }}>Move the pin closer to Koramangala, Bengaluru. Every kitchen here is within a few kilometres.</p>
              <button className="btn small" style={{ marginTop: 10 }} onClick={() => setPin(DEFAULT_PIN)}>
                Jump to Koramangala 5th Block
              </button>
            </div>
          )}
          {cards?.map((c, i) => (
            <Fragment key={c.id}>
              {!c.orderable && (i === 0 || cards[i - 1].orderable) && (
                <h2 className="span-all" style={{ fontSize: 16, margin: "8px 4px 0" }}>Not available right now</h2>
              )}
              <RestaurantCard r={c} big={i === 0 && c.orderable} />
            </Fragment>
          ))}
        </div>
      </section>

      {me === null && (
        <section id="demo" className="tile lav spring" style={{ marginTop: 12 }} aria-labelledby="demo-h">
          <div className="between" style={{ marginBottom: 10, flexWrap: "wrap" }}>
            <div>
              <h2 id="demo-h">Try every side of Platter</h2>
              <p className="muted" style={{ fontSize: 13 }}>One tap, no sign-up. Open two at once (a phone and a laptop) to see the live tracking.</p>
            </div>
            <Link className="btn small white" href="/sign-up">
              Create an account
            </Link>
          </div>
          <DemoCards />
        </section>
      )}
    </main>
  );
}

// ── search + filters ─────────────────────────────────────────────────────────────────────────

type Sort = "distance" | "rating" | "eta";
type Filters = { q: string; cuisine: string; veg: boolean; sort: Sort };
const EMPTY: Filters = { q: "", cuisine: "", veg: false, sort: "distance" };
const SORTS: Record<Sort, string> = { distance: "Nearest", rating: "Top rated", eta: "Fastest" };

function cuisinesOf(list: Card[]): string[] {
  return [...new Set(list.flatMap((c) => c.cuisines))].sort();
}

function fromUrl(): Filters {
  const u = new URLSearchParams(window.location.search);
  const sort = u.get("sort");
  return {
    q: (u.get("q") ?? "").slice(0, 60),
    cuisine: (u.get("cuisine") ?? "").slice(0, 40),
    veg: u.get("veg") === "1",
    sort: sort === "rating" || sort === "eta" ? sort : "distance",
  };
}

function toUrl(f: Filters) {
  const u = new URL(window.location.href);
  const set = (k: string, v: string) => (v ? u.searchParams.set(k, v) : u.searchParams.delete(k));
  set("q", f.q.trim());
  set("cuisine", f.cuisine);
  set("veg", f.veg ? "1" : "");
  set("sort", f.sort === "distance" ? "" : f.sort);
  if (u.href !== window.location.href) window.history.replaceState(null, "", u);
}

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = window.setTimeout(() => setV(value), ms);
    return () => window.clearTimeout(t);
  }, [value, ms]);
  return v;
}

function SearchBar({
  filters,
  setFilters,
  cuisines,
  count,
}: {
  filters: Filters;
  setFilters: (f: Filters) => void;
  cuisines: string[];
  count: number | null;
}) {
  const set = (patch: Partial<Filters>) => setFilters({ ...filters, ...patch });
  return (
    <div role="search" className="tile span-all home-search" aria-label="Find a kitchen">
      <div className="home-search-row">
        <label className="field home-q">
          <span className="sr-only">Search kitchens, cuisines or dishes</span>
          <input
            className="input"
            type="search"
            placeholder="Search a dish or kitchen: dosa, momos…"
            maxLength={60}
            value={filters.q}
            onChange={(e) => set({ q: e.target.value })}
          />
        </label>
        <label className="field home-sort">
          <span className="sr-only">Sort</span>
          <select className="input" value={filters.sort} onChange={(e) => set({ sort: e.target.value as Sort })}>
            {Object.entries(SORTS).map(([k, label]) => (
              <option key={k} value={k}>
                {label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="home-chips" role="group" aria-label="Filters">
        <button type="button" className={`chip ${filters.veg ? "dark" : ""}`} aria-pressed={filters.veg} onClick={() => set({ veg: !filters.veg })}>
          <span className="veg" aria-hidden="true" /> Pure veg
        </button>
        {cuisines.map((c) => {
          const on = filters.cuisine.toLowerCase() === c.toLowerCase();
          return (
            <button key={c} type="button" className={`chip ${on ? "dark" : ""}`} aria-pressed={on} onClick={() => set({ cuisine: on ? "" : c })}>
              {c}
            </button>
          );
        })}
      </div>
      <p className="sr-only" role="status">
        {count === null ? "" : `${count} kitchen${count === 1 ? "" : "s"} shown`}
      </p>
    </div>
  );
}
