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

  useEffect(() => {
    const ctrl = new AbortController();
    setFailed(false);
    api<Card[]>(`/restaurants?lat=${pin.lat}&lng=${pin.lng}`, { signal: ctrl.signal })
      .then(setCards)
      .catch((e) => (e as Error).name !== "AbortError" && setFailed(true));
    return () => ctrl.abort();
  }, [pin.lat, pin.lng]);

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
          {cards && cards.length === 0 && (
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
